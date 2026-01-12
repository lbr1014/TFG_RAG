from tests.base import BaseTestCase

class AuthTest(BaseTestCase):

    def test_login_correcto(self):
        self.crear_usuario(email="test@example.com", password="contraseña")

        r = self.client.post(
            "/login",
            data={"email": "test@example.com", "password": "contraseña"},
            follow_redirects=False,
        )

        self.assertIn(r.status_code, (302, 303))
        self.assertTrue(
            r.headers.get("Location"),
            "Login OK debería devolver cabecera Location con redirección",
        )

    def test_login_fallo(self):
        r = self.client.post(
            "/login",
            data={"email": "no@existe.com", "password": "mal"},
            follow_redirects=True,
        )

        self.assertEqual(r.status_code, 200)
