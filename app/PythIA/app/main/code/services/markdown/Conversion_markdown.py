"""
Autora: Lydia Blanco Ruiz
Script para convertir documentos PDF a Markdown mediante OCR y normalización de encabezados.
"""

import asyncio
import base64
import logging
import os
import shutil
import sys
import tempfile
from pathlib import Path

import httpx
from pdf2image import convert_from_path, pdfinfo_from_path
from PIL import Image

try:
    import torch
except ImportError:  # entorno sin torch fuera de Docker
    torch = None

logger = logging.getLogger(__name__)

PROMPT_BASE = """
You are converting a Spanish PDF (often legal / administrative) into clean Markdown.

Rules:
- Use Markdown headings:
  - Level 1: section numbers like "1. OBJETO DEL CONTRATO", etc.
  - Level 2: "1.1.", "1.2.", etc.
  - Level 3: "1.1.1.", etc.
- When there is a single number like "1.":
  - Only treat it as a title if the following words are mostly UPPERCASE.
- When there are more numbers, like "1.1." or "1.1.1.":
  - Always treat them as section/subsection titles.
- Also treat codes like "G.2.2." or "A.1.3." as valid section identifiers, at subsection level.
- Preserve bold text using **negrita** when the original text is visually bold
  (for example fully uppercase section titles or emphasized words).
- For tables, use HTML <table> output.
- For equations, use LaTeX ($...$ or $$...$$).
- If there is an image, wrap a short description in <img></img>.
- Wrap watermarks in <watermark>...</watermark>.
- Wrap page numbers in <page_number>...</page_number>.
- Prefer ☑ and ☒ for check boxes.

Index / table of contents:
- If a line has a section title followed by dots and then a page number
  (e.g. "1. OBJETO DEL CONTRATO............. 3"):
  - Remove the dots so it becomes "1. OBJETO DEL CONTRATO 3".
  - Do NOT output lines that are only dots or filler characters.

Return only valid Markdown, no explanations.
"""

DEFAULT_OCR_MODEL_NAME = os.getenv("OCR_MODEL_NAME", "blaifa/Nanonets-OCR-s")
MODEL_NAME = DEFAULT_OCR_MODEL_NAME
OLLAMA_CONNECT_TIMEOUT_SECONDS = int(os.getenv("OLLAMA_CONNECT_TIMEOUT_SECONDS", "10"))
OLLAMA_READ_TIMEOUT_SECONDS = int(os.getenv("OLLAMA_READ_TIMEOUT_SECONDS", "300"))
_ollama_num_gpu = os.getenv("OLLAMA_NUM_GPU")

# Determinar configuración de GPU
if _ollama_num_gpu not in (None, ""):
    DEFAULT_NUM_GPU = int(_ollama_num_gpu)
    OLLAMA_NUM_GPU_SOURCE = "env"
else:
    # Por defecto pedimos a Ollama que use GPU si es posible.
    # No lo inferimos de torch.cuda: Ollama puede estar en otra máquina/container.
    DEFAULT_NUM_GPU = -1
    OLLAMA_NUM_GPU_SOURCE = "auto-ollama"
PDF_RENDER_DPI = int(os.getenv("PDF_RENDER_DPI", "200"))
OCR_MAX_IMAGE_SIDE = int(os.getenv("OCR_MAX_IMAGE_SIDE", "1600"))
OCR_RETRY_MAX_IMAGE_SIDES = [
    int(value.strip())
    for value in os.getenv("OCR_RETRY_MAX_IMAGE_SIDES", "1600,1280,1024,896,768").split(",")
    if value.strip()
]
OCR_PAGE_FAILURE_MODE = os.getenv("OCR_PAGE_FAILURE_MODE", "placeholder").strip().lower()
PDF_INFO_TIMEOUT_SECONDS = int(os.getenv("PDF_INFO_TIMEOUT_SECONDS", "30"))
PDF_RENDER_TIMEOUT_SECONDS = int(os.getenv("PDF_RENDER_TIMEOUT_SECONDS", "120"))


