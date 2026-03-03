from __future__ import annotations
from datetime import datetime
from zoneinfo import ZoneInfo
from sqlalchemy import UniqueConstraint
from .extensions import db

class Chunk(db.Model):
    __tablename__ = "chunks"

    id = db.Column(db.Integer, primary_key=True)

    # Relación con Documento
    document_id = db.Column(db.Integer, db.ForeignKey("documents.id"), nullable=False, index=True)
    document = db.relationship("Documento", backref=db.backref("chunks_meta", lazy=True, cascade="all, delete-orphan"))

    # ID del punto en Qdrant
    qdrant_point_id = db.Column(db.String(36), nullable=False, index=True)

    # Posición dentro del documento (segment_index)
    segment_index = db.Column(db.Integer, nullable=False)

    # Control de versiones
    doc_sha256 = db.Column(db.String(100), nullable=False, index=True)

    # Metadatos
    n_chars = db.Column(db.Integer, nullable=True)
    n_tokens = db.Column(db.Integer, nullable=True)

    created_at = db.Column(db.DateTime(timezone=True), nullable=False, index=True)

    __table_args__ = (
        # Evita duplicar el mismo chunk
        UniqueConstraint("document_id", "doc_sha256", "segment_index", name="uq_chunk_doc_hash_seg"),
        {"sqlite_autoincrement": True},
    )

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        if not self.created_at:
            self.created_at = datetime.now(ZoneInfo("Europe/Madrid"))
