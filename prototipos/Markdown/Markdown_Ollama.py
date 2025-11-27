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
    """Llama a Ollama con Nanonets-OCR-s para una página."""
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
            # Línea que son solo puntos -> la omitimos
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

    image_paths = pdf_to_images(pdf_path)
    total_pages = len(image_paths)
    page_markdowns = []

    for i, img_path in enumerate(image_paths, start=1):
        print(f"  - Página {i}/{total_pages}")
        md_page = ocr_page_with_nanonets(img_path, i, total_pages)
        page_markdowns.append(md_page)

    full_md = "\n\n".join(page_markdowns)
    full_md = clean_index_dots(full_md)

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
