"""
Autora: Lydia Blanco Ruiz
Script para las rutas de consulta RAG, seguimiento de estado y cancelación de consultas.
"""

import asyncio
import json
import re
from collections import defaultdict
from pathlib import Path

from flask import (
    abort,
    current_app,
    jsonify,
    render_template,
    request,
    url_for,
)
from flask.typing import ResponseReturnValue
from flask_login import current_user, login_required

from app.main.code.extensions import db
from app.main.code.forms import EmptyForm, RAGDefaultQueryForm, RAGQueryForm
from app.main.code.inetrnacionalizacion.tarduccion import (
    get_locale,
    localize_runtime_message,
    t,
    translate_for,
)
from app.main.code.model.documento import Documento
from app.main.code.model.rag_evaluation_state import RAGEvaluationState
from app.main.code.model.rag_query_state import RAGQueryState
from app.main.code.services.async_tasks import cancel_tracked, executor, submit_tracked
from app.main.code.services.rag.PrototipoRAG import (
    QueryCancelledError,
    get_rag_llm_model_choices,
    resolve_rag_llm_model,
)
from app.main.code.services.rag.service import rag_answer, validate_question

from . import rag_bp


@rag_bp.get("/")
@login_required
def rag_page() -> str:
    """
    Muestra la página de consulta RAG.

    Returns:
        Respuesta HTML con el formulario de consulta.
    """
    form = RAGQueryForm()
    configure_model_choices(form)

    default_form = RAGDefaultQueryForm()
    configure_default_query_form(default_form)

    usage_payload = build_model_usage_index_payload()
    expediente_type_payload = build_expediente_type_payload()
    return render_template(
        "rag.html",
        form=form,
        default_form=default_form,
        model_usage_payload=usage_payload,
        expediente_type_payload=expediente_type_payload,
    )


@rag_bp.get("/evaluation/latest")
@login_required
def latest_rag_evaluation() -> ResponseReturnValue:
    """
    Devuelve el último resultado de evaluación del RAG ejecutado por un admin.
    
    Returns:
        JSON con el resumen de la última evaluación RAG, o un error si no hay resultados disponibles o si ocurre un problema al leerlos.
    """
    job = (
        RAGEvaluationState.query.filter(RAGEvaluationState.status == "done")
        .order_by(RAGEvaluationState.finished_at.desc(), RAGEvaluationState.id.desc())
        .first()
    )
    if not job or not job.results_json_path:
        return jsonify({"error": t("rag.evaluation.no_results")}), 404

    data_dir = Path(current_app.config.get("DATA_DIR") or Path.cwd()).resolve()
    results_path = Path(job.results_json_path).resolve()
    try:
        results_path.relative_to(data_dir)
    except ValueError:
        return jsonify({"error": "Ruta de resultados inválida."}), 400

    if not results_path.exists():
        return jsonify({"error": t("rag.evaluation.no_results")}), 404

    try:
        payload = json.loads(results_path.read_text(encoding="utf-8"))
    except Exception:
        return jsonify({"error": "No se pudieron leer los resultados."}), 500

    return jsonify(
        {
            "job_id": job.id,
            "finished_at": job.finished_at.isoformat() if job.finished_at else None,
            "final_metrics": payload.get("final_metrics") or {},
            "ragas_metrics": payload.get("ragas_metrics") or {},
            "coseno_metrics": payload.get("coseno_metrics") or {},
        }
    )


