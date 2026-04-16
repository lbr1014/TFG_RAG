from unittest.mock import MagicMock, patch

from tests.support import BaseAppTestCase

from app.entities.user import User


class UserUnitTest(BaseAppTestCase):
    def test_user_password_helpers_delegate_to_werkzeug(self):
        user = User(nombre="Persona", email="persona@example.com")

        with patch("app.entities.user.generate_password_hash", return_value="hashed") as mock_generate:
            user.set_password("Segura123")

        mock_generate.assert_called_once_with("Segura123")
        self.assertEqual(user.password_hash, "hashed")

        with patch("app.entities.user.check_password_hash", return_value=True) as mock_check:
            self.assertTrue(user.check_password("Segura123"))

        mock_check.assert_called_once_with("hashed", "Segura123")

    def test_user_lookup_helpers_use_db_and_query(self):
        expected_user = User(id=5, nombre="Persona", email="persona@example.com")

        with patch("app.entities.user.db.session.get", return_value=expected_user) as mock_get:
            self.assertIs(User.get_by_id(5), expected_user)

        mock_get.assert_called_once_with(User, 5)

        query = MagicMock()
        query.filter_by.return_value.first.return_value = expected_user
        with patch.object(User, "query", query):
            self.assertIs(User.get_by_email("persona@example.com"), expected_user)

        query.filter_by.assert_called_once_with(email="persona@example.com")

    def test_user_login_and_admin_state_helpers(self):
        user = self.create_user(email="persona@example.com", is_admin=False, password="Segura123")

        user.update_last_login()
        self.assertIsNotNone(user.last_login)

        user.make_admin()
        self.assertTrue(user.is_admin)
        user.make_user()
        self.assertFalse(user.is_admin)
        user.change_is_admin()
        self.assertTrue(user.is_admin)
