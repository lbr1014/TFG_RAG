from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

from flask import current_app
from flask_mail import Message

from app.extensions import db, mail


class MarkdownConversionState(db.Model):
    __tablename__ = "markdown_conversion_state"

    id = db.Column(db.Integer, primary_key=True)

    status = db.Column(db.String(20), nullable=False, default="queued", index=True)
    progress = db.Column(db.Integer, nullable=False, default=0)
    message = db.Column(db.String(255), nullable=True)
    cancel_requested = db.Column(db.Boolean, nullable=False, default=False, index=True)
    error = db.Column(db.Text, nullable=True)

    created_at = db.Column(db.DateTime(timezone=True), nullable=False, index=True)
    started_at = db.Column(db.DateTime(timezone=True), nullable=True, index=True)
    finished_at = db.Column(db.DateTime(timezone=True), nullable=True, index=True)

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        if not self.created_at:
            self.created_at = datetime.now(ZoneInfo("Europe/Madrid"))


def send_markdown_finished_email(
    to_email: str,
    ok: bool,
    message: str,
    job_id: int,
    docs_url: str | None = None,
    converted_docs: int | None = None,
    skipped_docs: int | None = None,
):
    subject = "Conversion a Markdown finalizada" if ok else "Conversion a Markdown fallida"

    base_url = current_app.config.get("FRONTEND_BASE_URL", "").rstrip("/")
    resolved_docs_url = docs_url or (
        f"{base_url}/admin/documents/list" if base_url else "/admin/documents/list"
    )

    details = []
    if converted_docs is not None:
        details.append(f"Documentos convertidos: {converted_docs}")
    if skipped_docs is not None:
        details.append(f"Documentos omitidos: {skipped_docs}")
    details_block = "\n".join(details) if details else "Sin metricas disponibles."

    body = (
        f"Hola,\n\n"
        f"{message}\n\n"
        f"Job ID: {job_id}\n"
        f"{details_block}\n\n"
        f"Puedes revisar los documentos aqui:\n"
        f"{resolved_docs_url}\n"
    )

    msg = Message(subject=subject, recipients=[to_email], body=body)
    mail.send(msg)
