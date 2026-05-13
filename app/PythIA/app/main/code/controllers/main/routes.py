"""
Autora: Lydia Blanco Ruiz
Script para las rutas principales, historial de consultas, perfil de usuario y estadÃ­sticas de uso.
"""

import calendar
import uuid
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone
from math import ceil
from pathlib import Path
from statistics import mean, median, variance

from flask import (
    Response,
    abort,
    current_app,
    flash,
    redirect,
    render_template,
    request,
    send_from_directory,
    session,
    url_for,
)
from flask_login import current_user, login_required, logout_user
from sqlalchemy import func
from werkzeug.utils import secure_filename

from app.main.code.countries import (
    country_name_for_code,
    country_numeric_for_code,
    normalize_country_code,
)
from app.main.code.extensions import db
from app.main.code.forms import EditUserForm, EmptyForm
from app.main.code.inetrnacionalizacion.tarduccion import get_locale, t
from app.main.code.services.rag.PrototipoRAG import qdrant_get_payloads

from ...model.consulta import Consulta
from ...model.rag_query_state import RAGQueryState
from ...model.user import User
from . import main_bp

HISTORY_ENDPOINT = "main.historial"
HISTORY_SORT_DATE_DESC = "date_desc"
HISTORY_SORT_DATE_ASC = "date_asc"
HISTORY_SORT_TIME_DESC = "time_desc"
HISTORY_SORT_TIME_ASC = "time_asc"
PROFILE_UPLOAD_SUBDIR = Path("uploads") / "profiles"
PROFILE_IMAGE_EXTENSIONS = {"jpg", "jpeg", "png", "webp"}


def paginate_consultas(base_query, per_page=10) -> tuple:
    """
    Aplica paginaciÃ³n estÃ¡ndar a una query de consultas.

    Extrae del request.args el nÃºmero de pÃ¡gina y aplica filtrado por usuario
    si el usuario actual no es administrador. Devuelve los elementos paginados
    con informaciÃ³n de pÃ¡ginas.

    Args:
        base_query (Query): Consulta SQLAlchemy base a paginar.
        per_page (int, optional): Elementos por pÃ¡gina. Defaults to 10.

    Returns:
        tuple: Tupla con (items, page, total_pages, total_consultas).
    """
    page = request.args.get("page", 1, type=int)
    page = max(page, 1)

    # Si no es admin, filtrar por usuario
    if not getattr(current_user, "is_admin", False):
        base_query = base_query.filter(
            Consulta.user_id == int(current_user.id)
        )

    total_consultas = base_query.count()
    total_pages = max(1, ceil(total_consultas / per_page))

    page = min(page, total_pages)

    items = (
        base_query
        .offset((page - 1) * per_page)
        .limit(per_page)
        .all()
    )

    return items, page, total_pages, total_consultas


def _history_filters() -> dict[str, str]:
    """
    Lee los filtros activos del historial.
    
    Returns:
        dict: Diccionario con los filtros y el orden aplicados.
    """
    allowed_sort_values = {
        HISTORY_SORT_DATE_DESC,
        HISTORY_SORT_DATE_ASC,
        HISTORY_SORT_TIME_DESC,
        HISTORY_SORT_TIME_ASC,
    }
    sort_value = (request.args.get("sort") or HISTORY_SORT_DATE_DESC).strip()
    if sort_value not in allowed_sort_values:
        sort_value = HISTORY_SORT_DATE_DESC

    return {
        "user_id": (request.args.get("user_id") or "").strip(),
        "date": (request.args.get("date") or "").strip(),
        "model": (request.args.get("model") or "").strip(),
        "device": (request.args.get("device") or "").strip().upper(),
        "sort": sort_value,
    }


def _apply_history_filters(query, filters: dict[str, str]) -> object:
    """
    Aplica filtros de historial sobre la query de consultas.
    
    Args:
        query: Query SQLAlchemy de consultas a filtrar.
        filters: Diccionario con los filtros a aplicar: user_id, date, model y device.
        
    Returns:
        Query: Query SQLAlchemy con los filtros aplicados.
    """
    if current_user.is_admin and filters["user_id"].isdigit():
        query = query.filter(Consulta.user_id == int(filters["user_id"]))

    if filters["date"]:
        try:
            selected_date = date.fromisoformat(filters["date"])
        except ValueError:
            selected_date = None
        if selected_date:
            start = datetime.combine(selected_date, datetime.min.time())
            end = start + timedelta(days=1)
            query = query.filter(Consulta.created_at >= start, Consulta.created_at < end)

    if filters["device"] in {"CPU", "GPU"}:
        query = query.filter(func.upper(Consulta.execution_device) == filters["device"])

    if filters["model"]:
        model_exists = (
            db.session.query(RAGQueryState.id)
            .filter(
                RAGQueryState.user_id == Consulta.user_id,
                RAGQueryState.question == Consulta.pregunta,
                RAGQueryState.status == "done",
                RAGQueryState.model_name == filters["model"],
            )
            .exists()
        )
        query = query.filter(model_exists)

    return query


