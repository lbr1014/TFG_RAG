from flask_login import UserMixin
from werkzeug.security import generate_password_hash, check_password_hash
from datetime import datetime
from zoneinfo import ZoneInfo

class User(UserMixin):
    def __init__(self, user_id: str, nombre: str, email: str, password_hash: str):
        self.id = user_id                 
        self.nombre = nombre
        self.email = email
        self.password_hash = password_hash
        self.last_login = None

    @classmethod
    def create(cls, user_id: str, nombre: str, email: str, password_plain: str):
        user= cls(
            user_id=user_id,
            nombre=nombre,
            email=email,
            password_hash=generate_password_hash(password_plain)
        )
        user.last_login = datetime.now(ZoneInfo("Europe/Madrid"))
        return user

    def check_password(self, password_plain: str) -> bool:
        return check_password_hash(self.password_hash, password_plain)

    def update_last_login(self):
        self.last_login = datetime.now(ZoneInfo("Europe/Madrid"))