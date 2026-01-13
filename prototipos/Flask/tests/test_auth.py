from tests.base import BaseTestCase
from app.usuario import User
from app.extensions import db

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
        
    def test_login_contraseña_incorrecta(self):
        # usuario existe pero password mal
        self.crear_usuario(email="test@example.com", password="contraseña")

        r = self.client.post(
            "/login",
            data={
                "email": "test@example.com", 
                "password": "contraseñaErronea", 
                "submit": "Iniciar sesión",
            },
            follow_redirects=True
        )
        self.assertEqual(r.status_code, 200)
        self.assertIn(b"Email o contrase\xc3\xb1a incorrectos.", r.data)

    def test_logout(self):
        self.crear_usuario(email="test@example.com", password="contraseña")
        self.login(email="test@example.com", password="contraseña", follow_redirects=True)

        r = self.client.get("/logout", follow_redirects=False)
        self.assertIn(r.status_code, (302, 303))
        self.assertIn("/", r.headers.get("Location", "")) 

    def test_signup(self):
        r = self.client.get("/singup")
        self.assertEqual(r.status_code, 200)
        self.assertTrue(len(r.data) > 0)

    def test_signup_correcto(self):
        r = self.client.post(
            "/singup",
            data={
                "nombre": "Alexia",
                "email": "alexia@example.com",
                "password": "123456",
                "confirm_password": "123456",
                "submit": "Registrarse",
            },
            follow_redirects=False
        )
        self.assertIn(r.status_code, (302, 303))
        self.assertIn("/pagina_principal", r.headers.get("Location", ""))

        u = User.get_by_email("alexia@example.com")
        self.assertIsNotNone(u)
        self.assertEqual(u.nombre, "Alexia")
        self.assertTrue(u.check_password("123456"))
        self.assertIsNotNone(u.last_login)
        
        # Borrar usuario
        user_id = u.id
        db.session.delete(u)
        db.session.commit()

        self.assertIsNone(User.get_by_id(user_id))

    def test_signup_email_duplicado(self):
        self.crear_usuario(email="dup@example.com", password="contraseña")

        r = self.client.post(
            "/singup",
            data={
                "nombre": "Otro",
                "email": "dup@example.com",
                "password": "123456",
                "confirm_password": "123456",
                "submit": "Registrarse",
            },
            follow_redirects=True
        )
        self.assertEqual(r.status_code, 200)
        self.assertIn(b"Ya existe un usuario con ese email.", r.data)

        # asegura que no creó otro usuario extra con ese email
        users = User.query.filter_by(email="dup@example.com").all()
        self.assertEqual(len(users), 1)
