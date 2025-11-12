# BaseDatos.py
from __future__ import annotations

import re
from dataclasses import dataclass
from functools import cached_property
from pathlib import Path
from typing import Any, Generic, Optional, Type, TypeVar
from uuid import UUID, uuid4

from pydantic import BaseModel, Field
from qdrant_client import QdrantClient
from qdrant_client import models as qmodels
from sentence_transformers import SentenceTransformer


# =========================
# Settings
# =========================
@dataclass
class Settings:
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
    _instance: "EmbeddingModelSingleton|None" = None

    def __new__(cls, *args, **kwargs):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(
        self,
        model_id: str = settings.TEXT_EMBEDDING_MODEL_ID,
        device: str = settings.RAG_MODEL_DEVICE,
        cache_dir: Optional[Path] = None,
    ):
        if hasattr(self, "_initialized"):
            return
        self._initialized = True

        self._model_id = model_id
        self._device = device
        self._model = SentenceTransformer(
            model_id,
            device=device,
            cache_folder=str(cache_dir) if cache_dir else None,
        )
        self._model.eval()

    @property
    def model_id(self) -> str:
        return self._model_id

    @cached_property
    def embedding_size(self) -> int:
        # devuelve la dimensión del vector de embeddings
        return int(self._model.get_sentence_embedding_dimension())

    @property
    def max_input_length(self) -> int:
        # longitud máx. de entrada que usa el splitter por tokens del libro
        return int(getattr(self._model, "max_seq_length", 512))

    @property
    def tokenizer(self):
        # acceso al tokenizer del modelo de embeddings
        return self._model.tokenizer

    def __call__(self, input_text, to_list: bool = True):
        emb = self._model.encode(input_text)
        if to_list:
            if isinstance(input_text, list):
                return [e.tolist() if hasattr(e, "tolist") else list(e) for e in emb]
            return emb.tolist() if hasattr(emb, "tolist") else list(emb)
        return emb


# Instancia única disponible para el resto del código
embedding_model = EmbeddingModelSingleton()


# =========================
# Conexión Qdrant
# =========================
def _make_qdrant_client() -> QdrantClient:
    if settings.USE_QDRANT_CLOUD:
        return QdrantClient(url=settings.QDRANT_CLOUD_URL, api_key=settings.QDRANT_APIKEY)
    return QdrantClient(host=settings.QDRANT_DATABASE_HOST, port=settings.QDRANT_DATABASE_PORT)


qdrant = _make_qdrant_client()

# =========================
# OVM mínimo (Object–Vector Mapping) según el libro
# =========================
T = TypeVar("T", bound="VectorBaseDocument")


class VectorBaseDocument(BaseModel, Generic[T]):
    """Entidad base con mapeo a Qdrant (payload + vector)."""

    id: UUID = Field(default_factory=uuid4)
    content: str
    # El vector se guarda fuera del payload en Qdrant
    embedding: list[float] | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)

    class Config:
        arbitrary_types_allowed = True

    # ---- utilidades de colección
    @classmethod
    def get_collection_name(cls) -> str:
        name = cls.__name__
        s1 = re.sub("(.)([A-Z][a-z]+)", r"\1_\2", name)
        return re.sub("([a-z0-9])([A-Z])", r"\1_\2", s1).lower()

    # ---- creación de colección (idempotente)
    @classmethod
    def _ensure_collection(cls) -> None:
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
        payload = record.payload or {}
        return cls(
            id=UUID(str(record.id)),
            content=payload.get("content", ""),
            embedding=getattr(record, "vector", None),
            metadata=payload.get("metadata", {}) or {},
        )

    # ---- escritura
    def save(self) -> None:
        type(self)._ensure_collection()
        point = self.to_point()
        qdrant.upsert(collection_name=type(self).get_collection_name(), points=[point])

    @classmethod
    def save_many(cls: Type[T], docs: list[T]) -> None:
        cls._ensure_collection()
        points = [d.to_point() for d in docs]
        qdrant.upsert(collection_name=cls.get_collection_name(), points=points)

    @classmethod
    def bulk_find(cls: Type[T], limit: int = 10, offset: UUID | None = None) -> tuple[list[T], UUID | None]:
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
    def search(cls: Type[T], query_vector: list[float], limit: int = 10, **kwargs) -> list[T]:
        cls._ensure_collection()
        records = qdrant.search(
            collection_name=cls.get_collection_name(),
            query_vector=query_vector,
            limit=limit,
            with_payload=kwargs.pop("with_payload", True),
            with_vectors=kwargs.pop("with_vectors", False),
            **kwargs,
        )
        return [cls.from_record(r) for r in records]


# =========================
# Caso mínimo de uso
# =========================
class EmbeddedSectionChunk(VectorBaseDocument):
    """Ejemplo de entidad concreta."""
    pass


if __name__ == "__main__":
    # Embebe y guarda un chunk
    text = "Hola Qdrant desde el libro."
    vec = embedding_model(text, to_list=True)
    doc = EmbeddedSectionChunk(content=text, embedding=vec)
    doc.save()
    results = EmbeddedSectionChunk.search(query_vector=vec, limit=3)
    print(f"Resultados: {len(results)}")
