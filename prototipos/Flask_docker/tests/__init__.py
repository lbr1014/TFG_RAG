import os
import unittest
import sqlite3
from sqlalchemy import event
from sqlalchemy.engine import Engine

from app import create_app
from app.extensions import db
from app.usuario import User

@event.listens_for(Engine, "connect")
def _set_sqlite_pragma(dbapi_connection, connection_record):
    if isinstance(dbapi_connection, sqlite3.Connection):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

class BaseTestCase(unittest.TestCase):
    def setUp(self):
        self.app = create_app()
        
        # Base de datos para los test a parte de la de la aplicación
        basedir = os.path.abspath(os.path.dirname(__file__))
        self.test_db_path = os.path.join(basedir, "test.db")
        self.test_db_uri = "sqlite:///" + self.test_db_path
        
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
        
        # Los ids de los usuarios creados para las pruebas
        self._created_user_ids = []

    def tearDown(self):
        
        # Borra los usuarios creados por el test
        if self._created_user_ids:
            User.query.filter(User.id.in_(self._created_user_ids)).delete(synchronize_session=False)
            db.session.commit()

        db.session.remove()
        #db.drop_all()
        self.ctx.pop()

    def crear_usuario(self, nombre="Test", email="test@example.com", password="contraseña", is_admin=False):
        u = User(nombre=nombre, email=email.lower().strip(), is_admin=is_admin)
        u.set_password(password)
        db.session.add(u)
        db.session.commit()
        self._created_user_ids.append(u.id)
        return u
    
    def login(self, email="test@example.com", password="contraseña", follow_redirects=False):
        return self.client.post(
            "/login",
            data={"email": email, "password": password},
            follow_redirects=follow_redirects,
        )
