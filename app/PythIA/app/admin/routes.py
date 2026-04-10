"""
Autora: Lydia Blanco Ruiz
Script para las rutas de administracion, incluyendo gestion de usuarios, documentos y procesos en segundo plano con estado y cancelacion.
"""

from datetime import datetime
import os
from pathlib import Path
import subprocess
import sys
from zoneinfo import ZoneInfo

from flask import Response, abort, current_app, jsonify, redirect, render_template, request, send_file, url_for
from flask_login import current_user, login_required

from . import admin_bp
from ..decorators import admin_required
from ..documentos import DocumentosService, Documento, JobCancelledError
from ..extensions import db
from ..forms import AdminCreateUserForm
from ..markdown_conversion_state import MarkdownConversionState, send_markdown_finished_email
from ..rag.PrototipoRAG import index_pliegos_dir, qdrant_delete_by_filename
from ..usuario import User
from ..vector_update_state import VectorUpdateState, send_update_finished_email
from ..web_scraping_state import WebScrapingSate, send_scraping_finished_email
from app.async_tasks import executor, markdown_executor
from ..inetrnacionalizacion.tarduccion import get_locale, localize_runtime_message, t, translate_for


USERS = "admin.users"
DOCUMENTS = "admin.documents_list_page"
JOBS_ALREADY_FINISHED = "jobs.already_finished"
MARKDOWN_CANCELLED = "markdown.cancelled"
SCRAPING_CANCELLED = "scraping.cancelled"
MARKDOWN_JOB_MESSAGE_MAX_LENGTH = 255
MADRID_TZ = ZoneInfo("Europe/Madrid")


def _fit_job_message(message: str | None, max_length: int = MARKDOWN_JOB_MESSAGE_MAX_LENGTH) -> str | None:
    """Ajusta un mensaje de job a la longitud maxima permitida.

    Args:
        message: Mensaje original asociado al job.
        max_length: Longitud maxima permitida para el mensaje.

    Returns:
        El mensaje original, truncado o ``None`` si no habia contenido.
    """
    if message is None:
        return None
    if len(message) <= max_length:
        return message
    if max_length <= 3:
        return message[:max_length]
    return message[: max_length - 3].rstrip() + "..."


def _now_madrid() -> datetime:
    """Obtiene la fecha y hora actual en la zona horaria de Madrid.

    Returns:
        La fecha y hora actual con zona horaria de Madrid.
    """
    return datetime.now(MADRID_TZ)


def _set_job_message(job, message: str | None) -> None:
    """Guarda el mensaje de un job aplicando el ajuste de longitud.

    Args:
        job: Instancia del job que se va a actualizar.
        message: Mensaje nuevo que se quiere almacenar.

    Returns:
        None.
    """
    if hasattr(job, "message"):
        job.message = _fit_job_message(message)


def _set_job_progress(job, current: int | float, total: int) -> None:
    """Calcula y guarda el progreso porcentual de un job.

    Args:
        job: Instancia del job que se va a actualizar.
        current: Progreso actual en unidades completadas.
        total: Numero total de unidades a completar.

    Returns:
        None.
    """
    job.progress = int((current / total) * 100) if total and total > 0 else 100


def _job_should_cancel(job) -> bool:
    """Indica si un job ha solicitado cancelacion.

    Args:
        job: Instancia del job que se quiere consultar.

    Returns:
        ``True`` si el job ha sido marcado para cancelacion.
    """
    db.session.refresh(job)
    return bool(job.cancel_requested)


def _mark_job_running(job, *, progress: int = 0, message: str | None = None) -> None:
    """Marca un job como en ejecucion.

    Args:
        job: Instancia del job que se actualiza.
        progress: Progreso inicial del job.
        message: Mensaje descriptivo opcional del estado.

    Returns:
        None.
    """
    job.status = "running"
    job.started_at = _now_madrid()
    job.progress = progress
    job.error = None
    _set_job_message(job, message)


def _mark_job_cancelled(job, *, message: str | None = None, clear_error: bool = True) -> None:
    """Marca un job como cancelado.

    Args:
        job: Instancia del job que se actualiza.
        message: Mensaje descriptivo opcional del estado.
        clear_error: Indica si debe limpiarse el error almacenado.

    Returns:
        None.
    """
    job.status = "cancelled"
    if clear_error and hasattr(job, "error"):
        job.error = None
    _set_job_message(job, message)
    job.finished_at = _now_madrid()


def _mark_job_done(job, *, progress: int = 100, message: str | None = None) -> None:
    """Marca un job como finalizado correctamente.

    Args:
        job: Instancia del job que se actualiza.
        progress: Progreso final del job.
        message: Mensaje descriptivo opcional del estado.

    Returns:
        None.
    """
    job.status = "done"
    job.progress = progress
    _set_job_message(job, message)
    job.finished_at = _now_madrid()


