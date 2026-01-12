from tests.base import BaseTestCase

class AdminTest(BaseTestCase):

    def login(self, email, password="contraseña", follow_redirects=True):
        return self.client.post(
            "/login",
            data={"email": email, "password": password},
            follow_redirects=follow_redirects,
        )

    def test_admin_necesita_admin(self):
        self.crear_usuario(email="user@example.com", password="contraseña", is_admin=False)

        self.login("user@example.com", follow_redirects=True)

        r = self.client.get("/admin/users", follow_redirects=False)

        self.assertIn(r.status_code, (302, 303, 403))

    def test_admin_pag_correcta_para_admin(self):
        self.crear_usuario(email="admin@example.com", password="contraseña", is_admin=True)

        self.login("admin@example.com", follow_redirects=True)

        r = self.client.get("/admin/users")
        self.assertEqual(r.status_code, 200)
