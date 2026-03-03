from flask import render_template, redirect, url_for, abort, request, jsonify, current_app
from flask_login import login_required, current_user
from pathlib import Path
import os
import sys
import subprocess
from datetime import datetime
from zoneinfo import ZoneInfo

from . import admin_bp
from ..decorators import admin_required
from ..usuario import User
from ..forms import AdminCreateUserForm
from ..extensions import db
from ..rag.PrototipoRAG import index_pliegos_dir, qdrant_delete_by_filename, qdrant_count_chunks_by_filename

from ..documentos import DocumentosService

from app.async_tasks import executor
from app.vector_update_state import VectorUpdateState
from app.web_scraping_state import WebScrapingSate
from app.web_scraping_state import send_scraping_finished_email
from app.vector_update_state import send_update_finished_email


ALLOWED_EXT = {".pdf"}
USERS = "admin.users"
DOCUMENTS = "admin.documents_list_page"

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
            form.email.errors.append("Ya existe un usuario con ese email.")
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

@admin_bp.post("/documents/upload")
@admin_required
def upload_documents():
    files = request.files.getlist("files")
    if not files:
        return redirect(url_for(DOCUMENTS))

    documentos_service().save_uploads(files)
    return redirect(url_for(DOCUMENTS))

@admin_bp.post("/vector-db/update")
@login_required
@admin_required
def update_vector_db():
    job = VectorUpdateState(
        status="queued",
        progress=0,
        current_doc=None,
        error=None,
    )
    db.session.add(job)
    db.session.commit()
    
    app_obj = current_app._get_current_object()
    executor.submit(documentos_async, app_obj, job.id,  current_user.email)
    
    return jsonify({"job_id": job.id}), 202

def documentos_service() -> DocumentosService:
    return DocumentosService(
        pliegos_dir(),
        index_pliegos_dir=index_pliegos_dir,
        delete_chunks=qdrant_delete_by_filename,
        count_chunks=qdrant_count_chunks_by_filename,
    )

def documentos_async(app, job_id: int, user_email: str) -> None:
    """
    Actualizar la base de datos vectorial de manera asincrona.
    """
    ZONE = datetime.now(ZoneInfo("Europe/Madrid"))
    with app.app_context():
        job = VectorUpdateState.query.get(job_id)
        if not job:
            return
        
        try:
            job.status = "running"
            job.started_at = ZONE
            job.progress = job.progress or 0
            job.error = None
            db.session.commit()
            
            def on_current_doc(nombre: str):
                job.current_doc = nombre
                db.session.commit()

            def on_progress(i: int, total: int):
                if total and total > 0:
                    job.progress = int((i / total) * 100)
                else:
                    job.progress = 100
                db.session.commit()
            
            documentos_service().update_vector_db(
                on_progress=on_progress,
                on_current_doc=on_current_doc,
            )
            
            job.status = "done"
            job.progress = 100
            job.finished_at = ZONE
            db.session.commit()
            
            send_update_finished_email(
                to_email=user_email,
                ok=True,
                message="La actualización de qdrant ha terminado correctamente.",
                job_id=job.id,
            )

            
        except Exception as e:
            # Marca failed y guarda error
            try:
                job.status = "failed"
                job.error = str(e)
                job.finished_at = ZONE
                db.session.commit()
                send_update_finished_email(
                    to_email=user_email,
                    ok=False,
                    message=f"La actualización de qdrant ha fallado: {job.error}",
                    job_id=job.id,
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

    return jsonify({
        "status": job.status,
        "progress": job.progress,
        "current_doc": job.current_doc,
        "error": job.error,
    })            

@admin_bp.get("/documents/list")
@login_required
@admin_required
def documents_list_page():
    """
    Página para ver los documentos PDF cargados y poder borrarlos.
    """
    page = request.args.get("page", 1, type=int)
    per_page = 10

    svc = documentos_service()
    svc.sync_from_folder()
    svc.purge_missing_files()
    
    pagination = svc.list_documents_paginated(page, per_page)
    docs = pagination.items

    return render_template(
        "admin_documents.html",
        docs=docs,
        page=pagination.page,
        total_pages=pagination.pages or 1,
        total_docs=pagination.total,
    )


@admin_bp.post("/documents/<int:doc_id>/delete")
@login_required
@admin_required
def delete_document(doc_id: int):
    """
    Borra un PDF de la carpeta pliegos y elimina todos sus chunks en Qdrant.
    """
    try:
        documentos_service().delete_document(doc_id)
    except Exception:
        current_app.logger.exception("Error borrando documento")
        abort(500)

    return redirect(url_for(DOCUMENTS))

@admin_bp.post("/documents/web_scraping")
@login_required
@admin_required
def web_scraping_documents():
    """
    Lanza el scraping con Playwright y guarda los PDFs en app/rag/pliegos.
    """
    job = WebScrapingSate(status="queued", progress=0, message="En cola", error=None)
    db.session.add(job)
    db.session.commit()

    app_obj = current_app._get_current_object()
    executor.submit(scraping_async, app_obj, job.id, current_user.email)

    return jsonify({"job_id": job.id}), 202

@admin_bp.get("/documents/web_scraping/status/<int:job_id>")
@admin_required
def web_scraping_status(job_id: int):
    job = WebScrapingSate.query.get(job_id)
    if not job:
        abort(404)

    return jsonify({
        "status": job.status,
        "progress": job.progress,
        "message": job.message,
        "error": job.error,
    })
    
def scraping_async(app, job_id: int, user_email: str) -> None:
    ZONE = datetime.now(ZoneInfo("Europe/Madrid"))

    with app.app_context():
        job = WebScrapingSate.query.get(job_id)
        if not job:
            return

        try:
            job.status = "running"
            job.started_at = ZONE
            job.progress = 0
            job.message = "Iniciando scraping…"
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

            job.message = "Ejecutando script 1/2…"
            db.session.commit()
            subprocess.run([sys.executable, str(script_1)], cwd=str(cwd), env=env, check=True)

            job.progress = 50
            job.message = "Ejecutando script 2/2…"
            db.session.commit()
            subprocess.run([sys.executable, str(script_2)], cwd=str(cwd), env=env, check=True)

            job.progress = 90
            job.message = "Sincronizando PDFs en la base de datos…"
            db.session.commit()
            documentos_service().sync_from_folder()

            job.status = "done"
            job.progress = 100
            job.message = "Scraping terminado."
            job.finished_at = ZONE
            db.session.commit()
            
            send_scraping_finished_email(
                to_email=user_email,
                ok=True,
                message="El scraping ha terminado correctamente.",
                job_id=job.id,
            )

        except Exception as e:
            try:
                job.status = "failed"
                job.error = str(e)
                job.message = "Falló el scraping."
                job.finished_at = ZONE
                db.session.commit()
                
                send_scraping_finished_email(
                    to_email=user_email,
                    ok=False,
                    message=f"El scraping ha fallado: {job.error}",
                    job_id=job.id,
                )
            finally:
                app.logger.exception("Error en scraping_async")
        finally:
            db.session.remove()
