import torch
from transformers import TextStreamer
from unsloth import FastLanguageModel
from pypdf import PdfReader
from pathlib import Path

max_seq_length = 2048
model, tokenizer = FastLanguageModel.from_pretrained(
    model_name="meta-llama/Meta-Llama-3.1-8B",
    max_seq_length=max_seq_length,
    load_in_4bit=False,
)

# Preparar modelo para inferencia
FastLanguageModel.for_inference(model)


# Formatear el prompt con tu plantilla de chat
def alpaca_format(instruction: str, response: str = "") -> str:
    return f"### Instruction:\n{instruction}\n\n### Response:\n{response}"


def read_pdf(path: str) -> str:
    reader = PdfReader(path)
    return "\n".join(page.extract_text() or "" for page in reader.pages)


def chunk(text: str, max_chars: int = 6000) -> str:
    return text[:max_chars]


pdf_path = "DOC20251103115131003_Proyecto_visado_11E25.pdf"
pdf_text = chunk(read_pdf(pdf_path))
message = alpaca_format("Escribe un párrafo sobre SFT.", "")

# Tokenizar con el tokenizer del modelo (clave para evitar errores de ids/espaciado)
device = "cuda" if torch.cuda.is_available() else "cpu"
inputs = tokenizer([message], return_tensors="pt").to(device)

# Generar (con streaming de tokens)
streamer = TextStreamer(tokenizer)
_ = model.generate(
    **inputs,
    streamer=streamer,
    max_new_tokens=256,
    use_cache=True,
)

# Guardar/push modelo + tokenizer juntos (consistencia en despliegue)
model.save_pretrained_merged("model", tokenizer, save_method="merged_16bit")
# model.push_to_hub_merged("tu-usuario/tu-modelo", tokenizer, save_method="merged_16bit")  # noqa: E501

