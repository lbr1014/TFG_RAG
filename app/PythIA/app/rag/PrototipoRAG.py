"""
Autora: Lydia Blanco Ruiz
Script para construir la base de datos vectorial de un sistema RAG.
"""

# =========================
# Imports
# =========================
from __future__ import annotations

import logging
import os
import re
import time
import atexit
import json
from contextlib import contextmanager
from dataclasses import dataclass
from functools import cached_property
from pathlib import Path
from typing import Any, Generic, Iterable, Optional, Type, TypeVar, Dict
from uuid import UUID, uuid4

import httpx
from pydantic import BaseModel, Field
from pypdf import PdfReader
from pypdf.errors import PdfReadError, PdfStreamError
from qdrant_client import QdrantClient
from qdrant_client import models as qmodels
from sentence_transformers import SentenceTransformer
try:
    import torch
except ImportError:  # pragma: no cover - entorno sin torch fuera de Docker
    torch = None

from hashlib import sha256

# Logger
logger = logging.getLogger(__name__)   


class QueryCancelledError(RuntimeError):
    pass


class OllamaTimeoutError(RuntimeError):
    pass

OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", "http://127.0.0.1:11434").rstrip("/")

# Qdrant (Docker / remoto)
QDRANT_URL = os.getenv("QDRANT_URL", "").strip()
QDRANT_HOST = os.getenv("QDRANT_HOST", "qdrant").strip()
QDRANT_PORT = int(os.getenv("QDRANT_PORT", "6333"))
QDRANT_API_KEY = os.getenv("QDRANT_API_KEY") or None

# =========================
# Función para medir los tiempos de ejecución
# =========================
@contextmanager
def timed_block(name: str):
    """
    Metodo para medir el tiempo de un bloque de código.
    Escribe el resultado en el logger.
    """
    start = time.perf_counter()
    try:
        yield
    finally:
        elapsed = time.perf_counter() - start
        logger.info("Tiempo %s: %.3f s", name, elapsed)


# =========================
# Settings: configuración del modelo de embeddings y de la base vectorial
# =========================
@dataclass
class Settings:
    """
    Parámetros de configuración básicos del sistema.

    Solo se guardan los valores necesarios para:
        Cargar el modelo de embeddings.
        Conectarse a Qdrant.
    """
    
    # Embeddings
    TEXT_EMBEDDING_MODEL_ID: str = os.getenv(
        "TEXT_EMBEDDING_MODEL_ID",
        "sentence-transformers/all-MiniLM-L6-v2",
    )
    RAG_MODEL_DEVICE: str = os.getenv(
        "RAG_MODEL_DEVICE",
        "cuda" if torch is not None and torch.cuda.is_available() else "cpu",
    )
    EMBEDDING_BATCH_SIZE: int = int(os.getenv("EMBEDDING_BATCH_SIZE", "32"))

    # Ollama
    _ollama_num_gpu = os.getenv("OLLAMA_NUM_GPU")
    OLLAMA_NUM_GPU: Optional[int] = (
        int(_ollama_num_gpu) if _ollama_num_gpu not in (None, "") else None
    )
    OLLAMA_CONNECT_TIMEOUT_SECONDS: float = float(
        os.getenv("OLLAMA_CONNECT_TIMEOUT_SECONDS", "10")
    )
    _ollama_read_timeout = os.getenv("OLLAMA_READ_TIMEOUT_SECONDS")
    OLLAMA_READ_TIMEOUT_SECONDS: Optional[float] = (
        float(_ollama_read_timeout)
        if _ollama_read_timeout not in (None, "")
        else None
    )
    OLLAMA_WRITE_TIMEOUT_SECONDS: float = float(
        os.getenv("OLLAMA_WRITE_TIMEOUT_SECONDS", "120")
    )
    OLLAMA_POOL_TIMEOUT_SECONDS: float = float(
        os.getenv("OLLAMA_POOL_TIMEOUT_SECONDS", "10")
    )

    # Qdrant
    USE_QDRANT_CLOUD: bool = False
    QDRANT_DATABASE_HOST: str = "localhost"
    QDRANT_DATABASE_PORT: int = 6333
    QDRANT_CLOUD_URL: str = "http://localhost:6333"
    QDRANT_APIKEY: Optional[str] = None


settings = Settings()


