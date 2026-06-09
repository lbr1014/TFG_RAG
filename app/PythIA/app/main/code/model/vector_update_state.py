"""
Autora: Lydia Blanco Ruiz
Script con la entidad SQLAlchemy que registra el estado de actualizaciones vectoriales.
"""

from __future__ import annotations

from app.main.code.extensions import db
from app.main.code.model.job_state import State


class VectorUpdateState(State):
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

    current_doc = db.Column(db.String(255), nullable=True)

    def set_current_doc(self, name: str | None) -> None:
        """
        Actualiza el documento que se esta procesando.
        """
        self.current_doc = name
