"""
Autora: Lydia Blanco Ruiz
Script para las rutas de administración, incluyendo gestión de usuarios, documentos y procesos en segundo plano con estado y cancelación.
"""

import os
import smtplib
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from flask import (
    Response,
    abort,
    current_app,
    flash,
    jsonify,
    redirect,
    render_template,
    request,
    send_file,
    url_for,
)
from flask.typing import ResponseReturnValue
from flask_login import current_user, login_required
from markupsafe import Markup
from sqlalchemy.exc import SQLAlchemyError

from app.main.code.countries import (
    COUNTRY_BY_CODE,
    country_choices,
    normalize_country_code,
)
from app.main.code.decorators import admin_required
from app.main.code.extensions import db
from app.main.code.forms import AdminCreateUserForm, EmptyForm, PdfUploadForm
from app.main.code.inetrnacionalizacion.tarduccion import (
    get_locale,
    localize_runtime_message,
    t,
    translate_for,
)
from app.main.code.model.job_state import JobStateMixin
from app.main.code.services.async_tasks import executor, markdown_executor
from app.main.code.services.markdown_conversion_state import (
    send_markdown_finished_email,
)
from app.main.code.services.vector_update_state import send_update_finished_email
from app.main.code.services.web_scraping_state import send_scraping_finished_email

from ...model.documento import Documento
from ...model.markdown_conversion_state import MarkdownConversionState
from ...model.user import User
from ...model.vector_update_state import VectorUpdateState
from ...model.web_scraping_state import WebScrapingSate
from ...services.documentos import DocumentosService, JobCancelledError
from ...services.rag.PrototipoRAG import index_pliegos_dir, qdrant_delete_by_filename
from . import admin_bp

USERS = "admin.users"
DOCUMENTS = "admin.documents_list_page"
DOC_TYPE_UNKNOWN = "unknown"
DOC_MARKDOWN_YES = "yes"
DOC_MARKDOWN_NO = "no"
JOBS_ALREADY_FINISHED = "jobs.already_finished"
MARKDOWN_CANCELLED = "markdown.cancelled"
SCRAPING_CANCELLED = "scraping.cancelled"
MARKDOWN_JOB_MESSAGE_MAX_LENGTH = 255
MADRID_TZ = ZoneInfo("Europe/Madrid")
ADMIN_RECOVERABLE_ERRORS = (
    FileNotFoundError,
    OSError,
    RuntimeError,
    SQLAlchemyError,
    subprocess.SubprocessError,
    ValueError,
)
MAIL_RECOVERABLE_ERRORS = (OSError, RuntimeError, smtplib.SMTPException)


def _fit_job_message(message: str | None, max_length: int = MARKDOWN_JOB_MESSAGE_MAX_LENGTH) -> str | None:
    """
    Ajusta un mensaje de job a la longitud maxima permitida.

    Args:
        message: Mensaje original asociado al job.
        max_length: Longitud maxima permitida para el mensaje.

    Returns:
        El mensaje original, truncado o ``None`` si no habia contenido.
    """
    return JobStateMixin.fit_message(message, max_length=max_length)


def _now_madrid() -> datetime:
    """
    Obtiene la fecha y hora actual en la zona horaria de Madrid.

    Returns:
        La fecha y hora actual con zona horaria de Madrid.
    """
    return JobStateMixin.now()


def _set_job_message(job, message: str | None) -> None:
    """
    Guarda el mensaje de un job aplicando el ajuste de longitud.

    Args:
        job: Instancia del job que se va a actualizar.
        message: Mensaje nuevo que se quiere almacenar.

    Returns:
        None.
    """
    if hasattr(job, "set_message"):
        job.set_message(message)
    elif hasattr(job, "message"):
        job.message = _fit_job_message(message)


def _set_job_progress(job, current: float, total: int) -> None:
    """
    Calcula y guarda el progreso porcentual de un job.

    Args:
        job: Instancia del job que se va a actualizar.
        current: Progreso actual en unidades completadas.
        total: Numero total de unidades a completar.

    Returns:
        None.
    """
    if hasattr(job, "set_progress"):
        job.set_progress(current, total)
    else:
        job.progress = int((current / total) * 100) if total and total > 0 else 100


def _job_should_cancel(job) -> bool:
    """
    Indica si un job ha solicitado cancelacion.

    Args:
        job: Instancia del job que se quiere consultar.

    Returns:
        ``True`` si el job ha sido marcado para cancelacion.
    """
    db.session.refresh(job)
    if hasattr(job, "should_cancel"):
        return job.should_cancel()
    return bool(job.cancel_requested)


def _mark_job_running(job, *, progress: int = 0, message: str | None = None) -> None:
    """
    Marca un job como en ejecucion.

    Args:
        job: Instancia del job que se actualiza.
        progress: Progreso inicial del job.
        message: Mensaje descriptivo opcional del estado.

    Returns:
        None.
    """
    if hasattr(job, "mark_running"):
        job.mark_running(progress=progress, message=message)
        return
    job.status = "running"
    job.started_at = _now_madrid()
    job.progress = progress
    job.error = None
    _set_job_message(job, message)


def _mark_job_cancelled(job, *, message: str | None = None, clear_error: bool = True) -> None:
    """
    Marca un job como cancelado.

    Args:
        job: Instancia del job que se actualiza.
        message: Mensaje descriptivo opcional del estado.
        clear_error: Indica si debe limpiarse el error almacenado.

    Returns:
        None.
    """
    if hasattr(job, "mark_cancelled"):
        job.mark_cancelled(message=message, clear_error=clear_error)
        return
    job.status = "cancelled"
    if clear_error and hasattr(job, "error"):
        job.error = None
    _set_job_message(job, message)
    job.finished_at = _now_madrid()


def _mark_job_done(job, *, progress: int = 100, message: str | None = None) -> None:
    """
    Marca un job como finalizado correctamente.

    Args:
        job: Instancia del job que se actualiza.
        progress: Progreso final del job.
        message: Mensaje descriptivo opcional del estado.

    Returns:
        None.
    """
    if hasattr(job, "mark_done"):
        job.mark_done(progress=progress, message=message)
        return
    job.status = "done"
    job.progress = progress
    _set_job_message(job, message)
    job.finished_at = _now_madrid()