# =========================
# Tokenizer / EmbeddingModelSingleton
# =========================
class EmbeddingModelSingleton:
    """
    Capa de acceso al modelo de embeddings (patrón Singleton).

    - Carga el modelo de sentence-transformers.
    - Expone:
        tokenizer: para dividir el texto en tokens y hacer el splitter.
        embedding_size: dimensión de los vectores (para configurar Qdrant).
        max_input_length: nº máximo de tokens (para controlar el tamaño de los chunks).
    - Permite llamar a la instancia como una función para obtener embeddings.
    """
    _instance: "EmbeddingModelSingleton|None" = None

    def __new__(cls, *args, **kwargs):
        """Garantiza que solo exista una instancia del modelo en todo el proceso."""
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(
        self,
        model_id: str = settings.TEXT_EMBEDDING_MODEL_ID,
        device: str = settings.RAG_MODEL_DEVICE,
        cache_dir: Optional[Path] = None,
    ):
        # Evita re-inicializar si el objeto ya estaba creado
        if hasattr(self, "_initialized"):
            return
        self._initialized = True

        self._model_id = model_id
        self._device = device
        # Carga del modelo de SentenceTransformers
        self._model = SentenceTransformer(
            model_id,
            device=device,
            cache_folder=str(cache_dir) if cache_dir else None,
        )
        # Modo evaluación
        self._model.eval()

    @property
    def model_id(self) -> str:
        """Devuelve el identificador del modelo de embeddings utilizado."""
        return self._model_id

    @cached_property
    def embedding_size(self) -> int:
        """
        Dimensión de los vectores de embeddings.
        Se usa al crear las colecciones de Qdrant para indicar el tamaño del vector.
        """
        return int(self._model.get_sentence_embedding_dimension())

    @property
    def max_input_length(self) -> int:
        """
        Longitud máxima de tokens que admite el modelo.
        Sirve para construir el splitter por tokens y evitar pasarle secuencias
        más largas de lo permitido.
        """
        return int(getattr(self._model, "max_seq_length", 512))

    @property
    def tokenizer(self):
        """
        Devuelve el tokenizer asociado al modelo de embeddings.
        Este tokenizer es el que se usa para contar tokens y trocear el texto
        en chunks de tamaño controlado.
        """
        return self._model.tokenizer

    def __call__(self, input_text, to_list: bool = True):
        """
        Calcula los embeddings de un texto o lista de textos.
        Argsumentos:
            input_text: str o list[str] con el texto de entrada.
            to_list: si es True, devuelve los vectores como listas de Python,
                     lo cual facilita su uso y serialización.
        Returns:
            Vector o lista de vectores de embeddings.
        """
        emb = self._model.encode(
            input_text,
            batch_size=settings.EMBEDDING_BATCH_SIZE,
            convert_to_numpy=True,
            show_progress_bar=False,
        )
        if to_list:
            if isinstance(input_text, list):
                #  Lista de vectores
                return [e.tolist() if hasattr(e, "tolist") else list(e) for e in emb]
            # Vector
            return emb.tolist() if hasattr(emb, "tolist") else list(emb)
        return emb


start_model = time.perf_counter()
# Instancia única disponible para el resto del código
embedding_model = EmbeddingModelSingleton()
logger.info("Tiempo carga modelo embeddings: %.3f s", time.perf_counter() - start_model)


# =========================
# Conexión Qdrant
# =========================
def _make_qdrant_client() -> QdrantClient:
    """
    Crea un cliente de Qdrant apuntando al servicio de Qdrant (Docker / remoto).
    Si no hay variables de entorno, intenta una conexión por host/port.    """
    try:
        client = (
            QdrantClient(url=QDRANT_URL, api_key=QDRANT_API_KEY)
            if QDRANT_URL
            else QdrantClient(host=QDRANT_HOST, port=QDRANT_PORT, api_key=QDRANT_API_KEY)
        )

        for _ in range(20):
            try:
                client.get_collections()
                return client
            except Exception:
                time.sleep(0.5)

        logger.warning("Qdrant no responde tras varios intentos.")
        return None
    except Exception as e:
        logger.warning("No se pudo inicializar Qdrant remoto (%s:%s / url=%s): %s",
                       QDRANT_HOST, QDRANT_PORT, QDRANT_URL or "-", e)
        raise RuntimeError("No se pudo conectar a Qdrant")



