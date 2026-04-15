"""
Autora: Lydia Blanco Ruiz
Script para las rutas de consulta RAG, seguimiento de estado y cancelación de consultas.
"""

import asyncio
from datetime import datetime
from zoneinfo import ZoneInfo

from flask import Blueprint, abort, current_app, jsonify, render_template, request
from flask_login import current_user, login_required

from app.async_tasks import executor
from app.entities.rag_query_state import RAGQueryState
from app.extensions import db
from app.forms import EmptyForm, RAGQueryForm

from app.rag.PrototipoRAG import QueryCancelledError
from app.rag.service import rag_answer, validate_question
from app.inetrnacionalizacion.tarduccion import get_locale, localize_runtime_message, t, translate_for

rag_bp = Blueprint("rag", __name__, url_prefix="/rag")


@rag_bp.get("/")
@login_required
def rag_page():
    """Muestra la página de consulta RAG.

    Returns:
        Respuesta HTML con el formulario de consulta.
    """
    form = RAGQueryForm()
    return render_template("rag.html", form=form)


def get_user_job_or_404(job_id: int) -> RAGQueryState:
    """Obtiene una consulta asíncrona del usuario actual o aborta.

    Args:
        job_id: Identificador de la consulta asíncrona.

    Returns:
        Estado de la consulta RAG perteneciente al usuario autenticado.

    Raises:
        werkzeug.exceptions.NotFound: Si no existe o no pertenece al usuario.
    """
    job = RAGQueryState.query.filter_by(id=job_id, user_id=int(current_user.id)).first()
    if not job:
        abort(404)
    return job


@rag_bp.post("/ask")
@login_required
def rag_ask():
    """Crea o reutiliza una consulta RAG asíncrona.

    Returns:
        Respuesta JSON con el identificador del trabajo creado o reutilizado.
    """
    form = RAGQueryForm()
    if not form.validate_on_submit():
        return jsonify({"error": t("rag.invalid_question")}), 400

    question = (form.question.data or "").strip()
    current_lang = get_locale()
    invalid = validate_question(question, lang=current_lang)
    if invalid:
        return jsonify({"error": invalid.get("answer") or t("rag.invalid_question")}), 400

    active_job = (
        RAGQueryState.query
        .filter(
            RAGQueryState.user_id == int(current_user.id),
            RAGQueryState.status.in_(["queued", "running"]),
        )
        .order_by(RAGQueryState.created_at.desc())
        .first()
    )
    if active_job:
        return jsonify({"job_id": active_job.id, "reused": True}), 202

    job = RAGQueryState(
        user_id=int(current_user.id),
        question=question,
        status="queued",
        message=t("rag.queued"),
        result_payload=None,
        error=None,
        cancel_requested=False,
    )
    db.session.add(job)
    db.session.commit()

    app_obj = current_app._get_current_object()
    executor.submit(run_rag_query_async, app_obj, job.id, int(current_user.id), current_lang)

    return jsonify({"job_id": job.id}), 202


@rag_bp.get("/status/<int:job_id>")
@login_required
def rag_status(job_id: int):
    """Devuelve el estado de una consulta RAG.

    Args:
        job_id: Identificador de la consulta asíncrona.

    Returns:
        Respuesta JSON con estado, mensaje, error y resultado.
    """
    job = get_user_job_or_404(job_id)
    return jsonify(
        {
            "status": job.status,
            "message": localize_runtime_message(job.message),
            "error": job.error,
            "result": job.result_payload,
            "cancel_requested": bool(job.cancel_requested),
        }
    )


@rag_bp.post("/cancel/<int:job_id>")
@login_required
def rag_cancel(job_id: int):
    """Solicita la cancelación de una consulta RAG.

    Args:
        job_id: Identificador de la consulta asíncrona.

    Returns:
        Respuesta JSON con el estado actualizado.
    """
    form = EmptyForm()
    if not form.validate_on_submit():
        return jsonify({"error": t("errors.bad_request_message")}), 400

    job = get_user_job_or_404(job_id)

    if job.status in {"done", "failed", "cancelled"}:
        return jsonify({"status": job.status, "message": localize_runtime_message(job.message)}), 200

    job.cancel_requested = True
    job.message = t("rag.cancelling")

    if job.status == "queued":
        job.status = "cancelled"
        job.finished_at = datetime.now(ZoneInfo("Europe/Madrid"))

    db.session.commit()
    return jsonify({"status": job.status, "message": localize_runtime_message(job.message)}), 202


def run_rag_query_async(app, job_id: int, user_id: int, lang: str = "es") -> None:
    """Ejecuta una consulta RAG dentro de un contexto de aplicación.

    Args:
        app: Aplicación Flask usada para abrir el contexto.
        job_id: Identificador de la consulta asíncrona.
        user_id: Identificador del usuario propietario.
        lang: Idioma usado para mensajes de estado.
    """
    zone_now = datetime.now(ZoneInfo("Europe/Madrid"))

    with app.app_context():
        job = db.session.get(RAGQueryState, job_id)
        if not job or job.user_id != user_id:
            return

        try:
            if job.cancel_requested:
                job.status = "cancelled"
                job.message = translate_for(lang, "rag.cancelled")
                job.finished_at = zone_now
                db.session.commit()
                return

            job.status = "running"
            job.started_at = zone_now
            job.message = translate_for(lang, "rag.starting")
            job.error = None
            job.result_payload = None
            db.session.commit()

            def should_cancel() -> bool:
                db.session.refresh(job)
                return bool(job.cancel_requested)

            def on_status(message: str) -> None:
                db.session.refresh(job)
                if job.status in {"done", "failed", "cancelled"}:
                    return
                job.message = message
                db.session.commit()

            result = asyncio.run(
                rag_answer(
                    job.question,
                    should_cancel=should_cancel,
                    on_status=on_status,
                    user_id=user_id,
                    lang=lang,
                )
            )

            db.session.refresh(job)
            if job.cancel_requested:
                job.status = "cancelled"
                job.message = localize_runtime_message("Consulta cancelada.", lang)
                job.finished_at = datetime.now(ZoneInfo("Europe/Madrid"))
                db.session.commit()
                return

            job.status = "done"
            job.message = localize_runtime_message("Consulta finalizada.", lang)
            job.result_payload = result
            job.finished_at = datetime.now(ZoneInfo("Europe/Madrid"))
            db.session.commit()
        except QueryCancelledError:
            db.session.rollback()
            job = db.session.get(RAGQueryState, job_id)
            if job:
                job.status = "cancelled"
                job.message = localize_runtime_message("Consulta cancelada.", lang)
                job.finished_at = datetime.now(ZoneInfo("Europe/Madrid"))
                db.session.commit()
        except Exception as exc:
            db.session.rollback()
            job = db.session.get(RAGQueryState, job_id)
            if job:
                job.status = "failed"
                job.message = localize_runtime_message("La consulta ha fallado.", lang)
                job.error = str(exc)
                job.finished_at = datetime.now(ZoneInfo("Europe/Madrid"))
                db.session.commit()
            app.logger.exception("Error en run_rag_query_async")
        finally:
            db.session.remove()
