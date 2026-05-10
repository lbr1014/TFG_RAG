"""
Autora: Lydia Blanco Ruiz
Script con la entidad SQLAlchemy que registra el estado de procesos de web scraping.
"""

from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

from app.main.code.extensions import db
from app.main.code.model.job_state import JobStateMixin


class WebScrapingSate(JobStateMixin, db.Model):
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

    id = db.Column(db.Integer, primary_key=True)
    status = db.Column(db.String(20), nullable=False, default="queued", index=True)
    progress = db.Column(db.Integer, nullable=False, default=0)
    message = db.Column(db.String(255), nullable=True)
    cancel_requested = db.Column(db.Boolean, nullable=False, default=False, index=True)
    error = db.Column(db.Text, nullable=True)
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, index=True)
    started_at = db.Column(db.DateTime(timezone=True), nullable=True, index=True)
    finished_at = db.Column(db.DateTime(timezone=True), nullable=True, index=True)

    def __init__(self, **kwargs) -> None:
        """
        Inicializa el estado con fecha de creación por defecto.

        Args:
            **kwargs: Valores iniciales del modelo SQLAlchemy.
        """
        super().__init__(**kwargs)
        if not self.created_at:
            self.created_at = datetime.now(ZoneInfo("Europe/Madrid"))
