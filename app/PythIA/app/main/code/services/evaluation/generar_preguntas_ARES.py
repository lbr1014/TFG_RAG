"""
Genera preguntas y respuestas de referencia para construir un dataset ARES.

Este módulo recupera fragmentos de texto (chunks) de la base de datos vectorial,
genera pares pregunta-respuesta automáticamente usando un modelo LLM, y almacena
el conjunto de preguntas validadas en un archivo JSON.

Autor:
    Lydia Blanco Ruiz

Configuration (via variables de entorno):
    OLLAMA_MODEL: Modelo LLM a usar para generar preguntas.
    ARES_QUESTIONS_PATH: Ruta de salida para el archivo JSON de preguntas.
    ARES_FORCE_REGENERATE: Si es "1", fuerza la regeneración de preguntas.
    ARES_NUM_QUESTIONS: Número objetivo de preguntas a generar.
    ARES_MAX_SOURCE_CHUNKS: Número máximo de chunks a procesar.
    ARES_QAS_PER_CHUNK: Número de pares Q&A a solicitar por chunk.
"""

import asyncio
import json
import os
import random
import re
from pathlib import Path

from app.main.code.services.rag.PrototipoRAG import VectorBaseDocument, ask_ollama

PROMPT_QA_FROM_CHUNK = """
Eres un experto en contratacion publica y pliegos (PCAP/PPT).
A partir del TEXTO, genera exactamente {n} pares (pregunta, respuesta) que se puedan responder SOLO con ese texto.

Reglas:
- Preguntas especificas y verificables; evita cuestiones generales.
- Deben cubrir detalles tipicos de pliegos: criterios de adjudicacion, solvencia, garantias, plazos, penalidades, condiciones tecnicas y documentacion.
- La RESPUESTA debe ser breve y estar sustentada por el texto.
- Si el texto no contiene informacion suficiente para una pregunta, no la inventes: genera otra distinta.
- Devuelve SOLO JSON valido con esta forma:
[
  {{
    "question": "...",
    "answer": "...",
    "evidence": "cita literal corta del texto (max 25 palabras)"
  }}
]

TEXTO:
\"\"\"{chunk}\"\"\"
"""

QUESTIONS_PATH = Path(os.getenv("ARES_QUESTIONS_PATH", "questions_auto_ARES.json"))
FORCE_REGENERATE = os.getenv("ARES_FORCE_REGENERATE", "0") == "1"


def iter_chunks(limit_total: int = 2000, batch: int = 100) -> list[VectorBaseDocument]:
    """
    Recupera lotes de chunks almacenados en la base vectorial.

    Realiza consultas paginadas a la base de datos para recuperar chunks,
    acumulando resultados hasta alcanzar el límite total especificado.

    Args:
        limit_total: Número máximo total de chunks a recuperar. Por defecto 2000.
        batch: Número de chunks solicitados en cada consulta paginada. Por defecto 100.

    Returns:
        list[VectorBaseDocument]: Lista acumulada de chunks recuperados.
    """
    docs = []
    offset = None
    got = 0
    while got < limit_total:
        batch_docs, offset = VectorBaseDocument.bulk_find(limit=batch, offset=offset)
        if not batch_docs:
            break
        docs.extend(batch_docs)
        got += len(batch_docs)
        if offset is None:
            break
    return docs


def clean_chunk(text: str) -> str:
    """
    Normaliza el texto de un chunk eliminando espacios redundantes.

    Reemplaza múltiples espacios en blanco (espacios, saltos de línea, tabulaciones)
    con un único espacio y elimina espacios en los extremos.

    Args:
        text: Texto original del chunk.

    Returns:
        str: Texto limpio y compacto sin espacios redundantes.
    """
    return re.sub(r"\s+", " ", (text or "")).strip()


def good_chunk(text: str) -> bool:
    """
    Valida si un chunk es adecuado para generar preguntas.

    Comprueba que el chunk cumpla criterios de longitud y calidad:
    - Longitud entre 500 y 4000 caracteres.
    - No está dominado por saltos de página (máximo 5 apariciones de \"Pagina\").

    Args:
        text: Texto del chunk a validar.

    Returns:
        bool: True si el chunk cumple los criterios, False en caso contrario.
    """
    if not text:
        return False
    if len(text) < 500:
        return False
    if len(text) > 4000:
        return False
    if text.count("Pagina") > 5 or text.count("Pág") > 5:
        return False
    return True


