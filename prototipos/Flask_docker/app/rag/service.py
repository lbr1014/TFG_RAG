from __future__ import annotations

import logging
import time
from typing import Any, Dict, Optional

from flask_login import current_user

from app.extensions import db
from app.consulta import Consulta
from app.chunk import Chunk
from app.consultaChunk import ConsultaChunk
from sqlalchemy import or_

logger = logging.getLogger(__name__)

from .PrototipoRAG import obtener_mejor_chunk
from qdrant_client import models as qmodels

EMPTY_ANSWER: Dict[str, Any] = {
    "answer": "",
    "title": "",
    "filename": "",
    "segment_index": -1,
    "chunk": "",
}

def rag_answer(question: str) -> Dict[str, Any]:
    """
    Devuelve dict con:
      answer, title, filename, segment_index, chunk
    y además guarda la consulta en BBDD asociada al usuario logueado.
    """
    question = (question or "").strip()
    invalid = validate_question(question)
    if invalid:
        return invalid

    start = time.perf_counter()
    data: Dict[str, Any]

    try:
        data = obtener_mejor_chunk(question)
    except Exception as e:
        logger.exception("Error en rag_answer: %s", e)
        data = message_error("Ha ocurrido un error consultando el sistema. Inténtalo de nuevo.")

    elapsed = time.perf_counter() - start

    # Guardado en BBDD
    try_persist(question, data, elapsed)

    data["elapsed_s"] = round(elapsed, 4)
    # Mejor chunk (ranking 1) para el front
    best_point_id = ""
    retrieved = data.get("retrieved") or []
    if retrieved:
        best_point_id = (retrieved[0].get("qdrant_point_id") or "").strip()

    data["qdrant_point_id"] = best_point_id
    return data

def message_error(msg: str) -> Dict[str, Any]:
    out = dict(EMPTY_ANSWER)
    out["answer"] = msg
    return out

def validate_question(question: str) -> Optional[Dict[str, Any]]:
    if not question:
        return message_error("Escribe una pregunta.")
    if len(question) > 2000:
        return message_error("La pregunta es demasiado larga (máx. 2000 caracteres).")
    return None

def try_persist(question: str, data: Dict[str, Any], elapsed: float) -> None:
    try:
        persist_consulta(question, data, elapsed)
    except Exception:
        logger.exception("No se pudo guardar la consulta en BBDD")
        db.session.rollback()
        
def persist_consulta(question: str, data: Dict[str, Any], elapsed: float) -> None:
    if current_user and getattr(current_user, "is_authenticated", False):

        consulta = Consulta(
            user_id=int(current_user.id),
            pregunta=question,
            respuesta=str(data.get("answer", "")),
            tiempo_respuestas=float(elapsed),
        )
        db.session.add(consulta)
        db.session.flush()
        
        retrieved = data.get("retrieved", []) or []
        for item in retrieved[:10]:
            chunk_obj = find_chunk(item)
                    
            if chunk_obj is None:
                continue

            db.session.add(
                ConsultaChunk(
                    consulta_id=int(consulta.id),
                    chunk_id=int(chunk_obj.id),
                    similitud=float(item.get("similitud", 0.0)),
                    ranking=int(item.get("ranking", 0)),
                )
            )

        db.session.commit()
        
def find_chunk(item: dict)-> Optional["Chunk"]:
    chunk_obj = None
    qid = (item.get("qdrant_point_id") or "").strip()
    if qid:
        chunk_obj = Chunk.query.filter_by(qdrant_point_id=qid).first()
        
    if chunk_obj is None:
        doc_id = item.get("document_id")
        doc_sha = item.get("doc_sha256")
        seg_idx = item.get("segment_index")
        if doc_id is not None and doc_sha and seg_idx is not None:
            chunk_obj = Chunk.query.filter_by(
                document_id=int(doc_id),
                doc_sha256=str(doc_sha),
                segment_index=int(seg_idx),
            ).first()
    return chunk_obj


def qdrant_search_with_scores(qdrant, collection_name: str, query_vector: list[float], limit: int = 10):
    """
    Devuelve lista de ScoredPoint de Qdrant (incluye .id y .score).
    """
    res = qdrant.query_points(
        collection_name=collection_name,
        query=query_vector,
        limit=limit,
        with_payload=True,
        with_vectors=False,
    )
    return getattr(res, "points", res) 