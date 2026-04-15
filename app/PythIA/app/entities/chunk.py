"""
Autora: Lydia Blanco Ruiz
Script con la entidad SQLAlchemy que representa un fragmento indexado de un documento.
"""

from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

from sqlalchemy import UniqueConstraint

from app.extensions import db


class Chunk(db.Model):
    """Fragmento indexado de un documento.

    Attributes:
        id: Identificador interno del fragmento.
        document_id: Identificador del documento de origen.
        document: Documento SQL asociado.
        qdrant_point_id: Identificador del punto almacenado en Qdrant.
        segment_index: Posición del fragmento dentro del documento.
        doc_sha256: Hash del documento usado para controlar versiones.
        n_chars: Número aproximado de caracteres del fragmento.
        n_tokens: Número aproximado de tokens, si está disponible.
        numero_expediente: Número de expediente inferido o recuperado.
        tipo_documento: Tipo documental inferido.
        created_at: Fecha y hora de creación del fragmento.
    """

    __tablename__ = "chunks"

    id = db.Column(db.Integer, primary_key=True)
    document_id = db.Column(db.Integer, db.ForeignKey("documents.id"), nullable=False, index=True)
    document = db.relationship("Documento", backref=db.backref("chunks_meta", lazy=True, cascade="all, delete-orphan"))
    qdrant_point_id = db.Column(db.String(36), nullable=False, index=True)
    segment_index = db.Column(db.Integer, nullable=False)
    doc_sha256 = db.Column(db.String(100), nullable=False, index=True)
    n_chars = db.Column(db.Integer, nullable=True)
    n_tokens = db.Column(db.Integer, nullable=True)
    numero_expediente = db.Column(db.String(255), nullable=True, index=True)
    tipo_documento = db.Column(db.String(30), nullable=True, index=True)
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, index=True)

    __table_args__ = (
        UniqueConstraint("document_id", "doc_sha256", "segment_index", name="uq_chunk_doc_hash_seg"),
        {"sqlite_autoincrement": True},
    )

    def __init__(self, **kwargs):
        """Inicializa el fragmento con fecha de creación por defecto.

        Args:
            **kwargs: Valores iniciales del modelo SQLAlchemy.
        """
        super().__init__(**kwargs)
        if not self.created_at:
            self.created_at = datetime.now(ZoneInfo("Europe/Madrid"))
