"""
Autora: Lydia Blanco Ruiz
Script con la entidad SQLAlchemy que registra el estado de actualizaciones vectoriales.
"""

from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

from app.main.code.extensions import db
from app.main.code.model.job_state import JobStateMixin


class VectorUpdateState(JobStateMixin, db.Model):
    """
    Estado persistido de un proceso de actualización vectorial.

    Attributes:
        id: Identificador del proceso.
        status: Estado actual del proceso.
        progress: Progreso porcentual.
        current_doc: Documento que se está procesando.
        cancel_requested: Indica si se ha solicitado cancelación.
        error: Error registrado, si lo hay.
        created_at: Fecha de creación.
        started_at: Fecha de inicio.
        finished_at: Fecha de finalización.
    """

    __tablename__ = "vector_update_state"

    id = db.Column(db.Integer, primary_key=True)
    status = db.Column(db.String(20), nullable=False, default="queued", index=True)
    progress = db.Column(db.Integer, nullable=False, default=0)
    current_doc = db.Column(db.String(255), nullable=True)
    cancel_requested = db.Column(db.Boolean, nullable=False, default=False, index=True)
    error = db.Column(db.Text, nullable=True)
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, index=True)
    started_at = db.Column(db.DateTime(timezone=True), nullable=True, index=True)
    finished_at = db.Column(db.DateTime(timezone=True), nullable=True, index=True)

    def __init__(self, **kwargs):
        """
        Inicializa el estado con fecha de creación por defecto.

        Args:
            **kwargs: Valores iniciales del modelo SQLAlchemy.
        """
        super().__init__(**kwargs)
        if not self.created_at:
            self.created_at = datetime.now(ZoneInfo("Europe/Madrid"))

    def set_current_doc(self, name: str | None) -> None:
        """
        Actualiza el documento que se está procesando.

        Args:
            name: Nombre del documento.
        """
        self.current_doc = name
