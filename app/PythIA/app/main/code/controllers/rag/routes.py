"""
Autora: Lydia Blanco Ruiz
Script para las rutas de consulta RAG, seguimiento de estado y cancelación de consultas.
"""

import asyncio
import re
from collections import defaultdict

from flask import abort, current_app, jsonify, render_template, request
from flask_login import current_user, login_required

from . import rag_bp
from app.main.code.services.async_tasks import executor
from app.main.code.model.rag_query_state import RAGQueryState
from app.main.code.extensions import db
from app.main.code.forms import EmptyForm, RAGDefaultQueryForm, RAGQueryForm
from app.main.code.model.documento import Documento
from app.main.code.services.rag.PrototipoRAG import QueryCancelledError, get_rag_llm_model_choices, resolve_rag_llm_model
from app.main.code.services.rag.service import rag_answer, validate_question
from app.main.code.inetrnacionalizacion.tarduccion import get_locale, localize_runtime_message, t, translate_for

@rag_bp.get("/")
@login_required
def rag_page():
    """
    Muestra la página de consulta RAG.

    Returns:
        Respuesta HTML con el formulario de consulta.
    """
    form = RAGQueryForm()
    configure_model_choices(form)
    return render_template("rag.html", form=form)


@rag_bp.get("/consultas-guiadas")
@login_required
def default_query_page():
    """
    Muestra un formulario guiado para construir consultas frecuentes sobre pliegos.

    Returns:
        Respuesta HTML con el formulario de consultas predefinidas.
    """
    form = RAGDefaultQueryForm()
    configure_default_query_form(form)
    return render_template("rag_default_query.html", form=form)


@rag_bp.get("/modelos")
@login_required
def model_comparison_page():
    """
    Muestra comparativas de uso y rendimiento por modelo RAG.
    Los administradores ven el uso global y los usuarios normales ven sus propias
    consultas terminadas.
    
    Returns:
        Respuesta HTML con la comparación de modelos y estadísticas agregadas.
    """
    payload = build_model_comparison_payload()
    return render_template("model_comparison.html", model_stats_payload=payload)


def build_model_comparison_payload() -> dict:
    """
    Construye los datos agregados para comparar modelos LLM.
    Usa RAGQueryState porque conserva el modelo seleccionado. Si el
    resultado no contiene contadores reales de tokens, usa una estimacion basada
    en el texto de entrada y salida para poder comparar consultas historicas.

    Returns:
        dict: Payload con comparación de modelos y estadísticas agregadas.
    """
    base_query = RAGQueryState.query.filter(RAGQueryState.status == "done")
    if not getattr(current_user, "is_admin", False):
        base_query = base_query.filter(RAGQueryState.user_id == int(current_user.id))

    jobs = base_query.order_by(RAGQueryState.finished_at.asc(), RAGQueryState.created_at.asc()).all()
    models = defaultdict(
        lambda: {
            "model": "",
            "uses": 0,
            "users": set(),
            "tokens": 0,
            "response_times": [],
            "cpu": 0,
            "gpu": 0,
            "unknown_device": 0,
        }
    )

    for job in jobs:
        result = job.result_payload or {}
        model_name = (job.model_name or result.get("model") or resolve_rag_llm_model()).strip()
        row = models[model_name]
        row["model"] = model_name
        row["uses"] += 1
        row["users"].add(int(job.user_id))
        row["tokens"] += extract_token_count(job, result)
        row["response_times"].append(extract_response_time(job, result))

        device = str(result.get("execution_device") or "").upper()
        if "GPU" in device:
            row["gpu"] += 1
        elif "CPU" in device:
            row["cpu"] += 1
        else:
            row["unknown_device"] += 1

    comparison = []
    total_uses = 0
    total_tokens = 0
    all_times = []
    for row in models.values():
        response_times = [value for value in row["response_times"] if value is not None]
        avg_time = round(sum(response_times) / len(response_times), 2) if response_times else 0
        item = {
            "model": row["model"],
            "uses": row["uses"],
            "users": len(row["users"]),
            "tokens": int(row["tokens"]),
            "avg_time": avg_time,
            "cpu": row["cpu"],
            "gpu": row["gpu"],
            "unknown_device": row["unknown_device"],
        }
        comparison.append(item)
        total_uses += item["uses"]
        total_tokens += item["tokens"]
        all_times.extend(response_times)

    comparison.sort(key=lambda item: (-item["uses"], item["model"]))
    return {
        "summary": {
            "models": len(comparison),
            "total_uses": total_uses,
            "total_tokens": total_tokens,
            "avg_time": round(sum(all_times) / len(all_times), 2) if all_times else 0,
        },
        "models": comparison,
        "scope": "global" if getattr(current_user, "is_admin", False) else "user",
    }


