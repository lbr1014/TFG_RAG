from flask import render_template, redirect, url_for, abort, request, jsonify, current_app
from flask_login import login_required, current_user
from pathlib import Path
import os
import sys
import subprocess

from . import admin_bp
from ..decorators import admin_required
from ..usuario import User
from ..forms import AdminCreateUserForm
from ..extensions import db
from ..rag.PrototipoRAG import index_pliegos_dir, qdrant_delete_by_filename, qdrant_count_chunks_by_filename

from ..documentos import DocumentosService

ALLOWED_EXT = {".pdf"}

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
    return redirect(url_for("admin.users"))

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
    return redirect(url_for("admin.users"))

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
        return redirect(url_for("admin.users"))

    return render_template("admin_create_user.html", form=form)

def pliegos_dir() -> Path:
    base = Path(current_app.root_path) / "rag" / "pliegos"
    base.mkdir(parents=True, exist_ok=True)
    return base

@admin_bp.post("/documents/upload")
@admin_required
def upload_documents():
    files = request.files.getlist("files")
    if not files:
        return redirect(url_for("admin.documents_list_page"))

    documentos_service().save_uploads(files)
    return redirect(url_for("admin.documents_list_page"))

@admin_bp.post("/vector-db/update")
@admin_required
def update_vector_db():
    try:
        documentos_service().update_vector_db()
    except Exception:
        current_app.logger.exception("Error actualizando base vectorial")
        abort(500)

    return redirect(url_for("admin.documents_list_page"))

def documentos_service() -> DocumentosService:
    return DocumentosService(
        pliegos_dir(),
        index_pliegos_dir=index_pliegos_dir,
        delete_chunks=qdrant_delete_by_filename,
        count_chunks=qdrant_count_chunks_by_filename,
    )


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

    return redirect(url_for("admin.documents_list_page"))

@admin_bp.post("/documents/web_scraping")
@login_required
@admin_required
def web_scraping_documents():
    """
    Lanza el scraping con Playwright y guarda los PDFs en app/rag/pliegos.
    """
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

    try:
        subprocess.run([sys.executable, str(script_1)], cwd=str(cwd), env=env, check=True)
        subprocess.run([sys.executable, str(script_2)], cwd=str(cwd), env=env, check=True)
    except subprocess.CalledProcessError:
        current_app.logger.exception("Error ejecutando scraping")
        
    documentos_service().sync_from_folder()

    return redirect(url_for("admin.documents_list_page"))