def _service_url_from_env(env_name: str, default_host: str) -> str:
    """
    Construye la URL del servicio Markdown a partir de una variable de entorno, con soporte para esquemas y puertos.

    Args:
        env_name (str): Nombre de la variable de entorno que contiene la URL o el host del servicio.
        default_host (str): Host por defecto si la variable de entorno no está definida.

    Returns:
        str: URL del servicio construida.
    """
    value = os.getenv(env_name, default_host).strip().rstrip("/")
    if "://" not in value:
        scheme = os.getenv(f"{env_name}_SCHEME", "http").strip() or "http"
        return f"{scheme}://{value}"
    return value


OLLAMA_BASE_URL = _service_url_from_env("OLLAMA_BASE_URL", "ollama:11434")


class OllamaOCRException(RuntimeError):
    """
    Error de OCR contra Ollama con contexto suficiente para depuración.
    El mensaje de error incluye detalles sobre la configuración utilizada (modelo, GPU, etc.)
    """


def resolve_ocr_model(model_name: str | None = None) -> str:
    """
    Resuelve el modelo visual de Ollama que se usara para OCR.

    Si no se le pasa ningun valor, se usa el modelo configurado.
    
    Args:
        model: nombre del modelo a usar (opcional).
        
    Returns:
        El nombre del modelo a usar, limpio de espacios.
    """
    selected_model = (model_name or "").strip()
    return selected_model or DEFAULT_OCR_MODEL_NAME


def _ocr_execution_backend() -> str:
    """
    Determina el backend de ejecución para OCR basado en la configuración de GPU.

    Returns:
        str: Descripción del backend de ejecución (GPU, CPU, etc.) con detalles
             sobre la configuración de GPU utilizada.
    """
    if DEFAULT_NUM_GPU == -1:
        if torch is not None and torch.cuda.is_available():
            gpu_name = torch.cuda.get_device_name(0)
            gpu_count = torch.cuda.device_count()
            return (
                "GPU "
                f"(num_gpu=-1, all layers when possible, gpu={gpu_name}, total_gpus={gpu_count}, "
                f"source={OLLAMA_NUM_GPU_SOURCE})"
            )
        return f"GPU solicitada (num_gpu=-1, source={OLLAMA_NUM_GPU_SOURCE})"
    if DEFAULT_NUM_GPU > 0:
        return f"GPU parcial (num_gpu={DEFAULT_NUM_GPU}, source={OLLAMA_NUM_GPU_SOURCE})"
    return f"CPU (num_gpu=0, source={OLLAMA_NUM_GPU_SOURCE})"


def _page_failure_markdown(page_number: int, total_pages: int, error: Exception) -> str:
    """
    Genera contenido Markdown para una página que falló durante el OCR.

    Args:
        page_number: Número de la página que falló (1-indexed).
        total_pages: Número total de páginas del documento.
        error: Excepción que causó el fallo del OCR.

    Returns:
        str: Contenido Markdown con comentario HTML y mensaje de error formateado.
    """
    message = str(error).replace("\n", " ").strip()
    return (
        f"<!-- OCR failed on page {page_number}/{total_pages}: {message} -->\n\n"
        f"> [OCR no disponible para la página {page_number}/{total_pages}. "
        "La conversión continuó con el resto del documento.]"
    )


def _build_chat_payload(
    user_content: str,
    image_base64: str,
    num_gpu: int,
    model_name: str | None = None,
) -> dict:
    """
    Construye el payload JSON para la API de chat de Ollama.

    Args:
        user_content: Contenido del mensaje del usuario (prompt + instrucciones).
        image_base64: Imagen codificada en base64 para el OCR.
        num_gpu: Número de GPUs a utilizar (-1 para todas, 0 para CPU, >0 para GPUs específicas).

    Returns:
        dict: Payload formateado para la API /api/chat de Ollama.
    """
    return {
        "model": resolve_ocr_model(model_name),
        "messages": [
            {
                "role": "user",
                "content": user_content,
                "images": [image_base64],
            }
        ],
        "stream": False,
        "options": {
            "num_gpu": num_gpu,
        },
    }


