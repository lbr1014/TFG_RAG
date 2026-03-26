import asyncio
from datetime import datetime
from zoneinfo import ZoneInfo

from flask import Blueprint, abort, current_app, jsonify, render_template, request
from flask_login import current_user, login_required

from app.async_tasks import executor
from app.extensions import db
from app.forms import RAGQueryForm
from app.rag_query_state import RAGQueryState

from app.rag.PrototipoRAG import QueryCancelledError
from app.rag.service import rag_answer, validate_question

rag_bp = Blueprint("rag", __name__, url_prefix="/rag")


@rag_bp.get("/")
@login_required
def rag_page():
    form = RAGQueryForm()
    return render_template("rag.html", form=form)


def get_user_job_or_404(job_id: int) -> RAGQueryState:
    job = RAGQueryState.query.filter_by(id=job_id, user_id=int(current_user.id)).first()
    if not job:
        abort(404)
    return job


@rag_bp.post("/ask")
@login_required
def rag_ask():
    question = (request.form.get("question") or "").strip()
    invalid = validate_question(question)
    if invalid:
        return jsonify({"error": invalid.get("answer") or "Escribe una pregunta valida."}), 400

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
        message="Consulta en cola.",
        result_payload=None,
        error=None,
        cancel_requested=False,
    )
    db.session.add(job)
    db.session.commit()

    app_obj = current_app._get_current_object()
    executor.submit(run_rag_query_async, app_obj, job.id, int(current_user.id))

    return jsonify({"job_id": job.id}), 202


@rag_bp.get("/status/<int:job_id>")
@login_required
def rag_status(job_id: int):
    job = get_user_job_or_404(job_id)
    return jsonify(
        {
            "status": job.status,
            "message": job.message,
            "error": job.error,
            "result": job.result_payload,
            "cancel_requested": bool(job.cancel_requested),
        }
    )


@rag_bp.post("/cancel/<int:job_id>")
@login_required
def rag_cancel(job_id: int):
    job = get_user_job_or_404(job_id)

    if job.status in {"done", "failed", "cancelled"}:
        return jsonify({"status": job.status, "message": job.message}), 200

    job.cancel_requested = True
    job.message = "Cancelando consulta..."

    if job.status == "queued":
        job.status = "cancelled"
        job.finished_at = datetime.now(ZoneInfo("Europe/Madrid"))

    db.session.commit()
    return jsonify({"status": job.status, "message": job.message}), 202


def run_rag_query_async(app, job_id: int, user_id: int) -> None:
    zone_now = datetime.now(ZoneInfo("Europe/Madrid"))

    with app.app_context():
        job = db.session.get(RAGQueryState, job_id)
        if not job or job.user_id != user_id:
            return

        try:
            if job.cancel_requested:
                job.status = "cancelled"
                job.message = "Consulta cancelada."
                job.finished_at = zone_now
                db.session.commit()
                return

            job.status = "running"
            job.started_at = zone_now
            job.message = "Iniciando consulta..."
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
                )
            )

            db.session.refresh(job)
            if job.cancel_requested:
                job.status = "cancelled"
                job.message = "Consulta cancelada."
                job.finished_at = datetime.now(ZoneInfo("Europe/Madrid"))
                db.session.commit()
                return

            job.status = "done"
            job.message = "Consulta finalizada."
            job.result_payload = result
            job.finished_at = datetime.now(ZoneInfo("Europe/Madrid"))
            db.session.commit()
        except QueryCancelledError:
            db.session.rollback()
            job = db.session.get(RAGQueryState, job_id)
            if job:
                job.status = "cancelled"
                job.message = "Consulta cancelada."
                job.finished_at = datetime.now(ZoneInfo("Europe/Madrid"))
                db.session.commit()
        except Exception as exc:
            db.session.rollback()
            job = db.session.get(RAGQueryState, job_id)
            if job:
                job.status = "failed"
                job.message = "La consulta ha fallado."
                job.error = str(exc)
                job.finished_at = datetime.now(ZoneInfo("Europe/Madrid"))
                db.session.commit()
            app.logger.exception("Error en run_rag_query_async")
        finally:
            db.session.remove()