def _mark_job_failed(job, error: Exception | str, *, message: str | None = None) -> None:
    """
    Marca un job como fallido y registra el error.

    Args:
        job: Instancia del job que se actualiza.
        error: Excepcion o texto descriptivo del fallo.
        message: Mensaje descriptivo opcional del estado.

    Returns:
        None.
    """
    if hasattr(job, "mark_failed"):
        job.mark_failed(error, message=message)
        return
    job.status = "failed"
    job.error = str(error)
    _set_job_message(job, message)
    job.finished_at = _now_madrid()


def _send_email_safe(send_fn, log_message: str, **kwargs) -> None:
    """
    Ejecuta un envio de correo registrando cualquier excepcion.

    Args:
        send_fn: Funcion encargada de enviar el correo.
        log_message: Mensaje a registrar si el envio falla.
        **kwargs: Argumentos que se pasan a la funcion de envio.

    Returns:
        None.
    """
    try:
        send_fn(**kwargs)
    except MAIL_RECOVERABLE_ERRORS:
        current_app.logger.exception(log_message)


def _validate_post_action(*, json_response: bool = False) -> ResponseReturnValue | None:
    """
    Valida el CSRF de acciones POST sin campos propios.
    
    Args:
        json_response: Indica si la respuesta de error debe ser JSON en lugar de HTML.
    
    Returns:
        None o una respuesta JSON de error si la validacion falla.
    """
    form = EmptyForm()
    if form.validate_on_submit():
        return None
    if json_response:
        return jsonify({"error": t("errors.bad_request_message")}), 400
    abort(400)


def _users_query_from_filters(filters: dict[str, str]) -> Any:
    """
    Construye la consulta de usuarios aplicando los filtros de la pagina.
    
    Args:
        filters: Diccionario con los filtros activos (nombre, pais, rol).
        
    Returns:
        La consulta SQLAlchemy con los filtros aplicados.
    """
    query = User.query
    name = filters.get("name", "").strip()
    country = filters.get("country", "").strip().upper()
    role = filters.get("role", "").strip()

    if name:
        query = query.filter(User.nombre.ilike(f"%{name}%"))
    if country in COUNTRY_BY_CODE:
        query = query.filter(User.country_code == country)
    if role == "admin":
        query = query.filter(User.is_admin.is_(True))
    elif role == "user":
        query = query.filter(User.is_admin.is_(False))

    return query.order_by(User.nombre.asc(), User.id.asc())


def _current_user_filters() -> dict[str, str]:
    """
    Lee y normaliza los filtros activos de la lista de usuarios.
    
    Returns:
        Un diccionario con los valores de los filtros de nombre, pais y rol.
    """
    return {
        "name": (request.args.get("name") or "").strip(),
        "country": (request.args.get("country") or "").strip().upper(),
        "role": (request.args.get("role") or "").strip(),
    }


def _render_users_page(form=None) -> ResponseReturnValue:
    """
    Renderiza la gestion de usuarios con formulario de alta y listado.
    
    Args:
        form: Instancia del formulario de creacion de usuario, opcionalmente con errores.
        
    Returns:
        La pagina HTML con el listado de usuarios y el formulario.
    """
    filters = _current_user_filters()
    users = _users_query_from_filters(filters).all()
    return render_template(
        "users.html",
        users=users,
        form=form or AdminCreateUserForm(),
        filters=filters,
        country_options=country_choices(get_locale()),
    )


@admin_bp.route("/users")
@login_required
@admin_required
def users() -> ResponseReturnValue:
    """
    Muestra el listado de usuarios administrables.

    Returns:
        La pagina HTML con todos los usuarios ordenados por identificador.
    """
    return _render_users_page()


@admin_bp.post("/users/<int:user_id>")
@login_required
@admin_required
def change_type(user_id) -> ResponseReturnValue:
    """
    Alterna el rol de administrador de un usuario.

    Args:
        user_id: Identificador del usuario cuyo rol se modifica.

    Returns:
        Una redireccion al listado de usuarios.
    """
    _validate_post_action()
    user = User.get_by_id(user_id)
    if not user:
        abort(404)
    if user.id == current_user.id:
        abort(400)

    user.change_is_admin()
    db.session.commit()
    return redirect(url_for(USERS))


@admin_bp.post("/users/<int:user_id>/delete")
@login_required
@admin_required
def delete_user(user_id) -> ResponseReturnValue:
    """
    Elimina un usuario distinto del administrador actual.

    Args:
        user_id: Identificador del usuario que se va a eliminar.

    Returns:
        Una redireccion al listado de usuarios.
    """
    _validate_post_action()
    user = User.get_by_id(user_id)
    if not user:
        abort(404)
    if user.id == current_user.id:
        abort(400)

    db.session.delete(user)
    db.session.commit()
    return redirect(url_for(USERS))


@admin_bp.post("/users/bulk")
@login_required
@admin_required
def bulk_users() -> ResponseReturnValue:
    """
    Ejecuta acciones sobre varios usuarios seleccionados.

    Returns:
        Una redireccion al listado de usuarios conservando los filtros activos.
    """
    _validate_post_action()
    action = (request.form.get("bulk_action") or "").strip()
    selected_ids = request.form.getlist("selected_user_ids", type=int)
    redirect_args = {
        "name": (request.form.get("filter_name") or "").strip(),
        "country": (request.form.get("filter_country") or "").strip(),
        "role": (request.form.get("filter_role") or "").strip(),
    }
    redirect_args = {key: value for key, value in redirect_args.items() if value}

    if not selected_ids or action not in {"delete", "toggle"}:
        return redirect(url_for(USERS, **redirect_args))
    if current_user.id in selected_ids:
        abort(400)

    selected_users = User.query.filter(User.id.in_(selected_ids)).all()
    if len(selected_users) != len(set(selected_ids)):
        abort(404)

    if action == "delete":
        for user in selected_users:
            db.session.delete(user)
    else:
        for user in selected_users:
            user.change_is_admin()

    db.session.commit()
    return redirect(url_for(USERS, **redirect_args))


@admin_bp.get("/users/add")
@admin_bp.post("/users/add")
@login_required
@admin_required
def create_user() -> ResponseReturnValue:
    """
    Crea un usuario nuevo desde el formulario de administracion.

    Returns:
        La plantilla del formulario o una redireccion al listado de usuarios.
    """
    form = AdminCreateUserForm()

    if form.validate_on_submit():
        nombre = form.nombre.data.strip()
        email = form.email.data.lower().strip()
        country_code = normalize_country_code(form.country_code.data)
        password = form.password.data
        is_admin = form.is_admin.data

        if User.get_by_email(email):
            form.email.errors.append(t("auth.email_exists"))
            return _render_users_page(form=form)

        user = User(nombre=nombre, email=email, country_code=country_code)
        user.set_password(password)
        user.is_admin = is_admin

        db.session.add(user)
        db.session.commit()
        return redirect(url_for(USERS))

    return _render_users_page(form=form)