@rag_bp.get("/evaluation/<int:job_id>")
@login_required
def rag_evaluation_detail(job_id: int) -> ResponseReturnValue:
    """
    Renderiza el detalle de una evaluación (resumen + filas por pregunta).
    
    Returns:
        Respuesta HTML con el detalle de la evaluación, o un error si el job no existe, no está terminado o si hay problemas al leer los resultados.
    """
    job = RAGEvaluationState.query.get_or_404(job_id)
    if job.status != "done" or not job.results_json_path or not job.row_results_json_path:
        abort(404)

    data_dir = Path(current_app.config.get("DATA_DIR") or Path.cwd()).resolve()
    results_path = Path(job.results_json_path).resolve()
    rows_path = Path(job.row_results_json_path).resolve()
    config_path = Path(job.config_json_path).resolve() if job.config_json_path else None

    for path in (results_path, rows_path, config_path):
        if not path:
            continue
        try:
            path.relative_to(data_dir)
        except ValueError:
            abort(400)

    if not results_path.exists() or not rows_path.exists():
        abort(404)

    try:
        summary = json.loads(results_path.read_text(encoding="utf-8"))
    except Exception:
        abort(500)

    try:
        rows_payload = json.loads(rows_path.read_text(encoding="utf-8"))
    except Exception:
        rows_payload = []

    config_payload = {}
    if config_path and config_path.exists():
        try:
            config_payload = json.loads(config_path.read_text(encoding="utf-8"))
        except Exception:
            config_payload = {}

    return render_template(
        "rag_evaluation_detail.html",
        job=job,
        summary=summary,
        rows=rows_payload,
        config=config_payload,
        back_url=url_for("rag.rag_page"),
    )

def build_expediente_type_payload() -> dict[str, list[str]]:
    """
    Mapa expediente -> lista de tipos de documento disponibles ('administrativo', 'tecnico').
    Sirve para filtrar expedientes en el formulario guiado del tab.
    
    Returns:
        dict con número de expediente como clave y lista de tipos documentales asociados como valor.
    """
    rows = (
        db.session.query(Documento.numero_expediente, Documento.tipo_documento)
        .filter(Documento.numero_expediente.isnot(None))
        .filter(Documento.numero_expediente != "")
        .filter(Documento.tipo_documento.isnot(None))
        .filter(Documento.tipo_documento != "")
        .distinct()
        .all()
    )
    out: dict[str, set[str]] = {}
    for expediente, tipo in rows:
        if not expediente or not tipo:
            continue
        expediente_key = str(expediente).strip()
        normalized_type = str(tipo).strip().lower()
        if not expediente_key or not normalized_type:
            continue
        out.setdefault(expediente_key, set()).add(normalized_type)
    return {k: sorted(v) for k, v in out.items()}


def build_model_usage_index_payload(months: int = 12) -> dict:
    """
    Construye un payload simple de uso por modelo a lo largo del tiempo, para
    dibujarlo con D3 en la pantalla RAG.
    
    Args:
        months: Número de meses hacia atrás a incluir en el índice (incluyendo el actual).

    Returns:
        dict con:
          - labels: lista de strings YYYY-MM
          - series: dict model_name -> lista de contadores por mes (alineados a labels)
    """
    base_query = RAGQueryState.query.filter(RAGQueryState.status == "done")

    jobs = base_query.order_by(RAGQueryState.created_at.asc()).all()

    # Etiquetas de los últimos N meses (incluyendo el actual)
    from datetime import datetime, timezone

    now = datetime.now(timezone.utc)
    month_labels: list[str] = []
    for offset in range(months - 1, -1, -1):
        y = now.year
        m = now.month - offset
        while m <= 0:
            m += 12
            y -= 1
        month_labels.append(f"{y:04d}-{m:02d}")

    index_by_label = {label: idx for idx, label in enumerate(month_labels)}
    series: dict[str, list[int]] = {}

    for job in jobs:
        created = job.created_at
        if not created:
            continue
        label = f"{created.year:04d}-{created.month:02d}"
        idx = index_by_label.get(label)
        if idx is None:
            continue
        result = job.result_payload or {}
        model_name = (job.model_name or result.get("model") or resolve_rag_llm_model()).strip() or "default"
        if model_name not in series:
            series[model_name] = [0 for _ in month_labels]
        series[model_name][idx] += 1

    return {"labels": month_labels, "series": series}


@rag_bp.get("/modelos")
@login_required
def model_comparison_page() -> ResponseReturnValue:
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
        "scope": "global",
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
    return round(len(words) * 1.33) if words else 0

