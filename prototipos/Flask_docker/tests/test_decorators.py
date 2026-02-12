from flask import Blueprint

from tests.__init__ import BaseTestCase
from app.decorators import admin_required


class DecoratorsTest(BaseTestCase):
    def setUp(self):
        super().setUp()

        # Ruta protegida por admin_required
        bp = Blueprint("decorators_test", __name__)

        @bp.route("/_test/admin-only")
        @admin_required
        def admin_only():
            return "OK", 200

        # Registrar blueprint solo para estos tests
        self.app.register_blueprint(bp)

    def test_admin_required_no_autenticado(self):
        # Usuario sin autentificar redirije a login
        r = self.client.get("/_test/admin-only", follow_redirects=False)
        self.assertIn(r.status_code, (302, 303))
        self.assertIn("/login", r.headers.get("Location", ""))

    def test_admin_required_no_admin(self):
        # Usuario normal logueado da error
        self.crear_usuario(email="user@example.com", password="contraseña", is_admin=False)
        self.login("user@example.com", follow_redirects=True)

        r = self.client.get("/_test/admin-only", follow_redirects=False)
        self.assertEqual(r.status_code, 403)

    def test_admin_required_admink(self):
        # Admin logueado caso correcto
        self.crear_usuario(email="admin@example.com", password="contraseña", is_admin=True)
        self.login("admin@example.com", follow_redirects=True)

        r = self.client.get("/_test/admin-only", follow_redirects=False)
        self.assertEqual(r.status_code, 200)
        self.assertIn(b"OK", r.data)
