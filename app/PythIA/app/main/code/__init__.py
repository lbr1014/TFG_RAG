"""
Autora: Lydia Blanco Ruiz
Script para crear y configurar la aplicación Flask principal, incluyendo extensiones, configuración, blueprints y manejadores globales.
"""

import os
from pathlib import Path

from dotenv import load_dotenv
from flask import Flask, flash, jsonify, redirect, request, url_for

from app.main.code.extensions import csrf, db, login_manager, mail, migrate
from app.main.code.model import (
    Consulta as Consulta,
)
from app.main.code.model import (
    Documento as Documento,
)
from app.main.code.model import (
    MarkdownConversionState as MarkdownConversionState,
)
from app.main.code.model import (
    RAGQueryState as RAGQueryState,
)
from app.main.code.model import (
    User,
)
from app.main.code.model import (
    VectorUpdateState as VectorUpdateState,
)
from app.main.code.model import (
    WebScrapingSate as WebScrapingSate,
)
from app.main.code.services.documentos import DocumentosService as DocumentosService

from .error_handling import register_error_handlers, wants_json_response
from .inetrnacionalizacion.tarduccion import init_app as init_i18n
from .inetrnacionalizacion.tarduccion import t

AUTH_LOGIN_REQUIRED = "auth.login_required"


def _is_test_env() -> bool:
    """
    Detecta si estamos ejecutando tests (pytest/unittest/CI) para relajar
    requisitos de configuración y usar defaults seguros.
    """
    return (
        os.environ.get("PYTHIA_TESTING") == "1"
        or os.environ.get("TESTING") == "1"
        or "PYTEST_CURRENT_TEST" in os.environ
        or os.environ.get("GITHUB_ACTIONS") == "true"
    )


def _get_required_env(var_name: str) -> str:
    """
    Devuelve una variable de entorno obligatoria.

    Args:
        var_name: Nombre de la variable de entorno que debe existir.

    Returns:
        El valor configurado para la variable de entorno.
    """
    value = os.environ.get(var_name)
    if value:
        return value
    if _is_test_env():
        return "test-secret"
    raise RuntimeError(f"{var_name} no está definida. Revisa tu .env o variables de entorno.")


def _flask_session_config_name() -> str:
    """
    Devuelve el nombre de configuración que Flask usa para firmar sesiones.
    
    Returns:
        El nombre de la clave de configuración para la firma de sesiones en Flask.
    """
    return "SECRET_KEY"


def _build_database_url_from_env() -> str | None:
    """
    Obtiene la URL de base de datos desde el entorno.
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


def _configure_max_content_length(app: Flask) -> None:
    """
    Configura la longitud máxima del contenido para la aplicación Flask.

    Args:
        app (Flask): La aplicación Flask a configurar.
    """
    max_len_raw = os.environ.get("MAX_CONTENT_LENGTH")
    default_len = 250 * 1024 * 1024
    if max_len_raw is None:
        max_len = default_len
    else:
        try:
            max_len = int(max_len_raw)
        except ValueError:
            max_len = default_len
    app.config["MAX_CONTENT_LENGTH"] = None if max_len <= 0 else max_len


def _configure_data_dirs(app: Flask, *, project_root: Path) -> None:
    """
    Configura los directorios de datos para la aplicación Flask.

    Args:
        app (Flask): La aplicación Flask a configurar.
        project_root (Path): La ruta raíz del proyecto.
    """
    data_dir = Path(os.environ.get("DATA_DIR") or (project_root / "data"))
    app.config["DATA_DIR"] = data_dir

    docs_dir_env = os.environ.get("DOCS_DIR")
    docs_dir = Path(docs_dir_env) if docs_dir_env else (data_dir / "pliegos")
    if not docs_dir.is_absolute():
        docs_dir = data_dir / docs_dir
    app.config["DOCS_DIR"] = docs_dir

    # Fotos de perfil: siempre dentro de DATA_DIR (no se permite override a rutas externas).
    app.config["PROFILE_UPLOAD_FOLDER"] = data_dir / "profiles"


def create_app():
    """
    Crea y configura la instancia principal de Flask.

    Returns:
        La aplicacion Flask ya configurada con extensiones, blueprints y
        manejadores globales.
    """
    project_root = Path(__file__).resolve().parents[3]

    load_dotenv(project_root / ".env", override=True)
    load_dotenv(project_root / "secret.env", override=True)
    
    main_dir = os.path.dirname(os.path.dirname(__file__))
    app = Flask(
        __name__,
        template_folder=os.path.join(main_dir, "resources", "templates"),
        static_folder=os.path.join(main_dir, "resources", "static"),
    )

    app.config[_flask_session_config_name()] = _get_required_env("FLASK_SESSION_SIGNER")
    db_url = _build_database_url_from_env()
    if not db_url:
        if _is_test_env():
            db_url = "sqlite:///:memory:"
        else:
            raise RuntimeError("DATABASE_URL no está definida y no se pudo construir con POSTGRES_*.")

    if db_url.startswith("postgres://"):
        db_url = db_url.replace("postgres://", "postgresql://", 1)

    app.config["SQLALCHEMY_DATABASE_URI"] = db_url
    app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False

    _configure_max_content_length(app)
    _configure_data_dirs(app, project_root=project_root)

    try:
        profile_dir = Path(app.config["PROFILE_UPLOAD_FOLDER"])
        profile_dir.mkdir(parents=True, exist_ok=True)
        if os.name != "nt":
            try:
                profile_dir.chmod(0o775)
            except OSError:
                pass
        write_test = profile_dir / ".write_test.tmp"
        try:
            write_test.write_text("ok", encoding="utf-8")
        finally:
            try:
                write_test.unlink(missing_ok=True)
            except OSError:
                pass
    except OSError as e:
        raise RuntimeError(
            f"No hay permisos de escritura en '{app.config['PROFILE_UPLOAD_FOLDER']}'. "
            "Asegura que el usuario del proceso puede escribir dentro de data/."
        ) from e

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
        """
        Redirige al login cuando una vista requiere autenticación.

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
    def _inject_post_forms() -> dict:
        """
        Expone formularios CSRF para acciones POST simples en plantillas.
        También expone una función para obtener el nombre de un país a partir de su código,
        utilizando la configuración de localización actual.
        
        Returns:
            Un diccionario con formularios y funciones para usar en las plantillas.
        """
        from .countries import country_name_for_code
        from .forms import EmptyForm, LanguageForm
        from .inetrnacionalizacion.tarduccion import get_locale

        return {
            "country_name_for_code": lambda code: country_name_for_code(code, get_locale()),
            "post_form": EmptyForm(),
            "logout_form": EmptyForm(),
            "language_form": LanguageForm(),
        }

    # register blueprints
    from .controllers.admin import admin_bp
    from .controllers.auth import auth_bp
    from .controllers.main import main_bp
    from .controllers.rag import rag_bp

    app.register_blueprint(main_bp)
    app.register_blueprint(auth_bp)
    app.register_blueprint(admin_bp)
    app.register_blueprint(rag_bp)
    register_error_handlers(app)

    return app