def generate_qas_for_chunk(chunk: str, n: int = 2, model: str | None = None) -> list[dict]:
    """
    Genera pares de pregunta-respuesta a partir de un chunk.

    Utiliza un modelo LLM para generar automáticamente n pares de preguntas
    y respuestas que puedan ser respondidas usando el contenido del chunk.

    Args:
        chunk: Fragmento de texto usado como contexto para generar preguntas.
        n: Número de pares pregunta-respuesta a solicitar al modelo. Por defecto 2.
        model: Nombre del modelo de Ollama a utilizar. Si es None, usa OLLAMA_MODEL.

    Returns:
        list[dict]: Lista de pares pregunta-respuesta validados como JSON.
                   Cada elemento contiene \"question\", \"answer\" y \"evidence\".
    """
    model = model or os.getenv("OLLAMA_MODEL", "llama3.1:8b-instruct-q4_K_M")
    prompt = PROMPT_QA_FROM_CHUNK.format(n=n, chunk=chunk)
    raw = asyncio.run(ask_ollama(prompt, model=model))
    try:
        data = json.loads(raw)
    except Exception:
        return []

    if not isinstance(data, list):
        return []
    return [item for item in data if isinstance(item, dict)]


def pass_quality(question: str, answer: str, evidence: str, chunk: str) -> bool:
    """
    Comprueba si una pregunta generada cumple los criterios mínimos.

    Valida que la pregunta, respuesta y evidencia sean suficientemente robustas:
    - Todos los campos deben estar presentes y no vacíos.
    - La pregunta debe tener al menos 6 palabras.
    - La evidencia debe aparecer literalmente en el chunk.

    Args:
        question: Pregunta candidata.
        answer: Respuesta candidata.
        evidence: Evidencia literal asociada (cita del chunk).
        chunk: Texto fuente del que procede la evidencia.

    Returns:
        bool: True si la pregunta cumple todos los criterios, False en caso contrario.
    """
    if not question or not answer or not evidence:
        return False
    if len(question.split()) < 6:
        return False
    if evidence not in chunk:
        return False
    return True


def main() -> None:
    """
    Genera y guarda automáticamente un conjunto de preguntas ARES.

    Orquesta el pipeline completo: recupera chunks, los filtra por calidad,
    genera pares pregunta-respuesta con LLM, aplica filtros de validación,
    elimina duplicados y guarda el conjunto final en ARES_QUESTIONS_PATH.

    Args:
        None.

    Returns:
        None.

    Raises:
        SystemExit: Si no se pueden generar preguntas automáticamente (dataset vacío).
    """
    if QUESTIONS_PATH.exists() and not FORCE_REGENERATE:
        print(f"Questions file already exists: {QUESTIONS_PATH}. Skipping generation.")
        return

    print("Starting question generation...")
    random.seed(7)

    docs = iter_chunks(limit_total=3000)
    print(f"Retrieved {len(docs)} chunks from database")
    chunks = [clean_chunk(d.content) for d in docs]
    chunks = [c for c in chunks if good_chunk(c)]
    print(f"After filtering, {len(chunks)} good chunks remain")
    random.shuffle(chunks)

    questions = []
    seen = set()
    target_questions = int(os.getenv("ARES_NUM_QUESTIONS", "10"))
    max_chunks = int(os.getenv("ARES_MAX_SOURCE_CHUNKS", "200"))
    qas_per_chunk = int(os.getenv("ARES_QAS_PER_CHUNK", "2"))
    print(f"Target: generate {target_questions} questions")

    processed_chunks = 0
    for chunk in chunks[:max_chunks]:
        processed_chunks += 1
        if processed_chunks % 10 == 0:
            print(
                f"Processed {processed_chunks} chunks, generated {len(questions)} questions so far"
            )

        qas = generate_qas_for_chunk(chunk, n=qas_per_chunk)
        print(f"Generated {len(qas)} Q&A pairs from chunk {processed_chunks}")

        for item in qas:
            question = (item.get("question") or "").strip()
            answer = (item.get("answer") or "").strip()
            evidence = (item.get("evidence") or "").strip()

            key = question.lower()
            if key in seen:
                continue
            if not pass_quality(question, answer, evidence, chunk):
                continue

            seen.add(key)
            questions.append(
                {
                    "question": question,
                    "ground_truth": answer,
                    "evidence": evidence,
                }
            )

            if len(questions) >= target_questions:
                break

        if len(questions) >= target_questions:
            break

    if not questions:
        raise SystemExit("No se pudieron generar preguntas automaticamente.")

    with open(QUESTIONS_PATH, "w", encoding="utf-8") as fh:
        json.dump(questions, fh, ensure_ascii=False, indent=2)

    print(f"Generadas {len(questions)} preguntas en {QUESTIONS_PATH}")


if __name__ == "__main__":
    main()