# Cliente global de Qdrant
qdrant = _make_qdrant_client()

@atexit.register
def _close_qdrant():
    global qdrant
    try:
        if qdrant is not None:
            qdrant.close()
    except Exception as e:
        logger.debug("Error cerrando Qdrant al salir: %s", e)
    finally:
        qdrant = None

def pdf_sha256(path: Path) -> str:
    """
    Calcula el hash SHA-256 de un archivo PDF.
    Este hash se utiliza como identificador de contenido del documento,
    permitiendo detectar si un PDF ha cambiado aunque mantenga el mismo nombre.

    Argumentos:
        path: Ruta al archivo PDF.

    Returns:
        Hash SHA-256 hexadecimal del contenido del archivo.
    """
    h = sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def _qdrant_filter_by_filename(filename: str) -> qmodels.Filter:
    """
    Construye un filtro de Qdrant para seleccionar todos los puntos asociados a un archivo PDF concreto, usando su nombre.

    Argumentos:
        filename: Nombre del archivo PDF.

    Returns:
        Filtro listo para usar para busqeuda o borrado.
    """
    return qmodels.Filter(
        must=[
            qmodels.FieldCondition(
                key="metadata.filename",
                match=qmodels.MatchValue(value=filename),
            )
        ]
    )


def _qdrant_filter_by_filename_and_hash(filename: str, doc_hash: str) -> qmodels.Filter:
    """
    Construye un filtro de Qdrant para comprobar si un PDF concreto ya está indexado y 
    coincide con una versión concreta del documento, es decir, si coinciden los hash.
    Este filtro se usa para decidir si un PDF puede omitirse durante el indexado incremental.

    Argumentos:
        filename: Nombre del archivo PDF.
        doc_hash: Hash SHA-256 del contenido del PDF.

    Returns:
        Filtro combinando nombre de archivo y hash.
    """
    return qmodels.Filter(
        must=[
            qmodels.FieldCondition(
                key="metadata.filename",
                match=qmodels.MatchValue(value=filename),
            ),
            qmodels.FieldCondition(
                key="metadata.sha256",
                match=qmodels.MatchValue(value=doc_hash),
            ),
        ]
    )


def qdrant_has_filename(filename: str) -> bool:
    """
    Comprueba si existen chunks indexados en Qdrant para un PDF concreto,
    independientemente de su versión. Se usa para distinguir entre un PDF nuevo y un PDF ya indexado.
    
    Argumentos:
        filename: Nombre del archivo PDF.

    Returns:
        True si existe al menos un chunk asociado al archivo.
    """
    records, _ = qdrant.scroll(
        collection_name=VectorBaseDocument.get_collection_name(),
        limit=1,
        with_payload=False,
        with_vectors=False,
        scroll_filter=_qdrant_filter_by_filename(filename),
    )
    return len(records) > 0


def qdrant_has_same_hash(filename: str, doc_hash: str) -> bool:
    """
    Comprueba si un PDF ya está indexado en Qdrant y además coincide con la versión actual 
    del archivo (mismo hash SHA-256).

    Argumentos:
        filename: Nombre del archivo PDF.
        doc_hash: Hash SHA-256 del contenido del PDF.

    Returns:
        True si el documento ya está indexado y no ha cambiado; Fase si el documento no esta inlcuido o ha cambiado.
    """
    records, _ = qdrant.scroll(
        collection_name=VectorBaseDocument.get_collection_name(),
        limit=1,
        with_payload=False,
        with_vectors=False,
        scroll_filter=_qdrant_filter_by_filename_and_hash(filename, doc_hash),
    )
    return len(records) > 0


def qdrant_delete_by_filename(filename: str) -> None:
    """
    Elimina de Qdrant todos los chunks asociados a un archivo PDF concreto.
    Esta función se utiliza cuando se detecta que un PDF ha cambiado. Primero eliminan los chunks 
    antiguos y luego indexa de nuevo el documento actualizado.

    Argumentos:
        filename: Nombre del archivo PDF a eliminar de la base vectorial.
    """
    VectorBaseDocument._ensure_collection()
    qdrant.delete(
        collection_name=VectorBaseDocument.get_collection_name(),
        points_selector=qmodels.FilterSelector(
            filter=_qdrant_filter_by_filename(filename)
        ),
    )
    
