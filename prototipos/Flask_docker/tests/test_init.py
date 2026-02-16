import os
import unittest
from tests.__init__ import BaseTestCase
from app.extensions import login_manager
from unittest.mock import patch
from app import create_app

class InitIncorrectoest(unittest.TestCase):
    
    def test_missing_secret_key(self):
        with patch("app.load_dotenv", return_value=False):
            with patch.dict(os.environ, {}, clear=True):
                with self.assertRaisesRegex(RuntimeError, r"SECRET_KEY no está definida"):
                    create_app()

    def test_missing_database(self):
        with patch("app.load_dotenv", return_value=False):
            with patch.dict(os.environ, {"SECRET_KEY": "test-secret"}, clear=True):
                with self.assertRaisesRegex(RuntimeError, r"DATABASE_URL no está definida"):
                    create_app()

    def test_rewrite_postgres(self):
         with patch("app.load_dotenv", return_value=False):
            env = {
                "SECRET_KEY": "test-secret",
                "DATABASE_URL": "postgres://user:pass@localhost:5432/dbname",
            }
            with patch.dict(os.environ, env, clear=True):
                app = create_app()
                self.assertTrue(app.config["SQLALCHEMY_DATABASE_URI"].startswith("postgresql://"))



class InitTest(BaseTestCase):

    def test_login_user_loader_carga_usuario(self):
        u = self.crear_usuario(email="loader@example.com", password="contraseña")

        cb = login_manager._user_callback
        self.assertIsNotNone(cb)

        u_loaded = cb(str(u.id))  
        self.assertIsNotNone(u_loaded)
        self.assertEqual(u_loaded.id, u.id)

        self.assertIsNone(cb("99999999"))
