from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

from sqlalchemy import JSON

from .extensions import db


class Consulta(db.Model):
    __tablename__ = "consultas"

    id = db.Column(db.Integer, primary_key=True)

    # El usuario que realizó la consulta
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False, index=True)
    user = db.relationship("User", backref=db.backref("consultas", lazy=True))

    # La pregunta que hizo
    pregunta = db.Column(db.Text, nullable=False)
    respuesta = db.Column(db.Text, nullable=False)

    # Los documentos en los que se baso
    fragmentos = db.Column(JSON, nullable=False, default=dict)

    # El tiempo que tardo en responder
    tiempo_respuestas = db.Column(db.Float, nullable=False)

    # Cuándo hizo la ocnsulta
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, index=True)

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        if not self.created_at:
            self.created_at = datetime.now(ZoneInfo("Europe/Madrid"))