def _apply_history_sort(query, sort_value: str):
    """
    Aplica el orden activo del historial.
    """
    sort_options = {
        HISTORY_SORT_DATE_ASC: Consulta.created_at.asc(),
        HISTORY_SORT_TIME_DESC: Consulta.tiempo_respuestas.desc(),
        HISTORY_SORT_TIME_ASC: Consulta.tiempo_respuestas.asc(),
    }
    return query.order_by(
        sort_options.get(sort_value, Consulta.created_at.desc())
    )


def _history_filter_options() -> tuple[list, list[str]]:
    """
    Devuelve usuarios y modelos disponibles para los filtros.
    
    Returns:
        tuple: Lista de usuarios (solo para admin) y lista de modelos distintos usados en consultas.
    """
    users = (
        User.query.order_by(User.nombre.asc(), User.email.asc()).all()
        if current_user.is_admin
        else []
    )
    model_query = RAGQueryState.query.filter(RAGQueryState.status == "done")
    if not current_user.is_admin:
        model_query = model_query.filter(RAGQueryState.user_id == int(current_user.id))
    models = [
        item[0]
        for item in (
            model_query.with_entities(RAGQueryState.model_name)
            .filter(RAGQueryState.model_name.isnot(None))
            .distinct()
            .order_by(RAGQueryState.model_name.asc())
            .all()
        )
        if item[0]
    ]
    return users, models


def build_model_by_consulta(consultas: list) -> dict[int, str]:
    """
    Obtiene el modelo asociado a cada consulta visible en la pagina.
    """
    if not consultas:
        return {}

    user_ids = {int(consulta.user_id) for consulta in consultas}
    questions = {consulta.pregunta for consulta in consultas}
    jobs = (
        RAGQueryState.query
        .filter(
            RAGQueryState.status == "done",
            RAGQueryState.user_id.in_(user_ids),
            RAGQueryState.question.in_(questions),
            RAGQueryState.model_name.isnot(None),
        )
        .order_by(RAGQueryState.finished_at.desc(), RAGQueryState.created_at.desc())
        .all()
    )

    model_by_key = {}
    for job in jobs:
        key = (int(job.user_id), job.question)
        if key not in model_by_key and job.model_name:
            model_by_key[key] = job.model_name

    return {
        int(consulta.id): model_by_key.get(
            (int(consulta.user_id), consulta.pregunta),
            "-",
        )
        for consulta in consultas
    }


@main_bp.route("/")
def inicio() -> str:
    """
    Renderiza la pÃ¡gina de inicio de la aplicaciÃ³n PythIA.

    Muestra la pÃ¡gina de inicio con el tÃ­tulo y autor de la aplicaciÃ³n,
    sin requerir autenticaciÃ³n.

    Returns:
        str: HTML renderizado de la pÃ¡gina de inicio.
    """
    return render_template(
        "index.html",
        titulo="PythIA",
        autor=t("app.author")
    )

@main_bp.route("/pagina_principal")
@login_required
def pag_principal() -> str:
    """
    Renderiza la pÃ¡gina principal del usuario autenticado.

    Obtiene las consultas mÃ¡s recientes del usuario (o todas si es admin),
    las pagina y construye metadatos asociados para mostrar en la pÃ¡gina.

    Returns:
        str: HTML renderizado de la pÃ¡gina principal con consultas y metadata.
    """
    consultas_usuario = (
        Consulta.query
        .filter(Consulta.user_id == int(current_user.id))
        .order_by(Consulta.created_at.asc())
        .all()
    )
    dashboard_metrics = build_home_dashboard_metrics(current_user, consultas_usuario)

    return render_template(
        "pag_principal.html", 
        user=current_user,  
        dashboard_metrics=dashboard_metrics,
    )


def build_activity_streak(user: User, consultas: list) -> int:
    """
    Calcula la racha de dÃ­as consecutivos con actividad reciente.
    Usa dÃ­as con consultas y el Ãºltimo inicio de sesiÃ³n del usuario. Si el usuario
    se ha conectado hoy, la racha puede continuar aunque todavÃ­a no haya consultado.
    
    Args:
        user (User): Usuario para el que se calcula la racha.
        consultas (list): Lista de consultas del usuario, ordenadas por fecha ascendente.
        
    Returns:
        int: NÃºmero de dÃ­as consecutivos con actividad, contando desde hoy hacia atrÃ¡s.
    """
    active_days = {_safe_created_at(consulta).date() for consulta in consultas}

    if getattr(user, "last_login", None):
        last_login = user.last_login.replace(tzinfo=None) if user.last_login.tzinfo else user.last_login
        active_days.add(last_login.date())

    if not active_days:
        return 0

    today = datetime.now(timezone.utc).date()
    current_day = today if today in active_days else max(active_days)
    streak = 0

    while current_day in active_days:
        streak += 1
        current_day -= timedelta(days=1)

    return streak


