"""
Autora: Lydia Blanco Ruiz
Script para construir apliación Flask de RAG con autenticación, gestión de documentos y consultas.
"""

import os

from dotenv import load_dotenv
from flask import Flask, flash, redirect, request, url_for

from .consulta import Consulta
from .documentos import Documento, DocumentosService
from .error_handling import register_error_handlers
from .extensions import db, login_manager, mail, migrate
from .inetrnacionalizacion.tarduccion import init_app as init_i18n, t
from .markdown_conversion_state import MarkdownConversionState
from .rag_query_state import RAGQueryState
from .usuario import User
from .vector_update_state import VectorUpdateState
from .web_scraping_state import WebScrapingSate


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
    app = Flask(
        __name__,
        template_folder=os.path.join(os.path.dirname(__file__), "..", "templates"),
        static_folder=os.path.join(os.path.dirname(__file__), "..", "static"),
    )

    app.config["SECRET_KEY"] = _get_required_env("SECRET_KEY")
    db_url = _build_database_url_from_env()
    if not db_url:
        raise RuntimeError("DATABASE_URL no está definida y no se pudo construir con POSTGRES_*.")

    if db_url.startswith("postgres://"):
        db_url = db_url.replace("postgres://", "postgresql://", 1)

    app.config["SQLALCHEMY_DATABASE_URI"] = db_url
    app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
    app.config["DOCS_DIR"] = os.environ.get("DOCS_DIR", "pliegos")

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
    init_i18n(app)

    login_manager.init_app(app)
    login_manager.login_view = "auth.login"
    login_manager.login_message = t("auth.login_required")

    @login_manager.unauthorized_handler
    def _unauthorized():
        """Redirige al login cuando una vista requiere autenticación.

        Returns:
            La respuesta de redireccion a la página de login.
        """
        flash(t("auth.login_required"), "warning")
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

    # register blueprints
    from .main.routes import main_bp
    from .auth.routes import auth_bp
    from .admin.routes import admin_bp
    from .rag.routes import rag_bp

    app.register_blueprint(main_bp)
    app.register_blueprint(auth_bp)
    app.register_blueprint(admin_bp)
    app.register_blueprint(rag_bp)
    register_error_handlers(app)

    return app