def qdrant_count_chunks_by_filename(filename: str) -> int:
    """
    Cuenta cuántos chunks hay indexados en Qdrant para un PDF.
    
    Argumentos:
        filename: Nombre del archivo PDF a eliminar de la base vectorial.
    """
    VectorBaseDocument._ensure_collection()
    res = qdrant.count(
        collection_name=VectorBaseDocument.get_collection_name(),
        count_filter=_qdrant_filter_by_filename(filename),
        exact=True,
    )
    return int(getattr(res, "count", 0))

def qdrant_get_payloads(point_ids: list[str]) -> dict[str, dict]:
    ids = [i for i in point_ids if i]
    if not ids:
        return {}
    try:
        res = qdrant.retrieve(
            collection_name=VectorBaseDocument.get_collection_name(),
            ids=ids,
            with_payload=True,
            with_vectors=False,
        )
    except ValueError as e:
        logger.warning("Qdrant sin colección (%s). Devolviendo payloads vacíos.", e)
        return {}
    except Exception as e:
        logger.warning("Error leyendo payloads de Qdrant: %s. Devolviendo payloads vacíos.", e)
        return {}
    
    out:  dict[str, dict] = {}
    for r in (res or []):
        out[str(r.id)] = (r.payload or {})
    return out

# =========================
# OVM mínimo (Object–Vector Mapping)
# =========================
T = TypeVar("T", bound="VectorBaseDocument")


class VectorBaseDocument(BaseModel, Generic[T]):
    """
    Entidad base con mapeo a Qdrant (payload + vector).

    Representa la forma estándar en la que cualquier "documento embebido"
    se guarda en la base de datos vectorial:

        id: identificador único (UUID).
        content: texto del chunk.
        embedding: vector de floats asociado al contenido.
        metadata: información adicional (nombre de archivo, tipo, etc.).

    Las subclases heredan estos campos y las operaciones de guardado/búsqueda.
    """

    id: UUID = Field(default_factory=uuid4)
    content: str
    # El vector se guarda fuera del payload en Qdrant
    embedding: list[float] | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)

    class Config:
        # Permite tipos que no son estándar de Pydantic
        arbitrary_types_allowed = True

    # ---- utilidades de colección
    @classmethod
    def get_collection_name(cls) -> str:
        """
        Obtiene el nombre de colección de Qdrant para esta clase.
        Cambia los espacios por '_' y elimina las mayúsculas.
        """
        name = cls.__name__
        s1 = re.sub("(.)([A-Z][a-z]+)", r"\1_\2", name)
        return re.sub("([a-z0-9])([A-Z])", r"\1_\2", s1).lower()

    # ---- creación de colección (idempotente)
    @classmethod
    def _ensure_collection(cls) -> None:
        """
        Garantiza que exista la colección asociada en Qdrant.
        Si la colección no existe, la crea usnado:
            tamaño de vector `embedding_model.embedding_size`
            métrica de similitud por coseno.
        """
        collection = cls.get_collection_name()
        dim = embedding_model.embedding_size
        try:
            qdrant.get_collection(collection)
        except Exception:
            qdrant.recreate_collection(
                collection_name=collection,
                vectors_config=qmodels.VectorParams(
                    size=dim,
                    distance=qmodels.Distance.COSINE,
                ),
            )

    # ---- mapeos
    def to_point(self) -> qmodels.PointStruct:
        """
        Convierte la instancia en un PointStruct de Qdrant.
        El payload incluye tanto el contenido como metadatos del modelo
        (id, dimensión, max_input_length) para poder auditar y reproducir
        la generación de embeddings.
        """
        payload = {
            "content": self.content,
            "metadata": self.metadata,
            "model_id": embedding_model.model_id,
            "embedding_size": embedding_model.embedding_size,
            "max_input_length": embedding_model.max_input_length,
        }
        return qmodels.PointStruct(
            id=str(self.id),
            vector=self.embedding,
            payload=payload,
        )

    @classmethod
    def from_record(cls: Type[T], record: qmodels.ScoredPoint | qmodels.Record) -> T:
        """
        Crea una instancia de la clase a partir de un registro de Qdrant
        """
        payload = record.payload or {}
        return cls(
            id=UUID(str(record.id)),
            content=payload.get("content", ""),
            embedding=getattr(record, "vector", None),
            metadata=payload.get("metadata", {}) or {},
        )

    # ---- escritura
    def save(self) -> None:
        """
        Guarda la instancia actual en Qdrant.
        Usa upsert, de modo que si el id ya existía lo sobrescribe.
        """
        type(self)._ensure_collection()
        point = self.to_point()
        qdrant.upsert(collection_name=type(self).get_collection_name(), points=[point])

    @classmethod
    def save_many(cls: Type[T], docs: list[T]) -> None:
        """
        Guarda una lista de documentos de golpe en Qdrant.
        Eficiente para cargar muchos chunks producidos en el pipeline.
        """
        cls._ensure_collection()
        points = [d.to_point() for d in docs]
        qdrant.upsert(collection_name=cls.get_collection_name(), points=points)

    @classmethod
    def bulk_find(
        cls: Type[T], 
        limit: int = 10, 
        offset: UUID | None = None,
    ) -> tuple[list[T], UUID | None]:
        """
        Recupera documentos de la colección usando scroll (paginación).
        Argsumentos:
            limit: número máximo de documentos a devolver.
            offset: id a partir del cual continuar el scroll.
        Returns:
            (lista_de_docs, siguiente_offset) donde siguiente_offset
            puede usarse en la siguiente llamada para seguir recorriendo.
        """
        cls._ensure_collection()
        off = str(offset) if offset else None
        records, next_off = qdrant.scroll(
            collection_name=cls.get_collection_name(),
            limit=limit,
            with_payload=True,
            with_vectors=False,
            offset=off,
        )
        docs = [cls.from_record(r) for r in records]
        return docs, (UUID(next_off, version=4) if next_off else None)

    # ---- búsqueda vectorial
    @classmethod
    def search(
        cls: Type[T],
        query_vector: list[float],
        limit: int = 10,
        **kwargs,
    ) -> list[T]:
        cls._ensure_collection()
        records = qdrant.query_points(
            collection_name=cls.get_collection_name(),
            query=query_vector,
            limit=limit,
            with_payload=True,
            with_vectors=False,
            **kwargs,
        )
        points = getattr(records, "points", records)
        return [cls.from_record(p) for p in points]
    
    
