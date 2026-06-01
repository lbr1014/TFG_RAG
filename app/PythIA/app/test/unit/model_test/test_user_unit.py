"""
Script con pruebas unitarias del modelo User, encargado de representar a los usuarios de la aplicación. 
Las pruebas verifican la gestión segura de contraseñas, los métodos de búsqueda de usuarios y las funcionalidades relacionadas con la administración de permisos y sesiones.
"""

import secrets
from unittest.mock import MagicMock, patch

from app.main.code.model.user import User
from app.test.support import BaseAppTestCase


class UserUnitTest(BaseAppTestCase):
    def test_user_password_helpers_delegate_to_werkzeug(self):
        """
        Verifica que la generación y comprobación de contraseñas delegan correctamente en las utilidades de seguridad de Werkzeug.
        """
        user = User(nombre="Persona", email="persona@example.com")

        self.assertEqual(user.country_code, "ES")

        raw_password = secrets.token_urlsafe(16)

        with patch("app.main.code.model.user.generate_password_hash", return_value="hashed") as mock_generate:
            user.set_password(raw_password)

        mock_generate.assert_called_once_with(raw_password)
        self.assertEqual(user.password_hash, "hashed")

        with patch("app.main.code.model.user.check_password_hash", return_value=True) as mock_check:
            self.assertTrue(user.check_password(raw_password))

        mock_check.assert_called_once_with("hashed", raw_password)

    def test_user_lookup_helpers_use_db_and_query(self):
        """
        Comprueba que los métodos de búsqueda de usuarios utilizan correctamente la base de datos para recuperar registros.
        """
        expected_user = User(id=5, nombre="Persona", email="persona@example.com")

        with patch("app.main.code.model.user.db.session.get", return_value=expected_user) as mock_get:
            self.assertIs(User.get_by_id(5), expected_user)

        mock_get.assert_called_once_with(User, 5)

        query = MagicMock()
        query.filter_by.return_value.first.return_value = expected_user
        with patch.object(User, "query", query):
            self.assertIs(User.get_by_email("persona@example.com"), expected_user)

        query.filter_by.assert_called_once_with(email="persona@example.com")

    def test_user_login_and_admin_state_helpers(self):
        """
        Verifica la actualización de información de inicio de sesión y la gestión de privilegios administrativos de los usuarios.
        """
        user = self.create_user(email="persona@example.com", is_admin=False, password=secrets.token_urlsafe(16))

        user.update_last_login()
        self.assertIsNotNone(user.last_login)

        user.make_admin()
        self.assertTrue(user.is_admin)
        user.make_user()
        self.assertFalse(user.is_admin)
        user.change_is_admin()
        self.assertTrue(user.is_admin)