def build_home_dashboard_metrics(user: User, consultas: list) -> dict:
    """
    Construye las mÃ©tricas resumidas que se muestran en la pÃ¡gina principal.
    
    Args:
        user (User): Usuario para el que se construyen las mÃ©tricas.
        consultas (list): Lista de consultas del usuario.
        
    Returns:        
        dict: Diccionario con mÃ©tricas como racha de actividad, total de consultas,
            modelos usados, dÃ­as activos, tiempo promedio de respuesta, fecha de Ãºltima consulta,
            datos para el grÃ¡fico de anillo de consultas y calendario mensual.
    """
    distinct_models = {
        (job.model_name or "").strip()
        for job in RAGQueryState.query.filter(RAGQueryState.user_id == int(user.id)).all()
        if (job.model_name or "").strip()
    }
    response_times = [float(consulta.tiempo_respuestas or 0) for consulta in consultas]
    active_days = {_safe_created_at(consulta).date() for consulta in consultas}
    last_query = max((_safe_created_at(consulta) for consulta in consultas), default=None)
    query_donut = build_home_query_donut(user, len(consultas))
    month_calendar = build_home_month_calendar(consultas)

    avg_response_time = round(sum(response_times) / len(response_times), 2) if response_times else 0

    return {
        "activity_streak": build_activity_streak(user, consultas),
        "total_queries": len(consultas),
        "models_used": len(distinct_models),
        "active_days": len(active_days),
        "avg_response_time": avg_response_time,
        "last_query": last_query.strftime("%d/%m/%Y") if last_query else "-",
        "query_donut_total": query_donut["total"],
        "query_donut_center_total": query_donut["center_total"],
        "query_donut_title": query_donut["title"],
        "query_donut_segments": query_donut["segments"],
        "month_calendar": month_calendar,
    }


def build_home_month_calendar(consultas: list) -> dict:
    """
    Construye el calendario del mes actual para la tarjeta principal.
    
    Args:
        consultas (list): Lista de consultas del usuario, ordenadas por fecha ascendente.
    
    Returns:
        dict: Diccionario con la estructura del calendario mensual, incluyendo el label del mes, los dÃ­as de la semana y 
            las semanas con sus dÃ­as y conteos de consultas.
    """
    today = datetime.now(timezone.utc).date()
    month_start = today.replace(day=1)
    _, days_in_month = calendar.monthrange(today.year, today.month)
    month_days = [
        month_start + timedelta(days=day_offset)
        for day_offset in range(days_in_month)
    ]
    counts_by_day = defaultdict(int)

    for consulta in consultas:
        created_day = _safe_created_at(consulta).date()
        if created_day.year == today.year and created_day.month == today.month:
            counts_by_day[created_day] += 1

    leading_empty_days = month_start.weekday()
    trailing_empty_days = (7 - ((leading_empty_days + days_in_month) % 7)) % 7
    cells = [{"empty": True} for _ in range(leading_empty_days)]
    max_count = max((counts_by_day[day] for day in month_days), default=0)

    for day in month_days:
        count = counts_by_day[day]
        cells.append(
            {
                "empty": False,
                "day": day.day,
                "date": day.isoformat(),
                "count": count,
                "is_today": day == today,
                "intensity": round(count / max_count, 2) if max_count else 0,
            }
        )

    cells.extend({"empty": True} for _ in range(trailing_empty_days))
    weeks = [cells[index:index + 7] for index in range(0, len(cells), 7)]

    month_names = {
        "es": [
            "enero", "febrero", "marzo", "abril", "mayo", "junio",
            "julio", "agosto", "septiembre", "octubre", "noviembre", "diciembre",
        ],
        "en": [
            "January", "February", "March", "April", "May", "June",
            "July", "August", "September", "October", "November", "December",
        ],
    }
    month_name = month_names.get(get_locale(), month_names["es"])[today.month - 1]

    return {
        "label": f"{month_name.capitalize()} {today.year}",
        "weekdays": [
            t("stats.day_0")[:1],
            t("stats.day_1")[:1],
            t("stats.day_2")[:1],
            t("stats.day_3")[:1],
            t("stats.day_4")[:1],
            t("stats.day_5")[:1],
            t("stats.day_6")[:1],
        ],
        "weeks": weeks,
    }


