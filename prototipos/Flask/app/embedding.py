from __future__ import annotations
from datetime import datetime
from zoneinfo import ZoneInfo
from .extensions import db

class Embedding(db.Model):
    __tablename__ = "embeddings"

    id = db.Column(db.Integer, primary_key=True)

    # Relación con Chunk
    chunk_id = db.Column(db.Integer, db.ForeignKey("chunks.id"), nullable=False, unique=True, index=True)
    chunk = db.relationship("Chunk", backref=db.backref("embedding_meta", uselist=False, cascade="all, delete-orphan"))

    model_id = db.Column(db.String(255), nullable=False)
    embedding_size = db.Column(db.Integer, nullable=False)
    distance = db.Column(db.String(50), nullable=False, default="cosine")

    created_at = db.Column(db.DateTime(timezone=True), nullable=False, index=True)

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        if not self.created_at:
            self.created_at = datetime.now(ZoneInfo("Europe/Madrid"))
