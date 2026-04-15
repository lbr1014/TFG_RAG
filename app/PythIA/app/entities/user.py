"""
Autora: Lydia Blanco Ruiz
Script con la entidad SQLAlchemy que representa usuarios registrados y sus permisos.
"""

from datetime import datetime
from zoneinfo import ZoneInfo

from flask_login import UserMixin
from werkzeug.security import check_password_hash, generate_password_hash

from app.extensions import db


class User(db.Model, UserMixin):
    """Usuario registrado en la aplicación.

    Attributes:
        id: Identificador interno del usuario.
        nombre: Nombre visible del usuario.
        email: Correo electrónico único usado para iniciar sesión.
        password_hash: Contraseña cifrada.
        last_login: Fecha y hora del último inicio de sesión.
        is_admin: Indica si el usuario tiene permisos de administración.
    """

    __tablename__ = "users"

    id = db.Column(db.Integer, primary_key=True)
    nombre = db.Column(db.String(50), nullable=False)
    email = db.Column(db.String(255), unique=True, nullable=False, index=True)
    password_hash = db.Column(db.String(255), nullable=False)
    last_login = db.Column(db.DateTime(timezone=True), nullable=True)
    is_admin = db.Column(db.Boolean, nullable=False, default=False)

    def set_password(self, password_plain: str):
        """Guarda la contraseña cifrada del usuario.

        Args:
            password_plain: Contraseña en texto plano introducida por el
                usuario.
        """
        self.password_hash = generate_password_hash(password_plain)

    def check_password(self, password_plain: str) -> bool:
        """Comprueba si una contraseña coincide con el hash guardado.

        Args:
            password_plain: Contraseña en texto plano que se quiere comprobar.

        Returns:
            ``True`` si la contraseña es correcta.
        """
        return check_password_hash(self.password_hash, password_plain)

    def update_last_login(self):
        """Actualiza la fecha del último inicio de sesión."""
        self.last_login = datetime.now(ZoneInfo("Europe/Madrid"))

    @staticmethod
    def get_by_id(user_id: int):
        """Busca un usuario por identificador.

        Args:
            user_id: Identificador del usuario.

        Returns:
            El usuario encontrado o ``None``.
        """
        return db.session.get(User, user_id)

    @staticmethod
    def get_by_email(email: str):
        """Busca un usuario por correo electrónico.

        Args:
            email: Correo electrónico del usuario.

        Returns:
            El usuario encontrado o ``None``.
        """
        return User.query.filter_by(email=email).first()

    def make_admin(self):
        """Concede permisos de administración al usuario."""
        self.is_admin = True

    def make_user(self):
        """Retira permisos de administración al usuario."""
        self.is_admin = False

    def change_is_admin(self):
        """Alterna el rol de administración del usuario."""
        self.is_admin = not self.is_admin
