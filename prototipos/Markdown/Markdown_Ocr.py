import re
import sys
from pathlib import Path

import fitz
import torch
from PIL import Image
from transformers import TrOCRProcessor, VisionEncoderDecoderModel

# ==========================
# CONFIGURACIÓN OCR (fallback)
# ==========================

HF_OCR_MODEL_NAME = "microsoft/trocr-base-printed"

DEVICE = torch.device("cuda" if torch.cuda.is_available() else "cpu")
print(f"[INFO] Dispositivo OCR: {DEVICE}")

OCR_PROCESSOR = TrOCRProcessor.from_pretrained(HF_OCR_MODEL_NAME)
OCR_MODEL = VisionEncoderDecoderModel.from_pretrained(HF_OCR_MODEL_NAME).to(DEVICE)


# ==========================
# UTILIDADES
# ==========================

def is_mostly_upper(text: str, threshold: float = 0.7) -> bool:
    """True si la mayoría de las letras del texto están en mayúsculas."""
    letters = [c for c in text if c.isalpha()]
    if not letters:
        return False
    upper = sum(1 for c in letters if c.isupper())
    return (upper / len(letters)) >= threshold


# ==========================
# EXTRACCIÓN DE TEXTO + NEGRITA CON PyMuPDF
# ==========================

def extract_page_text_with_styles(page: fitz.Page) -> str:
    """
    Extrae el texto de una página usando PyMuPDF conservando negritas
    Devuelve texto con **negrita** ya marcada.
    """
    page_dict = page.get_text("dict")
    lines_out = []

    for block in page_dict.get("blocks", []):
        if "lines" not in block:
            continue

        for line in block["lines"]:
            parts = []
            for span in line.get("spans", []):
                text = span.get("text", "")
                if not text:
                    continue

                font = span.get("font", "")
                flags = span.get("flags", 0)

                is_bold = ("Bold" in font) or (flags & 2) != 0

                if is_bold and text.strip():
                    parts.append(f"**{text}**")
                else:
                    parts.append(text)

            line_text = "".join(parts).rstrip()
            if line_text:
                lines_out.append(line_text)

        # Separar bloques como párrafos
        lines_out.append("")

    # eliminar líneas vacías duplicadas
    cleaned = []
    prev_blank = False
    for line in lines_out:
        if line.strip() == "":
            if not prev_blank:
                cleaned.append("")
            prev_blank = True
        else:
            cleaned.append(line)
            prev_blank = False

    return "\n".join(cleaned).strip("\n")


# ==========================
# OCR GPU
# ==========================

def ocr_page_with_hf(page: fitz.Page, dpi: int = 300) -> str:
    """
    Hace OCR de una página usando Hugging Face + GPU SOLO si no hay texto embebido.
    """
    # Renderizamos la página a imagen
    zoom = dpi / 72  # 72 dpi base
    mat = fitz.Matrix(zoom, zoom)
    pix = page.get_pixmap(matrix=mat)

    mode = "RGB"
    if pix.alpha:
        mode = "RGBA"
    img = Image.frombytes(mode, [pix.width, pix.height], pix.samples)

    # Convertimos a RGB para el modelo
    img = img.convert("RGB")

    inputs = OCR_PROCESSOR(images=img, return_tensors="pt").to(DEVICE)
    generated_ids = OCR_MODEL.generate(**inputs)
    text = OCR_PROCESSOR.batch_decode(generated_ids, skip_special_tokens=True)[0]
    return text.strip()


# ==========================
# DETECCIÓN DE TÍTULOS / SECCIONES
# ==========================

def detect_numbered_heading(line: str):
    """
    Devuelve (nivel_markdown, texto_título) o None.

    Regla:
    - '1. TEXTO EN MAYÚSCULAS' -> título nivel 1 (si el texto está en mayúsculas)
    - '1.1. Texto' / '1.1.1. Texto' -> título (nivel = nº de partes numéricas)
    - 'G.2.2. Texto' -> título (letra + números)
    - '1.- Texto' (listas) NO se considera título.
    """
    line_stripped = line.strip()
    if len(line_stripped) < 3:
        return None

    # Números puros: 1., 1.1., 1.1.1.
    m = re.match(r'^(\d+(?:\.\d+)*\.?)\s+(.+)$', line_stripped)
    if m:
        num_str, title = m.groups()
        num_clean = num_str.rstrip('.')
        parts = num_clean.split('.')

        if len(parts) == 1:
            # Solo '1.' -> título solo si el resto está en mayúsculas
            if is_mostly_upper(title):
                level = 1
            else:
                return None
        else:
            # '1.1', '1.2.3', etc. -> siempre título
            level = min(6, len(parts))

        title_text = f"{num_clean}. {title.strip()}"
        return level, title_text

    # Letra + número(s): G.2.2.
    m2 = re.match(r'^([A-ZÁÉÍÓÚÜÑ]\.\d+(?:\.\d+)*\.?)\s+(.+)$', line_stripped)
    if m2:
        sec_str, title = m2.groups()
        sec_clean = sec_str.rstrip('.')
        num_part = sec_clean.split('.', 1)[1]  # todo tras la letra
        sub_parts = num_part.split('.')
        level = min(6, 1 + len(sub_parts))
        title_text = f"{sec_clean}. {title.strip()}"
        return level, title_text

    return None