def build_home_query_donut(user: User, user_total_queries: int) -> dict:
    """
    Construye el reparto del anillo de consultas de la pÃ¡gina principal.
    
    Args:
        user (User): Usuario para el que se construye el anillo.
        user_total_queries (int): NÃºmero total de consultas del usuario.
        
    Returns:
        dict: Diccionario con el tÃ­tulo del anillo, el total de consultas, el total central (consultas del usuario) y los segmentos para el grÃ¡fico.
    """
    colors = ["#58d68d", "#5dade2", "#f4d03f", "#ec7063", "#af7ac5", "#48c9b0", "#eb984e", "#7fb3d5"]

    if getattr(user, "is_admin", False):
        counts_by_user = dict(db.session.query(Consulta.user_id, func.count(Consulta.id))
            .group_by(Consulta.user_id)
            .all())
        users = User.query.order_by(User.nombre.asc(), User.email.asc()).all()
        segments = [
            {
                "label": display_name_for_donut(user_item),
                "count": counts_by_user.get(int(user_item.id), 0),
                "color": colors[index % len(colors)],
            }
            for index, user_item in enumerate(users)
            if counts_by_user.get(int(user_item.id), 0)
        ]

        return {
            "title": t("home.donut_admin_title"),
            "total": sum(segment["count"] for segment in segments),
            "center_total": sum(segment["count"] for segment in segments),
            "segments": segments,
        }

    global_total_queries = Consulta.query.count()
    rest_total_queries = max(global_total_queries - user_total_queries, 0)
    segments = []

    if user_total_queries:
        segments.append(
            {
                "label": t("home.donut_user_segment"),
                "count": user_total_queries,
                "color": colors[0],
            }
        )

    if rest_total_queries:
        segments.append(
            {
                "label": t("home.donut_global_segment"),
                "count": rest_total_queries,
                "color": colors[1],
            }
        )

    return {
        "title": t("home.donut_user_title"),
        "total": global_total_queries,
        "center_total": user_total_queries,
        "segments": segments,
    }


def display_name_for_donut(user: User) -> str:
    """
    Devuelve una etiqueta breve para la leyenda del anillo.
    
    Args:
        user (User): Usuario para el que se genera la etiqueta.
        
    Returns:
        str: Nombre para mostrar en el anillo, preferentemente el nombre del usuario, luego su email, o un fallback con su ID.
    """
    return getattr(user, "nombre", None) or getattr(user, "email", None) or f"Usuario {user.id}"


def _profile_initial(user: User) -> str:
    """
    Devuelve la inicial visible para el avatar por defecto.
    
    Args:
        user (User): Usuario para el que se genera la inicial.
    
    Returns:
        str: Inicial para mostrar en el avatar, preferentemente la primera letra del nombre, luego del email, o "U" como fallback.
    """
    source = (getattr(user, "nombre", "") or getattr(user, "email", "") or "U").strip()
    return source[:1].upper() if source else "U"


def _profile_image_url(user: User) -> str | None:
    """
    Construye la URL estatica de la foto de perfil, si existe.
    
    Args:
        user (User): Usuario para el que se genera la URL de la foto de perfil.
        
    Returns:
        str | None: URL de la foto de perfil para usar en el src del img, o None si no hay foto de perfil.
    """
    if not getattr(user, "profile_image", None):
        return None

    filename = Path(user.profile_image).name

    return url_for("main.profile_image", filename=filename)

def _delete_profile_image(filename: str | None) -> None:
    """
    Elimina una foto de perfil guardada dentro de la carpeta data/profiles.
    
    Args:
        filename (str | None): Ruta relativa a la foto de perfil a eliminar.
    """
    if not filename:
        return

    upload_dir = current_app.config["PROFILE_UPLOAD_FOLDER"]
    target = upload_dir / Path(filename).name

    if target.exists():
        target.unlink()

def _save_profile_image(file_storage) -> str | None:
    """
    Guarda la imagen de perfil subida y devuelve su ruta relativa a static.
    
    Args:
        file_storage: Archivo subido desde el formulario, esperado un FileStorage de Werkzeug.
        
    Returns:
        str | None: Ruta relativa a la imagen guardada para almacenar en el perfil, o None si no se guardÃ³ ninguna imagen.
    """
    if not file_storage or not file_storage.filename:
        return None

    filename = secure_filename(file_storage.filename)
    extension = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    if extension not in PROFILE_IMAGE_EXTENSIONS:
        return None

    upload_dir = current_app.config["PROFILE_UPLOAD_FOLDER"]
    upload_dir.mkdir(parents=True, exist_ok=True)
    saved_name = f"user-{current_user.id}-{uuid.uuid4().hex}.{extension}"
    destination = upload_dir / saved_name
    file_storage.save(destination)
    return saved_name


