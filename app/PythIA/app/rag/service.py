from __future__ import annotations

import logging
import time
from typing import Any, Dict, Optional

from flask_login import current_user

from app.extensions import db
from app.consulta import Consulta
from app.chunk import Chunk
from app.consultaChunk import ConsultaChunk
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
        retrieved = data.get("retrieved", []) or []
        top_retrieved = retrieved[:10]
        chunk_links: list[tuple[dict[str, Any], Chunk]] = []
        fragmentos: list[dict[str, Any]] = []

        for item in top_retrieved:
            chunk_obj = find_chunk(item)
            if chunk_obj is not None:
                chunk_links.append((item, chunk_obj))
            fragmentos.append(build_fragmento(item, chunk_obj))

        consulta = Consulta(
            user_id=int(current_user.id),
            pregunta=question,
            respuesta=str(data.get("answer", "")),
            fragmentos=fragmentos,
            tiempo_respuestas=float(elapsed),
        )
        db.session.add(consulta)
        db.session.flush()

        
        for item, chunk_obj in chunk_links:
            db.session.add(
                ConsultaChunk(
                    consulta_id=int(consulta.id),
                    chunk_id=int(chunk_obj.id),
                    similitud=float(item.get("similitud", 0.0)),
                    ranking=int(item.get("ranking", 0)),
                )
            )

        db.session.commit()

def build_fragmento(item: dict[str, Any], chunk_obj: Optional["Chunk"]) -> dict[str, Any]:
    chunk_metadata = dict(item.get("metadata") or {})
    chunk = item.get("chunk", "") or ""
    document = getattr(chunk_obj, "document", None)

    if chunk_obj is not None:
        chunk_metadata.setdefault("chunk_id", int(chunk_obj.id))
        chunk_metadata.setdefault("document_id", int(chunk_obj.document_id))
        chunk_metadata.setdefault("doc_sha256", chunk_obj.doc_sha256)
        chunk_metadata.setdefault("segment_index", chunk_obj.segment_index)
        chunk_metadata.setdefault("n_chars", chunk_obj.n_chars)
        chunk_metadata.setdefault("n_tokens", chunk_obj.n_tokens)
        chunk_metadata.setdefault("qdrant_point_id", chunk_obj.qdrant_point_id)
        if chunk_obj.created_at is not None:
            chunk_metadata.setdefault("created_at", chunk_obj.created_at.isoformat())

    if document is not None:
        chunk_metadata.setdefault("document_name", document.nombre)
        chunk_metadata.setdefault("document_path", document.path)
        chunk_metadata.setdefault("document_hash", document.hash)

    for src_key, dst_key in (
        ("document_id", "document_id"),
        ("doc_sha256", "doc_sha256"),
        ("segment_index", "segment_index"),
        ("filename", "filename"),
        ("title", "title"),
        ("qdrant_point_id", "qdrant_point_id"),
    ):
        value = item.get(src_key)
        if value not in (None, ""):
            chunk_metadata.setdefault(dst_key, value)

    return {
        "ranking": int(item.get("ranking", 0)),
        "similitud": float(item.get("similitud", 0.0)),
        "qdrant_point_id": str(item.get("qdrant_point_id", "") or ""),
        "chunk": str(chunk),
        "metadata": chunk_metadata,
    }
        
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
