from __future__ import annotations

import logging
import time
from typing import Any, Dict

from flask_login import current_user

from app.extensions import db
from app.consulta import Consulta

logger = logging.getLogger(__name__)

from .PrototipoRAG import obtener_mejor_chunk


def rag_answer(question: str) -> Dict[str, Any]:
    """
    Devuelve dict con:
      answer, title, filename, segment_index, chunk
    y además guarda la consulta en BBDD asociada al usuario logueado.
    """
    question = (question or "").strip()
    if not question:
        return {
            "answer": "Escribe una pregunta.",
            "title": "",
            "filename": "",
            "segment_index": -1,
            "chunk": "",
        }

    if len(question) > 2000:
        return {
            "answer": "La pregunta es demasiado larga (máx. 2000 caracteres).",
            "title": "",
            "filename": "",
            "segment_index": -1,
            "chunk": "",
        }

    start = time.perf_counter()
    data: Dict[str, Any]

    try:
        data = obtener_mejor_chunk(question)
    except Exception as e:
        logger.exception("Error en rag_answer: %s", e)
        data = {
            "answer": "Ha ocurrido un error consultando el sistema. Inténtalo de nuevo.",
            "title": "",
            "filename": "",
            "segment_index": -1,
            "chunk": "",
        }

    elapsed = time.perf_counter() - start

    # Guardado en BBDD
    try:
        if current_user and getattr(current_user, "is_authenticated", False):
            fragmentos = {
                "title": data.get("title", ""),
                "filename": data.get("filename", ""),
                "segment_index": data.get("segment_index", -1),
                "chunks": [data.get("chunk", "")] if data.get("chunk") else [],
            }

            consulta = Consulta(
                user_id=int(current_user.id),
                pregunta=question,
                respuesta=str(data.get("answer", "")),
                fragmentos=fragmentos,
                tiempo_respuesta_s=float(elapsed),
            )
            db.session.add(consulta)
            db.session.commit()
    except Exception:
        logger.exception("No se pudo guardar la consulta en BBDD")
        db.session.rollback()

    data["elapsed_s"] = round(elapsed, 4)
    return data
