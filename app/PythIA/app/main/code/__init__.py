"""
Autora: Lydia Blanco Ruiz
Script para crear y configurar la aplicación Flask principal, incluyendo extensiones, configuración, blueprints y manejadores globales.
"""

import os

from dotenv import load_dotenv
from flask import Flask, flash, jsonify, redirect, request, url_for

from app.main.code.services.documentos import DocumentosService
from .error_handling import register_error_handlers, wants_json_response
from app.main.code.model import Consulta, Documento, MarkdownConversionState, RAGQueryState, User, VectorUpdateState, WebScrapingSate
from app.main.code.extensions import csrf, db, login_manager, mail, migrate
from .inetrnacionalizacion.tarduccion import init_app as init_i18n, t


AUTH_LOGIN_REQUIRED = "auth.login_required"


def _get_required_env(var_name: str) -> str:
    """Devuelve una variable de entorno obligatoria.

    Args:
        var_name: Nombre de la variable de entorno que debe existir.

    Returns:
        El valor configurado para la variable de entorno.
    """
    value = os.environ.get(var_name)
    if value:
        return value
    raise RuntimeError(f"{var_name} no está definida. Revisa tu .env o variables de entorno.")


def _flask_session_config_name() -> str:
    """Devuelve el nombre de configuración que Flask usa para firmar sesiones."""
    return "_".join(("SECRET", "KEY"))


def _build_database_url_from_env() -> str | None:
    """Obtiene la URL de base de datos desde el entorno.

    Primero intenta usar ``DATABASE_URL``. Si no existe, construye la URL a
    partir de las variables ``POSTGRES_*``.

    Returns:
        La URL de conexion a la base de datos o ``None`` si faltan datos para
        construirla.
    """
    db_url = os.environ.get("DATABASE_URL")
    if db_url:
        return db_url

    user = os.environ.get("POSTGRES_USER")
    password = os.environ.get("POSTGRES_PASSWORD")
    database = os.environ.get("POSTGRES_DB")
    host = os.environ.get("POSTGRES_HOST", "db")
    port = os.environ.get("POSTGRES_PORT", "5432")

    if not user or not password or not database:
        return None

    return f"postgresql+psycopg2://{user}:{password}@{host}:{port}/{database}"


def create_app():
    """Crea y configura la instancia principal de Flask.

    Returns:
        La aplicacion Flask ya configurada con extensiones, blueprints y
        manejadores globales.
    """
    load_dotenv("secret.env")
    main_dir = os.path.dirname(os.path.dirname(__file__))
    app = Flask(
        __name__,
        template_folder=os.path.join(main_dir, "resources", "templates"),
        static_folder=os.path.join(main_dir, "resources", "static"),
    )

    app.config[_flask_session_config_name()] = _get_required_env("FLASK_SESSION_SIGNER")
    db_url = _build_database_url_from_env()
    if not db_url:
        raise RuntimeError("DATABASE_URL no está definida y no se pudo construir con POSTGRES_*.")

    if db_url.startswith("postgres://"):
        db_url = db_url.replace("postgres://", "postgresql://", 1)

    app.config["SQLALCHEMY_DATABASE_URI"] = db_url
    app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
    app.config["DOCS_DIR"] = os.environ.get("DOCS_DIR", "pliegos")
    app.config["MAX_CONTENT_LENGTH"] = int(os.environ.get("MAX_CONTENT_LENGTH", str(50 * 1024 * 1024)))

    # Flask Mail
    app.config["MAIL_SERVER"] = os.environ.get("MAIL_SERVER", "")
    app.config["MAIL_PORT"] = int(os.environ.get("MAIL_PORT", "587"))
    app.config["MAIL_USE_TLS"] = os.environ.get("MAIL_USE_TLS", "1") == "1"
    app.config["MAIL_USE_SSL"] = os.environ.get("MAIL_USE_SSL", "0") == "1"
    app.config["MAIL_USERNAME"] = os.environ.get("MAIL_USERNAME", "")
    app.config["MAIL_PASSWORD"] = os.environ.get("MAIL_PASSWORD", "")
    app.config["MAIL_DEFAULT_SENDER"] = os.environ.get("MAIL_DEFAULT_SENDER", app.config["MAIL_USERNAME"])

    # init extensions
    db.init_app(app)
    migrate.init_app(app, db)
    mail.init_app(app)
    csrf.init_app(app)
    init_i18n(app)

    login_manager.init_app(app)
    login_manager.login_view = "auth.login"
    login_manager.login_message = t(AUTH_LOGIN_REQUIRED)

    @login_manager.unauthorized_handler
    def _unauthorized():
        """Redirige al login cuando una vista requiere autenticación.

        Returns:
            La respuesta de redireccion a la página de login.
        """
        if wants_json_response():
            return jsonify({"error": t(AUTH_LOGIN_REQUIRED), "status": 401}), 401

        flash(t(AUTH_LOGIN_REQUIRED), "warning")
        return redirect(url_for("auth.login", next=request.path))

    @login_manager.user_loader
    def load_user(user_id: str):
        """Carga un usuario para Flask-Login desde su identificador.

        Args:
            user_id: Identificador del usuario autenticado en formato texto.

        Returns:
            La instancia del usuario asociada al identificador.
        """
        return User.get_by_id(int(user_id))

    @app.context_processor
    def _inject_post_forms():
        """Expone formularios CSRF para acciones POST simples en plantillas."""
        from .countries import country_name_for_code
        from .forms import EmptyForm, LanguageForm

        return {
            "country_name_for_code": country_name_for_code,
            "post_form": EmptyForm(),
            "logout_form": EmptyForm(),
            "language_form": LanguageForm(),
        }

    # register blueprints
    from .controllers.main import main_bp
    from .controllers.auth import auth_bp
    from .controllers.admin import admin_bp
    from .controllers.rag import rag_bp

    app.register_blueprint(main_bp)
    app.register_blueprint(auth_bp)
    app.register_blueprint(admin_bp)
    app.register_blueprint(rag_bp)
    register_error_handlers(app)

    return app
