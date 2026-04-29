"""
Autora: Lydia Blanco Ruiz
Script con pruebas de integración de las rutas de la aplicación.
"""

from unittest.mock import patch

from app.test.support import BaseAppTestCase

from app.main.code.controllers.auth.routes import generate_reset_token
from app.main.code.extensions import db
from app.main.code.model.user import User

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

    def test_signup_get_renders_form_and_duplicate_email_stays_on_form(self):
        existing = self.create_user(email="duplicado@example.com")

        get_response = self.client.get("/signup")
        duplicate_response = self.client.post(
            "/signup",
            data={
                "nombre": "Duplicado",
                "email": existing.email,
                "password": "Segura123",
                "confirm_password": "Segura123",
            },
        )

        self.assertEqual(get_response.status_code, 200)
        self.assertEqual(duplicate_response.status_code, 200)
        self.assertEqual(User.query.filter_by(email=existing.email).count(), 1)

    def test_login_updates_last_login(self):
        user = self.create_user(email="login@example.com")

        response = self.login("login@example.com", follow_redirects=False)

        self.assertEqual(response.status_code, 302)
        db.session.refresh(user)
        self.assertIsNotNone(user.last_login)

    def test_login_get_and_invalid_credentials_render_form(self):
        self.create_user(email="login-invalid@example.com", password="Segura123")

        get_response = self.client.get("/login")
        invalid_response = self.client.post(
            "/login",
            data={"email": "login-invalid@example.com", "password": "Incorrecta123"},
        )

        self.assertEqual(get_response.status_code, 200)
        self.assertEqual(invalid_response.status_code, 200)

    def test_logout_valid_form_logs_user_out(self):
        user = self.create_user(email="logout@example.com")
        self.login(user.email)

        response = self.client.post("/logout", follow_redirects=False)

        self.assertEqual(response.status_code, 302)
        self.assertIn("/", response.headers["Location"])

    def test_logout_invalid_form_redirects_to_main_page(self):
        user = self.create_user(email="logout-invalid@example.com")
        self.login(user.email)

        with patch("app.main.code.controllers.auth.routes.EmptyForm") as mock_form:
            mock_form.return_value.validate_on_submit.return_value = False
            response = self.client.post("/logout", follow_redirects=False)

        self.assertEqual(response.status_code, 302)
        self.assertIn("/pagina_principal", response.headers["Location"])

    @patch("app.main.code.controllers.auth.routes.mail.send")
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

    @patch("app.main.code.controllers.auth.routes.mail.send")
    def test_forgot_password_get_and_unknown_email_do_not_send_email(self, mock_send):
        get_response = self.client.get("/forgot-password")
        unknown_response = self.client.post(
            "/forgot-password",
            data={"email": "unknown@example.com"},
            follow_redirects=False,
        )

        self.assertEqual(get_response.status_code, 200)
        self.assertEqual(unknown_response.status_code, 302)
        self.assertIn("/login", unknown_response.headers["Location"])
        mock_send.assert_not_called()

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

    def test_reset_password_get_renders_form_for_valid_token(self):
        user = self.create_user(email="recover-get@example.com")
        with self.app.app_context():
            token = generate_reset_token(user.email)

        response = self.client.get(f"/reset-password/{token}")

        self.assertEqual(response.status_code, 200)

    def test_reset_password_redirects_for_invalid_token(self):
        response = self.client.get("/reset-password/token-invalido", follow_redirects=False)

        self.assertEqual(response.status_code, 302)
        self.assertIn("/forgot-password", response.headers["Location"])

    def test_reset_password_redirects_when_token_user_no_longer_exists(self):
        with self.app.app_context():
            token = generate_reset_token("missing-user@example.com")

        response = self.client.get(f"/reset-password/{token}", follow_redirects=False)

        self.assertEqual(response.status_code, 302)
        self.assertIn("/forgot-password", response.headers["Location"])
