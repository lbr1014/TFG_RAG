"""
Autora: Lydia Blanco Ruiz
Script con la entidad SQLAlchemy que representa un fragmento indexado de un documento.
"""

from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

from sqlalchemy import UniqueConstraint

from app.main.code.extensions import db


class Chunk(db.Model):
    """
    Fragmento indexado de un documento.

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
        """
        Inicializa el fragmento con fecha de creación por defecto.

        Args:
            **kwargs: Valores iniciales del modelo SQLAlchemy.
        """
        super().__init__(**kwargs)
        if not self.created_at:
            self.created_at = datetime.now(ZoneInfo("Europe/Madrid"))
            
    @classmethod
    def find_from_retrieved_item(cls, item: dict) -> "Chunk | None":
        """
        Busca el chunk SQL correspondiente a un resultado recuperado.
        
        Args:
            item (dict): El item recuperado que contiene metadatos de chunk.
            
        Returns:
            Chunk | None: El objeto Chunk SQL correspondiente o None si no se encuentra.
        """
        chunk_obj = None
        qid = (item.get("qdrant_point_id") or "").strip()
        if qid:
            chunk_obj = cls.query.filter_by(qdrant_point_id=qid).first()

        if chunk_obj is None:
            doc_id = item.get("document_id")
            doc_sha = item.get("doc_sha256")
            seg_idx = item.get("segment_index")
            if doc_id is not None and doc_sha and seg_idx is not None:
                chunk_obj = cls.query.filter_by(
                    document_id=int(doc_id),
                    doc_sha256=str(doc_sha),
                    segment_index=int(seg_idx),
                ).first()
        return chunk_obj

    def metadata_for_fragment(self) -> dict:
        """
        Construye los metadatos propios del chunk para guardarlos en una consulta.
        
        Args:
            self: El objeto chunk del que extraer los metadatos.
            
        Returns:
            dict: Diccionario con los metadatos del chunk.
        """
        metadata = {
            "chunk_id": int(self.id),
            "document_id": int(self.document_id),
            "doc_sha256": self.doc_sha256,
            "segment_index": self.segment_index,
            "n_chars": self.n_chars,
            "n_tokens": self.n_tokens,
            "qdrant_point_id": self.qdrant_point_id,
        }
        if self.created_at is not None:
            metadata["created_at"] = self.created_at.isoformat()

        document = getattr(self, "document", None)
        if document is not None:
            metadata.update(
                {
                    "document_name": document.nombre,
                    "document_path": document.path,
                    "document_hash": document.hash,
                }
            )
        return metadata

    @staticmethod
    def build_fragment_from_retrieved_item(item: dict, chunk_obj: "Chunk | None" = None) -> dict:
        """
        Construye el fragmento serializable que se guarda en Consulta.fragmentos.
        
        Args:
            item (dict): El item recuperado.
            chunk_obj (Chunk | None): El objeto chunk SQL correspondiente.
            
        Returns:
            dict: El fragmento serializable.
        """
        chunk_metadata = dict(item.get("metadata") or {})
        chunk = item.get("chunk", "") or ""

        if chunk_obj is not None:
            for key, value in chunk_obj.metadata_for_fragment().items():
                chunk_metadata.setdefault(key, value)

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