def configure_model_choices(form: RAGQueryForm) -> None:
    """
    Carga en el formulario los modelos LLM disponibles para Ollama.
    
    Args:
        form (RAGQueryForm): El formulario a configurar.
    """
    form.model.choices = get_rag_llm_model_choices()
    preferred_model = resolve_rag_llm_model()

    if current_user.is_authenticated and current_user.preferred_model:
        preferred_model = current_user.preferred_model

    form.model.default = preferred_model

    if not form.model.data:
        form.model.data = preferred_model

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
    doc_scope = f" [doc_type={doc_type}]" if (not summary_mode and doc_type) else ""

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
        db.session.query(Documento.numero_expediente, Documento.tipo_documento, Documento.nombre)
        .filter(Documento.numero_expediente.isnot(None))
        .filter(Documento.numero_expediente != "")
        .order_by(Documento.numero_expediente.asc())
        .all()
    )

    by_expediente: dict[str, dict[str, object]] = {}
    process_rows(by_expediente, rows)

    choices: list[tuple[str, str]] = [("", t("rag_default.expediente_any"))]
    for exp in sorted(by_expediente.keys()):
        entry = by_expediente[exp]
        types = sorted(entry.get("types") or [])
        names = entry.get("names") or []
        pretty_types = " / ".join(type_label(v) for v in types) if types else t("rag_default.doc_type_any")
        title = min(names, key=lambda s: (len(s), s.lower()))[0] if names else "-"
        if title.lower().endswith(".pdf"):
            title = title[:-4]
        label = f"{exp} — {pretty_types} — {title}"
        choices.append((exp, label))

    return choices

def type_label(type_value: str) -> str:
    """
    Convierte un tipo documental en su etiqueta traducida.
    
    Args:
        type_value (str): El valor del tipo documental, como "administrativo" o " tecnico".

    Returns:
        str: La etiqueta traducida para el tipo documental, o el valor original si no se reconoce, o "-" si no se proporciona ningún valor.
    """
    value = (type_value or "").strip().lower()
    if value == "administrativo":
        return t("rag_default.doc_type_admin")
    if value == "tecnico":
        return t("rag_default.doc_type_technical")
    return value or "-"

def process_rows(by_expediente: dict[str, dict[str, object]], rows: list[tuple[str, str, str]]) -> None:
    for expediente, tipo, nombre in rows:
        if not expediente:
            continue
        exp = str(expediente).strip()
        if not exp:
            continue
        entry = by_expediente.setdefault(exp, {"types": set(), "names": []})
        if tipo:
            entry["types"].add(str(tipo))
        if nombre:
            entry["names"].append(str(nombre))

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
def rag_ask() -> ResponseReturnValue:
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
            RAGQueryState.cancel_requested.is_(False),
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
    submit_tracked(
        executor,
        "rag",
        job.id,
        run_rag_query_async,
        app_obj,
        job.id,
        int(current_user.id),
        current_lang,
    )

    return jsonify({"job_id": job.id}), 202


@rag_bp.get("/status/<int:job_id>")
@login_required
def rag_status(job_id: int) -> ResponseReturnValue:
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

@rag_bp.get("/active")
@login_required
def rag_active() -> ResponseReturnValue:
    """
    Devuelve el job RAG activo del usuario autenticado (si existe).
    Se usa para reanudar el polling de la UI tras recargar la página.
    
    Returns:
        Respuesta JSON con el identificador y estado del job activo, o null si no hay
    """
    active_job = (
        RAGQueryState.query.filter(
            RAGQueryState.user_id == int(current_user.id),
            RAGQueryState.status.in_(["queued", "running"]),
            RAGQueryState.cancel_requested.is_(False),
        )
        .order_by(RAGQueryState.created_at.desc())
        .first()
    )

    if not active_job:
        return jsonify({"job_id": None}), 200

    return jsonify({"job_id": active_job.id, "status": active_job.status}), 200

@rag_bp.post("/cancel/<int:job_id>")
@login_required
def rag_cancel(job_id: int) -> ResponseReturnValue:
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
        cancel_tracked(job_type="rag", tracked_job_id=job.id)
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
