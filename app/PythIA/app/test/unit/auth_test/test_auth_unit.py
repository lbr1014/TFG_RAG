"""
Autora: Lydia Blanco Ruiz
Script con pruebas unitarias de la aplicación. Su objetivo es verificar el correcto funcionamiento de los mecanismos de recuperación de contraseñas mediante tokens
y del proceso de registro de usuarios. Las pruebas comprueban tanto el comportamiento esperado en condiciones normales como la correcta gestión de situaciones de error. 
Así como el uso de tokens inválidos o el intento de registrar una cuenta con un correo electrónico ya existente
"""

from unittest.mock import MagicMock, patch

from app.main.code.controllers.auth.routes import (
    generate_reset_token,
    verify_reset_token,
)
from app.test.support import BaseAppTestCase


class AuthRoutesUnitTest(BaseAppTestCase):
    def test_generate_and_verify_reset_token(self):
        """
        Verifica que los tokens de recuperación de contraseña se generan correctamente y permiten recuperar la dirección de correo electrónico asociada.
        """
        with self.app.app_context():
            token = generate_reset_token("user@example.com")

        with self.app.app_context():
            email = verify_reset_token(token)

        self.assertEqual(email, "user@example.com")

    def test_verify_reset_token_returns_none_for_invalid_token(self):
        """
        Comprueba que la validación de un token de recuperación inválido devuelve un resultado nulo, impidiendo su utilización.
        """
        with self.app.app_context():
            email = verify_reset_token("token-invalido")

        self.assertIsNone(email)

    def test_signup_returns_signup_template_and_sets_email_error_when_user_exists(self):
        """
        Verifica que el proceso de registro detecta correctamente cuando el correo electrónico ya está registrado, añade el mensaje de error correspondiente al formulario 
        y vuelve a mostrar la página de registro.
        """
        user = self.create_user(email="exists@example.com")

        fake_form = MagicMock()
        fake_form.validate_on_submit.return_value = True
        fake_form.nombre.data = "Nombre"
        fake_form.email.data = user.email
        fake_form.country_code.data = "ES"
        fake_form.password.data = "Segura123!"
        fake_form.email.errors = []

        with patch("app.main.code.controllers.auth.routes.SignupForm", return_value=fake_form), patch(
            "app.main.code.controllers.auth.routes.User.get_by_email", return_value=user
        ), patch("app.main.code.controllers.auth.routes.t", lambda key, **kwargs: key), patch(
            "app.main.code.controllers.auth.routes.render_template", return_value="ok"
        ) as mock_render, self.app.test_request_context("/signup", method="POST"):
            from app.main.code.controllers.auth import routes as auth_routes

            out = auth_routes.singup()

        self.assertEqual(out, "ok")
        self.assertEqual(fake_form.email.errors, ["auth.email_exists"])
        mock_render.assert_called_once()