def _mark_job_failed(job, error: Exception | str, *, message: str | None = None) -> None:
    """Marca un job como fallido y registra el error.

    Args:
        job: Instancia del job que se actualiza.
        error: Excepcion o texto descriptivo del fallo.
        message: Mensaje descriptivo opcional del estado.

    Returns:
        None.
    """
    job.status = "failed"
    job.error = str(error)
    _set_job_message(job, message)
    job.finished_at = _now_madrid()


def _send_email_safe(send_fn, log_message: str, **kwargs) -> None:
    """Ejecuta un envio de correo registrando cualquier excepcion.

    Args:
        send_fn: Funcion encargada de enviar el correo.
        log_message: Mensaje a registrar si el envio falla.
        **kwargs: Argumentos que se pasan a la funcion de envio.

    Returns:
        None.
    """
    try:
        send_fn(**kwargs)
    except Exception:
        current_app.logger.exception(log_message)


@admin_bp.route("/users")
@login_required
@admin_required
def users():
    """Muestra el listado de usuarios administrables.

    Returns:
        La pagina HTML con todos los usuarios ordenados por identificador.
    """
    users = User.query.order_by(User.id.asc()).all()
    return render_template("users.html", users=users)


@admin_bp.route("/users/<int:user_id>", methods=["POST"])
@login_required
@admin_required
def change_type(user_id):
    """Alterna el rol de administrador de un usuario.

    Args:
        user_id: Identificador del usuario cuyo rol se modifica.

    Returns:
        Una redireccion al listado de usuarios.
    """
    user = User.get_by_id(user_id)
    if not user:
        abort(404)
    if user.id == current_user.id:
        abort(400)

    user.change_is_admin()
    db.session.commit()
    return redirect(url_for(USERS))


@admin_bp.route("/users/<int:user_id>/delete", methods=["POST"])
@login_required
@admin_required
def delete_user(user_id):
    """Elimina un usuario distinto del administrador actual.

    Args:
        user_id: Identificador del usuario que se va a eliminar.

    Returns:
        Una redireccion al listado de usuarios.
    """
    user = User.get_by_id(user_id)
    if not user:
        abort(404)
    if user.id == current_user.id:
        abort(400)

    db.session.delete(user)
    db.session.commit()
    return redirect(url_for(USERS))


@admin_bp.route("/users/add", methods=["GET", "POST"])
@login_required
@admin_required
def create_user():
    """Crea un usuario nuevo desde el formulario de administracion.

    Returns:
        La plantilla del formulario o una redireccion al listado de usuarios.
    """
    form = AdminCreateUserForm()

    if form.validate_on_submit():
        nombre = form.nombre.data.strip()
        email = form.email.data.lower().strip()
        password = form.password.data
        is_admin = form.is_admin.data

        if User.get_by_email(email):
            form.email.errors.append(t("auth.email_exists"))
            return render_template("admin_create_user.html", form=form)

        user = User(nombre=nombre, email=email)
        user.set_password(password)
        user.is_admin = is_admin

        db.session.add(user)
        db.session.commit()
        return redirect(url_for(USERS))

    return render_template("admin_create_user.html", form=form)


def pliegos_dir() -> Path:
    """Obtiene y garantiza la existencia del directorio de pliegos.

    Returns:
        La ruta absoluta al directorio configurado para pliegos.
    """
    base = Path(current_app.config.get("DOCS_DIR", "/data/pliegos")).resolve()
    base.mkdir(parents=True, exist_ok=True)
    return base


def documentos_service() -> DocumentosService:
    """Construye el servicio de gestion documental para administracion.

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
    """Construye la URL absoluta de la pagina de documentos.

    Returns:
        La URL completa a la pagina de administracion de documentos.
    """
    return f"{request.host_url.rstrip('/')}{url_for('admin.documents_list_page')}"


def convert_pdf_to_markdown(pdf_path: Path, on_page_start=None) -> str:
    """Convierte un PDF a Markdown mediante el procesador configurado.

    Args:
        pdf_path: Ruta del PDF origen.
        on_page_start: Callback opcional invocado al comenzar cada pagina.

    Returns:
        El contenido Markdown generado.
    """
    from ..markdown.Conversion_markdown import process_pdf

    return process_pdf(pdf_path, on_page_start=on_page_start)


@admin_bp.post("/documents/upload")
@admin_required
def upload_documents():
    """Guarda los documentos subidos desde la interfaz de administracion.

    Returns:
        Una redireccion a la pagina de documentos.
    """
    files = request.files.getlist("files")
    if not files:
        return redirect(url_for(DOCUMENTS))

    documentos_service().save_uploads(files)
    return redirect(url_for(DOCUMENTS))


@admin_bp.post("/documents/markdown/convert")
@login_required
@admin_required
def convert_documents_to_markdown():
    """Crea un job para convertir documentos pendientes a Markdown.

    Returns:
        Una respuesta JSON con el identificador del job creado.
    """
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
def cancel_markdown_conversion(job_id: int):
    """Solicita la cancelacion de un job de conversion a Markdown.

    Args:
        job_id: Identificador del job de conversion.

    Returns:
        Una respuesta JSON con el estado actualizado del job.
    """
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
def markdown_conversion_status(job_id: int):
    """Devuelve el estado actual de un job de conversion a Markdown.

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
    """Obtiene el mensaje traducido de cancelacion para Markdown.

    Args:
        lang: Codigo de idioma activo.

    Returns:
        El mensaje traducido de cancelacion.
    """
    return translate_for(lang, MARKDOWN_CANCELLED)