def extract_response_time(job: RAGQueryState, result: dict) -> float | None:
    """
    Extrae el tiempo de respuesta en segundos desde el payload ("elapsed_s") o las marcas del job.
    
    Args:
        job (RAGQueryState): El estado de la consulta RAG.
        result (dict): El resultado de la consulta que puede contener un campo "elapsed_s".
    
    Returns:
        float | None: El tiempo de respuesta en segundos, o None si no se puede determinar.
    """
    elapsed = result.get("elapsed_s")
    if isinstance(elapsed, (int, float)):
        return float(elapsed)

    if job.started_at and job.finished_at:
        return max(0.0, (job.finished_at - job.started_at).total_seconds())
    if job.created_at and job.finished_at:
        return max(0.0, (job.finished_at - job.created_at).total_seconds())
    return None


def extract_token_count(job: RAGQueryState, result: dict) -> int:
    """
    Extrae tokens reales si existen o calcula una estimacion sencilla.
    
    Args:
        job (RAGQueryState): El estado de la consulta RAG. 
        result (dict): El resultado de la consulta que puede contener campos de conteo de tokens.
    
    Returns:
        int: El número de tokens usados, o una estimación basada en el texto si no se dispone de contadores reales.
    """
    for key in ("total_tokens", "tokens", "eval_count"):
        value = result.get(key)
        if isinstance(value, (int, float)) and value >= 0:
            return int(value)

    usage = result.get("usage") or {}
    if isinstance(usage, dict):
        total = usage.get("total_tokens")
        if isinstance(total, (int, float)) and total >= 0:
            return int(total)

    text = f"{job.question or ''} {result.get('answer') or ''}"
    words = re.findall(r"\w+|[^\w\s]", text, flags=re.UNICODE)
    return int(round(len(words) * 1.33)) if words else 0

def configure_model_choices(form: RAGQueryForm) -> None:
    """
    Carga en el formulario los modelos LLM disponibles para Ollama.
    """
    form.model.choices = get_rag_llm_model_choices()
    form.model.default = resolve_rag_llm_model()
    if not form.model.data:
        form.model.data = form.model.default


def configure_default_query_form(form: RAGDefaultQueryForm) -> None:
    """
    Carga opciones de expedientes, tipos documentales, preguntas frecuentes y modelos.
    
    Args:
        form (RAGDefaultQueryForm): El formulario a configurar.
    """
    configure_model_choices(form)
    form.expediente.choices = get_expediente_choices()
    form.doc_type.choices = [
        ("", t("rag_default.doc_type_any")),
        ("administrativo", t("rag_default.doc_type_admin")),
        ("tecnico", t("rag_default.doc_type_technical")),
    ]
    form.question_kind.choices = [
        ("general", t("rag_default.question_general")),
        ("amounts", t("rag_default.question_amounts")),
        ("deadlines", t("rag_default.question_deadlines")),
        ("solvency", t("rag_default.question_solvency")),
        ("criteria", t("rag_default.question_criteria")),
        ("guarantees", t("rag_default.question_guarantees")),
        ("budget", t("rag_default.question_budget")),
        ("duration", t("rag_default.question_duration")),
        ("penalties", t("rag_default.question_penalties")),
        ("submission", t("rag_default.question_submission")),
    ]


GUIDED_QUESTION_TEXTS = {
    "general": "Indica la informacion principal y las clausulas mas relevantes.",
    "amounts": "Extrae todas las cantidades economicas, importes, presupuestos, garantias y umbrales relevantes.",
    "deadlines": "Resume los plazos importantes: presentacion de ofertas, ejecucion, adjudicacion, garantias y cualquier fecha limite.",
    "solvency": "Identifica los requisitos de solvencia economica, financiera, tecnica y profesional.",
    "criteria": "Resume los criterios de adjudicacion, su ponderacion y como se valoran.",
    "guarantees": "Indica las garantias provisionales o definitivas exigidas y sus importes o porcentajes.",
    "budget": "Explica el presupuesto base, el valor estimado, impuestos incluidos o excluidos y partidas relevantes.",
    "duration": "Indica la duracion del contrato, posibles prorrogas y condiciones de ejecucion temporal.",
    "penalties": "Resume penalizaciones, incumplimientos, causas de resolucion y obligaciones criticas.",
    "submission": "Explica como y donde presentar la oferta, documentacion requerida y sobres o archivos necesarios.",
}


def is_guided_query_request() -> bool:
    """
    Detecta si la petición procede del formulario de consultas guiadas.
    
    Returns:
        bool: True si la petición contiene campos específicos del formulario guiado, False en caso contrario.
    """
    return any(field in request.form for field in ("expediente", "doc_type", "question_kind", "summary"))


