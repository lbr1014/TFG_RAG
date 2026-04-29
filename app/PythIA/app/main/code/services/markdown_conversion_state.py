"""
Autora: Lydia Blanco Ruiz
Script para enviar notificaciones por correo al finalizar procesos de conversión a Markdown.
"""

from __future__ import annotations
from flask import current_app
from flask_mail import Message
from app.main.code.extensions import mail

def send_markdown_finished_email(
    to_email: str,
    ok: bool,
    message: str,
    job_id: int,
    docs_url: str | None = None,
    converted_docs: int | None = None,
    skipped_docs: int | None = None,
):
    """
    Envía el correo de fin de conversión a Markdown.

    Args:
        to_email: Destinatario del correo.
        ok: Indica si el proceso terminó correctamente.
        message: Mensaje principal del correo.
        job_id: Identificador del proceso.
        docs_url: URL de la página de documentos.
        converted_docs: Número de documentos convertidos.
        skipped_docs: Número de documentos omitidos.
    """
    subject = "Conversión a Markdown finalizada" if ok else "Conversión a Markdown fallida"
    base_url = current_app.config.get("FRONTEND_BASE_URL", "").rstrip("/")
    resolved_docs_url = docs_url or (
        f"{base_url}/admin/documents/list" if base_url else "/admin/documents/list"
    )

    details = []

    if converted_docs is not None:
        details.append(f"Documentos convertidos: {converted_docs}")

    if skipped_docs is not None:
        details.append(f"Documentos omitidos: {skipped_docs}")

    details_block = "\n".join(details) if details else "Sin métricas disponibles."

    body = (
        f"Hola,\n\n"
        f"{message}\n\n"
        f"Job ID: {job_id}\n"
        f"{details_block}\n\n"
        f"Puedes revisar los documentos aquí:\n"
        f"{resolved_docs_url}\n"
    )

    msg = Message(subject=subject, recipients=[to_email], body=body)
    mail.send(msg)

__all__ = ["send_markdown_finished_email"]
