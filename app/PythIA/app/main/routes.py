from flask import render_template, request, redirect, url_for, abort
from flask_login import login_required, current_user
from math import ceil
from . import main_bp
from ..extensions import db
from ..forms import EditUserForm
from ..usuario import User
from app.consulta import Consulta
from app.rag.PrototipoRAG import qdrant_get_payloads

def paginate_consultas(base_query, per_page=10):
    """
    Aplica paginación estándar a una query de consultas.
    Devuelve: consultas, page, total_pages, total_items
    """
    page = request.args.get("page", 1, type=int)
    if page < 1:
        page = 1

    # Si no es admin, filtrar por usuario
    if not getattr(current_user, "is_admin", False):
        base_query = base_query.filter(
            Consulta.user_id == int(current_user.id)
        )

    total_consultas = base_query.count()
    total_pages = max(1, ceil(total_consultas / per_page))

    if page > total_pages:
        page = total_pages

    items = (
        base_query
        .offset((page - 1) * per_page)
        .limit(per_page)
        .all()
    )

    return items, page, total_pages, total_consultas

@main_bp.route("/")
def inicio():
    return render_template(
        "index.html",
        titulo="PythIA",
        autor="Autora: Lydia Blanco Ruiz"
    )

@main_bp.route("/pagina_principal")
@login_required
def pag_principal():
    q = Consulta.query.order_by(Consulta.created_at.desc())
        
    consultas, page, total_pages, total_consultas = paginate_consultas(
        q, per_page=10
    )
    
    meta_by_consulta = build_meta_by_consulta(consultas)

    return render_template(
        "pag_principal.html", 
        user=current_user,  
        consultas=consultas, 
        meta_by_consulta=meta_by_consulta,
        page=page, 
        total_pages=total_pages, 
        total_consultas=total_consultas
    )

@main_bp.route("/edit_user", methods=["GET", "POST"])
@login_required
def edit_user():
    form = EditUserForm(obj=current_user) if request.method == "GET" else EditUserForm()

    
    if form.validate_on_submit():
        
        # === NOMBRE ===
        if form.nombre.data:
            current_user.nombre = form.nombre.data.strip()
            
        # === EMAIL ===
        if form.email.data:
            new_email = form.email.data.strip().lower()
        
            if new_email != current_user.email:
                exists = User.get_by_email(new_email)
                            
                if exists:
                    form.email.errors.append("Ya existe un usuario con ese email.")
                    return render_template("edit_user.html", form=form, user=current_user)

            current_user.email = new_email
        
        # === CONTRASEÑA ===
        if form.new_password.data:
            current_user.set_password(form.new_password.data)

        db.session.commit()
                 
    return render_template("edit_user.html", form=form, user=current_user)

@main_bp.get("/history")
@login_required
def historial():
    q = Consulta.query.order_by(Consulta.created_at.desc())

    consultas, page, total_pages, total_consultas = paginate_consultas(
        q, per_page=10
    )   
    
    meta_by_consulta = build_meta_by_consulta(consultas)
    
    return render_template(
        "history.html", 
        consultas=consultas,
        meta_by_consulta=meta_by_consulta,
        page=page,
        total_pages=total_pages,
        total_consultas=total_consultas
    )
    
def best_pid_for_consulta(consulta) -> str:
    chunks = consulta.consultaChunks or []
    best_cc = min(chunks, key=lambda cc: cc.ranking, default=None)

    if not best_cc:
        return ""

    chunk = getattr(best_cc, "chunk", None)
    return getattr(chunk, "qdrant_point_id", "") or ""
    
def build_meta_by_consulta(consultas):
    
    best_point_ids = {c.id: best_pid_for_consulta(c) for c in consultas}
            
    payload_by_pid = qdrant_get_payloads(pid for pid in best_point_ids.values() if pid) 
    
    meta_by_consulta = {}
    for cid, pid in best_point_ids.items():
        payload = payload_by_pid.get(pid) or {}
        meta_by_consulta[cid] = {
            "qdrant_point_id": pid,
            "metadata": payload.get("metadata") or {},
            "content": payload.get("content", "") or "",
        }
    return meta_by_consulta    

@main_bp.post("/consulta/<int:consulta_id>/delete")
@login_required
def delete_consulta(consulta_id: int):
    consulta = Consulta.query.get_or_404(consulta_id)

    if not current_user.is_admin and consulta.user_id != int(current_user.id):
        abort(403)

    db.session.delete(consulta)
    db.session.commit()

    return redirect(request.referrer or url_for("main.historial"))