def pliegos_dir() -> Path:
    """
    Obtiene y garantiza la existencia del directorio de pliegos.

    Returns:
        La ruta absoluta al directorio configurado para pliegos.
    """
    base = Path(current_app.config.get("DOCS_DIR", "/data/pliegos")).resolve()
    base.mkdir(parents=True, exist_ok=True)
    return base


def documentos_service() -> DocumentosService:
    """
    Construye el servicio de gestion documental para administracion.

    Returns:
        Una instancia configurada de ``DocumentosService``.
    """
    return DocumentosService(
        pliegos_dir(),
        index_pliegos_dir=index_pliegos_dir,
        delete_chunks=qdrant_delete_by_filename,
        markdown_converter=convert_pdf_to_markdown,
    )


def documents_page_url() -> str:
    """
    Construye la URL absoluta de la pagina de documentos.

    Returns:
        La URL completa a la pagina de administracion de documentos.
    """
    return f"{request.host_url.rstrip('/')}{url_for('admin.documents_list_page')}"


def _document_filters() -> dict[str, str]:
    """
    Lee los filtros activos de la administracion de documentos.
    
    Returns:
        Un diccionario con los valores de los filtros de nombre, tipo, estado y markdown.
    """
    return {
        "name": (request.args.get("name") or "").strip(),
        "type": (request.args.get("type") or "").strip(),
        "status": (request.args.get("status") or "").strip(),
        "markdown": (request.args.get("markdown") or "").strip(),
    }


def _apply_document_filters(query, filters: dict[str, str]) -> Any:
    """
    Aplica filtros sobre la query de documentos.
    
    Args:
        query: Consulta SQLAlchemy base sobre la que aplicar los filtros.
        filters: Diccionario con los filtros activos (nombre, tipo, estado, markdown).
        
    Returns:
        La consulta SQLAlchemy con los filtros aplicados.
    """
    if filters["name"]:
        query = query.filter(Documento.nombre.ilike(f"%{filters['name']}%"))

    if filters["type"] == DOC_TYPE_UNKNOWN:
        query = query.filter(Documento.tipo_documento.is_(None))
    elif filters["type"]:
        query = query.filter(Documento.tipo_documento == filters["type"])

    if filters["status"]:
        query = query.filter(Documento.status == filters["status"])

    if filters["markdown"] == DOC_MARKDOWN_YES:
        query = query.filter(
            Documento.markdown_content.isnot(None),
            Documento.markdown_content != "",
        )
    elif filters["markdown"] == DOC_MARKDOWN_NO:
        query = query.filter(
            (Documento.markdown_content.is_(None))
            | (Documento.markdown_content == "")
        )

    return query


def _document_filter_options() -> tuple[list[str], list[str]]:
    """
    Devuelve tipos y estados disponibles para los filtros.
    
    Returns:
        Una tupla con la lista de tipos de documento y la lista de estados disponibles.
    """
    type_values = [
        item[0]
        for item in (
            Documento.query.with_entities(Documento.tipo_documento)
            .filter(Documento.tipo_documento.isnot(None))
            .distinct()
            .order_by(Documento.tipo_documento.asc())
            .all()
        )
        if item[0]
    ]
    status_values = [
        item[0]
        for item in (
            Documento.query.with_entities(Documento.status)
            .distinct()
            .order_by(Documento.status.asc())
            .all()
        )
        if item[0]
    ]
    return type_values, status_values


def convert_pdf_to_markdown(pdf_path: Path, on_page_start=None) -> str:
    """
    Convierte un PDF a Markdown mediante el procesador configurado.

    Args:
        pdf_path: Ruta del PDF origen.
        on_page_start: Callback opcional invocado al comenzar cada pagina.

    Returns:
        El contenido Markdown generado.
    """
    from app.main.code.services.markdown.Conversion_markdown import process_pdf

    return process_pdf(pdf_path, on_page_start=on_page_start)


@admin_bp.post("/documents/upload")
@admin_required
def upload_documents() -> ResponseReturnValue:
    """
    Guarda los documentos subidos desde la interfaz de administracion.

    Returns:
        Una redireccion a la pagina de documentos.
    """
    form = PdfUploadForm()
    if not form.validate_on_submit():
        errors = []
        for field_errors in (form.errors or {}).values():
            errors.extend(field_errors or [])
        flash(errors[0] if errors else t("errors.bad_request_message"), "warning")
        return redirect(url_for(DOCUMENTS))

    files = form.files.data
    if not files:
        return redirect(url_for(DOCUMENTS))

    if not isinstance(files, (list, tuple)):
        files = [files]

    saved = documentos_service().save_uploads(files)
    if saved == 0:
        flash("No se ha subido ningun PDF valido.", "warning")
    return redirect(url_for(DOCUMENTS))


@admin_bp.post("/documents/markdown/convert")
@login_required
@admin_required
def convert_documents_to_markdown() -> ResponseReturnValue:
    """
    Crea un job para convertir documentos pendientes a Markdown.

    Returns:
        Una respuesta JSON con el identificador del job creado.
    """
    invalid = _validate_post_action(json_response=True)
    if invalid:
        return invalid

    lang = get_locale()
    job = MarkdownConversionState(
        status="queued",
        progress=0,
        message=translate_for(lang, "jobs.queued_short"),
        cancel_requested=False,
        error=None,
    )
    db.session.add(job)
    db.session.commit()

    app_obj = current_app._get_current_object()
    markdown_executor.submit(markdown_async, app_obj, job.id, current_user.email, documents_page_url(), lang)

    return jsonify({"job_id": job.id}), 202


