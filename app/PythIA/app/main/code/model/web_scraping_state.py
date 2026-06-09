"""
Autora: Lydia Blanco Ruiz
Script con la entidad SQLAlchemy que registra el estado de procesos de web scraping.
"""

from __future__ import annotations

from app.main.code.extensions import db
from app.main.code.model.job_state import State


class WebScrapingSate(State):
    """
    Estado persistido de un proceso de web scraping.

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

    __tablename__ = "web_scraping_sate"

    message = db.Column(db.String(255), nullable=True)