# =========================
# Chunks
# =========================
def chunk_text(text: str, overlap_ratio: float = 0.1) -> list[str]:
    """
    Trocea un texto largo en chunks controlando el nº de tokens. 
    Añade un pequeño solapamiento (overlap)
    Para ello:
        Se recorre el texto línea a línea.
        Se tokeniza cada línea con el tokenizer del modelo.
        Se van concatenando líneas hasta que el nº de tokens alcanza max_len.
        Cuando se supera el límite, se empieza un nuevo chunk.
    Si alguna línea produce un error de tokenización, se ignora.
    """
    # Obtiene el tokenizer del modelo y calculamos un límite de tokens
    tokenizer = embedding_model.tokenizer
    # Márgen de seguridad, solo se usa el 80% de la capacidad del modelo
    max_len = int(embedding_model.max_input_length * 0.8)

    # Tokens que se solapan entre chunks
    overlap_tokens = max(1, int(max_len * overlap_ratio))

    chunks: list[str] = []
    # Guardamos las líneas y su número de tokens para hacer el solapamiento
    current: list[tuple[str, int]] = []
    current_tokens = 0

    for line in iter_clean_lines(text):
        line_tokens = token_len(tokenizer, line)
        if line_tokens is None:
            continue
                
        # Si al añadir esta línea se supera el límite, se guarda el chunk actual
        if current_tokens + line_tokens > max_len and current:
            
            # Se guarda el chunk actual
            get_chunk(chunks, current)            
            # Se empieza un nuevo chunk con el solapamiento
            current, current_tokens = token_overlap(current, overlap_tokens)
        
        # Añadimos la línea actual al chunk
        current.append((line, line_tokens))
        current_tokens += line_tokens

    # Último chunk pendiente
    if current:
        get_chunk(chunks, current)  

    return chunks

def token_len(tokenizer, text: str) -> int | None:
    """
    Devuelve el número de tokens o None si falla la tokenización.
    """
    try:
        return len(tokenizer.tokenize(text))
    except Exception as e:
        logger.warning("No se puede tokenizar una línea: %s", e)
        return None