@admin_bp.post("/documents/markdown/cancel/<int:job_id>")
@login_required
@admin_required
def cancel_markdown_conversion(job_id: int) -> ResponseReturnValue:
    """
    Solicita la cancelacion de un job de conversion a Markdown.

    Args:
        job_id: Identificador del job de conversion.

    Returns:
        Una respuesta JSON con el estado actualizado del job.
    """
    invalid = _validate_post_action(json_response=True)
    if invalid:
        return invalid

    job = MarkdownConversionState.query.get_or_404(job_id)

    if job.status in {"done", "failed", "cancelled"}:
        return jsonify({"status": job.status, "message": t(JOBS_ALREADY_FINISHED)}), 200

    job.cancel_requested = True
    _set_job_message(job, t("markdown.cancelling"))
    if job.status == "queued":
        job.status = "cancelled"
        job.finished_at = _now_madrid()
    db.session.commit()

    return jsonify({"status": job.status, "message": localize_runtime_message(job.message)}), 202


@admin_bp.get("/documents/markdown/status/<int:job_id>")
@login_required
@admin_required
def markdown_conversion_status(job_id: int) -> ResponseReturnValue:
    """
    Devuelve el estado actual de un job de conversion a Markdown.

    Args:
        job_id: Identificador del job de conversion.

    Returns:
        Una respuesta JSON con progreso, mensaje y error del job.
    """
    job = MarkdownConversionState.query.get(job_id)
    if not job:
        abort(404)

    return jsonify(
        {
            "status": job.status,
            "progress": job.progress,
            "message": localize_runtime_message(job.message),
            "error": job.error,
            "cancel_requested": bool(job.cancel_requested),
        }
    )


def _markdown_cancel_message(lang: str) -> str:
    """
    Obtiene el mensaje traducido de cancelacion para Markdown.

    Args:
        lang: Codigo de idioma activo.

    Returns:
        El mensaje traducido de cancelacion.
    """
    return translate_for(lang, MARKDOWN_CANCELLED)


def _cancel_markdown_job(job, lang: str) -> None:
    """
    Marca un job de Markdown como cancelado y persiste el cambio.

    Args:
        job: Instancia del job de conversion.
        lang: Codigo de idioma activo.

    Returns:
        None.
    """
    _mark_job_cancelled(job, message=_markdown_cancel_message(lang))
    db.session.commit()


def _markdown_page_base_message(job, lang: str) -> str:
    """
    Extrae la parte base del mensaje de progreso de Markdown.

    Args:
        job: Instancia del job de conversion.
        lang: Codigo de idioma activo.

    Returns:
        El mensaje base sin informacion de pagina.
    """
    current_message = job.message or translate_for(lang, "markdown.converting_default")
    return current_message.split(" Pádina ", 1)[0].split(" Page ", 1)[0]


def _build_markdown_callbacks(job, lang: str):
    """
    Construye los callbacks usados durante la conversion a Markdown.

    Args:
        job: Instancia del job de conversion.
        lang: Codigo de idioma activo.

    Returns:
        Una tupla con los callbacks de cancelacion, progreso, documento y pagina.
    """
    current_doc_name = {"value": None}

    def should_cancel() -> bool:
        """
        Comprueba si el job de Markdown debe cancelarse.

        Returns:
            ``True`` si se ha solicitado cancelacion.
        """
        return _job_should_cancel(job)

    def raise_if_cancelled() -> None:
        """
        Interrumpe la ejecucion si el job de Markdown fue cancelado.

        Returns:
            None.
        """
        if should_cancel():
            raise JobCancelledError(_markdown_cancel_message(lang))

    def on_progress(i: int, total: int) -> None:
        """
        Actualiza el progreso del job de Markdown.

        Args:
            i: Numero de unidades completadas.
            total: Numero total de unidades del proceso.

        Returns:
            None.
        """
        raise_if_cancelled()
        _set_job_progress(job, i, total)
        db.session.commit()

    def on_current_doc(nombre: str) -> None:
        """
        Actualiza el documento actual en conversion a Markdown.

        Args:
            nombre: Nombre del documento que se esta procesando.

        Returns:
            None.
        """
        raise_if_cancelled()
        current_doc_name["value"] = nombre
        _set_job_message(job, translate_for(lang, "markdown.converting_doc", name=nombre))
        db.session.commit()

    def on_page_start(doc_index: int, total_docs: int, page: int, total_pages: int) -> None:
        """
        Actualiza el progreso al comenzar una pagina de conversion.

        Args:
            doc_index: Posicion del documento actual en el lote.
            total_docs: Numero total de documentos a convertir.
            page: Numero de pagina actual.
            total_pages: Numero total de paginas del documento.

        Returns:
            None.
        """
        raise_if_cancelled()
        completed = (doc_index - 1) + (page / total_pages if total_pages else 1)
        current_name = current_doc_name["value"] or _markdown_page_base_message(job, lang).removeprefix(
            "Convirtiendo "
        ).removeprefix("Converting ").removesuffix("...")
        _set_job_progress(job, completed, total_docs)
        _set_job_message(
            job,
            translate_for(
                lang,
                "markdown.converting_doc_page",
                name=current_name,
                page=page,
                total_pages=total_pages,
            ),
        )
        db.session.commit()

    return should_cancel, on_progress, on_current_doc, on_page_start


def _markdown_done_message(stats: dict[str, int], lang: str) -> str:
    """
    Genera el mensaje final de un job de conversion a Markdown.

    Args:
        stats: Estadisticas finales devueltas por la conversion.
        lang: Codigo de idioma activo.

    Returns:
        El mensaje traducido que resume el resultado del job.
    """
    if stats["converted"] == 0 and stats.get("failed", 0) == 0:
        return translate_for(lang, "markdown.none_pending")
    if stats.get("failed", 0):
        return translate_for(
            lang,
            "markdown.done_stats_with_failures",
            count=stats["converted"],
            failed=stats["failed"],
        )
    return translate_for(lang, "markdown.done_stats", count=stats["converted"])


def _finish_markdown_job(job, stats: dict[str, int], user_email: str, docs_url: str, lang: str) -> None:
    """
    Marca el job de Markdown como completado y envia la notificacion.

    Args:
        job: Instancia del job de conversion.
        stats: Estadisticas finales del proceso.
        user_email: Correo del usuario que inicio el job.
        docs_url: URL de la pagina de documentos.
        lang: Codigo de idioma activo.

    Returns:
        None.
    """
    _mark_job_done(job, message=_markdown_done_message(stats, lang))
    db.session.commit()
    _send_email_safe(
        send_markdown_finished_email,
        "No se pudo enviar el correo de fin de conversion a Markdown",
        to_email=user_email,
        ok=True,
        message=translate_for(lang, "markdown.done_email"),
        job_id=job.id,
        docs_url=docs_url,
        converted_docs=stats.get("converted", 0),
        skipped_docs=stats.get("skipped", 0),
    )


