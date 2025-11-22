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
from contextlib import contextmanager
from dataclasses import dataclass
from functools import cached_property
from pathlib import Path
from typing import Any, Generic, Optional, Type, TypeVar
from uuid import UUID, uuid4

import requests
from pydantic import BaseModel, Field
from pypdf import PdfReader
from pypdf.errors import PdfReadError, PdfStreamError
from qdrant_client import QdrantClient
from qdrant_client import models as qmodels
from sentence_transformers import SentenceTransformer

# Logger
logger = logging.getLogger(__name__)   

OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", "http://127.0.0.1:11434").rstrip("/")


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
    TEXT_EMBEDDING_MODEL_ID: str = "sentence-transformers/all-MiniLM-L6-v2"
    RAG_MODEL_DEVICE: str = "cpu"

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
        emb = self._model.encode(input_text)
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
    Crea un cliente de Qdrant local.
    Los datos se guardan en la carpeta `qdrant_data` situada junto al archivo
    actual. Esta opción evita tener que usar Docker o desplegar Qdrant aparte.
    """
    data_dir = Path(__file__).parent / "qdrant_data"
    data_dir.mkdir(exist_ok=True)
    return QdrantClient(path=str(data_dir))


# Cliente global de Qdrant
qdrant = _make_qdrant_client()

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
        records = qdrant.search(
            collection_name=cls.get_collection_name(),
            query_vector=query_vector,
            limit=limit,
            with_payload=True,
            with_vectors=False,
            **kwargs,
        )
        return [cls.from_record(r) for r in records]
    
    
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

    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue

        try:
            tokens = tokenizer.tokenize(line)
        except Exception as e:
            # Si el tokenizer falla con una línea extraña, la ignoramos
            logger.warning("No se puede tokenizar una línea: %s", e)
            continue
                
        line_tokens = len(tokens)
        # Si al añadir esta línea se supera el límite, se guarda el chunk actual
        if current_tokens + line_tokens > max_len and current:
            
            # Se guarda el chunk actual
            chunk_text_str = " ".join(long for (long, _) in current).strip()
            if chunk_text_str:
                chunks.append(chunk_text_str)
                
            # Se calcula las líneas que se reutilizan como solapamiento
            overlap: list[tuple[str, int]] = []
            tokens_in_overlap = 0
            for long, t in reversed(current):
                if tokens_in_overlap + t > overlap_tokens:
                    break
                overlap.append((long, t))
                tokens_in_overlap += t
            overlap.reverse()  # las volvemos a poner en orden original
            
            # Se empieza un nuevo chunk con el solapamiento
            current = overlap.copy()
            current_tokens = tokens_in_overlap
        
        # Añadimos la línea actual al chunk
        current.append((line, line_tokens))
        current_tokens += line_tokens

    # Último chunk pendiente
    if current:
        chunk_text_str = " ".join(long for (long, _) in current).strip()
        if chunk_text_str:
            chunks.append(chunk_text_str)

    return chunks


def recuperacion_chunk(user_query: str, k: int = 1) -> list[VectorBaseDocument]:
    """
    Dada una pregunta del usuario, recupera los chunks más similares
    desde Qdrant.
    """
    # Embedding de la pregunta
    query_vector = embedding_model(user_query, to_list=True)

    # Búsqueda vectorial en Qdrant
    docs = VectorBaseDocument.search(query_vector=query_vector, limit=k)

    return docs


# =========================
# Ollama
# =========================
def ask_ollama(prompt: str, model: str = "llama3.1:8b-instruct-q4_K_M") -> str:
    """
    Envía un prompt a Ollama usando /api/generate y devuelve el texto de respuesta.
    """
    
    url = f"{OLLAMA_BASE_URL}/api/generate"

    full_prompt = (
        "Responde en español de forma breve y precisa.\n\n"
        f"{prompt}"
    )

    resp = requests.post(
        url,
        json={
            "model": model,
            "prompt": full_prompt,
            "stream": False,
        },
        timeout=120,
    )
    resp.raise_for_status()
    data = resp.json()
    return data.get("response", "")


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
    
    
def obtener_mejor_chunk(
    user_query: str,
    model: str = "llama3.1:8b-instruct-q4_K_M",
    ) -> dict:
    """
    1) Recupera de Qdrant el chunk más parecido a la pregunta.
    2) Construye un prompt para Ollama con ese chunk.
    3) Llama a Ollama para que genere la respuesta usando SOLO ese chunk.
    4) Devuelve:
        - answer: respuesta del LLM
        - title: título del archivo
        - filename: nombre del PDF
        - segment_index: número de segmento
        - chunk: texto del fragmento usado
    """
    info = obtener_chunk_de_query(user_query)
    if info is None or not info.get("chunk"):
        return {
            "answer": "No he encontrado ningún fragmento relevante en la base de datos.",
            "title": "",
            "filename": "",
            "segment_index": -1,
            "chunk": "",
        }

    # Prompt para que Ollama conteste usando sólo ese chunk
    prompt = f"""
    Usa EXCLUSIVAMENTE el siguiente fragmento del pliego para responder.

    Título del archivo: {info['title']}
    Nombre del archivo: {info['filename']}
    Índice de segmento: {info['segment_index']}

    Fragmento:
    \"\"\"{info['chunk']}\"\"\"

    Pregunta del usuario:
    {user_query}

    Responde de forma breve y precisa en español.
    """

    answer = ask_ollama(prompt, model=model)

    info["answer"] = answer
    return info


if __name__ == "__main__":
    """
    Recorre todos los PDFs de la carpeta Pliegos.
    Extrae su texto, lo trocea en chunks respetando el nº máximo de tokens
    admitidos por el modelo de embeddings.
    Calcula los embeddings de cada chunk.
    Los guarda en Qdrant para poder hacer búsquedas vectoriales después.
    """
        
    collection = VectorBaseDocument.get_collection_name()
    
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    )
    
    try:
        qdrant.delete_collection(collection_name=collection)
    except Exception as e:
        logger.info("La base de datos no existe todavía: %s", e)

    # Carpeta del proyecto y carpeta con los pliegos
    base_dir = Path(__file__).parent
    pliegos_dir = base_dir / "pliegos"

    if not pliegos_dir.exists():
        logger.error("No se encuentra la carpeta %s", pliegos_dir)
        raise SystemExit(1)
        
    # Recorremos todos los PDFs de la carpeta Pliegos
    for pdf_path in sorted(pliegos_dir.glob("*.pdf")):
        with timed_block(f"total {pdf_path.name}"):
            logger.info("Procesando %s ...", pdf_path.name)
            # Lectura del pdf
            try:
                with timed_block(f"leer pdf {pdf_path.name}"):
                    reader = PdfReader(str(pdf_path))
                    full_text = ""
                    info = reader.metadata or {}
                    title = info.get("/Title") or pdf_path.stem
                    for page in reader.pages:
                        page_text = page.extract_text() or ""
                        full_text += page_text + "\n"
            except (PdfReadError, PdfStreamError, Exception) as e:
                # Se ignora el archivo si no es un PDF válido o está corrupto
                logger.error("Error leyendo %s: %s", pdf_path.name, e)
                continue

            if not full_text.strip():
                logger.warning("%s: sin texto extraído.", pdf_path.name)
                continue
                
            # Generación de chunks controlando el número de tokens
            try:
                with timed_block(f"chunking {pdf_path.name}"):
                    chunks = chunk_text(full_text)
            except Exception as e:
                logger.error("Error haciendo chunks en %s: %s", pdf_path.name, e)
                continue
            
            if not chunks:
                logger.warning("%s: sin chunks válidos", pdf_path.name)
                continue

            # Embeddings para todos los chunks de este PDF
            with timed_block(f"embeddings {pdf_path.name}"):
                vectors = embedding_model(chunks, to_list=True)

            # Se forman las entidades de dominio listas para guardar en Qdrant
            with timed_block(f"guardar qdrant {pdf_path.name}"):
                docs: list[VectorBaseDocument] = []
                for idx, (chunk, vec) in enumerate(zip(chunks, vectors)):
                    docs.append(
                        VectorBaseDocument(
                            content=chunk,
                            embedding=vec,
                            metadata={
                                "filename": pdf_path.name, 
                                "title": title, 
                                "segment_index": idx,
                            },
                        )
                    )
                # Se guardan en la colección correspondiente
                VectorBaseDocument.save_many(docs)
                logger.info("Guardados %d chunks en Qdrant", len(docs))
