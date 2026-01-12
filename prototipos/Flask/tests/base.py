import unittest

from app import create_app
from app.extensions import db
from app.usuario import User

class BaseTestCase(unittest.TestCase):
    def setUp(self):
        self.app = create_app()
        self.app.config.update(
            TESTING=True,
            WTF_CSRF_ENABLED=False,
            SQLALCHEMY_DATABASE_URI="sqlite:///:memory:",
            SQLALCHEMY_TRACK_MODIFICATIONS=False,
        )

        self.client = self.app.test_client()

        self.ctx = self.app.app_context()
        self.ctx.push()

        db.create_all()

    def tearDown(self):
        db.session.remove()
        db.drop_all()
        self.ctx.pop()

    def crear_usuario(self, nombre="Test", email="test@example.com", password="contraseña", is_admin=False):
        u = User(nombre=nombre, email=email.lower().strip(), is_admin=is_admin)
        u.set_password(password)
        db.session.add(u)
        db.session.commit()
        return u