def _handle_markdown_exception(app, job_id: int, user_email: str, docs_url: str, lang: str, exc: Exception) -> None:
    """
    Gestiona un error inesperado en un job de Markdown.

    Args:
        app: Aplicacion Flask activa.
        job_id: Identificador del job fallido.
        user_email: Correo del usuario que inicio el job.
        docs_url: URL de la pagina de documentos.
        lang: Codigo de idioma activo.
        exc: Excepcion capturada durante la ejecucion.

    Returns:
        None.
    """
    db.session.rollback()
    try:
        job = MarkdownConversionState.query.get(job_id)
        if not job:
            raise exc
        _mark_job_failed(job, exc, message=translate_for(lang, "markdown.failed"))
        db.session.commit()
        _send_email_safe(
            send_markdown_finished_email,
            "No se pudo enviar el correo de fin de conversion a Markdown",
            to_email=user_email,
            ok=False,
            message=translate_for(lang, "markdown.failed_email", error=job.error),
            job_id=job.id,
            docs_url=docs_url,
        )
    finally:
        app.logger.exception("Error en markdown_async")


def markdown_async(app, job_id: int, user_email: str, docs_url: str, lang: str = "es") -> None:
    """
    Ejecuta en segundo plano la conversion de documentos a Markdown.

    Args:
        app: Aplicacion Flask activa.
        job_id: Identificador del job de conversion.
        user_email: Correo del usuario que inicio el job.
        docs_url: URL de la pagina de documentos.
        lang: Codigo de idioma activo.

    Returns:
        None.
    """
    with app.app_context():
        job = MarkdownConversionState.query.get(job_id)
        if not job:
            return

        try:
            if job.cancel_requested:
                _cancel_markdown_job(job, lang)
                return

            _mark_job_running(job, message=translate_for(lang, "markdown.starting"))
            db.session.commit()
            should_cancel, on_progress, on_current_doc, on_page_start = _build_markdown_callbacks(job, lang)

            stats = documentos_service().convert_pending_to_markdown(
                on_progress=on_progress,
                on_current_doc=on_current_doc,
                should_cancel=should_cancel,
                on_page_start=on_page_start,
            )

            db.session.refresh(job)
            if job.cancel_requested:
                _cancel_markdown_job(job, lang)
                return

            _finish_markdown_job(job, stats, user_email, docs_url, lang)
        except JobCancelledError:
            db.session.rollback()
            job = MarkdownConversionState.query.get(job_id)
            if job:
                _cancel_markdown_job(job, lang)
        except ADMIN_RECOVERABLE_ERRORS as exc:
            _handle_markdown_exception(app, job_id, user_email, docs_url, lang, exc)
        finally:
            db.session.remove()


@admin_bp.post("/vector-db/update")
@login_required
@admin_required
def update_vector_db() -> ResponseReturnValue:
    """
    Crea un job para actualizar la base de datos vectorial.

    Returns:
        Una respuesta JSON con el identificador del job creado.
    """
    invalid = _validate_post_action(json_response=True)
    if invalid:
        return invalid

    lang = get_locale()
    job = VectorUpdateState(
        status="queued",
        progress=0,
        current_doc=None,
        cancel_requested=False,
        error=None,
    )
    db.session.add(job)
    db.session.commit()

    app_obj = current_app._get_current_object()
    executor.submit(documentos_async, app_obj, job.id, current_user.email, documents_page_url(), lang)

    return jsonify({"job_id": job.id}), 202


@admin_bp.post("/vector-db/cancel/<int:job_id>")
@login_required
@admin_required
def cancel_vector_db(job_id: int) -> ResponseReturnValue:
    """
    Solicita la cancelacion de un job de indexacion vectorial.

    Args:
        job_id: Identificador del job vectorial.

    Returns:
        Una respuesta JSON con el estado actualizado del job.
    """
    invalid = _validate_post_action(json_response=True)
    if invalid:
        return invalid

    job = VectorUpdateState.query.get_or_404(job_id)

    if job.status in {"done", "failed", "cancelled"}:
        return jsonify({"status": job.status, "message": t(JOBS_ALREADY_FINISHED)}), 200

    job.cancel_requested = True
    if job.status == "queued":
        job.status = "cancelled"
        job.finished_at = _now_madrid()
    db.session.commit()

    return jsonify({"status": job.status, "message": t("vector.cancelling")}), 202


def documentos_async(app, job_id: int, user_email: str, docs_url: str, lang: str = "es") -> None:
    """
    Ejecuta en segundo plano la indexacion vectorial de documentos.

    Args:
        app: Aplicacion Flask activa.
        job_id: Identificador del job vectorial.
        user_email: Correo del usuario que inicio el job.
        docs_url: URL de la pagina de documentos.
        lang: Codigo de idioma activo.

    Returns:
        None.
    """
    with app.app_context():
        job = VectorUpdateState.query.get(job_id)
        if not job:
            return

        try:
            if job.cancel_requested:
                _mark_job_cancelled(job)
                db.session.commit()
                return

            _mark_job_running(job, progress=job.progress or 0)
            db.session.commit()

            def should_cancel() -> bool:
                """
                Comprueba si el job vectorial debe cancelarse.

                Returns:
                    ``True`` si se ha solicitado cancelacion.
                """
                return _job_should_cancel(job)

            def on_current_doc(nombre: str):
                """
                Actualiza el documento actual del job vectorial.

                Args:
                    nombre: Nombre del documento que se esta indexando.

                Returns:
                    None.
                """
                if should_cancel():
                    raise JobCancelledError(translate_for(lang, "vector.cancelled_by_user"))
                job.current_doc = nombre
                db.session.commit()

            def on_progress(i: int, total: int):
                """
                Actualiza el progreso del job vectorial.

                Args:
                    i: Numero de unidades completadas.
                    total: Numero total de unidades del proceso.

                Returns:
                    None.
                """
                if should_cancel():
                    raise JobCancelledError(translate_for(lang, "vector.cancelled_by_user"))
                _set_job_progress(job, i, total)
                db.session.commit()

            stats = documentos_service().update_vector_db(
                on_progress=on_progress,
                on_current_doc=on_current_doc,
                should_cancel=should_cancel,
            )

            db.session.refresh(job)
            if job.cancel_requested:
                _mark_job_cancelled(job)
                db.session.commit()
                return

            _mark_job_done(job)
            db.session.commit()

            _send_email_safe(
                send_update_finished_email,
                "No se pudo enviar el correo de fin de actualizacion vectorial",
                to_email=user_email,
                ok=True,
                message=translate_for(lang, "vector.done_email"),
                job_id=job.id,
                docs_url=docs_url,
                indexed_docs=stats.get("indexed", 0),
                failed_docs=stats.get("failed", 0),
            )
        except JobCancelledError:
            db.session.rollback()
            job = VectorUpdateState.query.get(job_id)
            if job:
                _mark_job_cancelled(job)
                db.session.commit()
        except ADMIN_RECOVERABLE_ERRORS as exc:
            db.session.rollback()
            try:
                job = VectorUpdateState.query.get(job_id)
                if not job:
                    raise
                _mark_job_failed(job, exc)
                db.session.commit()
                _send_email_safe(
                    send_update_finished_email,
                    "No se pudo enviar el correo de fin de actualizacion vectorial",
                    to_email=user_email,
                    ok=False,
                    message=translate_for(lang, "vector.failed_email", error=job.error),
                    job_id=job.id,
                    docs_url=docs_url,
                    indexed_docs=None,
                    failed_docs=None,
                )
            finally:
                app.logger.exception("Error en documentos_async (update_vector_db)")
        finally:
            db.session.remove()


