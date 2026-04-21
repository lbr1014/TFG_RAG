"""
Autora: Lydia Blanco Ruiz
Script con pruebas de integracion de decoradores de autorizacion.
"""

from tests.support import BaseAppTestCase

from app.decorators import admin_required


class DecoratorsIntegrationTest(BaseAppTestCase):
    def setUp(self):
        super().setUp()

        @self.app.get("/test-decorators/admin-only")
        @admin_required
        def admin_only_route():
            return "admin ok"

    def test_admin_required_redirects_anonymous_user_to_login(self):
        response = self.client.get("/test-decorators/admin-only", follow_redirects=False)

        self.assertEqual(response.status_code, 302)
        self.assertIn("/login", response.headers["Location"])

    def test_admin_required_aborts_for_authenticated_non_admin_user(self):
        user = self.create_user(email="normal@example.com", is_admin=False)
        self.login(user.email)

        response = self.client.get(
            "/test-decorators/admin-only",
            headers={"Accept": "application/json"},
        )

        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.get_json()["status"], 403)

    def test_admin_required_allows_authenticated_admin_user(self):
        admin = self.create_user(email="admin-decorator@example.com", is_admin=True)
        self.login(admin.email)

        response = self.client.get("/test-decorators/admin-only")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data, b"admin ok")