def get_chunk(chunks: list[str], current: list[tuple[str, int]]) -> None:
    """
    Vuelca el chunk actual si hay contenido.
    """
    chunk = " ".join(s for s, _ in current).strip()
    if chunk:
        chunks.append(chunk)

def token_overlap(
    current: list[tuple[str, int]],
    overlap_tokens: int,
) -> tuple[list[tuple[str, int]], int]:
    """
    Calcula el solapamiento (líneas finales) y tokens solapados.
    """
    overlap: list[tuple[str, int]] = []
    tokens_in_overlap = 0

    for s, t in reversed(current):
        if tokens_in_overlap + t > overlap_tokens:
            break
        overlap.append((s, t))
        tokens_in_overlap += t

    overlap.reverse()
    return overlap, tokens_in_overlap

def iter_clean_lines(text: str) -> Iterable[str]:
    """
    Itera líneas limpias (strip) y no vacías.
    """
    for line in text.splitlines():
        line = line.strip()
        if line:
            yield line

def recuperacion_chunk(user_query: str, k: int = 10) -> list[VectorBaseDocument]:
    """
    Dada una pregunta del usuario, recupera los chunks más similares
    desde Qdrant.
    """
    # Embedding de la pregunta
    query_vector = embedding_model(user_query, to_list=True)

    # Búsqueda vectorial en Qdrant
    docs = VectorBaseDocument.search(query_vector=query_vector, limit=k)

    return docs

def recuperacion_chunk_con_scores(user_query: str, k: int = 10) -> list[qmodels.ScoredPoint]:
    """
    Recupera los k chunks más similares desde Qdrant, incluyendo score e id del punto.
    """
    # Embedding de la pregunta
    query_vector = embedding_model(user_query, to_list=True)
    try:
        VectorBaseDocument._ensure_collection()

        # Query con scores
        res = qdrant.query_points(
            collection_name=VectorBaseDocument.get_collection_name(),
            query=query_vector,
            limit=k,
            with_payload=True,
            with_vectors=False,
        )
        return getattr(res, "points", res)
    except Exception as e:
        logger.warning("Qdrant no disponible para recuperar chunks: %s", e)
        return []


# =========================
# Ollama
# =========================
async def ask_ollama(
    prompt: str,
    model: str = "llama3.1:8b-instruct-q4_K_M",
    should_cancel=None,
) -> str:
    """
    Envía un prompt a Ollama usando /api/generate y devuelve el texto de respuesta.
    """
    if should_cancel and should_cancel():
        raise QueryCancelledError("Consulta cancelada por el usuario.")

    full_prompt = (
        "Responde en español de forma breve y precisa.\n\n"
        f"{prompt}"
    )
    chunks: list[str] = []

    request_payload = {
        "model": model,
        "prompt": full_prompt,
        "stream": True,
    }
    if settings.OLLAMA_NUM_GPU is not None:
        request_payload["options"] = {
            "num_gpu": settings.OLLAMA_NUM_GPU,
        }

    timeout = httpx.Timeout(
        connect=settings.OLLAMA_CONNECT_TIMEOUT_SECONDS,
        read=settings.OLLAMA_READ_TIMEOUT_SECONDS,
        write=settings.OLLAMA_WRITE_TIMEOUT_SECONDS,
        pool=settings.OLLAMA_POOL_TIMEOUT_SECONDS,
    )
    try:
        async with httpx.AsyncClient(base_url=OLLAMA_BASE_URL, timeout=timeout) as client:
            async with client.stream(
                "POST",
                "/api/generate",
                json=request_payload,
            ) as resp:
                resp.raise_for_status()

                async for line in resp.aiter_lines():
                    if should_cancel and should_cancel():
                        raise QueryCancelledError("Consulta cancelada por el usuario.")
                    if not line:
                        continue

                    payload = json.loads(line)
                    piece = payload.get("response")
                    if piece:
                        chunks.append(piece)

                    if payload.get("done"):
                        break
    except httpx.TimeoutException as exc:
        timeout_label = (
            f"{settings.OLLAMA_READ_TIMEOUT_SECONDS:g} s"
            if settings.OLLAMA_READ_TIMEOUT_SECONDS is not None
            else "sin limite"
        )
        raise OllamaTimeoutError(
            f"Ollama ha superado el tiempo de espera de lectura ({timeout_label})."
        ) from exc
    return "".join(chunks)


