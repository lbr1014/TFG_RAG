"""
Autora: Lydia Blanco Ruiz
Script con pruebas de integración de las rutas de autentificación de la aplicación.
Su objetivo es verificar el correcto funcionamiento de los procesos de registro de usuarios, inicio y 
cierre de sesión, recuperación de contraseñas y restablecimiento de credenciales mediante tokens seguros. 
Las pruebas validan tanto los flujos de éxito como distintos escenarios de error, incluyendo correos 
electrónicos duplicados, credenciales incorrectas, usuarios inexistentes y tokens inválidos.
"""

import secrets
from unittest.mock import patch

from app.main.code.controllers.auth.routes import generate_reset_token
from app.main.code.extensions import db
from app.main.code.model.user import User
from app.test.support import BaseAppTestCase

DEFAULT_PASSWORD = secrets.token_urlsafe(16)
INCORRECT_PASSWORD = secrets.token_urlsafe(16)
NEW_PASSWORD = secrets.token_urlsafe(16)


class AuthRoutesIntegrationTest(BaseAppTestCase):
    def test_signup_creates_user_and_logs_him_in(self):
        """
        Verifica que el proceso de registro crea correctamente un nuevo usuario y lo autentica automáticamente tras completar el alta.
        """
        response = self.client.post(
            "/signup",
            data={
                "nombre": "Nuevo",
                "email": "lydiablanco71@gmail.com",
                "password": DEFAULT_PASSWORD,
                "confirm_password": DEFAULT_PASSWORD,
            },
            follow_redirects=False,
        )

        self.assertEqual(response.status_code, 302)
        self.assertIn("/pagina_principal", response.headers["Location"])
        self.assertIsNotNone(User.get_by_email("lydiablanco71@gmail.com"))

    def test_signup_get_renders_form_and_duplicate_email_stays_on_form(self):
        """
        Comprueba la visualización del formulario de registro y la validación de correos electrónicos ya existentes en la base de datos.
        """
        existing = self.create_user(email="duplicado@example.com")

        get_response = self.client.get("/signup")
        duplicate_response = self.client.post(
            "/signup",
            data={
                "nombre": "Duplicado",
                "email": existing.email,
                "password": DEFAULT_PASSWORD,
                "confirm_password": DEFAULT_PASSWORD,
            },
        )

        self.assertEqual(get_response.status_code, 200)
        self.assertEqual(duplicate_response.status_code, 200)
        self.assertEqual(User.query.filter_by(email=existing.email).count(), 1)

    def test_login_updates_last_login(self):
        """
        Verifica que el inicio de sesión actualiza correctamente la fecha y hora del último acceso del usuario.
        """
        user = self.create_user(email="login@example.com")

        response = self.login("login@example.com", follow_redirects=False)

        self.assertEqual(response.status_code, 302)
        db.session.refresh(user)
        self.assertIsNotNone(user.last_login)

    def test_login_get_and_invalid_credentials_render_form(self):
        """
        Comprueba la carga del formulario de acceso y el comportamiento del sistema cuando se proporcionan credenciales incorrectas.
        """
        self.create_user(email="login-invalid@example.com", password=DEFAULT_PASSWORD)

        get_response = self.client.get("/login")
        invalid_response = self.client.post(
            "/login",
            data={"email": "login-invalid@example.com", "password": INCORRECT_PASSWORD},
        )

        self.assertEqual(get_response.status_code, 200)
        self.assertEqual(invalid_response.status_code, 200)

    def test_logout_valid_form_logs_user_out(self):
        """
        Verifica que el cierre de sesión invalida correctamente la sesión activa y redirige al usuario a la página correspondiente.
        """
        user = self.create_user(email="logout@example.com")
        self.login(user.email)

        response = self.client.post("/logout", follow_redirects=False)

        self.assertEqual(response.status_code, 302)
        self.assertIn("/", response.headers["Location"])

    def test_logout_invalid_form_redirects_to_main_page(self):
        """
        Comprueba el comportamiento del sistema cuando el formulario de cierre de sesión no supera las validaciones requeridas.
        """
        user = self.create_user(email="logout-invalid@example.com")
        self.login(user.email)

        with patch("app.main.code.controllers.auth.routes.EmptyForm") as mock_form:
            mock_form.return_value.validate_on_submit.return_value = False
            response = self.client.post("/logout", follow_redirects=False)

        self.assertEqual(response.status_code, 302)
        self.assertIn("/pagina_principal", response.headers["Location"])

    @patch("app.main.code.controllers.auth.routes.mail.send")
    def test_forgot_password_sends_email_when_user_exists(self, mock_send):
        """
        Verifica que se envía correctamente un correo electrónico de recuperación cuando la dirección indicada pertenece a un usuario registrado.
        """
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
        """
        Comprueba la visualización del formulario de recuperación y que no se envían correos cuando el usuario solicitado no existe.
        """
        get_response = self.client.get("/forgot-password")
        unknown_response = self.client.post(
            "/forgot-password",
            data={"email": "unknown@example.com"},
            follow_redirects=False,
        )

        self.assertEqual(get_response.status_code, 200)
        self.assertEqual(unknown_response.status_code, 200)
        mock_send.assert_not_called()

    def test_reset_password_updates_password(self):
        """
        Verifica que el restablecimiento de contraseña actualiza correctamente las credenciales del usuario cuando se utiliza un token válido.
        """
        user = self.create_user(email="recover@example.com")
        with self.app.app_context():
            token = generate_reset_token(user.email)

        response = self.client.post(
            f"/reset-password/{token}",
            data={"password": NEW_PASSWORD, "confirm_password": NEW_PASSWORD},
            follow_redirects=False,
        )

        self.assertEqual(response.status_code, 302)
        db.session.refresh(user)
        self.assertTrue(user.check_password(NEW_PASSWORD))

    def test_reset_password_get_renders_form_for_valid_token(self):
        """
        Comprueba que se muestra correctamente el formulario de restablecimiento cuando se accede mediante un token de recuperación válido.
        """
        user = self.create_user(email="recover-get@example.com")
        with self.app.app_context():
            token = generate_reset_token(user.email)

        response = self.client.get(f"/reset-password/{token}")

        self.assertEqual(response.status_code, 200)

    def test_reset_password_redirects_for_invalid_token(self):
        """
        Verifica que los tokens inválidos provocan la redirección al flujo de recuperación de contraseña.
        """
        response = self.client.get("/reset-password/token-invalido", follow_redirects=False)

        self.assertEqual(response.status_code, 302)
        self.assertIn("/forgot-password", response.headers["Location"])

    def test_reset_password_redirects_when_token_user_no_longer_exists(self):
        """
        Comprueba que el sistema rechaza correctamente los tokens asociados a usuarios inexistentes o eliminados.
        """
        with self.app.app_context():
            token = generate_reset_token("missing-user@example.com")

        response = self.client.get(f"/reset-password/{token}", follow_redirects=False)

        self.assertEqual(response.status_code, 302)
        self.assertIn("/forgot-password", response.headers["Location"])
