"""
Autora: Lydia Blanco Ruiz
Script con la lógica de servicio para validar preguntas, consultar el sistema RAG y persistir resultados.
"""

from __future__ import annotations

import logging
import re
import time
import unicodedata
from typing import Any, Dict, Optional

from flask_login import current_user
from app.main.code.extensions import db
from app.main.code.model.chunk import Chunk
from app.main.code.model.consulta import Consulta
from app.main.code.inetrnacionalizacion.tarduccion import translate_for
logger = logging.getLogger(__name__)

from .PrototipoRAG import (
    OllamaModelNotFoundError,
    OllamaTimeoutError,
    QueryCancelledError,
    get_ollama_execution_device,
    obtener_mejor_chunk,
)
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
    """
    Normaliza un texto para comparación: minúsculas, sin acentos, espacios normalizados.

    Args:
        value: Texto a normalizar. Puede ser None.

    Returns:
        Texto normalizado: minúsculas, sin caracteres diacríticos,
        espacios consecutivos convertidos a uno solo, y sin espacios al inicio/fin.
        Retorna string vacío si el valor es None o vacío.
    """

    value = (value or "").strip().lower()

    if not value:

        return ""

    normalized = unicodedata.normalize("NFKD", value)
    normalized = "".join(ch for ch in normalized if not unicodedata.combining(ch))
    return re.sub(r"\s+", " ", normalized).strip()





def detect_tipo_documento(question: str) -> str | None:
    """
    Detecta si la pregunta se refiere a pliegos administrativos o técnicos.
    Analiza el texto de la pregunta para determinar si solicita información
    específica sobre pliegos administrativos o técnicos basándose en palabras clave.

    Args:
        question: Texto de la pregunta del usuario.

    Returns:
        "administrativo" si la pregunta menciona pliegos administrativos,
        "tecnico" si menciona pliegos técnicos,
        None si no se detecta un tipo específico o se mencionan ambos.
    """

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
    """
    Extrae un posible número de expediente de una pregunta usando expresiones regulares.
    Busca patrones comunes de referencia a expedientes en el texto de la pregunta,
    tanto entre comillas como en formatos estándar de expediente.

    Args:
        question: Texto de la pregunta que puede contener una referencia a expediente.

    Returns:
        Número de expediente candidato si se encuentra un patrón válido,
        None si no se encuentra ningún patrón o el candidato está vacío.
    """
    
    expediente_prefix = r"expediente(?:\s+n[uú]mero|\s+n[ºo]?)?"
    expediente_separator = r"\s*[:#-]?\s*"
    expediente_token = r"[A-Za-z0-9][A-Za-z0-9/_.-]*"
    expediente_smulti = rf"{expediente_token}(?:\s+{expediente_token}){{0,5}}"

    question = (question or "").strip()

    if not question:
        return None

    quoted_pattern = rf"{expediente_prefix}{expediente_separator}[\"“](.+?)[\"”]"
    quoted = re.search(quoted_pattern, question, re.IGNORECASE)

    if quoted:
        return quoted.group(1).strip() or None

    normal_pattern = rf"{expediente_prefix}{expediente_separator}({expediente_smulti})"
    match = re.search(normal_pattern, question, re.IGNORECASE)

    if not match:
        return None

    words = match.group(1).strip().split()

    while words and normalize_text(words[-1]) in EXPEDIENTE_KEYWORDS:
        words.pop()

    candidate = " ".join(words).strip(" ,.;:")
    return candidate or None

def resolve_numero_expediente(question: str) -> str | None:
    """
    Resuelve un número de expediente válido a partir de una pregunta.
    Extrae un candidato de expediente de la pregunta y lo valida contra
    los expedientes existentes en la base de datos, intentando coincidencias
    exactas y normalizadas.

    Args:
        question: Texto de la pregunta que puede contener una referencia a expediente.

    Returns:
        Número de expediente válido de la base de datos si se encuentra coincidencia,
        el candidato original si no se encuentra en BD pero tiene formato válido,
        None si no se puede extraer ningún candidato.
    """

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