def obtener_chunk_de_query(user_query: str) -> dict | None:
    """
    Toma una pregunta de usuario, recupera el chunk más relevante de Qdrant
    y devuelve:
        - title: título del archivo
        - filename: nombre del archivo PDF
        - segment_index: índice de segmento/chunk
        - chunk: texto del chunk recuperado

    Devuelve None si no hay resultados.
    """
    docs = recuperacion_chunk(user_query, k=1)
    if not docs:
        return None

    doc = docs[0]
    metadata = doc.metadata or {}

    return {
        "title": metadata.get("title", ""),
        "filename": metadata.get("filename", ""),
        "segment_index": metadata.get("segment_index", -1),
        "chunk": doc.content,
    }
    
    
async def obtener_mejor_chunk(
    user_query: str,
    model: str = "llama3.1:8b-instruct-q4_K_M",
    should_cancel=None,
    on_status=None,
    ) -> dict:
    """
    1) Recupera de Qdrant los 10 chunk más parecido a la pregunta.
    2) Construye un prompt para Ollama con esos chunk.
    3) Llama a Ollama para que genere la respuesta usando los chunk.
    4) Devuelve:
        - answer: respuesta del LLM
        - title: título del archivo
        - filename: nombre del PDF
        - segment_index: número de segmento
        - chunk: texto del fragmento usado
        - retrieved: top 10 chunks 
    """
    user_query = (user_query or "").strip()
    if should_cancel and should_cancel():
        raise QueryCancelledError("Consulta cancelada por el usuario.")

    if on_status:
        on_status("Recuperando fragmentos relevantes...")

    points = recuperacion_chunk_con_scores(user_query, k=10)
    if not points:
        return {
            "answer": "No he encontrado ningún fragmento relevante en la base de datos.",
            "title": "",
            "filename": "",
            "segment_index": -1,
            "chunk": "",
            "retrieved": [],
        }
    
    # Normaliza a lista de dicts
    retrieved: list[dict] = []
    context_blocks: list[str] = []
    
    for idx, p in enumerate(points, start=1):
        if should_cancel and should_cancel():
            raise QueryCancelledError("Consulta cancelada por el usuario.")

        payload = p.payload or {}
        meta = (payload.get("metadata") or {})
        content = payload.get("content", "") or ""

        item = {
            "ranking": idx,
            "similitud": float(getattr(p, "score", 0.0)),
            "qdrant_point_id": str(getattr(p, "id", "")),
            "document_id": meta.get("document_id"),
            "doc_sha256": meta.get("sha256"),
            "segment_index": meta.get("segment_index", -1),
            "filename": meta.get("filename", ""),
            "title": meta.get("title", ""),
            "metadata": dict(meta),
            "chunk": content,
        }
        retrieved.append(item)
        context_blocks.append(
            f"""[CHUNK #{idx} | score={item['similitud']:.6f} | file={item['filename']} | seg={item['segment_index']}]
            \"\"\"{content}\"\"\""""
        )
        
    best = retrieved[0]
        
    # Prompt para que Ollama conteste usando los 10 chunk en ranking
    prompt = f"""
    Usa EXCLUSIVAMENTE los fragmentos proporcionados (CHUNK #1 a CHUNK #10) para responder.
    Si la respuesta no puede deducirse de esos fragmentos, di explícitamente que no hay información suficiente.

    Pregunta del usuario:
    {user_query}
    
    Fragmentos (ordenados por relevancia):
    {chr(10).join(context_blocks)}

    Responde de forma breve y precisa en español.
    """

    if on_status:
        on_status("Generando respuesta del modelo...")

    answer = await ask_ollama(prompt, model=model, should_cancel=should_cancel)

    return {
        "answer": answer,
        "title": best.get("title", ""),
        "filename": best.get("filename", ""),
        "segment_index": best.get("segment_index", -1),
        "chunk": best.get("chunk", ""),
        "retrieved": retrieved, 
    }

