from __future__ import annotations

import logging
import re
import time
import unicodedata
from typing import Any, Dict, Optional

from flask_login import current_user

from app.extensions import db
from app.consulta import Consulta
from app.chunk import Chunk
from app.consultaChunk import ConsultaChunk
from app.inetrnacionalizacion.tarduccion import translate_for
logger = logging.getLogger(__name__)

from .PrototipoRAG import OllamaTimeoutError, QueryCancelledError, obtener_mejor_chunk
from qdrant_client import models as qmodels

EMPTY_ANSWER: Dict[str, Any] = {
    "answer": "",
    "title": "",
    "filename": "",
    "segment_index": -1,
    "chunk": "",
}

EXPEDIENTE_KEYWORDS = {
    "administrativo",
    "administrativa",
    "administrativos",
    "administrativas",
    "tecnico",
    "tecnica",
    "tecnicos",
    "tecnicas",
    "pliego",
    "pliegos",
    "documento",
    "documentos",
    "sobre",
    "del",
    "de",
    "que",
    "y",
    "o",
}


def normalize_text(value: str | None) -> str:
    value = (value or "").strip().lower()
    if not value:
        return ""
    normalized = unicodedata.normalize("NFKD", value)
    normalized = "".join(ch for ch in normalized if not unicodedata.combining(ch))
    return re.sub(r"\s+", " ", normalized).strip()


def detect_tipo_documento(question: str) -> str | None:
    normalized = normalize_text(question)
    asks_admin = any(
        token in normalized
        for token in (
            "pliego administrativo",
            "pliegos administrativos",
            "clausulas administrativas",
            "clausula administrativa",
        )
    )
    asks_tech = any(
        token in normalized
        for token in (
            "pliego tecnico",
            "pliegos tecnicos",
            "prescripciones tecnicas",
            "prescripcion tecnica",
        )
    )

    if asks_admin and not asks_tech:
        return "administrativo"
    if asks_tech and not asks_admin:
        return "tecnico"
    return None


def extract_expediente_candidate(question: str) -> str | None:
    question = (question or "").strip()
    if not question:
        return None

    quoted = re.search(
        r'expediente(?:\s+n[uú]mero|\s+n[ºo.]?)?\s*[:#-]?\s*["“](.+?)["”]',
        question,
        re.IGNORECASE,
    )
    if quoted:
        return quoted.group(1).strip() or None

    match = re.search(
        r"expediente(?:\s+n[uú]mero|\s+n[ºo.]?)?\s*[:#-]?\s*([A-Za-z0-9][A-Za-z0-9/_.-]*(?:\s+[A-Za-z0-9][A-Za-z0-9/_.-]*){0,5})",
        question,
        re.IGNORECASE,
    )
    if not match:
        return None

    words = match.group(1).strip().split()
    while words and normalize_text(words[-1]) in EXPEDIENTE_KEYWORDS:
        words.pop()
    candidate = " ".join(words).strip(" ,.;:")
    return candidate or None


def resolve_numero_expediente(question: str) -> str | None:
    candidate = extract_expediente_candidate(question)
    if not candidate:
        return None

    normalized_candidate = normalize_text(candidate)
    available = (
        db.session.query(Chunk.numero_expediente)
        .filter(Chunk.numero_expediente.isnot(None))
        .distinct()
        .all()
    )
    existing_values = [value for (value,) in available if value]

    for value in existing_values:
        if normalize_text(value) == normalized_candidate:
            return value

    compact_candidate = re.sub(r"[\s./_-]+", "", normalized_candidate)
    for value in existing_values:
        normalized_value = normalize_text(value)
        if re.sub(r"[\s./_-]+", "", normalized_value) == compact_candidate:
            return value

    return candidate

async def rag_answer(question: str, should_cancel=None, on_status=None, user_id: int | None = None, lang: str = "es") -> Dict[str, Any]:
    """
    Devuelve dict con:
      answer, title, filename, segment_index, chunk
    y además guarda la consulta en BBDD asociada al usuario logueado.
    """
    question = (question or "").strip()
    invalid = validate_question(question, lang=lang)
    if invalid:
        return invalid

    start = time.perf_counter()
    data: Dict[str, Any]
    numero_expediente = resolve_numero_expediente(question)
    tipo_documento = detect_tipo_documento(question)

    try:
        if on_status:
            on_status(translate_for(lang, "rag.preparing"))
        data = await obtener_mejor_chunk(
            question,
            should_cancel=should_cancel,
            on_status=on_status,
            numero_expediente=numero_expediente,
            tipo_documento=tipo_documento,
        )
    except QueryCancelledError:
        raise
    except OllamaTimeoutError as e:
        logger.warning("Timeout consultando Ollama: %s", e)
        data = message_error(translate_for(lang, "rag.timeout_error"))
    except Exception as e:
        logger.exception("Error en rag_answer: %s", e)
        data = message_error(translate_for(lang, "rag.system_error"))

    elapsed = time.perf_counter() - start

    # Guardado en BBDD
    try_persist(question, data, elapsed, user_id=user_id)

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

def validate_question(question: str, lang: str = "es") -> Optional[Dict[str, Any]]:
    if not question:
        return message_error(translate_for(lang, "rag.empty_question"))
    if len(question) > 2000:
        return message_error(translate_for(lang, "rag.question_too_long"))
    return None

def try_persist(question: str, data: Dict[str, Any], elapsed: float, user_id: int | None = None) -> None:
    try:
        persist_consulta(question, data, elapsed, user_id=user_id)
    except Exception:
        logger.exception("No se pudo guardar la consulta en BBDD")
        db.session.rollback()
        
def persist_consulta(question: str, data: Dict[str, Any], elapsed: float, user_id: int | None = None) -> None:
    owner_id = user_id
    if owner_id is None and current_user and getattr(current_user, "is_authenticated", False):
        owner_id = int(current_user.id)

    if owner_id is not None:
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
            user_id=int(owner_id),
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
