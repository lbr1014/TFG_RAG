"""
Autora: Lydia Blanco Ruiz
Script con la entidad SQLAlchemy que registra el estado de consultas RAG asíncronas.
"""

from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

from app.extensions import db


class RAGQueryState(db.Model):
    """Estado persistido de una consulta RAG asíncrona.

    Attributes:
        id: Identificador de la consulta asíncrona.
        user_id: Identificador del usuario propietario.
        question: Pregunta enviada por el usuario.
        status: Estado actual de la consulta.
        message: Mensaje visible para el usuario.
        result_payload: Resultado serializable de la consulta.
        error: Error registrado, si lo hay.
        cancel_requested: Indica si se ha solicitado cancelación.
        created_at: Fecha de creación.
        started_at: Fecha de inicio.
        finished_at: Fecha de finalización.
    """

    __tablename__ = "rag_query_state"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    question = db.Column(db.Text, nullable=False)
    status = db.Column(db.String(20), nullable=False, default="queued", index=True)
    message = db.Column(db.String(255), nullable=True)
    result_payload = db.Column(db.JSON, nullable=True)
    error = db.Column(db.Text, nullable=True)
    cancel_requested = db.Column(db.Boolean, nullable=False, default=False, index=True)
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, index=True)
    started_at = db.Column(db.DateTime(timezone=True), nullable=True, index=True)
    finished_at = db.Column(db.DateTime(timezone=True), nullable=True, index=True)

    def __init__(self, **kwargs):
        """Inicializa el estado con fecha de creación por defecto.

        Args:
            **kwargs: Valores iniciales del modelo SQLAlchemy.
        """
        super().__init__(**kwargs)
        if not self.created_at:
            self.created_at = datetime.now(ZoneInfo("Europe/Madrid"))