@admin_bp.get("/vector-db/status/<int:job_id>")
@admin_required
def vector_db_status(job_id: int) -> ResponseReturnValue:
    """
    Devuelve el estado actual de un job de indexacion vectorial.

    Args:
        job_id: Identificador del job vectorial.

    Returns:
        Una respuesta JSON con progreso, documento actual y error del job.
    """
    job = VectorUpdateState.query.get(job_id)
    if not job:
        abort(404)

    return jsonify(
        {
            "status": job.status,
            "progress": job.progress,
            "current_doc": job.current_doc,
            "error": job.error,
            "cancel_requested": bool(job.cancel_requested),
        }
    )


@admin_bp.get("/documents/list")
@login_required
@admin_required
def documents_list_page() -> ResponseReturnValue:
    """
    Muestra la pagina de administracion de documentos.

    Returns:
        La plantilla HTML con la lista paginada y el estado de Markdown.
    """
    page = request.args.get("page", 1, type=int)
    per_page = 10

    svc = documentos_service()
    svc.sync_from_folder()
    svc.purge_missing_files()

    filters = _document_filters()
    if any(filters.values()):
        query = _apply_document_filters(Documento.query, filters).order_by(
            Documento.modified_at.desc()
        )
        pagination = query.paginate(page=page, per_page=per_page, error_out=False)
    else:
        pagination = svc.list_documents_paginated(page, per_page)
    docs = pagination.items
    markdown_status = svc.get_markdown_status_map(docs)
    pending_markdown = svc.count_pending_markdown()
    doc_type_options, doc_status_options = _document_filter_options()

    return render_template(
        "admin_documents.html",
        docs=docs,
        markdown_status=markdown_status,
        pending_markdown=pending_markdown,
        filters=filters,
        doc_type_options=doc_type_options,
        doc_status_options=doc_status_options,
        page=pagination.page,
        total_pages=pagination.pages or 1,
        total_docs=pagination.total,
        upload_form=PdfUploadForm(),
    )


@admin_bp.post("/documents/bulk-delete")
@login_required
@admin_required
def bulk_delete_documents() -> ResponseReturnValue:
    """
    Elimina varios documentos seleccionados.
    """
    _validate_post_action()
    selected_ids = request.form.getlist("selected_doc_ids", type=int)
    if not selected_ids:
        return redirect(request.referrer or url_for(DOCUMENTS))

    try:
        for doc_id in set(selected_ids):
            documentos_service().delete_document(doc_id)
    except (OSError, SQLAlchemyError, RuntimeError):
        current_app.logger.exception("Error borrando documentos")
        abort(500)

    return redirect(request.referrer or url_for(DOCUMENTS))


@admin_bp.post("/documents/<int:doc_id>/delete")
@login_required
@admin_required
def delete_document(doc_id: int) -> ResponseReturnValue:
    """
    Elimina un documento y sus datos asociados.

    Args:
        doc_id: Identificador del documento que se va a eliminar.

    Returns:
        Una redireccion a la pagina de documentos.
    """
    _validate_post_action()
    try:
        documentos_service().delete_document(doc_id)
    except (OSError, SQLAlchemyError, RuntimeError):
        current_app.logger.exception("Error borrando documento")
        abort(500)

    return redirect(url_for(DOCUMENTS))


@admin_bp.get("/documents/<int:doc_id>/download")
@login_required
@admin_required
def download_document(doc_id: int) -> ResponseReturnValue:
    """
    Descarga un documento PDF o su version Markdown.

    Args:
        doc_id: Identificador del documento solicitado.

    Returns:
        Una respuesta de archivo para descarga.
    """
    doc = Documento.query.get_or_404(doc_id)
    fmt = (request.args.get("format") or "pdf").strip().lower()

    if fmt == "markdown":
        if not doc.markdown_content:
            abort(404)
        response = Response(doc.markdown_content, mimetype="text/markdown; charset=utf-8")
        response.headers["Content-Disposition"] = f'attachment; filename="{Path(doc.nombre).stem}.md"'
        return response

    pdf_path = Path(doc.path)
    if not pdf_path.exists():
        abort(404)

    return send_file(pdf_path, as_attachment=True, download_name=doc.nombre, mimetype="application/pdf")


@admin_bp.get("/documents/<int:doc_id>/view")
@login_required
@admin_required
def view_document(doc_id: int) -> ResponseReturnValue:
    """
    Muestra en navegador un documento PDF o Markdown.

    Args:
        doc_id: Identificador del documento solicitado.

    Returns:
        Una respuesta de archivo en modo visualizacion.
    """
    doc = Documento.query.get_or_404(doc_id)
    fmt = (request.args.get("format") or "pdf").strip().lower()

    if fmt == "markdown":
        if not doc.markdown_content:
            abort(404)
        try:
            import importlib

            md = importlib.import_module("markdown")
            render_markdown = md.markdown
        except ModuleNotFoundError:
            # Fallback: si la libreria no esta instalada, devuelve el markdown en bruto.
            return Response(doc.markdown_content, mimetype="text/markdown; charset=utf-8")

        rendered = render_markdown(
            doc.markdown_content,
            extensions=["extra", "fenced_code", "tables", "toc"],
            output_format="html5",
        )
        return render_template(
            "view_markdown.html",
            doc=doc,
            content=Markup(rendered),
            lang=get_locale(),
        )

    pdf_path = Path(doc.path)
    if not pdf_path.exists():
        abort(404)

    return send_file(pdf_path, as_attachment=False, download_name=doc.nombre, mimetype="application/pdf")