def _response_error_details(response: httpx.Response) -> str:
    """
    Extrae detalles de error de una respuesta HTTP de Ollama.

    Args:
        response: Respuesta HTTP de la API de Ollama.

    Returns:
        str: Detalles del error extraídos del cuerpo de la respuesta,
             limitados a 500 caracteres.
    """
    try:
        data = response.json()
    except ValueError:
        body = (response.text or "").strip()
        return body[:500] if body else "sin cuerpo de respuesta"

    if isinstance(data, dict):
        for key in ("error", "message", "detail"):
            value = data.get(key)
            if value:
                return str(value)[:500]

    return str(data)[:500]


async def _post_ollama_chat_async(client: httpx.AsyncClient, payload: dict) -> dict:
    """
    Realiza una petición POST asíncrona a la API de chat de Ollama.

    Args:
        client: Cliente HTTP asíncrono configurado para Ollama.
        payload: Payload JSON para enviar a la API /api/chat.

    Returns:
        dict: Respuesta JSON de la API de Ollama.

    Raises:
        OllamaOCRException: Si ocurre un timeout, error de conexión,
                           respuesta HTTP de error, o respuesta no JSON.
    """
    model_name = str(payload.get("model") or MODEL_NAME)
    try:
        response = await client.post("/api/chat", json=payload)
    except httpx.TimeoutException as exc:
        raise OllamaOCRException(
            f"Timeout en Ollama tras {OLLAMA_READ_TIMEOUT_SECONDS}s con el modelo '{model_name}'."
        ) from exc
    except httpx.HTTPError as exc:
        raise OllamaOCRException(f"No se pudo conectar con Ollama: {exc}") from exc

    try:
        response.raise_for_status()
    except httpx.HTTPStatusError as exc:
        details = _response_error_details(response)
        raise OllamaOCRException(
            f"Ollama devolvió HTTP {response.status_code} para el modelo '{model_name}': {details}"
        ) from exc

    try:
        return response.json()
    except ValueError as exc:
        raise OllamaOCRException("Ollama devolvió una respuesta no JSON en /api/chat.") from exc


def get_pdf_page_count(pdf_path: Path) -> int:
    """
    Obtiene el número total de páginas de un documento PDF.

    Args:
        pdf_path: Ruta al archivo PDF.

    Returns:
        int: Número total de páginas del documento.

    Raises:
        RuntimeError: Si no se puede determinar el número de páginas
                     o si el documento no tiene páginas válidas.
    """
    info = pdfinfo_from_path(str(pdf_path), timeout=PDF_INFO_TIMEOUT_SECONDS)
    pages = int(info.get("Pages", 0))
    if pages <= 0:
        raise RuntimeError(f"No se pudo determinar el número de páginas de {pdf_path.name}.")
    return pages


def pdf_page_to_image(pdf_path: Path, page_number: int, output_dir: Path, dpi: int = PDF_RENDER_DPI) -> Path:
    """
    Convierte una sola página del PDF en una imagen PNG para evitar cargar el documento completo en memoria.

    Args:
        pdf_path: Ruta al archivo PDF.
        page_number: Número de la página a convertir (1-indexed).
        output_dir: Directorio donde guardar la imagen temporal.
        dpi: Resolución en DPI para la conversión (por defecto PDF_RENDER_DPI).

    Returns:
        Path: Ruta al archivo PNG generado.

    Raises:
        RuntimeError: Si no se puede convertir la página.
    """
    images = convert_from_path(
        str(pdf_path),
        dpi=dpi,
        first_page=page_number,
        last_page=page_number,
        fmt="png",
        single_file=True,
        timeout=PDF_RENDER_TIMEOUT_SECONDS,
    )
    if not images:
        raise RuntimeError(f"No se pudo convertir la página {page_number} de {pdf_path.name}.")

    img_path = output_dir / f"{pdf_path.stem}_page_{page_number}.png"
    images[0].save(img_path, "PNG")
    return img_path


