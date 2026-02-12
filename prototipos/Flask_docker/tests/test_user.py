from datetime import datetime
from zoneinfo import ZoneInfo

from tests.__init__ import BaseTestCase
from app.extensions import db
from app.usuario import User


class UsuarioModelTest(BaseTestCase):

    def test_contraseñ(self):
        u = self.crear_usuario(password="mi_contraseña")

        # Debe validar la contraseña correcta
        self.assertTrue(u.check_password("mi_contraseña"))

        # Debe fallar con una contraseña incorrecta
        self.assertFalse(u.check_password("otra_contraseña"))

        # El hash no debería ser el texto plano
        self.assertNotEqual(u.password_hash, "mi_contraseña")

    def test_update_last_login(self):
        u = self.crear_usuario()

        self.assertIsNone(u.last_login)

        u.update_last_login()
        db.session.commit()

        u_db = User.get_by_id(u.id)
        self.assertIsNotNone(u_db.last_login)

        # Comprobar que sea reciente
        now = datetime.now(ZoneInfo("Europe/Madrid")).replace(tzinfo=None)
        delta_seconds = abs((now - u_db.last_login).total_seconds())
        self.assertLess(delta_seconds, 10)

    def test_get_by_id(self):
        u = self.crear_usuario(email="idtest@example.com")

        u_db = User.get_by_id(u.id)
        self.assertIsNotNone(u_db)
        self.assertEqual(u_db.id, u.id)
        self.assertEqual(u_db.email, "idtest@example.com")
        
        u_db = User.get_by_id(999999)
        self.assertIsNone(u_db)        

    def test_get_by_email(self):
        u = self.crear_usuario(email="emailtest@example.com")

        u_db = User.get_by_email("emailtest@example.com")
        self.assertIsNotNone(u_db)
        self.assertEqual(u_db.id, u.id)
        
        u_db = User.get_by_email("noexiste@example.com")
        self.assertIsNone(u_db)       

    def test_change_type(self):
        u = self.crear_usuario(is_admin=False)
        self.assertFalse(u.is_admin)

        u.make_admin()
        db.session.commit()
        u_db = User.get_by_id(u.id)
        self.assertTrue(u_db.is_admin)

        u_db.make_user()
        db.session.commit()
        u_db2 = User.get_by_id(u.id)
        self.assertFalse(u_db2.is_admin)

    def test_change_is_admin(self):
        u = self.crear_usuario(is_admin=False)

        u.change_is_admin()
        db.session.commit()
        u_db = User.get_by_id(u.id)
        self.assertTrue(u_db.is_admin)

        u_db.change_is_admin()
        db.session.commit()
        u_db2 = User.get_by_id(u.id)
        self.assertFalse(u_db2.is_admin)
