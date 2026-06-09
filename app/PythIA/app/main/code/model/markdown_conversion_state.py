"""
Autora: Lydia Blanco Ruiz
Script con la entidad SQLAlchemy que registra el estado de conversiones a Markdown.
"""

from __future__ import annotations

from app.main.code.extensions import db
from app.main.code.model.job_state import State


class MarkdownConversionState(State):
    """
    Estado persistido de un proceso de conversión a Markdown.

    Attributes:
        id: Identificador del proceso.
        status: Estado actual del proceso.
        progress: Progreso porcentual.
        message: Mensaje visible para el usuario.
        cancel_requested: Indica si se ha solicitado cancelación.
        error: Error registrado, si lo hay.
        created_at: Fecha de creación.
        started_at: Fecha de inicio.
        finished_at: Fecha de finalización.
    """

    __tablename__ = "markdown_conversion_state"

    message = db.Column(db.String(255), nullable=True)
