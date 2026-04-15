"""
Autora: Lydia Blanco Ruiz
Script con pruebas de integración de las rutas de la aplicación.
"""

from unittest.mock import patch

from tests.support import BaseAppTestCase

from app.auth.routes import generate_reset_token
from app.extensions import db
from app.entities.user import User


class AuthRoutesIntegrationTest(BaseAppTestCase):
    def test_signup_creates_user_and_logs_him_in(self):
        response = self.client.post(
            "/signup",
            data={
                "nombre": "Nuevo",
                "email": "nuevo@example.com",
                "password": "Segura123",
                "confirm_password": "Segura123",
            },
            follow_redirects=False,
        )

        self.assertEqual(response.status_code, 302)
        self.assertIn("/pagina_principal", response.headers["Location"])
        self.assertIsNotNone(User.get_by_email("nuevo@example.com"))

    def test_login_updates_last_login(self):
        user = self.create_user(email="login@example.com")

        response = self.login("login@example.com", follow_redirects=False)

        self.assertEqual(response.status_code, 302)
        db.session.refresh(user)
        self.assertIsNotNone(user.last_login)

    @patch("app.auth.routes.mail.send")
    def test_forgot_password_sends_email_when_user_exists(self, mock_send):
        self.create_user(email="reset@example.com")

        response = self.client.post(
            "/forgot-password",
            data={"email": "reset@example.com"},
            follow_redirects=False,
        )

        self.assertEqual(response.status_code, 302)
        self.assertIn("/login", response.headers["Location"])
        mock_send.assert_called_once()

    def test_reset_password_updates_password(self):
        user = self.create_user(email="recover@example.com")
        with self.app.app_context():
            token = generate_reset_token(user.email)

        response = self.client.post(
            f"/reset-password/{token}",
            data={"password": "Nueva123", "confirm_password": "Nueva123"},
            follow_redirects=False,
        )

        self.assertEqual(response.status_code, 302)
        db.session.refresh(user)
        self.assertTrue(user.check_password("Nueva123"))