@admin_bp.post("/documents/web_scraping")
@login_required
@admin_required
def web_scraping_documents() -> ResponseReturnValue:
    """
    Crea un job para lanzar el proceso de web scraping.

    Returns:
        Una respuesta JSON con el identificador del job creado.
    """
    invalid = _validate_post_action(json_response=True)
    if invalid:
        return invalid

    lang = get_locale()
    job = WebScrapingSate(
        status="queued",
        progress=0,
        message=translate_for(lang, "jobs.queued_short"),
        cancel_requested=False,
        error=None,
    )
    db.session.add(job)
    db.session.commit()

    app_obj = current_app._get_current_object()
    executor.submit(scraping_async, app_obj, job.id, current_user.email, documents_page_url(), lang)

    return jsonify({"job_id": job.id}), 202


@admin_bp.post("/documents/web_scraping/cancel/<int:job_id>")
@login_required
@admin_required
def cancel_web_scraping(job_id: int) -> ResponseReturnValue:
    """
    Solicita la cancelacion de un job de web scraping.

    Args:
        job_id: Identificador del job de scraping.

    Returns:
        Una respuesta JSON con el estado actualizado del job.
    """
    invalid = _validate_post_action(json_response=True)
    if invalid:
        return invalid

    job = WebScrapingSate.query.get_or_404(job_id)

    if job.status in {"done", "failed", "cancelled"}:
        return jsonify({"status": job.status, "message": t(JOBS_ALREADY_FINISHED)}), 200

    job.cancel_requested = True
    _set_job_message(job, t("scraping.cancelling"))
    if job.status == "queued":
        job.status = "cancelled"
        job.finished_at = _now_madrid()
    db.session.commit()

    return jsonify({"status": job.status, "message": localize_runtime_message(job.message)}), 202


@admin_bp.get("/documents/web_scraping/status/<int:job_id>")
@admin_required
def web_scraping_status(job_id: int) -> ResponseReturnValue:
    """
    Devuelve el estado actual de un job de web scraping.

    Args:
        job_id: Identificador del job de scraping.

    Returns:
        Una respuesta JSON con progreso, mensaje y error del job.
    """
    job = WebScrapingSate.query.get(job_id)
    if not job:
        abort(404)

    return jsonify(
        {
            "status": job.status,
            "progress": job.progress,
            "message": localize_runtime_message(job.message),
            "error": job.error,
            "cancel_requested": bool(job.cancel_requested),
        }
    )


def _scraping_cancel_message(lang: str) -> str:
    """
    Obtiene el mensaje traducido de cancelacion para scraping.

    Args:
        lang: Codigo de idioma activo.

    Returns:
        El mensaje traducido de cancelacion.
    """
    return translate_for(lang, SCRAPING_CANCELLED)


def _build_scraping_context() -> tuple[Path, Path, Path, Path, Path, dict[str, str], Path, Path]:
    """
    Construye el contexto necesario para ejecutar el scraping.

    Returns:
        Una tupla con directorios, scripts y variables de entorno para scraping.
    """
    base_pliegos = pliegos_dir()
    root = Path(current_app.root_path)
    scraper_dir = root / "services" / "web_scraping"
    script_1 = scraper_dir / "PliegosPlaywrightAsincrono.py"
    script_2 = scraper_dir / "DescargarPliegos.py"
    data_dir = Path(current_app.config["DATA_DIR"])
    scraping_data_dir = data_dir / "web_scraping"
    resultados_json = scraping_data_dir / "resultados_playwright_asincrono_servidor.json"
    pliegos_json = scraping_data_dir / "pliegos_pdfs.json"
    env = os.environ.copy()
    env["PLIEGOS_DEST"] = str(base_pliegos)
    return base_pliegos, scraper_dir, script_1, script_2, root, env, resultados_json, pliegos_json


