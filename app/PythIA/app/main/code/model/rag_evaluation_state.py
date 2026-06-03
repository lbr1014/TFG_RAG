"""
Autora: Lydia Blanco Ruiz
Entidad SQLAlchemy que registra el estado de evaluaciones del RAG.
"""

from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

from app.main.code.extensions import db
from app.main.code.model.job_state import JobStateMixin


class RAGEvaluationState(JobStateMixin, db.Model):
    """
    Estado persistido de una ejecución de evaluación del RAG.
    Guarda progreso y rutas a los resultados generados (resúmenes/resultados).
    
    Args:
        JobStateMixin: Mezcla común para estados de jobs, con campos como status, progress, message, cancel_requested y error.
        db.Model: Modelo base de SQLAlchemy para persistencia en la base de datos.
    """

    __tablename__ = "rag_evaluation_state"

    id = db.Column(db.Integer, primary_key=True)
    status = db.Column(db.String(20), nullable=False, default="queued", index=True)
    progress = db.Column(db.Integer, nullable=False, default=0)
    message = db.Column(db.String(255), nullable=True)
    cancel_requested = db.Column(db.Boolean, nullable=False, default=False, index=True)
    error = db.Column(db.Text, nullable=True)

    output_dir = db.Column(db.String(512), nullable=True)
    results_json_path = db.Column(db.String(512), nullable=True)
    row_results_json_path = db.Column(db.String(512), nullable=True)
    config_json_path = db.Column(db.String(512), nullable=True)
    ares_questions_json_path = db.Column(db.String(512), nullable=True)
    ares_dataset_json_path = db.Column(db.String(512), nullable=True)
    ares_dataset_tsv_path = db.Column(db.String(512), nullable=True)

    created_at = db.Column(db.DateTime(timezone=True), nullable=False, index=True)
    started_at = db.Column(db.DateTime(timezone=True), nullable=True, index=True)
    finished_at = db.Column(db.DateTime(timezone=True), nullable=True, index=True)

    def __init__(self, **kwargs) -> None:
        """
        Inicializa un nuevo estado de evaluación del RAG, estableciendo created_at si no se proporciona.
        
        Args:
            **kwargs: Argumentos para inicializar el modelo, como status, message, etc.
        """
        super().__init__(**kwargs)
        if not self.created_at:
            self.created_at = datetime.now(ZoneInfo("Europe/Madrid"))