def build_guided_question(form: RAGDefaultQueryForm) -> str:
    """
    Construye en servidor la pregunta del formulario guiado para evita depender exclusivamente del JavaScript del template.
    
    Args:
        form (RAGDefaultQueryForm): El formulario con los datos enviados por el usuario.
        
    Returns:
        str: La pregunta construida para la consulta RAG basada en las opciones seleccionadas.
    """
    expediente = (form.expediente.data or "").strip()
    doc_type = (form.doc_type.data or "").strip()
    question_kind = (form.question_kind.data or "general").strip() or "general"
    summary_mode = bool(form.summary.data)

    scope = f"Para el expediente {expediente}" if expediente else "Para los pliegos disponibles de forma general"
    doc_scope = ""
    if not summary_mode and doc_type:
        doc_type_text = "tecnico" if doc_type == "tecnico" else "administrativo"
        doc_scope = f" en el pliego {doc_type_text}"

    task = (
        "elabora un resumen general y detallado del documento completo."
        if summary_mode
        else GUIDED_QUESTION_TEXTS.get(question_kind, GUIDED_QUESTION_TEXTS["general"])
    )
    return f"{scope}{doc_scope}, {task}".strip()


def get_expediente_choices() -> list[tuple[str, str]]:
    """
    Obtiene los expedientes disponibles desde los documentos cargados.
    
    Returns:
        list[tuple[str, str]]: Lista de tuplas con número de expediente y su traducción para el formulario, incluyendo una opción para "cualquiera".
    """
    rows = (
        db.session.query(Documento.numero_expediente)
        .filter(Documento.numero_expediente.isnot(None))
        .filter(Documento.numero_expediente != "")
        .distinct()
        .order_by(Documento.numero_expediente.asc())
        .all()
    )
    choices = [("", t("rag_default.expediente_any"))]
    choices.extend((value, value) for (value,) in rows if value)
    return choices


def get_user_job_or_404(job_id: int) -> RAGQueryState:
    """
    Obtiene una consulta asíncrona del usuario actual o aborta.

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
    """
    Crea o reutiliza una consulta RAG asíncrona.

    Returns:
        Respuesta JSON con el identificador del trabajo creado o reutilizado.
    """
    guided_request = is_guided_query_request()
    form = RAGDefaultQueryForm() if guided_request else RAGQueryForm()
    if guided_request:
        configure_default_query_form(form)
        form.question.data = build_guided_question(form)
    else:
        configure_model_choices(form)
    if not form.validate_on_submit():
        return jsonify({"error": t("rag.invalid_question")}), 400

    question = (form.question.data or "").strip()
    model_name = resolve_rag_llm_model(form.model.data)
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
        model_name=model_name,
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
    """
    Devuelve el estado de una consulta RAG.

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
    """
    Solicita la cancelación de una consulta RAG.

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

    job.mark_cancel_requested(t("rag.cancelling"))

    if job.status == "queued":
        job.mark_cancelled()

    db.session.commit()

    return jsonify({"status": job.status, "message": localize_runtime_message(job.message)}), 202

def run_rag_query_async(app, job_id: int, user_id: int, lang: str = "es") -> None:
    """
    Ejecuta una consulta RAG dentro de un contexto de aplicación.

    Args:
        app: Aplicación Flask usada para abrir el contexto.
        job_id: Identificador de la consulta asíncrona.
        user_id: Identificador del usuario propietario.
        lang: Idioma usado para mensajes de estado.
    """
    with app.app_context():
        job = db.session.get(RAGQueryState, job_id)
        if not job or job.user_id != user_id:
            return

        try:
            if job.cancel_requested:
                job.mark_cancelled(message=translate_for(lang, "rag.cancelled"))
                db.session.commit()
                return

            job.mark_running(message=translate_for(lang, "rag.starting"))
            job.result_payload = None
            db.session.commit()

            def should_cancel() -> bool:
                db.session.refresh(job)
                return job.should_cancel()

            def on_status(message: str) -> None:
                db.session.refresh(job)
                if job.status in {"done", "failed", "cancelled"}:
                    return

                job.set_message(message)
                db.session.commit()

            result = asyncio.run(
                rag_answer(
                    job.question,
                    model=job.model_name,
                    should_cancel=should_cancel,
                    on_status=on_status,
                    user_id=user_id,
                    lang=lang,
                )
            )

            db.session.refresh(job)
            
            if job.cancel_requested:
                job.mark_cancelled(message=localize_runtime_message("Consulta cancelada.", lang))
                db.session.commit()
                return
            job.mark_result(result, message=localize_runtime_message("Consulta finalizada.", lang))
            db.session.commit()
        except QueryCancelledError:
            db.session.rollback()
            job = db.session.get(RAGQueryState, job_id)
            if job:
                job.mark_cancelled(message=localize_runtime_message("Consulta cancelada.", lang))
                db.session.commit()
        except Exception as exc:
            db.session.rollback()
            job = db.session.get(RAGQueryState, job_id)
            if job:
                job.mark_failed(exc, message=localize_runtime_message("La consulta ha fallado.", lang))
                db.session.commit()
            app.logger.exception("Error en run_rag_query_async")
        finally:
            db.session.remove()