def resize_image_for_ocr(image_path: Path, max_side: int) -> Path:
    """
    Limita el tamaño de la imagen para evitar fallos internos del modelo visual en Ollama.

    Si la imagen es más grande que max_side en cualquiera de sus dimensiones,
    se redimensiona manteniendo la proporción de aspecto.

    Args:
        image_path: Ruta a la imagen original.
        max_side: Tamaño máximo permitido para el lado más largo de la imagen.

    Returns:
        Path: Ruta a la imagen redimensionada (o la original si no necesita redimensionamiento).
             Las imágenes redimensionadas se guardan con un sufijo indicando el tamaño máximo.
    """
    with Image.open(image_path) as image:
        width, height = image.size
        longest_side = max(width, height)
        if longest_side <= max_side:
            return image_path

        scale = max_side / longest_side
        resized = image.resize(
            (max(1, int(width * scale)), max(1, int(height * scale))),
            Image.Resampling.LANCZOS,
        )

        resized_path = image_path.with_name(f"{image_path.stem}_max{max_side}{image_path.suffix}")
        resized.save(resized_path, "PNG", optimize=True)
        return resized_path


async def ocr_page_with_nanonets_async(
    client: httpx.AsyncClient,
    image_path: Path,
    page_number: int,
    total_pages: int,
    model_name: str | None = None,
) -> str:
    """
    Realiza OCR en una página individual usando el modelo Nanonets-OCR-s de Ollama.

    Intenta múltiples estrategias en caso de fallo:
    1. Diferentes tamaños de imagen (si está configurado OCR_RETRY_MAX_IMAGE_SIDES)
    2. Diferentes configuraciones de GPU (GPU primero, luego CPU como fallback)

    Args:
        client: Cliente HTTP asíncrono configurado para Ollama.
        image_path: Ruta a la imagen de la página a procesar.
        page_number: Número de la página actual (1-indexed).
        total_pages: Número total de páginas del documento.

    Returns:
        str: Contenido Markdown generado por el modelo OCR.

    Raises:
        OllamaOCRException: Si todas las estrategias de OCR fallan.
    """
    resolved_model = resolve_ocr_model(model_name)
    user_content = (
        PROMPT_BASE
        + f"\n\nThis is page {page_number} of {total_pages} of a Spanish PDF. "
          "Use consistent headings and formatting across pages.\n"
    )

    attempts = [DEFAULT_NUM_GPU]
    if DEFAULT_NUM_GPU != 0:
        attempts.append(0)

    last_error = None
    temp_files_to_delete = []
    try:
        for max_side in OCR_RETRY_MAX_IMAGE_SIDES or [OCR_MAX_IMAGE_SIDE]:
            candidate_path = resize_image_for_ocr(image_path, max_side)
            if candidate_path != image_path:
                temp_files_to_delete.append(candidate_path)

            image_base64 = base64.b64encode(candidate_path.read_bytes()).decode("ascii")

            for num_gpu in attempts:
                try:
                    data = await _post_ollama_chat_async(
                        client,
                        _build_chat_payload(user_content, image_base64, num_gpu, model_name=resolved_model),
                    )
                    return data["message"]["content"]
                except (OllamaOCRException, KeyError) as exc:
                    last_error = exc
    finally:
        for temp_path in temp_files_to_delete:
            try:
                temp_path.unlink(missing_ok=True)
            except OSError:
                pass

    raise OllamaOCRException(
        f"Fallo el OCR de la página {page_number}/{total_pages} con {image_path.name}: {last_error}"
    ) from last_error


def clean_index_dots(markdown: str) -> str:
    """
    Postprocesa el contenido Markdown para limpiar líneas de índice con puntos separadores.

    Convierte líneas como "1. OBJETO DEL CONTRATO............. 3"
    en "1. OBJETO DEL CONTRATO 3".

    También elimina líneas que consistan únicamente de puntos.

    Args:
        markdown: Contenido Markdown a procesar.

    Returns:
        str: Contenido Markdown con las líneas de índice limpiadas.
    """
    cleaned_lines = []

    for line in markdown.splitlines():
        stripped = line.strip()
        if stripped and all(char == "." for char in stripped):
            continue

        cleaned_lines.append(_clean_index_dot_leader(line))

    return "\n".join(cleaned_lines)


