from __future__ import annotations
from datetime import datetime
from zoneinfo import ZoneInfo
from app.extensions import db, mail
from flask_mail import Message
from flask import current_app

class VectorUpdateState(db.Model):
    __tablename__ = "vector_update_state"

    id = db.Column(db.Integer, primary_key=True)

    status = db.Column(db.String(20), nullable=False, default="queued", index=True)
    # queued | running | done | failed

    progress = db.Column(db.Integer, nullable=False, default=0) 
    current_doc = db.Column(db.String(255), nullable=True)

    error = db.Column(db.Text, nullable=True)

    created_at = db.Column(db.DateTime(timezone=True), nullable=False, index=True)
    started_at = db.Column(db.DateTime(timezone=True), nullable=True, index=True)
    finished_at = db.Column(db.DateTime(timezone=True), nullable=True, index=True)

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        if not self.created_at:
            self.created_at = datetime.now(ZoneInfo("Europe/Madrid"))
            
def send_update_finished_email(to_email: str, ok: bool, message: str, job_id: int):
    subject = "Actualización base de datos vectorial finalizado" if ok else "Actualización base de datos vectorial fallido"

    base_url = current_app.config.get("FRONTEND_BASE_URL", "")
    docs_url = f"{base_url}/admin/documents/list" if base_url else None

    body = f"""Hola,

    {message}

    Job ID: {job_id}
    
    Puedes ver los documentos aquí:\n{docs_url}\n
    """
    msg = Message(subject=subject, recipients=[to_email], body=body)
    mail.send(msg)

