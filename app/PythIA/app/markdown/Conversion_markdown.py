import asyncio
import base64
import os
import re
import shutil
import sys
import tempfile
from pathlib import Path

import httpx
from PIL import Image
from pdf2image import convert_from_path, pdfinfo_from_path
try:
    import torch
except ImportError:  # pragma: no cover - entorno sin torch fuera de Docker
    torch = None

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

MODEL_NAME = os.getenv("OCR_MODEL_NAME", "blaifa/Nanonets-OCR-s")
OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", "http://ollama:11434").rstrip("/")
OLLAMA_CONNECT_TIMEOUT_SECONDS = int(os.getenv("OLLAMA_CONNECT_TIMEOUT_SECONDS", "10"))
OLLAMA_READ_TIMEOUT_SECONDS = int(os.getenv("OLLAMA_READ_TIMEOUT_SECONDS", "300"))
_ollama_num_gpu = os.getenv("OLLAMA_NUM_GPU")
DEFAULT_NUM_GPU = (
    int(_ollama_num_gpu)
    if _ollama_num_gpu not in (None, "")
    else (-1 if torch is not None and torch.cuda.is_available() else 0)
)
OLLAMA_NUM_GPU_SOURCE = (
    "env"
    if _ollama_num_gpu not in (None, "")
    else ("auto-cuda-full-offload" if torch is not None and torch.cuda.is_available() else "auto-cpu")
)
PDF_RENDER_DPI = int(os.getenv("PDF_RENDER_DPI", "200"))
OCR_MAX_IMAGE_SIDE = int(os.getenv("OCR_MAX_IMAGE_SIDE", "1600"))
OCR_RETRY_MAX_IMAGE_SIDES = [
    int(value.strip())
    for value in os.getenv("OCR_RETRY_MAX_IMAGE_SIDES", "1600,1280,1024,896,768").split(",")
    if value.strip()
]
OCR_PAGE_FAILURE_MODE = os.getenv("OCR_PAGE_FAILURE_MODE", "placeholder").strip().lower()


class OllamaOCRException(RuntimeError):
    """Error de OCR contra Ollama con contexto suficiente para depuración."""


def _ocr_execution_backend() -> str:
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
    message = str(error).replace("\n", " ").strip()
    return (
        f"<!-- OCR failed on page {page_number}/{total_pages}: {message} -->\n\n"
        f"> [OCR no disponible para la pagina {page_number}/{total_pages}. "
        "La conversion continuo con el resto del documento.]"
    )


