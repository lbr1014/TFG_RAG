from datetime import datetime
import os
from pathlib import Path
import subprocess
import sys
from zoneinfo import ZoneInfo

from flask import abort, current_app, jsonify, redirect, render_template, request, send_file, url_for
from flask_login import current_user, login_required

from . import admin_bp
from ..decorators import admin_required
from ..documentos import DocumentosService, Documento, JobCancelledError
from ..extensions import db
from ..forms import AdminCreateUserForm
from ..markdown_conversion_state import MarkdownConversionState, send_markdown_finished_email
from ..rag.PrototipoRAG import (
    index_pliegos_dir,
    qdrant_count_chunks_by_filename,
    qdrant_delete_by_filename,
)
from ..usuario import User
from ..vector_update_state import VectorUpdateState, send_update_finished_email
from ..web_scraping_state import WebScrapingSate, send_scraping_finished_email
from app.async_tasks import executor, markdown_executor
from ..inetrnacionalizacion.tarduccion import get_locale, localize_runtime_message, t, translate_for


USERS = "admin.users"
DOCUMENTS = "admin.documents_list_page"
MARKDOWN_JOB_MESSAGE_MAX_LENGTH = 255


def _fit_job_message(message: str | None, max_length: int = MARKDOWN_JOB_MESSAGE_MAX_LENGTH) -> str | None:
    if message is None:
        return None
    if len(message) <= max_length:
        return message
    if max_length <= 3:
        return message[:max_length]
    return message[: max_length - 3].rstrip() + "..."


def _set_markdown_job_message(job: MarkdownConversionState, message: str | None) -> None:
    job.message = _fit_job_message(message)


@admin_bp.route("/users")
@login_required
@admin_required
def users():
    users = User.query.order_by(User.id.asc()).all()
    return render_template("users.html", users=users)


@admin_bp.route("/users/<int:user_id>", methods=["POST"])
@login_required
@admin_required
def change_type(user_id):
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
    base = Path(current_app.config.get("DOCS_DIR", "/data/pliegos")).resolve()
    base.mkdir(parents=True, exist_ok=True)
    return base


def documentos_service() -> DocumentosService:
    return DocumentosService(
        pliegos_dir(),
        index_pliegos_dir=index_pliegos_dir,
        delete_chunks=qdrant_delete_by_filename,
        count_chunks=qdrant_count_chunks_by_filename,
        markdown_dir=markdown_dir(),
        markdown_converter=convert_pdf_to_markdown,
    )


def documents_page_url() -> str:
    return f"{request.host_url.rstrip('/')}{url_for('admin.documents_list_page')}"


def markdown_dir() -> Path:
    configured = current_app.config.get("DOCS_MD_DIR")
    base = Path(configured).resolve() if configured else (pliegos_dir() / "markdown").resolve()
    base.mkdir(parents=True, exist_ok=True)
    return base


def convert_pdf_to_markdown(pdf_path: Path, output_dir: Path, on_page_start=None) -> None:
    from ..markdown.Conversion_markdown import process_pdf

    process_pdf(pdf_path, output_dir, on_page_start=on_page_start)


@admin_bp.post("/documents/upload")
@admin_required
def upload_documents():
    files = request.files.getlist("files")
    if not files:
        return redirect(url_for(DOCUMENTS))

    documentos_service().save_uploads(files)
    return redirect(url_for(DOCUMENTS))


@admin_bp.post("/documents/markdown/convert")
@login_required
@admin_required
def convert_documents_to_markdown():
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
    job = MarkdownConversionState.query.get_or_404(job_id)

    if job.status in {"done", "failed", "cancelled"}:
        return jsonify({"status": job.status, "message": t("jobs.already_finished")}), 200

    job.cancel_requested = True
    _set_markdown_job_message(job, t("markdown.cancelling"))
    if job.status == "queued":
        job.status = "cancelled"
        job.finished_at = datetime.now(ZoneInfo("Europe/Madrid"))
    db.session.commit()

    return jsonify({"status": job.status, "message": localize_runtime_message(job.message)}), 202