def _clean_index_dot_leader(line: str) -> str:
    """
    Limpia una línea de índice eliminando los puntos separadores entre el título y el número de página.

    Busca secuencias de al menos 3 puntos seguidos de un dígito y los reemplaza por un espacio.

    Args:
        line: Línea de texto original.

    Returns:
        str: Línea con los puntos separadores eliminados.
    """
    run_start = None
    run_end = None
    index = 0

    while index < len(line):
        if line[index] != ".":
            index += 1
            continue

        start = index
        while index < len(line) and line[index] == ".":
            index += 1

        if index - start >= 3 and line[index:].lstrip()[:1].isdigit():
            run_start = start
            run_end = index

    if run_start is None or run_end is None:
        return line

    left = line[:run_start].strip()
    right = line[run_end:].strip()
    return f"{left} {right}".strip()


def _should_skip_line(raw: str, stripped: str) -> bool:
    """
    Determina si una línea debe ser omitida del procesamiento de encabezados.

    Args:
        raw: Línea original sin modificar.
        stripped: Línea con espacios en blanco eliminados de los extremos.

    Returns:
        bool: True si la línea debe ser omitida, False si debe procesarse.
    """
    # Línea vacía o ya título markdown
    if not stripped or stripped.startswith("#"):
        return True
    # No tocar listas, tablas, citas ni HTML directamente
    return bool(raw.startswith((" ", "\t", "-", "*", ">", "|", "<")))


def _is_mostly_upper(text: str) -> bool:
    """
    Verifica si un texto está mayoritariamente en mayúsculas.

    Se considera mayoritariamente en mayúsculas si al menos el 70%
    de los caracteres alfabéticos están en mayúscula.

    Args:
        text: Texto a analizar.

    Returns:
        bool: True si el texto está mayoritariamente en mayúsculas.
    """
    letters = [char for char in text if char.isalpha()]
    if not letters:
        return False
    upper = sum(1 for char in letters if char.isupper())
    return upper / len(letters) >= 0.7


def _split_numeric_heading(stripped: str, expected_parts: int) -> tuple[str, str] | None:
    """
    Divide un encabezado numérico en marcador y título.

    Args:
        stripped: Línea de texto sin espacios extremos.
        expected_parts: Número esperado de partes numéricas (ej. 1 para "1.", 2 para "1.1.").

    Returns:
        tuple[str, str] | None: Tupla (marcador, título) si coincide, None en caso contrario.
    """
    marker_end = next((idx for idx, char in enumerate(stripped) if char.isspace()), len(stripped))
    marker = stripped[:marker_end]
    title = stripped[marker_end:].strip()

    if not marker.endswith(".") or not title:
        return None

    parts = marker[:-1].split(".")
    if len(parts) != expected_parts:
        return None

    if not all(part.isdigit() and 1 <= len(part) <= 2 for part in parts):
        return None

    return ".".join(parts), title


def _split_letter_code_heading(stripped: str) -> tuple[str, str] | None:
    """
    Divide un encabezado con código de letra en marcador y título.

    Args:
        stripped: Línea de texto sin espacios extremos.

    Returns:
        tuple[str, str] | None: Tupla (código, título) si coincide, None en caso contrario.
    """
    marker_end = next((idx for idx, char in enumerate(stripped) if char.isspace()), len(stripped))
    marker = stripped[:marker_end]
    title = stripped[marker_end:].strip()

    if len(marker) < 4 or not marker.endswith(".") or not marker[0].isupper():
        return None
    if marker[1] != ".":
        return None

    numeric_parts = marker[2:-1].split(".")
    if not numeric_parts or not all(part.isdigit() for part in numeric_parts):
        return None

    return marker, title


def _process_single_level_heading(stripped: str) -> str | None:
    """
    Procesa encabezados de nivel único que requieren estar en mayúsculas.

    Convierte líneas como "1. OBJETO DEL CONTRATO" en "# 1. OBJETO DEL CONTRATO"
    solo si el texto después del número está mayoritariamente en mayúsculas.

    Args:
        stripped: Línea de texto sin espacios en blanco extremos.

    Returns:
        str | None: Encabezado Markdown de nivel 1 si coincide y está en mayúsculas,
                   None si no cumple los criterios.
    """
    parsed = _split_numeric_heading(stripped, expected_parts=1)
    if parsed:
        num, title = parsed
        if _is_mostly_upper(title):
            return f"# {num}. {title}"
    return None


