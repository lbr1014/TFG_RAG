from tests.base import BaseTestCase

class MainRoutesTest(BaseTestCase):

    def test_pag_principal_correcto(self):
        r = self.client.get("/")
        self.assertEqual(r.status_code, 200)

    def test_pag_login_correcto(self):
        r = self.client.get("/login")
        self.assertEqual(r.status_code, 200)
