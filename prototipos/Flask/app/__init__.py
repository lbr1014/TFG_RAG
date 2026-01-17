from flask import Flask
import os

from .extensions import db, login_manager, migrate
from .usuario import User
from .consulta import Consulta
from .auth import auth_bp

def create_app():
    app = Flask(
        __name__,
        template_folder=os.path.join(os.path.dirname(__file__), "..", "templates"),
        static_folder=os.path.join(os.path.dirname(__file__), "..", "static"),
    )

    app.config["SECRET_KEY"] = "una_clave_cualquiera_118732hfshdfiuhwy!!$%"
    basedir = os.path.abspath(os.path.dirname(__file__))
    app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite:///" + os.path.join(basedir, "..", "app.db")
    app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False

    # init extensions
    db.init_app(app)
    migrate.init_app(app, db)

    login_manager.init_app(app)
    login_manager.login_view = "auth.login"
    login_manager.login_message = "Debes iniciar sesión para acceder a esta página."

    @login_manager.user_loader
    def load_user(user_id: str):
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

    return app
