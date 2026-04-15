"""
Autora: Lydia Blanco Ruiz
Script con la entidad SQLAlchemy que relaciona consultas con fragmentos recuperados.
"""

from __future__ import annotations

from sqlalchemy import UniqueConstraint

from app.extensions import db


class ConsultaChunk(db.Model):
    """Relación entre una consulta y un fragmento recuperado.

    Attributes:
        consulta_id: Identificador de la consulta.
        chunk_id: Identificador del fragmento usado.
        similitud: Puntuación de similitud del fragmento.
        ranking: Posición del fragmento en los resultados recuperados.
        consulta: Consulta asociada.
        chunk: Fragmento asociado.
    """

    __tablename__ = "consultaChunks"

    consulta_id = db.Column(db.Integer, db.ForeignKey("consultas.id", ondelete="CASCADE"), primary_key=True)
    chunk_id = db.Column(db.Integer, db.ForeignKey("chunks.id", ondelete="CASCADE"), primary_key=True)
    similitud = db.Column(db.Float, nullable=False)
    ranking = db.Column(db.Integer, nullable=False)
    consulta = db.relationship(
        "Consulta",
        backref=db.backref("consultaChunks", lazy=True, cascade="all, delete-orphan"),
        passive_deletes=True,
    )
    chunk = db.relationship("Chunk", passive_deletes=True)

    __table_args__ = (
        UniqueConstraint("consulta_id", "ranking", name="uq_consulta_rank"),
    )