def _build_chat_payload(user_content: str, image_base64: str, num_gpu: int) -> dict:
    return {
        "model": MODEL_NAME,
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
    try:
        response = await client.post("/api/chat", json=payload)
    except httpx.TimeoutException as exc:
        raise OllamaOCRException(
            f"Timeout en Ollama tras {OLLAMA_READ_TIMEOUT_SECONDS}s con el modelo '{MODEL_NAME}'."
        ) from exc
    except httpx.HTTPError as exc:
        raise OllamaOCRException(f"No se pudo conectar con Ollama: {exc}") from exc

    try:
        response.raise_for_status()
    except httpx.HTTPStatusError as exc:
        details = _response_error_details(response)
        raise OllamaOCRException(
            f"Ollama devolvio HTTP {response.status_code} para el modelo '{MODEL_NAME}': {details}"
        ) from exc

    try:
        return response.json()
    except ValueError as exc:
        raise OllamaOCRException("Ollama devolvio una respuesta no JSON en /api/chat.") from exc


def get_pdf_page_count(pdf_path: Path) -> int:
    info = pdfinfo_from_path(str(pdf_path))
    pages = int(info.get("Pages", 0))
    if pages <= 0:
        raise RuntimeError(f"No se pudo determinar el numero de paginas de {pdf_path.name}.")
    return pages


def pdf_page_to_image(pdf_path: Path, page_number: int, output_dir: Path, dpi: int = PDF_RENDER_DPI) -> Path:
    """
    Convierte una sola página del PDF en PNG para evitar cargar el documento completo en memoria.
    """
    images = convert_from_path(
        str(pdf_path),
        dpi=dpi,
        first_page=page_number,
        last_page=page_number,
        fmt="png",
        single_file=True,
    )
    if not images:
        raise RuntimeError(f"No se pudo convertir la pagina {page_number} de {pdf_path.name}.")

    img_path = output_dir / f"{pdf_path.stem}_page_{page_number}.png"
    images[0].save(img_path, "PNG")
    return img_path


def resize_image_for_ocr(image_path: Path, max_side: int) -> Path:
    """
    Limita el tamaño de la imagen para evitar fallos internos del modelo visual en Ollama.
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
) -> str:
    """
    Llama a Ollama con Nanonets-OCR-s para una página. Para ello se usa la GPU
    """
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
                        _build_chat_payload(user_content, image_base64, num_gpu),
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
        f"Fallo el OCR de la pagina {page_number}/{total_pages} con {image_path.name}: {last_error}"
    ) from last_error


def clean_index_dots(markdown: str) -> str:
    """
    Postprocesado: líneas tipo
    '1. OBJETO DEL CONTRATO............. 3'
    -> '1. OBJETO DEL CONTRATO 3'

    Evita líneas que sean solo puntos.
    """
    cleaned_lines = []
    pattern = re.compile(r"^(.*?)(\.{3,})(\s*\d+.*?)$")

    for line in markdown.splitlines():
        stripped = line.strip()
        if stripped and all(char == "." for char in stripped):
            continue

        match = pattern.match(line)
        if match:
            left, _, right = match.groups()
            cleaned_lines.append(f"{left.strip()} {right.strip()}")
        else:
            cleaned_lines.append(line)

    return "\n".join(cleaned_lines)


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

    single_num_re = re.compile(r"^(\d{1,2})\.\s+(.+)$")
    level2_re = re.compile(r"^(\d{1,2}\.\d{1,2})\.\s+(.+)$")
    level3_re = re.compile(r"^(\d{1,2}\.\d{1,2}\.\d{1,2})\.\s+(.+)$")
    # Ejemplos: "G.2.2.", "A.3.1. Texto"
    letter_multi_re = re.compile(r"^([A-Z])\.(\d+(?:\.\d+)*)\.\s*(.*)$")

    def is_mostly_upper(text: str) -> bool:
        letters = [char for char in text if char.isalpha()]
        if not letters:
            return False
        upper = sum(1 for char in letters if char.isupper())
        return upper / len(letters) >= 0.7

    for line in lines:
        raw = line
        stripped = line.strip()

        # Línea vacía o ya título markdown
        if not stripped or stripped.startswith("#"):
            out_lines.append(raw)
            continue

        # No tocar listas, tablas, citas ni HTML directamente
        if raw.startswith((" ", "\t", "-", "*", ">", "|", "<")):
            out_lines.append(raw)
            continue
        
        # 1) Títulos tipo "1. TEXTO" (requiere mayúsculas)
        match = single_num_re.match(stripped)
        if match:
            num, title = match.groups()
            if is_mostly_upper(title):
                out_lines.append(f"# {num}. {title.strip()}")
                continue

        # 2) Títulos tipo "1.1. Texto"
        match = level2_re.match(stripped)
        if match:
            num, title = match.groups()
            out_lines.append(f"## {num}. {title.strip()}")
            continue

        # 3) Títulos tipo "1.1.1. Texto"
        match = level3_re.match(stripped)
        if match:
            num, title = match.groups()
            out_lines.append(f"### {num}. {title.strip()}")
            continue

        # 4) Códigos tipo "G.2.2." o "G.2.2. Texto"
        match = letter_multi_re.match(stripped)
        if match:
            letter, nums, title = match.groups()
            code = f"{letter}.{nums}."
            out_lines.append(f"### {code} {title.strip()}".rstrip())
            continue

        # Si nada encaja, dejamos la línea tal cual
        out_lines.append(raw)

    return "\n".join(out_lines)


async def process_pdf_async(pdf_path: Path, output_dir: Path, on_page_start=None):
    print(
        f"Procesando {pdf_path.name}... "
        f"OCR model={MODEL_NAME} | backend={_ocr_execution_backend()} | base_url={OLLAMA_BASE_URL}"
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
                print(f"  - Pagina {page_number}/{total_pages}")
                img_path = pdf_page_to_image(pdf_path, page_number, tmp_dir)
                try:
                    try:
                        page_markdowns.append(
                            await ocr_page_with_nanonets_async(client, img_path, page_number, total_pages)
                        )
                    except OllamaOCRException as exc:
                        if OCR_PAGE_FAILURE_MODE == "raise":
                            raise
                        print(
                            f"  ! OCR omitido en pagina {page_number}/{total_pages}: {exc}",
                            file=sys.stderr,
                        )
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

    output_dir.mkdir(parents=True, exist_ok=True)
    out_path = output_dir / f"{pdf_path.stem}.md"
    out_path.write_text(full_md, encoding="utf-8")
    print(f"Markdown guardado en: {out_path}")


def process_pdf(pdf_path: Path, output_dir: Path, on_page_start=None):
    asyncio.run(process_pdf_async(pdf_path, output_dir, on_page_start=on_page_start))


def main():
    if len(sys.argv) < 3:
        print("Uso: python pdfs_a_markdown_nanonets.py <carpeta_pdfs> <carpeta_salida>")
        sys.exit(1)

    in_dir = Path(sys.argv[1])
    out_dir = Path(sys.argv[2])

    pdf_files = sorted(in_dir.glob("*.pdf"))
    if not pdf_files:
        print(f"No se han encontrado PDFs en {in_dir}")
        sys.exit(1)

    for pdf in pdf_files:
        process_pdf(pdf, out_dir)


if __name__ == "__main__":
    main()