def _cancel_markdown_job(job, lang: str) -> None:
    """Marca un job de Markdown como cancelado y persiste el cambio.

    Args:
        job: Instancia del job de conversion.
        lang: Codigo de idioma activo.

    Returns:
        None.
    """
    _mark_job_cancelled(job, message=_markdown_cancel_message(lang))
    db.session.commit()


def _markdown_page_base_message(job, lang: str) -> str:
    """Extrae la parte base del mensaje de progreso de Markdown.

    Args:
        job: Instancia del job de conversion.
        lang: Codigo de idioma activo.

    Returns:
        El mensaje base sin informacion de pagina.
    """
    current_message = job.message or translate_for(lang, "markdown.converting_default")
    return current_message.split(" Pádina ", 1)[0].split(" Page ", 1)[0]


def _build_markdown_callbacks(job, lang: str):
    """Construye los callbacks usados durante la conversion a Markdown.

    Args:
        job: Instancia del job de conversion.
        lang: Codigo de idioma activo.

    Returns:
        Una tupla con los callbacks de cancelacion, progreso, documento y pagina.
    """
    current_doc_name = {"value": None}

    def should_cancel() -> bool:
        """Comprueba si el job de Markdown debe cancelarse.

        Returns:
            ``True`` si se ha solicitado cancelacion.
        """
        return _job_should_cancel(job)

    def raise_if_cancelled() -> None:
        """Interrumpe la ejecucion si el job de Markdown fue cancelado.

        Returns:
            None.
        """
        if should_cancel():
            raise JobCancelledError(_markdown_cancel_message(lang))

    def on_progress(i: int, total: int) -> None:
        """Actualiza el progreso del job de Markdown.

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
        """Actualiza el documento actual en conversion a Markdown.

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
        """Actualiza el progreso al comenzar una pagina de conversion.

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
    """Genera el mensaje final de un job de conversion a Markdown.

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
    """Marca el job de Markdown como completado y envia la notificacion.

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
    """Gestiona un error inesperado en un job de Markdown.

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
    """Ejecuta en segundo plano la conversion de documentos a Markdown.

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
        except Exception as exc:
            _handle_markdown_exception(app, job_id, user_email, docs_url, lang, exc)
        finally:
            db.session.remove()


@admin_bp.post("/vector-db/update")
@login_required
@admin_required
def update_vector_db():
    """Crea un job para actualizar la base de datos vectorial.

    Returns:
        Una respuesta JSON con el identificador del job creado.
    """
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
def cancel_vector_db(job_id: int):
    """Solicita la cancelacion de un job de indexacion vectorial.

    Args:
        job_id: Identificador del job vectorial.

    Returns:
        Una respuesta JSON con el estado actualizado del job.
    """
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
    """Ejecuta en segundo plano la indexacion vectorial de documentos.

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
                """Comprueba si el job vectorial debe cancelarse.

                Returns:
                    ``True`` si se ha solicitado cancelacion.
                """
                return _job_should_cancel(job)

            def on_current_doc(nombre: str):
                """Actualiza el documento actual del job vectorial.

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
                """Actualiza el progreso del job vectorial.

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
        except Exception as exc:
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
def vector_db_status(job_id: int):
    """Devuelve el estado actual de un job de indexacion vectorial.

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
def documents_list_page():
    """Muestra la pagina de administracion de documentos.

    Returns:
        La plantilla HTML con la lista paginada y el estado de Markdown.
    """
    page = request.args.get("page", 1, type=int)
    per_page = 10

    svc = documentos_service()
    svc.sync_from_folder()
    svc.purge_missing_files()

    pagination = svc.list_documents_paginated(page, per_page)
    docs = pagination.items
    markdown_status = svc.get_markdown_status_map(docs)
    pending_markdown = svc.count_pending_markdown()

    return render_template(
        "admin_documents.html",
        docs=docs,
        markdown_status=markdown_status,
        pending_markdown=pending_markdown,
        page=pagination.page,
        total_pages=pagination.pages or 1,
        total_docs=pagination.total,
    )


@admin_bp.post("/documents/<int:doc_id>/delete")
@login_required
@admin_required
def delete_document(doc_id: int):
    """Elimina un documento y sus datos asociados.

    Args:
        doc_id: Identificador del documento que se va a eliminar.

    Returns:
        Una redireccion a la pagina de documentos.
    """
    try:
        documentos_service().delete_document(doc_id)
    except Exception:
        current_app.logger.exception("Error borrando documento")
        abort(500)

    return redirect(url_for(DOCUMENTS))


@admin_bp.get("/documents/<int:doc_id>/download")
@login_required
@admin_required
def download_document(doc_id: int):
    """Descarga un documento PDF o su version Markdown.

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
def view_document(doc_id: int):
    """Muestra en navegador un documento PDF o Markdown.

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
        return Response(doc.markdown_content, mimetype="text/markdown; charset=utf-8")

    pdf_path = Path(doc.path)
    if not pdf_path.exists():
        abort(404)

    return send_file(pdf_path, as_attachment=False, download_name=doc.nombre, mimetype="application/pdf")


@admin_bp.post("/documents/web_scraping")
@login_required
@admin_required
def web_scraping_documents():
    """Crea un job para lanzar el proceso de web scraping.

    Returns:
        Una respuesta JSON con el identificador del job creado.
    """
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
def cancel_web_scraping(job_id: int):
    """Solicita la cancelacion de un job de web scraping.

    Args:
        job_id: Identificador del job de scraping.

    Returns:
        Una respuesta JSON con el estado actualizado del job.
    """
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
def web_scraping_status(job_id: int):
    """Devuelve el estado actual de un job de web scraping.

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
    """Obtiene el mensaje traducido de cancelacion para scraping.

    Args:
        lang: Codigo de idioma activo.

    Returns:
        El mensaje traducido de cancelacion.
    """
    return translate_for(lang, SCRAPING_CANCELLED)


