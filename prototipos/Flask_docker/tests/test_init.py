from tests.__init__ import BaseTestCase
from app.extensions import login_manager

class InitTest(BaseTestCase):

    def test_login_user_loader_carga_usuario(self):
        u = self.crear_usuario(email="loader@example.com", password="contraseña")

        cb = login_manager._user_callback
        self.assertIsNotNone(cb)

        u_loaded = cb(str(u.id))  
        self.assertIsNotNone(u_loaded)
        self.assertEqual(u_loaded.id, u.id)

        self.assertIsNone(cb("99999999"))
