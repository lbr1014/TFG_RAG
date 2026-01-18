from flask import render_template, redirect, url_for, abort, request, jsonify, current_app
from flask_login import login_required, current_user
from pathlib import Path
from werkzeug.utils import secure_filename
from datetime import datetime

from . import admin_bp
from ..decorators import admin_required
from ..usuario import User
from ..forms import AdminCreateUserForm
from ..extensions import db
from ..rag.PrototipoRAG import index_pliegos_dir, qdrant_delete_by_filename, qdrant_count_chunks_by_filename

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
        return jsonify({"ok": False, "error": "No se han enviado archivos"}), 400

    docs = []
    for f in files:
        name = secure_filename(f.filename or "")
        if not name:
            continue
        if Path(name).suffix.lower() not in ALLOWED_EXT:
            continue
        dest = pliegos_dir() / name
        f.save(dest)
        stat = dest.stat()
        modified_dt = datetime.fromtimestamp(stat.st_mtime)
        try:
            chunks = qdrant_count_chunks_by_filename(name)
        except Exception:
            chunks = 0

        docs.append({
            "name": name,
            "size_bytes": stat.st_size,
            "modified": modified_dt.isoformat(timespec="seconds"),
            "chunks": chunks,
        })

    return jsonify({"ok": True, "docs": docs})

@admin_bp.post("/vector-db/update")
@admin_required
def update_vector_db():
    summary = index_pliegos_dir(pliegos_dir())
    
    chunk_counts = {}
    for pdf_path in sorted(pliegos_dir().glob("*.pdf")):
        name = pdf_path.name
        chunk_counts[name] = qdrant_count_chunks_by_filename(name)
    
    return jsonify({"ok": True, "summary": summary,  "chunk_counts": chunk_counts})

@admin_bp.get("/documents")
@login_required
@admin_required
def documents_page():
    return render_template("admin_upload_pdfs.html")

@admin_bp.get("/documents/list")
@login_required
@admin_required
def documents_list_page():
    """
    Página para ver los documentos PDF cargados y poder borrarlos.
    """
    base = pliegos_dir()
    docs = []
    for p in sorted(base.glob("*.pdf")):
        stat = p.stat()
        docs.append({
            "name": p.name,
            "size_bytes": stat.st_size,
            "modified": datetime.fromtimestamp(stat.st_mtime),
        })

    return render_template("admin_documents.html", docs=docs)


@admin_bp.post("/documents/<path:filename>/delete")
@login_required
@admin_required
def delete_document(filename: str):
    """
    Borra un PDF de la carpeta pliegos y elimina todos sus chunks en Qdrant.
    """
    # Solo permitimos borrar archivos dentro de pliegos_dir
    safe_name = secure_filename(filename)
    if not safe_name:
        return jsonify({"ok": False, "error": "Nombre de archivo inválido"}), 400

    # Ruta real del PDF
    pdf_path = pliegos_dir() / safe_name
    if not pdf_path.exists():
        return jsonify({"ok": False, "error": "El archivo no existe"}), 404

    # Borrar primero de Qdrant (chunks/metadata/embeddings)
    try:
        qdrant_delete_by_filename(safe_name)
    except Exception as e:
        # Si falla no borra el PDF para no dejar estado inconsistente
        current_app.logger.exception("Error borrando en Qdrant: %s", e)
        return jsonify({"ok": False, "error": "No se pudo borrar de la base vectorial"}), 500

    # Borrar del disco
    try:
        pdf_path.unlink()
    except Exception as e:
        current_app.logger.exception("Error borrando el archivo: %s", e)
        return jsonify({"ok": False, "error": "Se borró de la base vectorial pero no del disco"}), 500

    return jsonify({"ok": True, "deleted": safe_name})