def _render_edit_user(form: EditUserForm) -> str:
    """
    Renderiza la pagina de perfil con el avatar calculado.
    """
    return render_template(
        "edit_user.html",
        form=form,
        user=current_user,
        profile_initial=_profile_initial(current_user),
        profile_image_url=_profile_image_url(current_user),
    )


def _update_profile_name(form: EditUserForm) -> None:
    """
    Actualiza el nombre del usuario si el formulario lo incluye.
    """
    if form.nombre.data:
        current_user.nombre = form.nombre.data.strip()


def _update_profile_email(form: EditUserForm) -> bool:
    """
    Actualiza el email y devuelve False si ya existe en otro usuario.
    """
    if not form.email.data:
        return True

    new_email = form.email.data.strip().lower()
    if new_email != current_user.email and User.get_by_email(new_email):
        form.email.errors.append(t("auth.email_exists"))
        return False

    current_user.email = new_email
    return True


def _update_profile_image(form: EditUserForm) -> None:
    """
    Guarda la nueva foto de perfil si el usuario ha subido una.
    """
    uploaded_profile_image = _save_profile_image(form.profile_image.data)
    if not uploaded_profile_image:
        return

    _delete_profile_image(current_user.profile_image)
    current_user.profile_image = uploaded_profile_image
    
@main_bp.get("/profile_image/<path:filename>")
@login_required
def profile_image(filename: str):
    """
    Sirve imágenes de perfil almacenadas en data/profiles.
    """

    upload_dir = current_app.config["PROFILE_UPLOAD_FOLDER"]

    return send_from_directory(
        str(upload_dir),
        filename,
    )


def _update_profile_password(form: EditUserForm) -> None:
    """
    Actualiza la contraseña solo cuando se ha indicado una nueva.
    """
    if form.new_password.data:
        current_user.set_password(form.new_password.data)


def _apply_edit_user_form(form: EditUserForm) -> bool:
    """
    Aplica los cambios del formulario al usuario actual.
    """
    _update_profile_name(form)
    if not _update_profile_email(form):
        return False

    current_user.country_code = normalize_country_code(form.country_code.data)
    _update_profile_password(form)
    current_user.theme_mode = form.theme_mode.data
    current_user.language = form.language.data
    current_user.preferred_model = form.preferred_model.data
    session["lang"] = form.language.data
        
    _update_profile_image(form)

    db.session.commit()
    return True

@main_bp.get("/edit_user")
@main_bp.post("/edit_user")
@login_required
def edit_user() -> str | Response:
    """
    Gestiona la edición del perfil de usuario.

    En GET: presenta el formulario de edición con los datos actuales del usuario.
    En POST: valida y guarda cambios en nombre, email y contraseña.
    Valida unicidad del email antes de actualizar.

    Returns:
        str | Response: HTML renderizado del formulario de edición de usuario.
    """
    
    if request.method == "GET":
        form = EditUserForm(obj=current_user)
        form.theme_mode.data = current_user.theme_mode
        form.preferred_model.data = current_user.preferred_model
        form.language.data = current_user.language
    else:
        form = EditUserForm()

    if form.validate_on_submit():
        if not _apply_edit_user_form(form):
            return _render_edit_user(form)

        flash(t("user.profile_updated"), "success")
        return redirect(url_for("main.edit_user"))

    return _render_edit_user(form)

@main_bp.post("/edit_user/delete")
@login_required
def delete_own_account() -> Response:
    """
    Elimina la cuenta del usuario autenticado y cierra su sesion.
    """
    form = EmptyForm()
    if not form.validate_on_submit():
        abort(400)

    user = User.get_by_id(current_user.id)
    if not user:
        abort(404)

    profile_image = user.profile_image
    logout_user()
    db.session.delete(user)
    db.session.commit()
    _delete_profile_image(profile_image)
    return redirect(url_for("auth.login"))


@main_bp.get("/history")
@login_required
def historial() -> str:
    """
    Renderiza el historial de consultas del usuario.

    Obtiene todas las consultas del usuario ordenadas por fecha descendente,
    las pagina y construye los metadatos asociados para cada consulta.

    Returns:
        str: HTML renderizado del historial de consultas paginado.
    """
    filters = _history_filters()
    q = _apply_history_sort(
        _apply_history_filters(Consulta.query, filters),
        filters["sort"],
    )

    consultas, page, total_pages, total_consultas = paginate_consultas(
        q, per_page=10
    )   
    
    meta_by_consulta = build_meta_by_consulta(consultas)
    model_by_consulta = build_model_by_consulta(consultas)
    history_users, history_models = _history_filter_options()
    
    return render_template(
        "history.html", 
        consultas=consultas,
        meta_by_consulta=meta_by_consulta,
        model_by_consulta=model_by_consulta,
        page=page,
        total_pages=total_pages,
        total_consultas=total_consultas,
        filters=filters,
        history_users=history_users,
        history_models=history_models,
    )