def index_pdf(pdf_path: Path, document_id: int | None = None) -> list[VectorBaseDocument]:
    """
    Esta función indexa un PDF para ello lee el texto, lo trocea en chunks, calcula embeddings y guarda los puntos en Qdrant.
    """
    with timed_block(f"total {pdf_path.name}"):
        logger.info("Procesando %s ...", pdf_path.name)

        # 1) Lectura del PDF
        try:
            with timed_block(f"leer pdf {pdf_path.name}"):
                reader = PdfReader(str(pdf_path))
                info = reader.metadata or {}
                title = info.get("/Title") or pdf_path.stem
                doc_hash = pdf_sha256(pdf_path)
                parts: list[str] = []
                for page in reader.pages:
                    parts.append((page.extract_text() or ""))
                full_text = "\n".join(parts)
        except (PdfReadError, PdfStreamError, Exception) as e:
            logger.error("Error leyendo %s: %s", pdf_path.name, e)
            return []

        if not full_text.strip():
            logger.warning("%s: sin texto extraído.", pdf_path.name)
            return []

        # 2) Chunking
        try:
            with timed_block(f"chunking {pdf_path.name}"):
                chunks = chunk_text(full_text)
        except Exception as e:
            logger.error("Error haciendo chunks en %s: %s", pdf_path.name, e)
            return []

        if not chunks:
            logger.warning("%s: sin chunks válidos", pdf_path.name)
            return []

        # 3) Embeddings
        with timed_block(f"embeddings {pdf_path.name}"):
            vectors = embedding_model(chunks, to_list=True)
            
        # Seguridad si no coinciden longitudes
        if len(vectors) != len(chunks):
            logger.error(
                "%s: nº chunks (%d) != nº embeddings (%d)",
                pdf_path.name, len(chunks), len(vectors)
            )
            return []

        # 4) Guardado en Qdrant
        with timed_block(f"guardar qdrant {pdf_path.name}"):
            docs: list[VectorBaseDocument] = []
            base_meta = {
                "filename": pdf_path.name,
                "title": title,
                "sha256": doc_hash,
            }
            if document_id is not None:
                base_meta["document_id"] = int(document_id)
                
            for idx, (chunk, vec) in enumerate(zip(chunks, vectors)):
                meta = dict(base_meta)
                meta["segment_index"] = idx
                docs.append(
                    VectorBaseDocument(
                        content=chunk,
                        embedding=vec,
                        metadata=meta,
                    )
                )
            VectorBaseDocument.save_many(docs)
            logger.info("Guardados %d chunks en Qdrant", len(docs))
        return docs


def index_pliegos_dir(pliegos_dir: Path) -> dict:
    """
    Recorre todos los PDFs de un directorio y los indexa de forma incremental.
    Si el PDF no existe en Qdrant lo indexa, si existe y el hash coincide no lo indexa y si existe y el has no coincide borra sus chunks y lo reindexa
    Devuelve un resumen con contadores. 
    """
    if not pliegos_dir.exists():
        logger.error("No se encuentra la carpeta %s", pliegos_dir)
        raise SystemExit(1)

    # Asegura colección antes de empezar
    VectorBaseDocument._ensure_collection()

    summary = {
        "pdfs_total": 0,
        "pdfs_nuevos": 0,
        "pdfs_modificados": 0,
        "pdfs_omitidos": 0,
        "pdfs_error_o_sin_texto": 0,
        "chunks_guardados": 0,
    }

    pdfs = sorted(pliegos_dir.glob("*.pdf"))
    summary["pdfs_total"] = len(pdfs)

    for pdf_path in pdfs:
        filename = pdf_path.name
        doc_hash = pdf_sha256(pdf_path)

        # Si está y coincide hash no lo añade
        if qdrant_has_same_hash(filename, doc_hash):
            summary["pdfs_omitidos"] += 1
            continue

        # Si está pero hash distinto, borrar los chunks antiguos y genera los nuevos
        if qdrant_has_filename(filename):
            logger.info("%s ha cambiado => reindexando", filename)
            qdrant_delete_by_filename(filename)
            summary["pdfs_modificados"] += 1
        else:
            summary["pdfs_nuevos"] += 1

        # Si no esta lo añade
        docs = index_pdf(pdf_path)
        n_chunks = len(docs)
        if n_chunks > 0:
            summary["chunks_guardados"] += n_chunks
        else:
            summary["pdfs_error_o_sin_texto"] += 1

    return summary



if __name__ == "__main__":
    """
    Construye la base de datos vectorial a partir de los PDFs de ./pliegos
    """
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    )

    base_dir = Path(__file__).parent
    pliegos_dir = base_dir / "pliegos"

    summary = index_pliegos_dir(pliegos_dir)
    logger.info("Resumen indexado: %s", summary)
