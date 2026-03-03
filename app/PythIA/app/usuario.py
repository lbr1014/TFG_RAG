from flask_login import UserMixin
from werkzeug.security import generate_password_hash, check_password_hash
from datetime import datetime
from zoneinfo import ZoneInfo

from .extensions  import db

class User(db.Model, UserMixin):
    __tablename__ = "users"
     
    id = db.Column(db.Integer, primary_key=True)
    nombre = db.Column(db.String(50), nullable=False)
    email = db.Column(db.String(255), unique=True, nullable=False, index=True)
    password_hash = db.Column(db.String(255), nullable=False)
    last_login = db.Column(db.DateTime(timezone=True), nullable=True)
    is_admin = db.Column(db.Boolean, nullable=False, default=False)

    def set_password(self, password_plain: str):
        self.password_hash = generate_password_hash(password_plain)

    def check_password(self, password_plain: str) -> bool:
        return check_password_hash(self.password_hash, password_plain)

    def update_last_login(self):
        self.last_login = datetime.now(ZoneInfo("Europe/Madrid"))

    @staticmethod
    def get_by_id(user_id: int):
        return db.session.get(User, user_id) 

    @staticmethod
    def get_by_email(email: str):
        return User.query.filter_by(email=email).first()
    
    def make_admin(self):
        self.is_admin = True

    def make_user(self):
        self.is_admin = False

    def change_is_admin(self):
        self.is_admin = not self.is_admin
