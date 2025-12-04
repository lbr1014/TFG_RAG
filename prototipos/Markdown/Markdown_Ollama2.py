import re
import sys
import tempfile
from pathlib import Path

import ollama
from pdf2image import convert_from_path

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
- Prefer ☐ and ☑ for check boxes.

Index / table of contents:
- If a line has a section title followed by dots and then a page number
  (e.g. "1. OBJETO DEL CONTRATO............. 3"):
  - Remove the dots so it becomes "1. OBJETO DEL CONTRATO 3".
  - Do NOT output lines that are only dots or filler characters.

Return only valid Markdown, no explanations.
"""

MODEL_NAME = "blaifa/Nanonets-OCR-s"


def pdf_to_images(pdf_path: Path, dpi: int = 300):
    """Devuelve una lista de rutas a imágenes PNG generadas a partir del PDF."""
    images = convert_from_path(str(pdf_path), dpi=dpi)

    tmp_dir = Path(tempfile.mkdtemp(prefix="nanonets_ocr_"))
    image_paths = []
    for i, img in enumerate(images, start=1):
        img_path = tmp_dir / f"{pdf_path.stem}_page_{i}.png"
        img.save(img_path, "PNG")
        image_paths.append(img_path)

    return image_paths


def ocr_page_with_nanonets(image_path: Path, page_number: int, total_pages: int) -> str:
    """
    Llama a Ollama con Nanonets-OCR-s para una página. Para ello se usa la GPU
    """
    user_content = (
        PROMPT_BASE
        + f"\n\nThis is page {page_number} of {total_pages} of a Spanish PDF. "
          "Use consistent headings and formatting across pages.\n"
    )

    response = ollama.chat(
        model=MODEL_NAME,
        messages=[
            {
                "role": "user",
                "content": user_content,
                "images": [str(image_path)],
            }
        ],
        # Fuerza que el modelo use GPU
        options={
            "num_gpu": 1
        },
    )

    return response["message"]["content"]


def clean_index_dots(markdown: str) -> str:
    """
    Postprocesado: líneas tipo
    '1. OBJETO DEL CONTRATO............. 3'
    → '1. OBJETO DEL CONTRATO 3'

    Evita líneas que sean solo puntos.
    """
    cleaned_lines = []
    pattern = re.compile(r"^(.*?)(\.{3,})(\s*\d+.*?)$")

    for line in markdown.splitlines():
        stripped = line.strip()
        if stripped and all(c == "." for c in stripped):
            # Se omiten líneaa que solo tienen puntos
            continue

        m = pattern.match(line)
        if m:
            left, _, right = m.groups()
            new_line = f"{left.strip()} {right.strip()}"
            cleaned_lines.append(new_line)
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
        letters = [c for c in text if c.isalpha()]
        if not letters:
            return False
        upper = sum(1 for c in letters if c.isupper())
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
        m = single_num_re.match(stripped)
        if m:
            num, title = m.groups()
            if is_mostly_upper(title):
                out_lines.append(f"# {num}. {title.strip()}")
                continue  # ya procesado

        # 2) Títulos tipo "1.1. Texto"
        m = level2_re.match(stripped)
        if m:
            num, title = m.groups()
            out_lines.append(f"## {num}. {title.strip()}")
            continue

        # 3) Títulos tipo "1.1.1. Texto"
        m = level3_re.match(stripped)
        if m:
            num, title = m.groups()
            out_lines.append(f"### {num}. {title.strip()}")
            continue

        # 4) Códigos tipo "G.2.2." o "G.2.2. Texto"
        m = letter_multi_re.match(stripped)
        if m:
            letter, nums, title = m.groups()
            code = f"{letter}.{nums}."
            if title:
                out_lines.append(f"### {code} {title.strip()}")
            else:
                # Solo el código sin texto, también lo marcamos como sección
                out_lines.append(f"### {code}")
            continue

        # Si nada encaja, dejamos la línea tal cual
        out_lines.append(raw)

    return "\n".join(out_lines)


def process_pdf(pdf_path: Path, output_dir: Path):
    print(f"Procesando {pdf_path.name}...")

    image_paths = pdf_to_images(pdf_path)
    total_pages = len(image_paths)
    page_markdowns = []

    for i, img_path in enumerate(image_paths, start=1):
        print(f"  - Página {i}/{total_pages}")
        md_page = ocr_page_with_nanonets(img_path, i, total_pages)
        page_markdowns.append(md_page)

    full_md = "\n\n".join(page_markdowns)
    full_md = clean_index_dots(full_md)
    full_md = normalize_headings(full_md)

    output_dir.mkdir(parents=True, exist_ok=True)
    out_path = output_dir / f"{pdf_path.stem}.md"
    out_path.write_text(full_md, encoding="utf-8")
    print(f"  → Markdown guardado en: {out_path}")


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