@admin_bp.get("/documents/markdown/status/<int:job_id>")
@login_required
@admin_required
def markdown_conversion_status(job_id: int):
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


def markdown_async(app, job_id: int, user_email: str, docs_url: str, lang: str = "es") -> None:
    zone_now = datetime.now(ZoneInfo("Europe/Madrid"))

    with app.app_context():
        job = MarkdownConversionState.query.get(job_id)
        if not job:
            return

        try:
            if job.cancel_requested:
                job.status = "cancelled"
                _set_markdown_job_message(job, translate_for(lang, "markdown.cancelled"))
                job.finished_at = zone_now
                db.session.commit()
                return

            job.status = "running"
            job.started_at = zone_now
            job.progress = 0
            _set_markdown_job_message(job, translate_for(lang, "markdown.starting"))
            job.error = None
            db.session.commit()
            current_doc_name: str | None = None

            def should_cancel() -> bool:
                db.session.refresh(job)
                return bool(job.cancel_requested)

            def on_progress(i: int, total: int):
                if should_cancel():
                    raise JobCancelledError(translate_for(lang, "markdown.cancelled"))
                job.progress = int((i / total) * 100) if total and total > 0 else 100
                db.session.commit()

            def on_current_doc(nombre: str):
                nonlocal current_doc_name
                if should_cancel():
                    raise JobCancelledError(translate_for(lang, "markdown.cancelled"))
                current_doc_name = nombre
                _set_markdown_job_message(job, translate_for(lang, "markdown.converting_doc", name=nombre))
                db.session.commit()

            def on_page_start(doc_index: int, total_docs: int, page: int, total_pages: int):
                if should_cancel():
                    raise JobCancelledError(translate_for(lang, "markdown.cancelled"))
                current_message = (job.message or translate_for(lang, "markdown.converting_default")).split(" Página ", 1)[0].split(" Page ", 1)[0]
                completed = (doc_index - 1) + (page / total_pages if total_pages else 1)
                job.progress = int((completed / total_docs) * 100) if total_docs and total_docs > 0 else 100
                _set_markdown_job_message(job, translate_for(lang, "markdown.converting_doc_page", name=current_doc_name or current_message.removeprefix("Convirtiendo ").removeprefix("Converting ").removesuffix("..."), page=page, total_pages=total_pages))
                db.session.commit()

            stats = documentos_service().convert_pending_to_markdown(
                on_progress=on_progress,
                on_current_doc=on_current_doc,
                should_cancel=should_cancel,
                on_page_start=on_page_start,
            )

            db.session.refresh(job)
            if job.cancel_requested:
                job.status = "cancelled"
                _set_markdown_job_message(job, translate_for(lang, "markdown.cancelled"))
                job.finished_at = datetime.now(ZoneInfo("Europe/Madrid"))
                db.session.commit()
                return

            job.status = "done"
            job.progress = 100
            if stats["converted"] == 0:
                _set_markdown_job_message(job, translate_for(lang, "markdown.none_pending"))
            else:
                _set_markdown_job_message(job, translate_for(lang, "markdown.done_stats", count=stats["converted"]))
            job.finished_at = zone_now
            db.session.commit()
            send_markdown_finished_email(
                to_email=user_email,
                ok=True,
                message=translate_for(lang, "markdown.done_email"),
                job_id=job.id,
                docs_url=docs_url,
                converted_docs=stats.get("converted", 0),
                skipped_docs=stats.get("skipped", 0),
            )
        except JobCancelledError:
            db.session.rollback()
            job = MarkdownConversionState.query.get(job_id)
            if job:
                job.status = "cancelled"
                _set_markdown_job_message(job, translate_for(lang, "markdown.cancelled"))
                job.error = None
                job.finished_at = datetime.now(ZoneInfo("Europe/Madrid"))
                db.session.commit()
        except Exception as exc:
            db.session.rollback()
            try:
                job = MarkdownConversionState.query.get(job_id)
                if not job:
                    raise
                job.status = "failed"
                job.error = str(exc)
                _set_markdown_job_message(job, translate_for(lang, "markdown.failed"))
                job.finished_at = zone_now
                db.session.commit()
                send_markdown_finished_email(
                    to_email=user_email,
                    ok=False,
                    message=translate_for(lang, "markdown.failed_email", error=job.error),
                    job_id=job.id,
                    docs_url=docs_url,
                )
            finally:
                app.logger.exception("Error en markdown_async")
        finally:
            db.session.remove()


