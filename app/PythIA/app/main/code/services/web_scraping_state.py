"""
Autora: Lydia Blanco Ruiz
Script para enviar notificaciones por correo al finalizar procesos de web scraping.
"""
from __future__ import annotations

from flask import current_app
from flask_mail import Message

from app.main.code.extensions import mail


def send_scraping_finished_email(
    to_email: str,
    ok: bool,
    message: str,
    job_id: int,
    docs_url: str | None = None,
    extracted_docs: int | None = None,
    synced_total_docs: int | None = None,
) -> None:
    """
    Envía el correo de fin de web scraping.

    Args:
        to_email: Destinatario del correo.
        ok: Indica si el proceso terminó correctamente.
        message: Mensaje principal del correo.
        job_id: Identificador del proceso.
        docs_url: URL de la página de documentos.
        extracted_docs: Número de documentos extraídos.
        synced_total_docs: Total de documentos sincronizados después de proceso.
    """
    subject = "Web scraping finalizado" if ok else "Web scraping fallido"
    base_url = current_app.config.get("FRONTEND_BASE_URL", "").rstrip("/")
    resolved_docs_url = docs_url or (
        f"{base_url}/admin/documents/list" if base_url else "/admin/documents/list"
    )
    details = []
    if extracted_docs is not None:
        details.append(f"Documentos extraídos del scraping: {extracted_docs}")

    if synced_total_docs is not None:
        details.append(f"Documentos sincronizados tras el proceso: {synced_total_docs}")

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

__all__ = ["send_scraping_finished_email"]