def _process_level2_heading(stripped: str) -> str | None:
    """
    Procesa encabezados de nivel 2 (subsecciones).

    Convierte líneas como "1.1. Definición" en "## 1.1. Definición".

    Args:
        stripped: Línea de texto sin espacios en blanco extremos.

    Returns:
        str | None: Encabezado Markdown de nivel 2 si coincide, None en caso contrario.
    """
    parsed = _split_numeric_heading(stripped, expected_parts=2)
    if parsed:
        num, title = parsed
        return f"## {num}. {title}"
    return None


def _process_level3_heading(stripped: str) -> str | None:
    """
    Procesa encabezados de nivel 3 (subsubsecciones).

    Convierte líneas como "1.1.1. Definición" en "### 1.1.1. Definición".

    Args:
        stripped: Línea de texto sin espacios en blanco extremos.

    Returns:
        str | None: Encabezado Markdown de nivel 3 si coincide, None en caso contrario.
    """
    parsed = _split_numeric_heading(stripped, expected_parts=3)
    if parsed:
        num, title = parsed
        return f"### {num}. {title}"
    return None


def _process_letter_code_heading(stripped: str) -> str | None:
    """
    Procesa códigos de letra con números múltiples como encabezados de nivel 3.

    Convierte líneas como "G.2.2. Texto" en "### G.2.2. Texto".

    Args:
        stripped: Línea de texto sin espacios en blanco extremos.

    Returns:
        str | None: Encabezado Markdown de nivel 3 si coincide, None en caso contrario.
    """
    parsed = _split_letter_code_heading(stripped)
    if parsed:
        code, title = parsed
        return f"### {code} {title}".rstrip()
    return None


def normalize_headings(markdown: str) -> str:
    """
    Asegura que las secciones numeradas se convierten en títulos Markdown,
    incluso si el modelo no las ha marcado como tales.

    Reglas:
    - Si ya empieza por '#', no se toca.
    - Solo se consideran líneas en columna 0 (sin indentación) y que no sean listas.
    - '1. TÍTULO EN MAYÚSCULAS' → '# 1. TÍTULO EN MAYÚSCULAS'
      (para un único número se exige MAYÚSCULAS).
    - '1.1. Texto' → '## 1.1. Texto'
    - '1.1.1. Texto' → '### 1.1.1. Texto'
    - 'G.2.2. Texto' o 'G.2.2.' → '### G.2.2. Texto'
    """
    lines = markdown.splitlines()
    out_lines = []

    for line in lines:
        raw = line
        stripped = line.strip()

        if _should_skip_line(raw, stripped):
            out_lines.append(raw)
            continue

        # Intentar procesar diferentes tipos de encabezados
        processed_line = (
            _process_single_level_heading(stripped) or
            _process_level2_heading(stripped) or
            _process_level3_heading(stripped) or
            _process_letter_code_heading(stripped)
        )

        if processed_line:
            out_lines.append(processed_line)
        else:
            out_lines.append(raw)

    return "\n".join(out_lines)