@admin_bp.post("/vector-db/update")
@login_required
@admin_required
def update_vector_db():
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
    job = VectorUpdateState.query.get_or_404(job_id)

    if job.status in {"done", "failed", "cancelled"}:
        return jsonify({"status": job.status, "message": t("jobs.already_finished")}), 200

    job.cancel_requested = True
    if job.status == "queued":
        job.status = "cancelled"
        job.finished_at = datetime.now(ZoneInfo("Europe/Madrid"))
    db.session.commit()

    return jsonify({"status": job.status, "message": t("vector.cancelling")}), 202


def documentos_async(app, job_id: int, user_email: str, docs_url: str, lang: str = "es") -> None:
    zone_now = datetime.now(ZoneInfo("Europe/Madrid"))
    with app.app_context():
        job = VectorUpdateState.query.get(job_id)
        if not job:
            return

        try:
            if job.cancel_requested:
                job.status = "cancelled"
                job.finished_at = zone_now
                db.session.commit()
                return

            job.status = "running"
            job.started_at = zone_now
            job.progress = job.progress or 0
            job.error = None
            db.session.commit()

            def should_cancel() -> bool:
                db.session.refresh(job)
                return bool(job.cancel_requested)

            def on_current_doc(nombre: str):
                if should_cancel():
                    raise JobCancelledError(translate_for(lang, "vector.cancelled_by_user"))
                job.current_doc = nombre
                db.session.commit()

            def on_progress(i: int, total: int):
                if should_cancel():
                    raise JobCancelledError(translate_for(lang, "vector.cancelled_by_user"))
                job.progress = int((i / total) * 100) if total and total > 0 else 100
                db.session.commit()

            stats = documentos_service().update_vector_db(
                on_progress=on_progress,
                on_current_doc=on_current_doc,
                should_cancel=should_cancel,
            )

            db.session.refresh(job)
            if job.cancel_requested:
                job.status = "cancelled"
                job.finished_at = datetime.now(ZoneInfo("Europe/Madrid"))
                db.session.commit()
                return

            job.status = "done"
            job.progress = 100
            job.finished_at = zone_now
            db.session.commit()

            send_update_finished_email(
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
                job.status = "cancelled"
                job.error = None
                job.finished_at = datetime.now(ZoneInfo("Europe/Madrid"))
                db.session.commit()
        except Exception as exc:
            try:
                job.status = "failed"
                job.error = str(exc)
                job.finished_at = zone_now
                db.session.commit()
                send_update_finished_email(
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
    doc = Documento.query.get_or_404(doc_id)
    pdf_path = Path(doc.path)

    if not pdf_path.exists():
        abort(404)

    return send_file(pdf_path, as_attachment=True, download_name=doc.nombre, mimetype="application/pdf")


@admin_bp.get("/documents/<int:doc_id>/view")
@login_required
@admin_required
def view_document(doc_id: int):
    doc = Documento.query.get_or_404(doc_id)
    pdf_path = Path(doc.path)

    if not pdf_path.exists():
        abort(404)

    return send_file(pdf_path, as_attachment=False, download_name=doc.nombre, mimetype="application/pdf")


@admin_bp.post("/documents/web_scraping")
@login_required
@admin_required
def web_scraping_documents():
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
    job = WebScrapingSate.query.get_or_404(job_id)

    if job.status in {"done", "failed", "cancelled"}:
        return jsonify({"status": job.status, "message": t("jobs.already_finished")}), 200

    job.cancel_requested = True
    job.message = t("scraping.cancelling")
    if job.status == "queued":
        job.status = "cancelled"
        job.finished_at = datetime.now(ZoneInfo("Europe/Madrid"))
    db.session.commit()

    return jsonify({"status": job.status, "message": localize_runtime_message(job.message)}), 202


@admin_bp.get("/documents/web_scraping/status/<int:job_id>")
@admin_required
def web_scraping_status(job_id: int):
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


def scraping_async(app, job_id: int, user_email: str, docs_url: str, lang: str = "es") -> None:
    zone_now = datetime.now(ZoneInfo("Europe/Madrid"))

    with app.app_context():
        job = WebScrapingSate.query.get(job_id)
        if not job:
            return

        try:
            if job.cancel_requested:
                job.status = "cancelled"
                job.message = translate_for(lang, "scraping.cancelled")
                job.finished_at = zone_now
                db.session.commit()
                return

            job.status = "running"
            job.started_at = zone_now
            job.progress = 0
            job.message = translate_for(lang, "scraping.starting")
            job.error = None
            db.session.commit()

            base_pliegos = pliegos_dir()
            root = Path(current_app.root_path)
            scraper_dir = root / "web_scraping"
            script_1 = scraper_dir / "PliegosPlaywrightAsincrono.py"
            script_2 = scraper_dir / "DescargarPliegos.py"
            cwd = scraper_dir

            env = os.environ.copy()
            env["PLIEGOS_DEST"] = str(base_pliegos)
            env["PLIEGOS_INPUT_JSON"] = str(cwd / "resultados_playwright_asincrono_servidor.json")
            env["PLIEGOS_OUTPUT_JSON"] = str(cwd / "pliegos_pdfs.json")

            def should_cancel() -> bool:
                db.session.refresh(job)
                return bool(job.cancel_requested)

            def run_script_with_cancel(script_path: Path, progress: int | None = None, message: str | None = None) -> None:
                if should_cancel():
                    raise JobCancelledError(translate_for(lang, "scraping.cancelled"))

                if progress is not None:
                    job.progress = progress
                if message is not None:
                    job.message = message
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
                        raise JobCancelledError(translate_for(lang, "scraping.cancelled"))

                    code = proc.poll()
                    if code is not None:
                        if code != 0:
                            raise subprocess.CalledProcessError(code, [sys.executable, str(script_path)])
                        return

                    try:
                        proc.wait(timeout=1)
                    except subprocess.TimeoutExpired:
                        continue

            before_files = {p.name for p in base_pliegos.glob("*.pdf")}

            run_script_with_cancel(script_1, message=translate_for(lang, "scraping.script_1"))
            run_script_with_cancel(script_2, progress=50, message=translate_for(lang, "scraping.script_2"))

            if should_cancel():
                raise JobCancelledError(translate_for(lang, "scraping.cancelled"))

            job.progress = 90
            job.message = translate_for(lang, "scraping.syncing")
            db.session.commit()
            documentos_service().sync_from_folder()
            after_files = {p.name for p in base_pliegos.glob("*.pdf")}
            extracted_docs = len(after_files - before_files)
            synced_total_docs = len(after_files)

            if should_cancel():
                raise JobCancelledError(translate_for(lang, "scraping.cancelled"))

            job.status = "done"
            job.progress = 100
            job.message = translate_for(lang, "scraping.done")
            job.finished_at = zone_now
            db.session.commit()

            send_scraping_finished_email(
                to_email=user_email,
                ok=True,
                message=translate_for(lang, "scraping.done_email"),
                job_id=job.id,
                docs_url=docs_url,
                extracted_docs=extracted_docs,
                synced_total_docs=synced_total_docs,
            )
        except JobCancelledError:
            db.session.rollback()
            job = WebScrapingSate.query.get(job_id)
            if job:
                job.status = "cancelled"
                job.message = translate_for(lang, "scraping.cancelled")
                job.error = None
                job.finished_at = datetime.now(ZoneInfo("Europe/Madrid"))
                db.session.commit()
        except Exception as exc:
            try:
                job.status = "failed"
                job.error = str(exc)
                job.message = translate_for(lang, "scraping.failed")
                job.finished_at = zone_now
                db.session.commit()
                send_scraping_finished_email(
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
        finally:
            db.session.remove()
