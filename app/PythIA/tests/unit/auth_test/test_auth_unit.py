"""
Autora: Lydia Blanco Ruiz
Script con pruebas unitarias de la aplicación.
"""

from tests.support import BaseAppTestCase

from app.auth.routes import generate_reset_token, verify_reset_token


class AuthRoutesUnitTest(BaseAppTestCase):
    def test_generate_and_verify_reset_token(self):
        with self.app.app_context():
            token = generate_reset_token("user@example.com")

        with self.app.app_context():
            email = verify_reset_token(token)

        self.assertEqual(email, "user@example.com")

    def test_verify_reset_token_returns_none_for_invalid_token(self):
        with self.app.app_context():
            email = verify_reset_token("token-invalido")

        self.assertIsNone(email)
