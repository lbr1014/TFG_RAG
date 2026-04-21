"""
Autora: Lydia Blanco Ruiz
Script con la entidad SQLAlchemy que representa una consulta realizada al sistema RAG.
"""

from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

from sqlalchemy import JSON

from app.extensions import db


class Consulta(db.Model):
    """Consulta realizada por un usuario y respuesta generada por el sistema.

    Attributes:
        id: Identificador interno de la consulta.
        user_id: Identificador del usuario que hizo la pregunta.
        user: Usuario asociado a la consulta.
        pregunta: Texto enviado por el usuario.
        respuesta: Respuesta generada por el sistema RAG.
        fragmentos: Fragmentos recuperados y guardados junto a la respuesta.
        tiempo_respuestas: Tiempo de generación de la respuesta, en segundos.
        created_at: Fecha y hora de creación de la consulta.
    """

    __tablename__ = "consultas"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    user = db.relationship(
        "User",
        backref=db.backref("consultas", lazy=True, cascade="all, delete-orphan", passive_deletes=True),
        passive_deletes=True,
    )
    pregunta = db.Column(db.Text, nullable=False)
    respuesta = db.Column(db.Text, nullable=False)
    fragmentos = db.Column(JSON, nullable=False, default=list)
    tiempo_respuestas = db.Column(db.Float, nullable=False)
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, index=True)

    def __init__(self, **kwargs):
        """Inicializa la consulta con fecha de creación por defecto.

        Args:
            **kwargs: Valores iniciales del modelo SQLAlchemy.
        """
        super().__init__(**kwargs)
        if not self.created_at:
            self.created_at = datetime.now(ZoneInfo("Europe/Madrid"))
