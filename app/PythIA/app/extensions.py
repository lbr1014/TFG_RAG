"""
Autora: Lydia Blanco Ruiz
Script para declarar las extensiones Flask compartidas por la aplicación.
"""

from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager
from flask_migrate import Migrate
from flask_mail import Mail
from flask_wtf import CSRFProtect

db = SQLAlchemy()
login_manager = LoginManager()
migrate = Migrate()
mail = Mail()
csrf = CSRFProtect()
