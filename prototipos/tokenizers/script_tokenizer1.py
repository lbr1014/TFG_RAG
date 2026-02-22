import torch
import re, json
from pathlib import Path
from typing import List, Tuple
from pypdf import PdfReader
from transformers import AutoTokenizer, AutoModelForCausalLM

# ===== Parámetros de generación =====
max_seq_length = 2048
max_new_tokens = 256
prompt_reserva = 200
max_input_tokens = max_seq_length - max_new_tokens - prompt_reserva
overlap_tokens = 60  # solape moderado 
model_name = "meta-llama/Meta-Llama-3.1-8B"

# ===== Utilidades de prompting =====
def alpaca_format(instruction: str, response: str = "") -> str:
    return f"### Instruction:\n{instruction}\n\n### Response:\n{response}"

def build_prompt(text: str) -> str:
    return f"""
Eres un analista técnico. Te paso el texto de un PDF entre <document>…</document>.
Resume el contenido en 3–5 líneas, estilo telegráfico y preciso. Evita redundancias.

<document>
{text}
</document>
""".strip()


# ===== Lectura y limpieza del PDF =====
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


# ===== Heurísticas de títulos / secciones =====
RE_NUMERIC_HEADING = re.compile(r"^\s*\d+(\.\d+)*\s+[A-ZÁÉÍÓÚÑ0-9].{2,}$")
RE_ALLCAPS_HEADING = re.compile(r"^[A-ZÁÉÍÓÚÑ0-9][A-ZÁÉÍÓÚÑ0-9\s\-–,:;.()]{4,}$")
RE_SPECIAL = re.compile(r"^(CAP[IÍ]TULO|ANEXO|AP[EÉ]NDICE)\b", re.I)

def looks_like_heading(line: str) -> bool:
    s = line.strip()
    if len(s) > 120:
        return False
    if RE_INDEX_LINE.search(s) or RE_TRAILING_PAGENUM.search(s):
        return False
    return bool(
        RE_NUMERIC_HEADING.match(s)
        or RE_SPECIAL.match(s)
        or (RE_ALLCAPS_HEADING.match(s) and " " in s)
    )

def split_into_sections(text: str) -> List[Tuple[str, str]]:
    """Devuelve [(titulo, cuerpo), ...] en orden."""
    lines = [ln for ln in text.splitlines()]
    sections: List[Tuple[str, str]] = []
    cur_title, cur_buf = None, []

    def push():
        nonlocal cur_title, cur_buf
        if cur_title and cur_buf:
            body = "\n".join(cur_buf).strip()
            if body:
                sections.append((cur_title.strip(), body))
        cur_title, cur_buf = None, []

    for ln in lines:
        if looks_like_heading(ln):
            push()
            cur_title = ln.strip()
        else:
            if cur_title is None:
                cur_title = "Preámbulo"
            cur_buf.append(ln)
    push()
    return sections


# ===== Empaquetado por frases (antes de tokens) =====
def split_by_sentences_pack(text: str, min_len=800, max_len=1200):
    """
    Junta frases hasta ~max_len. Si aún quedan bloques demasiado largos en tokens,
    se re-dividirán con split_by_tokens().
    """
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


# ===== Corte por tokens con solape =====
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
        start = max(0, end - overlap)
    return chunks


# ===== Carga de modelo y utilidades de resumen =====
device = "cuda" if torch.cuda.is_available() else "cpu"
tokenizer = AutoTokenizer.from_pretrained(model_name, use_fast=False)
if tokenizer.pad_token is None:
    tokenizer.pad_token = tokenizer.eos_token

if device.startswith("cuda"):
    model = AutoModelForCausalLM.from_pretrained(
        model_name,
        torch_dtype=torch.float16,
        low_cpu_mem_usage=True,
    ).to(device)
else:
    model = AutoModelForCausalLM.from_pretrained(
        model_name,
        torch_dtype=torch.float32,
    ).to(device)

@torch.no_grad()
def generate_summary(text: str) -> str:
    prompt = alpaca_format(build_prompt(text), "")
    inputs = tokenizer([prompt], return_tensors="pt").to(device)
    out = model.generate(
        **inputs,
        max_new_tokens=max_new_tokens,
        do_sample=False,
        use_cache=True,
        eos_token_id=tokenizer.eos_token_id,
    )
    decoded = tokenizer.decode(out[0], skip_special_tokens=True)
    if "### Response:" in decoded:
        decoded = decoded.split("### Response:", 1)[-1]
    return decoded.strip()


# ===== Orquestación completa =====
def resumir_pdf(pdf_path: str, salida_json: str = "resumen2.json"):
    pdf_text = read_pdf_text(pdf_path)
    sections = split_into_sections(pdf_text)

    resumenes = []
    for titulo, cuerpo in sections:
        # Empaqueta por frases
        packs = split_by_sentences_pack(cuerpo)

        # Asegura límite de tokens con solape
        trozos: List[str] = []
        for pack in packs if packs else [cuerpo]:
            # si excede el límite en tokens, redivide por tokens
            ids_len = len(tokenizer.encode(pack, add_special_tokens=False))
            if ids_len > max_input_tokens:
                trozos.extend(split_by_tokens(tokenizer, pack, max_input_tokens, overlap_tokens))
            else:
                trozos.append(pack)

        # Resumen por trozo 
        parciales = [generate_summary(t) for t in trozos if t.strip()]

        # Fusión dentro de la sección 
        if len(parciales) > 1:
            fusion_text = "\n".join(f"- {p}" for p in parciales if p)
            resumen_final = generate_summary(
                f"Fusiona en 3–5 líneas los siguientes subresúmenes de la sección '{titulo}':\n{fusion_text}"
            )
        else:
            resumen_final = parciales[0] if parciales else ""

        if resumen_final:
            resumenes.append({"apartado": titulo, "resumen": resumen_final})

    # Guardar JSON final
    data = {"resumenes": resumenes}
    Path(salida_json).write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Guardado: {salida_json}")


if __name__ == "__main__":
    pdf_path = "pruebas.pdf"
    resumir_pdf(pdf_path, "resumen.json")
