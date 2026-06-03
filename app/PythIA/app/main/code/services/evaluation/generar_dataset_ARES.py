"""
Genera el dataset de evaluación para ARES a partir de preguntas predefinidas.

Este módulo lee preguntas almacenadas en JSON, ejecuta las preguntas a través del
sistema RAG para obtener respuestas y documentos recuperados, y crea un dataset
de evaluación en formatos JSON y TSV.

Autor:
    Lydia Blanco Ruiz

Configuration (via variables sde entorno):
    ARES_DATASET_JSON_PATH: Ruta de salida para el archivo JSON.
    ARES_DATASET_TSV_PATH: Ruta de salida para el archivo TSV.
    ARES_QUESTIONS_PATH: Ruta del archivo de preguntas JSON de entrada.
    ARES_FORCE_REGENERATE: Si es "1", fuerza la regeneración del dataset.
"""

import asyncio
import json
import os
from pathlib import Path

import pandas as pd

OUT_JSON = Path(os.getenv("ARES_DATASET_JSON_PATH", "ares_dataset.json"))
OUT_TSV = Path(os.getenv("ARES_DATASET_TSV_PATH", "dataset_auto_ARES.tsv"))
QUESTIONS_PATH = Path(os.getenv("ARES_QUESTIONS_PATH", "questions_auto_ARES.json"))
FORCE_REGENERATE = os.getenv("ARES_FORCE_REGENERATE", "0") == "1"


def main() -> None:
    """
    Construye y exporta el dataset base para la evaluación ARES.

    Lee preguntas de un archivo JSON, ejecuta el pipeline RAG para obtener respuestas
    y documentos recuperados, y exporta el dataset en formatos JSON y TSV.

    Verifica si el dataset ya existe y omite la generación si FORCE_REGENERATE no es True.

    Args:
        None.

    Returns:
        None.

    Raises:
        SystemExit: Si el dataset generado está vacío o si questions_auto_ARES.json
            no contiene preguntas o Qdrant no tiene chunks indexados.
    """
    if OUT_JSON.exists() and OUT_TSV.exists() and not FORCE_REGENERATE:
        print(f"Dataset already exists: {OUT_JSON} and {OUT_TSV}. Skipping generation.")
        return

    with open(QUESTIONS_PATH, "r", encoding="utf-8") as fh:
        questions = json.load(fh)

    print(f"Loaded {len(questions)} questions from JSON")
    dataset = []

    # (import actualizado abajo)
    # Import correcto dentro de la app (evita depender de un módulo "RAG" inexistente).
    from app.main.code.services.rag.PrototipoRAG import obtener_mejor_chunk

    def obtener_mejor_chunk_sync(question: str) -> dict:
        return asyncio.run(obtener_mejor_chunk(question))

    for index, item in enumerate(questions):
        question = (item.get("question") or "").strip()
        if not question:
            continue

        print(f"Processing question {index + 1}/{len(questions)}: {question[:80]}...")

        try:
            result = obtener_mejor_chunk_sync(question)
        except Exception as exc:
            print(f"ERROR processing question {index + 1}: {exc}")
            continue

        dataset.append(
            {
                "question": question,
                "ground_truth": (item.get("ground_truth") or "").strip(),
                "evidence": (item.get("evidence") or "").strip(),
                "documents": [c["chunk"] for c in (result.get("retrieved") or [])],
                "answer": (result.get("answer") or "").strip(),
            }
        )

    print(f"Processed {len(dataset)} questions successfully")

    if not dataset:
        raise SystemExit(
            "ERROR: dataset vacio. Revisa que questions_auto_ARES.json tenga preguntas y que Qdrant tenga chunks indexados."
        )

    with open(OUT_JSON, "w", encoding="utf-8") as fh:
        json.dump(dataset, fh, ensure_ascii=False, indent=2)

    df = pd.DataFrame(dataset)
    out = pd.DataFrame(
        {
            "Query": df["question"].astype(str),
            "Document": df["documents"].apply(
                lambda items: "\n\n".join(
                    [
                        s.strip()
                        for s in (items or [])
                        if isinstance(s, str) and s.strip()
                    ]
                )
            ),
            "Answer": df["answer"].astype(str),
        }
    )

    out.to_csv(OUT_TSV, sep="\t", index=False)
    print(f"OK -> {OUT_TSV} con columnas: {list(out.columns)} y {len(out)} filas")


if __name__ == "__main__":
    main()
