import torch
from pathlib import Path
from pypdf import PdfReader
from transformers import AutoTokenizer, AutoModelForCausalLM, TextStreamer

max_seq_length = 2048
max_new_tokens = 256
model_name="meta-llama/Meta-Llama-3.1-8B"


def alpaca_format(instruction: str, response: str = "") -> str:
    return f"### Instruction:\n{instruction}\n\n### Response:\n{response}"


def read_pdf(path: str) -> str:
    reader = PdfReader(path)
    return "\n".join(page.extract_text() or "" for page in reader.pages)


def chunk(text: str, max_chars: int = 6000) -> str:
    return text[:max_chars]


pdf_path = "DOC20251103115131003_Proyecto_visado_11E25.pdf"
pdf_text = read_pdf(pdf_path)

promp = (
    "A continuación tienes el texto extraído de un PDF. "
    "Conociendo el indice explica cada uno de sus apartados brevemente. "
    "No copies los índices:\n\n"
    f"{pdf_text}"
)

message = alpaca_format(promp, "")

# Tokenizar con el tokenizer del modelo (clave para evitar errores de ids/espaciado)
device = "cuda" if torch.cuda.is_available() else "cpu"

# Carga de tokenizer y modelo
tokenizer = AutoTokenizer.from_pretrained(model_name, use_fast=False)
model = AutoModelForCausalLM.from_pretrained(
    model_name,
    torch_dtype=torch.float16 if device == "cuda" else torch.float32,
    device_map="auto" if device == "cuda" else None,
)

inputs = tokenizer([message], return_tensors="pt").to(device)

# Generar (con streaming de tokens)
streamer = TextStreamer(tokenizer)
_ = model.generate(
    **inputs,
    streamer=streamer,
    max_new_tokens=max_new_tokens,
    use_cache=True,
)

save_dir = Path("model")
save_dir.mkdir(exist_ok=True)
model.save_pretrained(save_dir)
tokenizer.save_pretrained(save_dir)


