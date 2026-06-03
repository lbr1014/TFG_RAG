"""
Autora: Lydia Blanco Ruiz
Script con la entidad SQLAlchemy que guarda metadatos de embeddings asociados a fragmentos.
"""

from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

from app.main.code.extensions import db


class Embedding(db.Model):
    """
    Metadatos del embedding asociado a un fragmento.

    Attributes:
        id: Identificador interno del registro.
        chunk_id: Identificador del fragmento asociado.
        chunk: Fragmento relacionado.
        model_id: Identificador del modelo de embeddings usado.
        embedding_size: Dimensión del vector generado.
        distance: Métrica de distancia usada en la base vectorial.
        created_at: Fecha y hora de creación del registro.
    """

    __tablename__ = "embeddings"

    id = db.Column(db.Integer, primary_key=True)
    chunk_id = db.Column(db.Integer, db.ForeignKey("chunks.id"), nullable=False, unique=True, index=True)
    chunk = db.relationship("Chunk", backref=db.backref("embedding_meta", uselist=False, cascade="all, delete-orphan"))
    model_id = db.Column(db.String(255), nullable=False)
    embedding_size = db.Column(db.Integer, nullable=False)
    distance = db.Column(db.String(50), nullable=False, default="cosine")
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, index=True)

    def __init__(self, **kwargs) -> None:
        """
        Inicializa el registro con fecha de creación por defecto.

        Args:
            **kwargs: Valores iniciales del modelo SQLAlchemy.
        """
        super().__init__(**kwargs)
        if not self.created_at:
            self.created_at = datetime.now(ZoneInfo("Europe/Madrid"))
