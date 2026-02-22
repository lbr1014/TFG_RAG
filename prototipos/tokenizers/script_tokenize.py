import json
import re
from typing import List, Tuple

import torch
from pypdf import PdfReader
from transformers import AutoModelForCausalLM, AutoTokenizer

max_seq_length = 2048
max_new_tokens = 256
prompt_reserva = 200 
max_input_tokens = max_seq_length - max_new_tokens - prompt_reserva
model_name = "meta-llama/Meta-Llama-3.1-8B"


def alpaca_format(instruction: str, response: str = "") -> str:
    return f"### Instruction:\n{instruction}\n\n### Response:\n{response}"


def read_pdf(path: str) -> str:
    reader = PdfReader(path)
    return "\n".join(page.extract_text() or "" for page in reader.pages)


def split_by_tokens(tokenizer, text: str, max_tokens: int, overlap: int = 50):
    ids = tokenizer.encode(text, add_special_tokens=False)
    chunks = []
    start = 0
    while start < len(ids):
        end = min(start + max_tokens, len(ids))
        piece_ids = ids[start:end]
        chunks.append(tokenizer.decode(piece_ids))
        if end == len(ids):
            break
        start = end - overlap  # solape
        if start < 0: 
            start = 0
    return chunks


def split_by_sentences_pack(text: str, min_len=800, max_len=1200):
    # une frases hasta max_len
    sents = re.split(r"(?<!\w\.\w.)(?<![A-ZÁÉÍÓÚÑ][a-záéíóúñ]\.)(?<=\.|\?|!)\s", text)
    packs, cur = [], ""
    for s in sents:
        s = s.strip()
        if not s: 
            continue
        if len(cur) + len(s) <= max_len:
            cur += (s + " ")
        else:
            if len(cur) >= min_len:
                packs.append(cur.strip())
                cur = s + " "
            else:
                cur += (s + " ")
    if len(cur) >= min_len:
        packs.append(cur.strip())
    return packs


DOTS = r"[.\·•·∙⋅··…]" 
RE_INDEX_LINE = re.compile(rf"^\s*\d*(\.\d+)*\s*[^\d{DOTS}]+?\s{DOTS}{{4,}}\s*\d{{1,4}}\s*$")
RE_TRAILING_PAGENUM = re.compile(rf"{DOTS}{{3,}}\s*\d{{1,4}}\s*$")
RE_HEADER_FOOTER = re.compile(r"^\s*(Página\s+\d+|ÍNDICE|INDEX|CONTENIDOS?)\s*$", re.I)


def clean_page(text: str) -> str:
    out = []
    for ln in (text or "").splitlines():
        s = ln.strip()
        if not s: 
            continue
        if RE_HEADER_FOOTER.match(s): 
            continue
        if RE_INDEX_LINE.search(s): 
            continue
        if RE_TRAILING_PAGENUM.search(s): 
            continue
        out.append(s)
    return "\n".join(out)


def read_pdf_text(path: str) -> str:
    r = PdfReader(path)
    chunks = []
    for i, p in enumerate(r.pages):
        txt = clean_page(p.extract_text() or "")
        chunks.append(txt)
    return "\n".join(chunks)


# --- Heurísticas de título de apartado ---
RE_NUMERIC_HEADING = re.compile(r"^\s*\d+(\.\d+)*\s+[A-ZÁÉÍÓÚÑ0-9].{2,}$")
RE_ALLCAPS_HEADING = re.compile(r"^[A-ZÁÉÍÓÚÑ0-9][A-ZÁÉÍÓÚÑ0-9\s\-–,:;.()]{4,}$")
RE_SPECIAL = re.compile(r"^(CAP[IÍ]TULO|ANEXO|AP[EÉ]NDICE)\b", re.I)


def looks_like_heading(line: str) -> bool:
    s = line.strip()
    if len(s) > 120: 
        return False
    # evita líneas del índice
    if RE_INDEX_LINE.search(s) or RE_TRAILING_PAGENUM.search(s):
        return False
    return bool(
        RE_NUMERIC_HEADING.match(s) or
        RE_SPECIAL.match(s) or
        (RE_ALLCAPS_HEADING.match(s) and " " in s)  # MAYÚSCULAS con espacios
    )
    
    
def split_into_sections(text: str) -> List[Tuple[str, str]]:
    """Devuelve [(titulo, cuerpo), ...] en orden."""
    lines = [ln for ln in text.splitlines()]
    sections: List[Tuple[str, str]] = []
    cur_title, cur_buf = None, []

    def push():
        nonlocal cur_title, cur_buf
        if cur_title and cur_buf:
            # limpia espacios vacíos al final
            body = "\n".join([x for x in cur_buf]).strip()
            if body:
                sections.append((cur_title.strip(), body))
        cur_title, cur_buf = None, []

    for ln in lines:
        if looks_like_heading(ln):
            push()
            cur_title = ln.strip()
        else:
            if cur_title is None:
                # si el documento empieza con texto crea un “Preámbulo”
                cur_title = "Preámbulo"
            cur_buf.append(ln)

    push()
    return sections


pdf_path = "pruebas.pdf"
pdf_text = read_pdf_text(pdf_path)
sections = split_into_sections(pdf_text) 


def build_prompt(text):
    return f"""
        Te paso el texto de un PDF entre <document>…</document>. 
        Resume el contenido en 3–5 líneas, con estilo telegráfico y preciso.

        <document>
        {text}
        </document>
    """


def generate_summary(text):
    prompt = alpaca_format(build_prompt(text), "")
    inputs = tokenizer([prompt], return_tensors="pt").to(device)
    out = model.generate(**inputs, max_new_tokens=max_new_tokens, use_cache=True)
    return tokenizer.decode(out[0], skip_special_tokens=True).split("### Response:")[-1].strip()


# Tokenizar con el tokenizer del modelo
device = "cuda" if torch.cuda.is_available() else "cpu"

# Carga de tokenizer y modelo
tokenizer = AutoTokenizer.from_pretrained(model_name, use_fast=False)
model = AutoModelForCausalLM.from_pretrained(
    model_name,
    torch_dtype=torch.float16 if device == "cuda" else torch.float32,
    device_map="auto" if device == "cuda" else None,
)

max_input_tokens = max_seq_length - max_new_tokens - 200
overlap_tokens = 50

resumenes = []
for titulo, cuerpo in sections:
    # trocea cuerpo por tokens si hace falta
    trozos = split_by_tokens(tokenizer, cuerpo, max_input_tokens, overlap_tokens)
    parciales = [generate_summary(t) for t in trozos]

    # fusiona los resúmenes parciales de esta sección (si hay varios)
    if len(parciales) > 1:
        fusion_text = "\n".join(f"- {p}" for p in parciales)
        resumen_final = generate_summary(f"La sección '{titulo}' se compone de estos subresúmenes:\n{fusion_text}\n\nFusiona en 3–5 líneas.")
    else:
        resumen_final = parciales[0] if parciales else ""

    if resumen_final:
        resumenes.append({"apartado": titulo, "resumen": resumen_final})

print(json.dumps({"resumenes": resumenes}, ensure_ascii=False, indent=2))