def _month_sequence(total_months: int = 12) -> list:
    """
    Genera una secuencia de tuplas (aÃ±o, mes) hacia el pasado.

    Comienza desde el primer dÃ­a del mes actual y retrocede el nÃºmero
    de meses especificado, retornando la secuencia en orden ascendente.

    Args:
        total_months (int, optional): NÃºmero de meses a generar. Defaults to 12.

    Returns:
        list: Lista de tuplas (aÃ±o, mes) ordenadas ascendentemente.
    """
    today = datetime.now(timezone.utc).date().replace(day=1)
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
    """
    Obtiene la fecha de creaciÃ³n de una consulta sin informaciÃ³n de zona horaria.

    Si la consulta no tiene fecha de creaciÃ³n, devuelve la fecha/hora actual.
    Elimina la informaciÃ³n de zona horaria (tzinfo) si existe.

    Args:
        consulta (Consulta): Entidad de consulta a procesar.

    Returns:
        datetime: Fecha y hora sin informaciÃ³n de zona horaria.
    """
    created_at = consulta.created_at or datetime.now(timezone.utc)
    return created_at.replace(tzinfo=None) if created_at.tzinfo else created_at


def _process_consulta_stats(
    consulta: Consulta,
    monthly_counts: dict,
    monthly_times: defaultdict,
    daily_counts: dict,
    daily_times: defaultdict,
    daily_hourly_counts: dict,
    weekday_counts: dict,
    hourly_counts: dict,
    user_counter: defaultdict,
) -> None:
    """
    Procesa y actualiza las estadÃ­sticas de una consulta individual.

    Extrae informaciÃ³n de fecha/hora de la consulta y la distribuye en los
    contadores por mes, dÃ­a, dÃ­a de semana, hora y usuario.

    Args:
        consulta (Consulta): Consulta a procesar.
        monthly_counts (dict): Contador de consultas por mes.
        monthly_times (defaultdict): Tiempos de respuesta agrupados por mes.
        daily_counts (dict): Contador de consultas por dÃ­a.
        weekday_counts (dict): Contador de consultas por dÃ­a de semana.
        hourly_counts (dict): Contador de consultas por hora.
        user_counter (defaultdict): Contador de consultas por usuario.

    Returns:
        None: Actualiza los diccionarios.
    """
    created_at = _safe_created_at(consulta)
    month_key = (created_at.year, created_at.month)
    if month_key in monthly_counts:
        monthly_counts[month_key] += 1
        monthly_times[month_key].append(float(consulta.tiempo_respuestas or 0))
    
    day_key = created_at.date().isoformat()
    if day_key in daily_counts:
        daily_counts[day_key] += 1
        daily_times[day_key].append(float(consulta.tiempo_respuestas or 0))
        daily_hourly_counts[day_key][created_at.hour] += 1
    
    weekday_counts[created_at.weekday()] += 1
    hourly_counts[created_at.hour] += 1
    
    user_name = getattr(getattr(consulta, "user", None), "nombre", None)
    if user_name:
        user_counter[user_name] += 1


