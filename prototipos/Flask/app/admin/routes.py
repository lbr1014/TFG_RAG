from flask import render_template, redirect, url_for, abort, request, jsonify, current_app
from flask_login import login_required, current_user
from pathlib import Path
from werkzeug.utils import secure_filename

from . import admin_bp
from ..decorators import admin_required
from ..usuario import User
from ..forms import AdminCreateUserForm
from ..extensions import db
from ..rag.PrototipoRAG import index_pliegos_dir

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

    saved = []
    for f in files:
        name = secure_filename(f.filename or "")
        if not name:
            continue
        if Path(name).suffix.lower() not in ALLOWED_EXT:
            continue
        dest = pliegos_dir() / name
        f.save(dest)
        saved.append(name)

    return jsonify({"ok": True, "saved": saved})

@admin_bp.post("/vector-db/update")
@admin_required
def update_vector_db():
    summary = index_pliegos_dir(pliegos_dir())
    return jsonify({"ok": True, "summary": summary})

@admin_bp.get("/documents")
@login_required
@admin_required
def documents_page():
    return render_template("admin_upload_pdfs.html")
