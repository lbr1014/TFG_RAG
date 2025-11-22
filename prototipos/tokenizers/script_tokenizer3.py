# guardar como script_tokenizer_fix.py
import re
import json
from pathlib import Path
from typing import List, Tuple, Dict

import torch
from pypdf import PdfReader
from transformers import AutoTokenizer, AutoModelForCausalLM

# =========================
# 0) Parámetros de modelo y ventanas
# =========================
max_seq_length = 2048
max_new_tokens = 256
prompt_reserva = 200  # margen para instrucciones
max_input_tokens = max_seq_length - max_new_tokens - prompt_reserva
overlap_tokens = 60
model_name = "meta-llama/Meta-Llama-3.1-8B"

# =========================
# 1) Utilidades de prompting/tokenizer (estrategia del libro)
# =========================
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

def split_by_sentences_pack(text: str, min_len=800, max_len=1200) -> List[str]:
    """
    Paso previo recomendado en el handbook:
    Empaqueta por frases hasta ~max_len para evitar cortes a mitad de oración.
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

def split_by_tokens(tokenizer, text: str, max_tokens: int, overlap: int = 50) -> List[str]:
    """
    Corte consciente de tokens con solape para mantener contexto entre fragmentos.
    """
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

# =========================
# 2) Lectura y limpieza PDF (ignorar índice)
# =========================
DOTS = r"[.\·•·∙⋅··…]"
RE_INDEX_LINE = re.compile(rf"^\s*\d*(\.\d+)*\s*[^\d{DOTS}]+?\s{DOTS}{{4,}}\s*\d{{1,4}}\s*$")
RE_TRAILING_PAGENUM = re.compile(rf"{DOTS}{{3,}}\s*\d{{1,4}}\s*$")
RE_HEADER_FOOTER = re.compile(r"^\s*(Página\s+\d+|ÍNDICE|INDEX|CONTENIDOS?)\s*$", re.I)

def limpiar_linea(s: str) -> str:
    s = s.replace("\u00A0", " ")  # nbsp
    s = re.sub(r"[ \t]+", " ", s)
    return s.strip()

def clean_page(text: str) -> str:
    out = []
    for ln in (text or "").splitlines():
        s = limpiar_linea(ln)
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

def read_pdf_text(path: str) -> List[str]:
    """
    Devuelve lista de líneas limpias (sin índices/cabeceras).
    """
    reader = PdfReader(path)
    lineas: List[str] = []
    for page in reader.pages:
        txt = clean_page(page.extract_text() or "")
        lineas.extend(txt.splitlines())
    # Filtra vacías
    return [l for l in lineas if l]

def es_linea_indice(s: str) -> bool:
    s_clean = limpiar_linea(s)
    puntos_relleno = re.search(r"(?:\.\s*){3,}|·{3,}|…{1,}", s_clean)
    termina_en_numero = re.search(r"\d+\s*$", s_clean) is not None
    es_corta = len(s_clean) < 160
    return (puntos_relleno and termina_en_numero and es_corta) or (
        termina_en_numero and "ÍNDICE" in s_clean.upper()
    )

def filtrar_indice(lineas: List[str]) -> List[str]:
    res: List[str] = []
    en_indice = False
    for l in lineas:
        u = l.upper()
        if not en_indice and ("ÍNDICE" in u or "INDICE" in u):
            en_indice = True
            continue
        if en_indice:
            if es_linea_indice(l):
                continue
            # salimos del bloque al detectar primer título real
            if es_titulo_seccion(l)[0]:
                en_indice = False
                res.append(l)
            else:
                continue
        else:
            if es_linea_indice(l):
                continue
            res.append(l)
    return res

# =========================
# 3) Detección de secciones
#    (numeración inicial y termina en letra, no dígito)
# =========================
RE_TITULO = re.compile(
    r"""
    ^\s*
    (?P<num>\d+(?:\.\d+)*)      # 1 / 1.1 / 1.4.1 ...
    [\s\-—:]+
    (?P<titulo>.*\S)            # algún texto no vacío
    \s*$
    """,
    re.VERBOSE,
)

def es_titulo_seccion(linea: str) -> Tuple[bool, str]:
    s = limpiar_linea(linea)
    if not s:
        return False, ""
    # fuera cualquier patrón típico de índice
    if es_linea_indice(s):
        return False, ""
    if re.search(r"(?:\.\s*){3,}|·{3,}|…{1,}", s):
        return False, ""
    m = RE_TITULO.match(s) or re.match(r"^\s*(\d+(?:\.\d+)*)\s+(.*\S)\s*$", s)
    if not m:
        return False, ""
    # clave: el TÍTULO debe ACABAR EN LETRA (no en dígito)
    if re.search(r"\d\s*$", s):
        return False, ""
    return True, s

def secciones_desde_lineas(lineas: List[str]) -> List[Tuple[str, List[str]]]:
    secciones: List[Tuple[str, List[str]]] = []
    titulo_actual: str | None = None
    buffer: List[str] = []
    for l in lineas:
        es_tit, titulo = es_titulo_seccion(l)
        if es_tit:
            if titulo_actual is not None:
                secciones.append((titulo_actual, buffer))
            titulo_actual = titulo
            buffer = []
        else:
            if titulo_actual is not None:
                buffer.append(l)
    if titulo_actual is not None:
        secciones.append((titulo_actual, buffer))
    return secciones

# =========================
# 4) Carga de modelo (un solo device) y generación
# =========================
device = "cuda:0" if torch.cuda.is_available() else "cpu"

tokenizer = AutoTokenizer.from_pretrained(model_name, use_fast=False)
if tokenizer.pad_token is None:
    tokenizer.pad_token = tokenizer.eos_token  # para evitar warnings en generate

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
    enc = tokenizer(
        [prompt],
        return_tensors="pt",
        padding=True,
        truncation=False,  # ya limitamos por tokens antes
    )
    # mueve inputs al mismo device que el modelo
    model_device = next(model.parameters()).device
    enc = {k: v.to(model_device) for k, v in enc.items()}

    out = model.generate(
        **enc,
        max_new_tokens=max_new_tokens,
        do_sample=False,
        use_cache=True,
        eos_token_id=tokenizer.eos_token_id,
        pad_token_id=tokenizer.pad_token_id,
    )
    decoded = tokenizer.decode(out[0], skip_special_tokens=True)
    if "### Response:" in decoded:
        decoded = decoded.split("### Response:", 1)[-1]
    return decoded.strip()

# =========================
# 5) Resumen por sección con Map-Reduce
# =========================
def resumir_secciones(secciones: List[Tuple[str, List[str]]]) -> List[Dict[str, str]]:
    resultados: List[Dict[str, str]] = []
    for titulo, contenido in secciones:
        cuerpo = "\n".join(contenido).strip()
        if not cuerpo:
            continue

        # Paso A: empaquetar por frases (evitar cortes raros)
        packs = split_by_sentences_pack(cuerpo)

        # Paso B: asegurar límite de tokens (con solape)
        trozos: List[str] = []
        for pack in packs if packs else [cuerpo]:
            ids_len = len(tokenizer.encode(pack, add_special_tokens=False))
            if ids_len > max_input_tokens:
                trozos.extend(split_by_tokens(tokenizer, pack, max_input_tokens, overlap_tokens))
            else:
                trozos.append(pack)

        # Paso C (Map): resumen por trozo
        parciales = [generate_summary(t) for t in trozos if t.strip()]

        # Paso D (Reduce): fusión de resúmenes de la sección
        if len(parciales) > 1:
            fusion_text = "\n".join(f"- {p}" for p in parciales if p)
            resumen_final = generate_summary(
                f"Fusiona en 3–5 líneas los siguientes subresúmenes de la sección '{titulo}':\n{fusion_text}"
            )
        else:
            resumen_final = parciales[0] if parciales else ""

        if resumen_final:
            resultados.append({"apartado": titulo, "resumen": resumen_final})
    return resultados

# =========================
# 6) Orquestación
# =========================
def procesar_pdf(pdf_path: str) -> List[Dict[str, str]]:
    lineas = read_pdf_text(pdf_path)
    lineas = filtrar_indice(lineas)
    seccs = secciones_desde_lineas(lineas)
    return resumir_secciones(seccs)

def main(pdf_path: str, salida_json: str = "resumen.json"):
    resumenes = procesar_pdf(pdf_path)
    data = {"resumenes": resumenes}
    Path(salida_json).write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Guardado: {salida_json} ({len(resumenes)} secciones)")

if __name__ == "__main__":
    # Cambia esta ruta por tu PDF real
    PDF = "DOC20251103115131003_Proyecto_visado_11E25.pdf"
    main(PDF, "resumen.json")