async def process_pdf_async(pdf_path: Path, on_page_start=None, model_name: str | None = None) -> str:
    """
    Procesa un PDF de forma asíncrona convirtiéndolo a Markdown mediante OCR.

    Args:
        pdf_path: Ruta al archivo PDF a procesar.
        on_page_start: Función opcional de callback llamada al inicio de cada página,
                      recibe (page_number, total_pages).

    Returns:
        str: Contenido completo del PDF convertido a Markdown.
    """
    resolved_model = resolve_ocr_model(model_name)
    logger.info(
        "Procesando %s... OCR model=%s | backend=%s | base_url=%s",
        pdf_path.name,
        resolved_model,
        _ocr_execution_backend(),
        OLLAMA_BASE_URL,
    )

    total_pages = get_pdf_page_count(pdf_path)
    page_markdowns = []
    tmp_dir = Path(tempfile.mkdtemp(prefix="nanonets_ocr_"))
    timeout = httpx.Timeout(
        connect=OLLAMA_CONNECT_TIMEOUT_SECONDS,
        read=OLLAMA_READ_TIMEOUT_SECONDS,
        write=OLLAMA_READ_TIMEOUT_SECONDS,
        pool=OLLAMA_CONNECT_TIMEOUT_SECONDS,
    )

    try:
        async with httpx.AsyncClient(base_url=OLLAMA_BASE_URL, timeout=timeout) as client:
            for page_number in range(1, total_pages + 1):
                if on_page_start is not None:
                    on_page_start(page_number, total_pages)
                logger.info("Página %s/%s", page_number, total_pages)
                img_path = pdf_page_to_image(pdf_path, page_number, tmp_dir)
                try:
                    try:
                        page_markdowns.append(
                            await ocr_page_with_nanonets_async(
                                client,
                                img_path,
                                page_number,
                                total_pages,
                                model_name=resolved_model,
                            )
                        )
                    except OllamaOCRException as exc:
                        if OCR_PAGE_FAILURE_MODE == "raise":
                            raise
                        logger.warning("OCR omitido en página %s/%s: %s", page_number, total_pages, exc)
                        page_markdowns.append(_page_failure_markdown(page_number, total_pages, exc))
                finally:
                    try:
                        img_path.unlink(missing_ok=True)
                    except OSError:
                        pass
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)

    full_md = "\n\n".join(page_markdowns)
    full_md = clean_index_dots(full_md)
    full_md = normalize_headings(full_md)

    return full_md


def process_pdf(pdf_path: Path, on_page_start=None, model_name: str | None = None) -> str:
    """
    Procesa un PDF convirtiéndolo a Markdown mediante OCR.

    Args:
        pdf_path: Ruta al archivo PDF a procesar.
        on_page_start: Función opcional de callback llamada al inicio de cada página,
                      recibe (page_number, total_pages).

    Returns:
        str: Contenido completo del PDF convertido a Markdown.
    """
    return asyncio.run(process_pdf_async(pdf_path, on_page_start=on_page_start, model_name=model_name))


def save_markdown_to_file(
    pdf_path: Path,
    output_dir: Path,
    on_page_start=None,
    model_name: str | None = None,
) -> Path:
    """
    Procesa un PDF y guarda el contenido Markdown en un archivo.

    Args:
        pdf_path: Ruta al archivo PDF a procesar.
        output_dir: Directorio donde guardar el archivo Markdown.
        on_page_start: Función opcional de callback llamada al inicio de cada página,
                      recibe (page_number, total_pages).

    Returns:
        Path: Ruta al archivo Markdown generado.
    """
    output_dir.mkdir(parents=True, exist_ok=True)
    full_md = process_pdf(pdf_path, on_page_start=on_page_start, model_name=model_name)
    out_path = output_dir / f"{pdf_path.stem}.md"
    out_path.write_text(full_md, encoding="utf-8")
    logger.info("Markdown guardado en: %s", out_path)
    return out_path


def main():
    """
    Función principal para procesar PDFs desde línea de comandos.

    Uso: python Conversion_markdown.py <carpeta_pdfs> <carpeta_salida>

    Procesa todos los archivos PDF en la carpeta de entrada y guarda
    los archivos Markdown correspondientes en la carpeta de salida.
    """
    if len(sys.argv) < 3:
        logger.error("Uso: python Conversion_markdown.py <carpeta_pdfs> <carpeta_salida>")
        sys.exit(1)

    in_dir = Path(sys.argv[1])
    out_dir = Path(sys.argv[2])

    pdf_files = sorted(in_dir.glob("*.pdf"))
    if not pdf_files:
        logger.warning("No se han encontrado PDFs en %s", in_dir)
        sys.exit(1)

    for pdf in pdf_files:
        save_markdown_to_file(pdf, out_dir)


if __name__ == "__main__":
    main()