def _execute_subprocess_with_cancellation(script_path: Path, cwd: Path, env: dict[str, str], should_cancel, lang: str) -> None:
    """
    Ejecuta un subprocess con soporte de cancelacion.

    Args:
        script_path: Ruta del script que se va a ejecutar.
        cwd: Directorio de trabajo del proceso.
        env: Variables de entorno del proceso hijo.
        should_cancel: Callback que indica si el job debe cancelarse.
        lang: Codigo de idioma activo.

    Returns:
        None.
    """
    proc = subprocess.Popen(
        [sys.executable, str(script_path)],
        cwd=str(cwd),
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    while True:
        if should_cancel():
            proc.terminate()
            try:
                proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait()
            raise JobCancelledError(_scraping_cancel_message(lang))

        code = proc.poll()
        if code is not None:
            if code != 0:
                stdout, stderr = proc.communicate(timeout=5)
                raise subprocess.CalledProcessError(
                    code,
                    [sys.executable, str(script_path)],
                    output=stdout,
                    stderr=stderr,
                )
            return

        try:
            proc.wait(timeout=1)
        except subprocess.TimeoutExpired:
            continue


def _run_scraping_script(job, script_path: Path, cwd: Path, env: dict[str, str], should_cancel, lang: str, *, progress: int | None = None, message: str | None = None) -> None:
    """
    Ejecuta un script de scraping con soporte de cancelacion.

    Args:
        job: Instancia del job de scraping.
        script_path: Ruta del script que se va a ejecutar.
        cwd: Directorio de trabajo del proceso.
        env: Variables de entorno del proceso hijo.
        should_cancel: Callback que indica si el job debe cancelarse.
        lang: Codigo de idioma activo.
        progress: Progreso opcional a registrar antes de ejecutar.
        message: Mensaje opcional a registrar antes de ejecutar.

    Returns:
        None.
    """
    if should_cancel():
        raise JobCancelledError(_scraping_cancel_message(lang))

    if progress is not None:
        job.progress = progress
    if message is not None:
        _set_job_message(job, message)
    db.session.commit()

    _execute_subprocess_with_cancellation(script_path, cwd, env, should_cancel, lang)


def _sync_scraping_results(job, base_pliegos: Path, lang: str, should_cancel) -> tuple[int, int]:
    """
    Sincroniza los documentos descargados tras el scraping.

    Args:
        job: Instancia del job de scraping.
        base_pliegos: Directorio donde se guardan los PDFs descargados.
        lang: Codigo de idioma activo.
        should_cancel: Callback que indica si el job debe cancelarse.

    Returns:
        Una tupla con el numero de documentos nuevos y el total sincronizado.
    """
    if should_cancel():
        raise JobCancelledError(_scraping_cancel_message(lang))

    before_files = {p.name for p in base_pliegos.glob("*.pdf")}
    job.progress = 90
    _set_job_message(job, translate_for(lang, "scraping.syncing"))
    db.session.commit()
    documentos_service().sync_from_folder()
    after_files = {p.name for p in base_pliegos.glob("*.pdf")}

    if should_cancel():
        raise JobCancelledError(_scraping_cancel_message(lang))

    return len(after_files - before_files), len(after_files)


def _finish_scraping_job(job, user_email: str, docs_url: str, lang: str, extracted_docs: int, synced_total_docs: int) -> None:
    """
    Marca el job de scraping como completado y envia la notificacion.

    Args:
        job: Instancia del job de scraping.
        user_email: Correo del usuario que inicio el job.
        docs_url: URL de la pagina de documentos.
        lang: Codigo de idioma activo.
        extracted_docs: Numero de documentos nuevos descargados.
        synced_total_docs: Numero total de documentos sincronizados.

    Returns:
        None.
    """
    _mark_job_done(job, message=translate_for(lang, "scraping.done"))
    db.session.commit()
    _send_email_safe(
        send_scraping_finished_email,
        "No se pudo enviar el correo de fin de web scraping",
        to_email=user_email,
        ok=True,
        message=translate_for(lang, "scraping.done_email"),
        job_id=job.id,
        docs_url=docs_url,
        extracted_docs=extracted_docs,
        synced_total_docs=synced_total_docs,
    )


def _handle_scraping_exception(app, job_id: int, user_email: str, docs_url: str, lang: str, exc: Exception) -> None:
    """
    Gestiona un error inesperado en un job de scraping.

    Args:
        app: Aplicacion Flask activa.
        job_id: Identificador del job fallido.
        user_email: Correo del usuario que inicio el job.
        docs_url: URL de la pagina de documentos.
        lang: Codigo de idioma activo.
        exc: Excepcion capturada durante la ejecucion.

    Returns:
        None.
    """
    db.session.rollback()
    try:
        job = WebScrapingSate.query.get(job_id)
        if not job:
            raise exc

        # Si el fallo proviene de un subprocess, adjuntar stderr/stdout para diagnóstico.
        if isinstance(exc, subprocess.CalledProcessError):
            details = []
            if getattr(exc, "stderr", None):
                details.append(f"stderr:\n{exc.stderr.strip()}")
            if getattr(exc, "output", None):
                details.append(f"stdout:\n{exc.output.strip()}")
            if details:
                exc = RuntimeError(f"{exc}\n\n" + "\n\n".join(details))
        _mark_job_failed(job, exc, message=translate_for(lang, "scraping.failed"))
        db.session.commit()
        _send_email_safe(
            send_scraping_finished_email,
            "No se pudo enviar el correo de fin de web scraping",
            to_email=user_email,
            ok=False,
            message=translate_for(lang, "scraping.failed_email", error=job.error),
            job_id=job.id,
            docs_url=docs_url,
            extracted_docs=None,
            synced_total_docs=None,
        )
    finally:
        app.logger.exception("Error en scraping_async")


def scraping_async(app, job_id: int, user_email: str, docs_url: str, lang: str = "es") -> None:
    """
    Ejecuta en segundo plano el proceso completo de web scraping.

    Args:
        app: Aplicacion Flask activa.
        job_id: Identificador del job de scraping.
        user_email: Correo del usuario que inicio el job.
        docs_url: URL de la pagina de documentos.
        lang: Codigo de idioma activo.

    Returns:
        None.
    """
    with app.app_context():
        job = WebScrapingSate.query.get(job_id)
        if not job:
            return

        try:
            if job.cancel_requested:
                _mark_job_cancelled(job, message=_scraping_cancel_message(lang))
                db.session.commit()
                return

            _mark_job_running(job, message=translate_for(lang, "scraping.starting"))
            db.session.commit()

            base_pliegos, scraper_dir, script_1, script_2, _root, env, resultados_json, _pliegos_json = _build_scraping_context()

            def should_cancel() -> bool:
                """
                Comprueba si el job de scraping debe cancelarse.

                Returns:
                    ``True`` si se ha solicitado cancelacion.
                """
                return _job_should_cancel(job)

            try:
                _run_scraping_script(
                    job,
                    script_1,
                    scraper_dir,
                    env,
                    should_cancel,
                    lang,
                    message=translate_for(lang, "scraping.script_1"),
                )
            except subprocess.CalledProcessError as exc:
                # Si el extractor falla pero ya ha ido persistiendo resultados, intentamos descargar con lo disponible para maximizar pliegos.
                if resultados_json.exists():
                    app.logger.warning(
                        "El extractor falló, pero existe '%s'. Continuando con descarga. stderr=%s",
                        resultados_json,
                        (exc.stderr or "")[-2000:],
                    )
                else:
                    raise
            _run_scraping_script(
                job,
                script_2,
                scraper_dir,
                env,
                should_cancel,
                lang,
                progress=50,
                message=translate_for(lang, "scraping.script_2"),
            )
            extracted_docs, synced_total_docs = _sync_scraping_results(job, base_pliegos, lang, should_cancel)
            _finish_scraping_job(job, user_email, docs_url, lang, extracted_docs, synced_total_docs)
        except JobCancelledError:
            db.session.rollback()
            job = WebScrapingSate.query.get(job_id)
            if job:
                _mark_job_cancelled(job, message=_scraping_cancel_message(lang))
                db.session.commit()
        except ADMIN_RECOVERABLE_ERRORS as exc:
            _handle_scraping_exception(app, job_id, user_email, docs_url, lang, exc)
        finally:
            db.session.remove()