async def rag_answer(
    question: str,
    model: str | None = None,
    should_cancel=None,
    on_status=None,
    user_id: int | None = None,
    lang: str = "es",
) -> Dict[str, Any]:
    """
    Procesa una pregunta usando el sistema RAG y guarda la consulta en BD.
    Valida la pregunta, extrae metadatos (expediente, tipo documento),
    consulta el sistema RAG para obtener la mejor respuesta, mide el tiempo
    de respuesta y guarda toda la información en la base de datos.

    Args:
        question: Texto de la pregunta del usuario.
        should_cancel: Función opcional que retorna True para cancelar la consulta.
        on_status: Función opcional callback para reportar progreso/status.
        user_id: ID del usuario que realiza la consulta. Si None, usa current_user.
        lang: Código de idioma para mensajes de error ("es", "en"). Defaults to "es".

    Returns:
        Diccionario con respuesta RAG y metadatos adicionales:
        - answer: Respuesta generada por el sistema
        - title: Título del documento fuente
        - filename: Nombre del archivo fuente
        - segment_index: Índice del segmento en el documento
        - chunk: Texto del fragmento relevante
        - qdrant_point_id: ID del punto en Qdrant
        - elapsed_s: Tiempo de procesamiento en segundos

    Raises:
        QueryCancelledError: Si should_cancel retorna True durante el procesamiento.
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
            model=model,
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
    except OllamaModelNotFoundError as e:
        logger.warning("Modelo de Ollama no disponible: %s", e)
        data = message_error(translate_for(lang, "rag.model_not_found_error"))
    except Exception as e:
        logger.exception("Error en rag_answer: %s", e)
        data = message_error(translate_for(lang, "rag.system_error"))

    elapsed = time.perf_counter() - start
    data.setdefault("execution_device", get_ollama_execution_device())

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
    """
    Crea un diccionario de respuesta de error para el sistema RAG.

    Args:
        msg: Mensaje de error descriptivo.

    Returns:
        Diccionario con estructura de respuesta RAG pero con campos vacíos
        excepto el campo 'answer' que contiene el mensaje de error.
    """

    out = dict(EMPTY_ANSWER)
    out["answer"] = msg
    return out

def validate_question(question: str, lang: str = "es") -> Optional[Dict[str, Any]]:
    """
    Valida una pregunta antes de procesarla en el sistema RAG.
    Verifica que la pregunta no esté vacía y no exceda la longitud máxima permitida.

    Args:
        question: Texto de la pregunta a validar.
        lang: Código de idioma para los mensajes de error. Defaults to "es".

    Returns:
        Diccionario de error si la validación falla (pregunta vacía o demasiado larga),
        None si la pregunta es válida.
    """

    if not question:
        return message_error(translate_for(lang, "rag.empty_question"))

    if len(question) > 2000:
        return message_error(translate_for(lang, "rag.question_too_long"))

    return None

def try_persist(question: str, data: Dict[str, Any], elapsed: float, user_id: int | None = None) -> None:
    """
    Intenta guardar una consulta en la base de datos con manejo de errores.
    Envuelve la función persist_consulta en un try-catch para evitar que
    errores de base de datos interrumpan el flujo principal de respuesta RAG.

    Args:
        question: Texto de la pregunta realizada.
        data: Diccionario con la respuesta y metadatos del sistema RAG.
        elapsed: Tiempo transcurrido en segundos para procesar la consulta.
        user_id: ID del usuario que realizó la consulta. Si None, usa current_user.

    Returns:
        None: La función no retorna valor. Los errores se loggean.
    """

    try:
        persist_consulta(question, data, elapsed, user_id=user_id)

    except Exception:
        logger.exception("No se pudo guardar la consulta en BBDD")
        db.session.rollback()
        

def persist_consulta(question: str, data: Dict[str, Any], elapsed: float, user_id: int | None = None) -> None:
    """
    Guarda una consulta completa en la base de datos con todos sus metadatos.
    Crea una entidad Consulta con la pregunta, respuesta, tiempo de procesamiento,
    fragmentos recuperados y enlaces a chunks. También crea las entidades
    ConsultaChunk para mantener las relaciones many-to-many.

    Args:
        question: Texto de la pregunta realizada.
        data: Diccionario con la respuesta y metadatos del sistema RAG.
        elapsed: Tiempo transcurrido en segundos para procesar la consulta.
        user_id: ID del usuario que realizó la consulta. Si es None, usa current_user.

    Returns:
        None: Los datos se guardan en la base de datos.

    Raises:
        Exception: Si ocurre un error durante el guardado (se propaga desde try_persist).

    """

    owner_id = user_id

    if owner_id is None and current_user and getattr(current_user, "is_authenticated", False):
        owner_id = int(current_user.id)

    if owner_id is not None:
        Consulta.from_rag_result(
            user_id=int(owner_id),
            question=question,
            data=data,
            elapsed=elapsed,
        )
        db.session.commit()

def build_fragmento(item: dict[str, Any], chunk_obj: Optional["Chunk"]) -> dict[str, Any]:
    """
    Construye un diccionario de fragmento con metadatos completos.
    Combina la información del item recuperado de Qdrant con los metadatos
    adicionales del objeto Chunk de la base de datos, creando una estructura
    completa de fragmento para almacenar en la consulta.

    Args:
        item: Diccionario con datos del fragmento recuperado de Qdrant.
        chunk_obj: Objeto Chunk de la base de datos, puede ser None.

    Returns:
        Diccionario con estructura completa del fragmento:
        - ranking: Posición en los resultados
        - similitud: Puntaje de similitud
        - qdrant_point_id: ID del punto en Qdrant
        - chunk: Texto del fragmento
        - metadata: Diccionario con metadatos adicionales
    """
    return Chunk.build_fragment_from_retrieved_item(item, chunk_obj)
        

def find_chunk(item: dict) -> Optional["Chunk"]:
    """
    Busca un objeto Chunk en la base de datos usando diferentes estrategias.
    Primero intenta encontrar el chunk por qdrant_point_id, y si no lo encuentra,
    usa la combinación de document_id, doc_sha256 y segment_index como fallback.

    Args:
        item: Diccionario con metadatos del fragmento recuperado.

    Returns:
        Objeto Chunk si se encuentra en la base de datos, None en caso contrario.
    """

    return Chunk.find_from_retrieved_item(item)

def qdrant_search_with_scores(qdrant, collection_name: str, query_vector: list[float], limit: int = 10):
    """
    Realiza una búsqueda vectorial en Qdrant y retorna puntos con puntuaciones (scores).

    Args:
        qdrant: Cliente de Qdrant configurado.
        collection_name: Nombre de la colección en Qdrant.
        query_vector: Vector de consulta para la búsqueda.
        limit: Número máximo de resultados a retornar. Defaults to 10.

    Returns:
        Lista de objetos ScoredPoint con .id, .score y payload incluido.
    """
    res = qdrant.query_points(
        collection_name=collection_name,
        query=query_vector,
        limit=limit,
        with_payload=True,
        with_vectors=False,
    )
    return getattr(res, "points", res) 