def build_usage_stats_payload(consultas: list[Consulta], *, include_top_users: bool = False) -> dict:
    """
    Construye un payload completo de estadÃ­sticas de uso de consultas.

    Procesa una lista de consultas para generar estadÃ­sticas agregadas:
    resÃºmenes, consultas mensuales, tiempos promedio, histogramas diarios,
    semanales y horarios. Opcionalmente incluye los 8 usuarios mÃ¡s activos.

    Args:
        consultas (list[Consulta]): Lista de entidades Consulta a procesar.
        include_top_users (bool, optional): Incluir los 8 usuarios mÃ¡s activos. Defaults to False.

    Returns:
        dict: Diccionario con keys: summary, monthly_queries, monthly_avg_time,
              daily_queries, weekday_queries, hourly_queries, top_users (opcional).
    """
    consultas = sorted(consultas, key=lambda item: _safe_created_at(item))
    recent_months = _month_sequence(12)
    monthly_counts = dict.fromkeys(recent_months, 0)
    monthly_times = defaultdict(list)
    daily_counts = {}
    daily_times = defaultdict(list)
    daily_hourly_counts = {}
    weekday_counts = dict.fromkeys(range(7), 0)
    hourly_counts = dict.fromkeys(range(24), 0)
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
        daily_hourly_counts[current_day.isoformat()] = dict.fromkeys(range(24), 0)
        current_day += timedelta(days=1)

    for consulta in consultas:
        _process_consulta_stats(
            consulta,
            monthly_counts,
            monthly_times,
            daily_counts,
            daily_times,
            daily_hourly_counts,
            weekday_counts,
            hourly_counts,
            user_counter,
        )

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
        "daily_avg_time": [
            {
                "date": iso_date,
                "avg_time": round(sum(daily_times[iso_date]) / len(daily_times[iso_date]), 2)
                if daily_times[iso_date]
                else 0,
            }
            for iso_date in daily_counts
        ],
        "daily_hourly_queries": [
            {
                "date": iso_date,
                "hours": [
                    {"hour": hour, "count": count}
                    for hour, count in hourly_values.items()
                ],
            }
            for iso_date, hourly_values in daily_hourly_counts.items()
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
        payload["user_comparison"] = build_user_comparison_payload(user_counter)

    return payload


def build_user_comparison_payload(user_counter: dict[str, int]) -> dict:
    """
    Construye la payload de comparaciÃ³n de usuarios con estadÃ­sticas de uso.
    Calcula la media, mediana y varianza del nÃºmero de consultas por usuario
    y ordena a los usuarios por nÃºmero de consultas para mostrar en la comparaciÃ³n.
    
    Args:
        user_counter (dict): Diccionario con el nÃºmero de consultas por usuario.
    
    Returns:
        dict: Payload con la comparaciÃ³n de usuarios y estadÃ­sticas agregadas.
    """
    counts = [count for count in user_counter.values() if count is not None]
    if not counts:
        return {"data": [], "stats": {"mean": 0, "median": 0, "variance": 0}}

    avg_value = round(mean(counts), 2)
    median_value = round(median(counts), 2)
    variance_value = round(variance(counts), 2) if len(counts) > 1 else 0

    comparison_data = [
        {"user": name, "count": count}
        for name, count in sorted(user_counter.items(), key=lambda item: (-item[1], item[0]))
    ]

    return {
        "data": comparison_data,
        "stats": {
            "mean": avg_value,
            "median": median_value,
            "variance": variance_value,
        },
    }


def build_selected_user_comparison_payload(consultas: list[Consulta], users: list[User], selected_user_ids=None) -> dict:
    """
    Construye la comparacion de usuarios que el administrador quiere ver.
    
    Args:
        consultas (list[Consulta]): Lista de consultas a analizar.
        users (list[User]): Lista de usuarios registrados.
        selected_user_ids (list[int], optional): Lista de IDs de usuarios seleccionados para comparaciÃ³n. Si no se proporciona, se ordenan por nÃºmero de consultas y se seleccionan todos.
    
    Returns:
        dict: Payload con comparaciÃ³n de usuarios seleccionados y sus estadÃ­sticas de uso.
    """
    users_by_id = {int(user.id): user for user in users}
    counts_by_user_id = defaultdict(int)

    for consulta in consultas:
        user_id = getattr(consulta, "user_id", None)
        if user_id is not None:
            counts_by_user_id[int(user_id)] += 1

    selected_ids = [
        user_id for user_id in (selected_user_ids or [])
        if user_id in users_by_id
    ]

    if not selected_ids:
        selected_ids = [
            user_id
            for user_id, _user in sorted(
                users_by_id.items(),
                key=lambda item: (-counts_by_user_id.get(item[0], 0), item[1].nombre, item[1].email),
            )
        ]

    comparison_counter = {
        f"{users_by_id[user_id].nombre} ({users_by_id[user_id].email})": counts_by_user_id.get(user_id, 0)
        for user_id in selected_ids
    }
    payload = build_user_comparison_payload(comparison_counter)
    payload["selected_user_ids"] = selected_ids
    return payload


def build_user_country_map_payload(users: list[User], *, include_user_names: bool = False) -> list:
    """
    Construye los datos del mapa de usuarios por pais.

    Args:
        users (list[User]): Usuarios registrados.
        include_user_names (bool): Incluye nombres solo para administradores.

    Returns:
        list: Datos agregados por pais para colorear el mapa D3.
    """
    countries = {}

    for user in users:
        code = normalize_country_code(getattr(user, "country_code", None))
        if code not in countries:
            countries[code] = {
                "country_code": code,
                "country_id": country_numeric_for_code(code),
                "country_name": country_name_for_code(code, get_locale()),
                "count": 0,
            }
            if include_user_names:
                countries[code]["users"] = []

        countries[code]["count"] += 1
        if include_user_names:
            countries[code]["users"].append(getattr(user, "nombre", ""))

    if include_user_names:
        for item in countries.values():
            item["users"] = sorted(name for name in item["users"] if name)

    return sorted(countries.values(), key=lambda item: item["country_name"])


@main_bp.get("/stats")
@login_required
def stats_page() -> str:
    """
    Renderiza la pÃ¡gina de estadÃ­sticas de uso.

    Si el usuario es administrador, permite seleccionar un usuario especÃ­fico
    o ver estadÃ­sticas globales. Usuarios regulares ven sÃ³lo sus estadÃ­sticas.
    Genera un payload completo de estadÃ­sticas y lo pasa al template.

    Returns:
        str: HTML renderizado de la pÃ¡gina de estadÃ­sticas.
    """
    selected_user = current_user
    selected_user_id = None
    selected_comparison_user_ids = []
    users = []
    is_global_scope = False

    if current_user.is_admin:
        users = User.query.order_by(User.nombre.asc(), User.email.asc()).all()
        selected_user_id = request.args.get("user_id", type=int)
        selected_comparison_user_ids = request.args.getlist("comparison_user_ids", type=int)
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
    if current_user.is_admin and is_global_scope:
        stats_payload["user_comparison"] = build_selected_user_comparison_payload(
            consultas,
            users,
            selected_comparison_user_ids,
        )
    elif not current_user.is_admin:
        stats_payload["user_comparison"] = build_user_comparison_payload(
            {
                f"{t('stats.comparison_current_user', name=current_user.nombre)} ({current_user.email})": len(consultas),
                t("stats.comparison_global"): Consulta.query.count(),
            }
        )

    stats_payload["user_locations"] = build_user_country_map_payload(
        User.query.order_by(User.nombre.asc(), User.email.asc()).all(),
        include_user_names=current_user.is_admin,
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
        selected_comparison_user_ids=stats_payload.get("user_comparison", {}).get("selected_user_ids", []),
    )
    
def best_pid_for_consulta(consulta: Consulta) -> str:
    """
    Obtiene el ID de punto Qdrant del mejor fragmento/chunk de una consulta.

    Intenta primero obtener el ID del fragmento con mejor ranking de la lista
    de fragmentos. Si no hay fragmentos, busca el chunk con mejor ranking
    entre los consultaChunks. Devuelve un string vacÃ­o si no hay ninguno.

    Args:
        consulta (Consulta): Consulta a procesar.

    Returns:
        str: ID de punto Qdrant del mejor fragmento, o string vacÃ­o.
    """
    fragmentos = sorted(consulta.fragmentos or [], key=lambda item: item.get("ranking", 0))
    if fragmentos:
        return (fragmentos[0].get("qdrant_point_id") or "").strip()

    chunks = consulta.consultaChunks or []
    best_cc = min(chunks, key=lambda cc: cc.ranking, default=None)

    if not best_cc:
        return ""

    chunk = getattr(best_cc, "chunk", None)
    return getattr(chunk, "qdrant_point_id", "") or ""
    
def build_meta_by_consulta(consultas: list[Consulta]) -> dict:
    """
    Construye un diccionario de metadatos indexado por ID de consulta.

    Para cada consulta, extrae el fragmento con mejor ranking y obtiene su
    qdrant_point_id, metadata y contenido. Para consultas sin fragmentos,
    recupera la informaciÃ³n desde Qdrant usando el legacy pid.

    Args:
        consultas (list): Lista de entidades Consulta a procesar.

    Returns:
        dict: Diccionario indexado por consulta.id con metadatos
              {qdrant_point_id, metadata, content}.
    """
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
def delete_consulta(consulta_id: int) -> Response:
    """
    Elimina una consulta especÃ­fica del usuario.

    Valida el formulario CSRF y verifica que el usuario actual sea propietario
    de la consulta o administrador. Elimina la consulta de la base de datos y
    redirige al referrer o al historial.

    Args:
        consulta_id (int): ID de la consulta a eliminar.

    Returns:
        Response: RedirecciÃ³n al referrer o al historial.
    """
    form = EmptyForm()
    if not form.validate_on_submit():
        abort(400)

    consulta = Consulta.query.get_or_404(consulta_id)

    if not current_user.is_admin and consulta.user_id != int(current_user.id):
        abort(403)

    db.session.delete(consulta)
    db.session.commit()

    return redirect(request.referrer or url_for(HISTORY_ENDPOINT))


@main_bp.post("/history/delete")
@login_required
def bulk_delete_consultas() -> Response:
    """
    Elimina varias consultas seleccionadas desde el historial.
    """
    form = EmptyForm()
    if not form.validate_on_submit():
        abort(400)

    selected_ids = request.form.getlist("selected_consulta_ids", type=int)
    if not selected_ids:
        return redirect(request.referrer or url_for(HISTORY_ENDPOINT))

    query = Consulta.query.filter(Consulta.id.in_(selected_ids))
    if not current_user.is_admin:
        query = query.filter(Consulta.user_id == int(current_user.id))

    consultas = query.all()
    if len(consultas) != len(set(selected_ids)):
        abort(403)

    for consulta in consultas:
        db.session.delete(consulta)
    db.session.commit()

    return redirect(request.referrer or url_for(HISTORY_ENDPOINT))