def _build_scraping_context() -> tuple[Path, Path, Path, Path, Path, dict[str, str]]:
    """Construye el contexto necesario para ejecutar el scraping.

    Returns:
        Una tupla con directorios, scripts y variables de entorno para scraping.
    """
    base_pliegos = pliegos_dir()
    root = Path(current_app.root_path)
    scraper_dir = root / "web_scraping"
    script_1 = scraper_dir / "PliegosPlaywrightAsincrono.py"
    script_2 = scraper_dir / "DescargarPliegos.py"
    env = os.environ.copy()
    env["PLIEGOS_DEST"] = str(base_pliegos)
    env["PLIEGOS_INPUT_JSON"] = str(scraper_dir / "resultados_playwright_asincrono_servidor.json")
    env["PLIEGOS_OUTPUT_JSON"] = str(scraper_dir / "pliegos_pdfs.json")
    return base_pliegos, scraper_dir, script_1, script_2, root, env


def _run_scraping_script(job, script_path: Path, cwd: Path, env: dict[str, str], should_cancel, lang: str, *, progress: int | None = None, message: str | None = None) -> None:
    """Ejecuta un script de scraping con soporte de cancelacion.

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

    proc = subprocess.Popen([sys.executable, str(script_path)], cwd=str(cwd), env=env)
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
                raise subprocess.CalledProcessError(code, [sys.executable, str(script_path)])
            return

        try:
            proc.wait(timeout=1)
        except subprocess.TimeoutExpired:
            continue


def _sync_scraping_results(job, base_pliegos: Path, lang: str, should_cancel) -> tuple[int, int]:
    """Sincroniza los documentos descargados tras el scraping.

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
    """Marca el job de scraping como completado y envia la notificacion.

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
    """Gestiona un error inesperado en un job de scraping.

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
    """Ejecuta en segundo plano el proceso completo de web scraping.

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

            base_pliegos, scraper_dir, script_1, script_2, _root, env = _build_scraping_context()

            def should_cancel() -> bool:
                """Comprueba si el job de scraping debe cancelarse.

                Returns:
                    ``True`` si se ha solicitado cancelacion.
                """
                return _job_should_cancel(job)

            _run_scraping_script(
                job,
                script_1,
                scraper_dir,
                env,
                should_cancel,
                lang,
                message=translate_for(lang, "scraping.script_1"),
            )
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
        except Exception as exc:
            _handle_scraping_exception(app, job_id, user_email, docs_url, lang, exc)
        finally:
            db.session.remove()
