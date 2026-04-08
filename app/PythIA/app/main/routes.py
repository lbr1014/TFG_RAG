from collections import defaultdict
from datetime import date, datetime, timedelta

from flask import render_template, request, redirect, url_for, abort
from flask_login import login_required, current_user
from math import ceil
from . import main_bp
from ..extensions import db
from ..forms import EditUserForm
from ..usuario import User
from app.consulta import Consulta
from app.rag.PrototipoRAG import qdrant_get_payloads
from ..inetrnacionalizacion.tarduccion import t

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
        autor=t("app.author")
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
                    form.email.errors.append(t("auth.email_exists"))
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


def _month_sequence(total_months: int = 12):
    today = datetime.now().date().replace(day=1)
    months = []
    year = today.year
    month = today.month

    for _ in range(total_months):
        months.append((year, month))
        month -= 1
        if month == 0:
            month = 12
            year -= 1

    months.reverse()
    return months


def _safe_created_at(consulta: Consulta) -> datetime:
    created_at = consulta.created_at or datetime.now()
    return created_at.replace(tzinfo=None) if created_at.tzinfo else created_at


def build_usage_stats_payload(consultas, *, include_top_users: bool = False):
    consultas = sorted(consultas, key=lambda item: _safe_created_at(item))
    recent_months = _month_sequence(12)
    monthly_counts = {month: 0 for month in recent_months}
    monthly_times = defaultdict(list)
    daily_counts = {}
    weekday_counts = {day: 0 for day in range(7)}
    hourly_counts = {hour: 0 for hour in range(24)}
    user_counter = defaultdict(int)

    start_year, start_month = recent_months[0]
    end_year, end_month = recent_months[-1]
    calendar_start = date(start_year, start_month, 1)
    if end_month == 12:
        calendar_end = date(end_year + 1, 1, 1) - timedelta(days=1)
    else:
        calendar_end = date(end_year, end_month + 1, 1) - timedelta(days=1)

    current_day = calendar_start
    while current_day <= calendar_end:
        daily_counts[current_day.isoformat()] = 0
        current_day += timedelta(days=1)

    for consulta in consultas:
        created_at = _safe_created_at(consulta)
        month_key = (created_at.year, created_at.month)
        if month_key in monthly_counts:
            monthly_counts[month_key] += 1
            monthly_times[month_key].append(float(consulta.tiempo_respuestas or 0))
        day_key = created_at.date().isoformat()
        if day_key in daily_counts:
            daily_counts[day_key] += 1
        weekday_counts[created_at.weekday()] += 1
        hourly_counts[created_at.hour] += 1
        user_name = getattr(getattr(consulta, "user", None), "nombre", None)
        if user_name:
            user_counter[user_name] += 1

    monthly_queries = [
        {
            "month": f"{year:04d}-{month:02d}-01",
            "count": monthly_counts[(year, month)],
        }
        for year, month in recent_months
    ]
    monthly_avg_time = [
        {
            "month": f"{year:04d}-{month:02d}-01",
            "avg_time": round(sum(values) / len(values), 2) if values else 0,
        }
        for (year, month), values in (
            ((year, month), monthly_times.get((year, month), []))
            for year, month in recent_months
        )
    ]

    summary = {
        "total_queries": len(consultas),
        "avg_response_time": round(
            sum(float(consulta.tiempo_respuestas or 0) for consulta in consultas) / len(consultas),
            2,
        ) if consultas else 0,
        "active_days": len({_safe_created_at(consulta).date().isoformat() for consulta in consultas}),
        "first_query_at": consultas[0].created_at.isoformat() if consultas else None,
        "last_query_at": consultas[-1].created_at.isoformat() if consultas else None,
    }

    payload = {
        "summary": summary,
        "monthly_queries": monthly_queries,
        "monthly_avg_time": monthly_avg_time,
        "daily_queries": [
            {"date": iso_date, "count": count}
            for iso_date, count in daily_counts.items()
        ],
        "weekday_queries": [
            {"weekday": weekday, "count": count}
            for weekday, count in weekday_counts.items()
        ],
        "hourly_queries": [
            {"hour": hour, "count": count}
            for hour, count in hourly_counts.items()
        ],
    }

    if include_top_users:
        payload["top_users"] = [
            {"user": name, "count": count}
            for name, count in sorted(user_counter.items(), key=lambda item: (-item[1], item[0]))[:8]
        ]

    return payload


@main_bp.get("/stats")
@login_required
def stats_page():
    selected_user = current_user
    selected_user_id = None
    users = []
    is_global_scope = False

    if current_user.is_admin:
        users = User.query.order_by(User.nombre.asc(), User.email.asc()).all()
        selected_user_id = request.args.get("user_id", type=int)
        if selected_user_id:
            selected_user = User.get_by_id(selected_user_id)
            if not selected_user:
                abort(404)
        else:
            selected_user = None
            is_global_scope = True

    base_query = Consulta.query.order_by(Consulta.created_at.asc())
    if selected_user is not None:
        base_query = base_query.filter(Consulta.user_id == int(selected_user.id))

    consultas = base_query.all()
    stats_payload = build_usage_stats_payload(
        consultas,
        include_top_users=current_user.is_admin and is_global_scope,
    )

    scope_title = (
        t("stats.scope_global")
        if is_global_scope
        else t("stats.scope_user", name=selected_user.nombre)
    )

    return render_template(
        "stats.html",
        stats_payload=stats_payload,
        stats_scope_title=scope_title,
        is_global_scope=is_global_scope,
        users=users,
        selected_user=selected_user,
        selected_user_id=selected_user_id,
    )
    
def best_pid_for_consulta(consulta) -> str:
    fragmentos = sorted(consulta.fragmentos or [], key=lambda item: item.get("ranking", 0))
    if fragmentos:
        return (fragmentos[0].get("qdrant_point_id") or "").strip()

    chunks = consulta.consultaChunks or []
    best_cc = min(chunks, key=lambda cc: cc.ranking, default=None)

    if not best_cc:
        return ""

    chunk = getattr(best_cc, "chunk", None)
    return getattr(chunk, "qdrant_point_id", "") or ""
    
def build_meta_by_consulta(consultas):
    meta_by_consulta = {}
    legacy_pids = {}

    for consulta in consultas:
        fragmentos = sorted(consulta.fragmentos or [], key=lambda item: item.get("ranking", 0))
        if fragmentos:
            best = fragmentos[0]
            meta_by_consulta[consulta.id] = {
                "qdrant_point_id": (best.get("qdrant_point_id") or "").strip(),
                "metadata": best.get("metadata") or {},
                "content": best.get("chunk", "") or "",
            }
            continue

        legacy_pids[consulta.id] = best_pid_for_consulta(consulta)

    if legacy_pids:
        payload_by_pid = qdrant_get_payloads(pid for pid in legacy_pids.values() if pid)
        for cid, pid in legacy_pids.items():
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
