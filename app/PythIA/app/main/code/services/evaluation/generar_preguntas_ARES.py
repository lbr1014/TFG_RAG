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

from __future__ import annotations

import asyncio
import json
import os
import random
import re
import secrets
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
    return not (text.count("Pagina") > 5 or text.count("Pág") > 5)


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
    except json.JSONDecodeError:
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
    return evidence in chunk


def _build_shuffle_rng() -> secrets.SystemRandom | random.Random:
    """
    Construye un generador de números aleatorios para mezclar los chunks.
    
    Returns:
        secrets.SystemRandom: Si no se especifica una semilla, se utiliza un generador criptográficamente seguro.
        random.Random: Si se especifica una semilla a través de ARES_SHUFFLE_SEED, se utiliza un generador determinista con esa semilla.
    """
    shuffle_seed_raw = os.getenv("ARES_SHUFFLE_SEED")
    if shuffle_seed_raw is None or shuffle_seed_raw == "":
        print(
            "Shuffling chunks with a cryptographically secure RNG (ARES_SHUFFLE_SEED not set)"
        )
        return secrets.SystemRandom()

    print(f"Shuffling chunks with a deterministic seed (ARES_SHUFFLE_SEED={shuffle_seed_raw})")
    return random.Random(int(shuffle_seed_raw))


def _load_good_chunks() -> list[str]:
    """
    Recupera y filtra los chunks de la base de datos para obtener solo aquellos adecuados para generar preguntas.

    Returns:
        list[str]: Lista de chunks filtrados.
    """
    docs = iter_chunks(limit_total=3000)
    print(f"Retrieved {len(docs)} chunks from database")
    chunks_local = [clean_chunk(d.content) for d in docs]
    chunks_local = [c for c in chunks_local if good_chunk(c)]
    print(f"After filtering, {len(chunks_local)} good chunks remain")
    return chunks_local


def _accumulate_questions_config() -> tuple[int, int, int]:
    """
    Lee la configuración para la acumulación de preguntas desde variables de entorno.

    Returns:
        tuple[int, int, int]: Devuelve los parámetros necesarios para controlar el proceso de generación de preguntas:
            - target_questions: Número objetivo de preguntas a generar.
            - max_chunks: Número máximo de chunks a procesar para generar preguntas.
            - qas_per_chunk: Número de pares pregunta-respuesta a solicitar por cada chunk.

    """
    target_questions = int(os.getenv("ARES_NUM_QUESTIONS", "10"))
    max_chunks = int(os.getenv("ARES_MAX_SOURCE_CHUNKS", "200"))
    qas_per_chunk = int(os.getenv("ARES_QAS_PER_CHUNK", "2"))
    return target_questions, max_chunks, qas_per_chunk


def _try_add_question(
    *,
    questions: list[dict],
    seen: set[str],
    chunk: str,
    item: dict,
) -> None:
    """
    Intenta agregar una pregunta generada a la lista acumulada de preguntas, aplicando filtros de calidad y evitando duplicados.

    Args:
        questions (list[dict]): Lista acumulada de preguntas validadas a las que se intentará agregar la nueva pregunta si pasa los filtros.
        seen (set[str]): Conjunto de preguntas ya vistas (para evitar duplicados).
        chunk (str): El chunk de texto del que se generó la pregunta.
        item (dict): El par pregunta-respuesta generado.
    """
    question = (item.get("question") or "").strip()
    answer = (item.get("answer") or "").strip()
    evidence = (item.get("evidence") or "").strip()

    key = question.lower()
    if key in seen:
        return
    if not pass_quality(question, answer, evidence, chunk):
        return

    seen.add(key)
    questions.append(
        {
            "question": question,
            "ground_truth": answer,
            "evidence": evidence,
        }
    )


def _accumulate_questions(chunks_local: list[str]) -> list[dict]:
    """
    Procesa los chunks de texto para generar y acumular preguntas, aplicando filtros de calidad y evitando duplicados.

    Args:
        chunks_local (list[str]): Lista de chunks de texto limpios y filtrados que se usarán como contexto para generar preguntas.

    Returns:
        list[dict]: Lista de preguntas generadas y validadas.
    """
    questions_local: list[dict] = []
    seen_local: set[str] = set()
    target_questions, max_chunks, qas_per_chunk = _accumulate_questions_config()
    print(f"Target: generate {target_questions} questions")

    for idx, chunk in enumerate(chunks_local[:max_chunks], start=1):
        if idx % 10 == 0:
            print(f"Processed {idx} chunks, generated {len(questions_local)} questions so far")

        qas = generate_qas_for_chunk(chunk, n=qas_per_chunk)
        print(f"Generated {len(qas)} Q&A pairs from chunk {idx}")

        for item in qas:
            _try_add_question(
                questions=questions_local,
                seen=seen_local,
                chunk=chunk,
                item=item,
            )
            if len(questions_local) >= target_questions:
                return questions_local

    return questions_local


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
    rng = _build_shuffle_rng()
    chunks = _load_good_chunks()
    rng.shuffle(chunks)
    questions = _accumulate_questions(chunks)

    if not questions:
        raise SystemExit("No se pudieron generar preguntas automaticamente.")

    with open(QUESTIONS_PATH, "w", encoding="utf-8") as fh:
        json.dump(questions, fh, ensure_ascii=False, indent=2)

    print(f"Generadas {len(questions)} preguntas en {QUESTIONS_PATH}")


if __name__ == "__main__":
    main()