def detect_plain_heading(line: str):
    """
    Títulos no numerados en MAYÚSCULAS.
    Devuelve (nivel, texto) o None.
    """
    stripped = line.strip()
    if len(stripped) < 4:
        return None
    if stripped.endswith(':'):
        return None
    if is_mostly_upper(stripped):
        return 1, stripped
    return None


def normalize_bullets(line: str) -> str:
    """
    Normaliza viñetas del texto
    """
    stripped = line.lstrip()
    bullet_patterns = [
        r'^[-*•·]\s+(.*)$',
        r'^\s+(.*)$',
        r'^o\s+(.*)$',
    ]
    for pat in bullet_patterns:
        m = re.match(pat, stripped)
        if m:
            return f"- {m.group(1).strip()}"
    return line


# ==========================
# TEXTO COMPLETO A MARKDOWN
# ==========================

def text_to_markdown(full_text: str) -> str:
    """
    Convierte todo el texto plano (con **negrita** ya marcada) en Markdown,
    añadiendo headings según reglas de numeración y mayúsculas.
    """
    md_lines = []

    for raw_line in full_text.splitlines():
        line = raw_line.rstrip("\n")

        if not line.strip():
            md_lines.append("")
            continue

        # Título numerado
        heading_info = detect_numbered_heading(line)
        if heading_info:
            level, title_text = heading_info
            md_lines.append(f"{'#' * level} {title_text}")
            continue

        # Título en mayúsculas no numerado
        heading_info = detect_plain_heading(line)
        if heading_info:
            level, title_text = heading_info
            md_lines.append(f"{'#' * level} {title_text}")
            continue

        # Viñetas
        bullet_line = normalize_bullets(line)
        md_lines.append(bullet_line)

    markdown = "\n".join(md_lines)
    return markdown


# ==========================
# POSTPROCESADO ÍNDICE
# ==========================

def clean_index_dots(markdown: str) -> str:
    """
    Se eliminan líneas que sean solo puntos.
    """
    cleaned_lines = []
    pattern = re.compile(r"^(.*?)(\.{3,})(\s*\d+.*?)$")

    for line in markdown.splitlines():
        stripped = line.strip()
        if stripped and all(c == "." for c in stripped):
            continue

        m = pattern.match(line)
        if m:
            left, _, right = m.groups()
            new_line = f"{left.strip()} {right.strip()}"
            cleaned_lines.append(new_line)
        else:
            cleaned_lines.append(line)

    return "\n".join(cleaned_lines)


def process_pdf(pdf_path: Path, output_dir: Path):
    print(f"Procesando {pdf_path.name}...")

    doc = fitz.open(str(pdf_path))
    page_texts = []

    for i, page in enumerate(doc, start=1):
        print(f"  - Página {i}/{len(doc)}")

        # 1) Intentar extraer texto embebido con estilos
        text = extract_page_text_with_styles(page)

        # 2) Si no hay texto, usar OCR en GPU como rescate
        if not text.strip():
            print("    [INFO] Página sin texto embebido, usando OCR...")
            text = ocr_page_with_hf(page)

        page_texts.append(text)

    doc.close()

    full_text = "\n\n".join(page_texts)

    # Convierte el texto a Markdown
    full_md = text_to_markdown(full_text)

    # Limpiar índices con puntos
    full_md = clean_index_dots(full_md)

    # Guardar
    output_dir.mkdir(parents=True, exist_ok=True)
    out_path = output_dir / f"{pdf_path.stem}.md"
    out_path.write_text(full_md, encoding="utf-8")
    print(f"  → Markdown guardado en: {out_path}")


def main():
    if len(sys.argv) < 3:
        print("Uso: python Markdown_Ocr.py <carpeta_pdfs> <carpeta_salida>")
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
