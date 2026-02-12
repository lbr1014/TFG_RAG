from tests.__init__ import BaseTestCase
from app.extensions import db
from app.usuario import User

class MainRoutesTest(BaseTestCase):

    def test_pag_principal_correcto(self):
        r = self.client.get("/")
        self.assertEqual(r.status_code, 200)

    def test_pag_login_correcto(self):
        r = self.client.get("/login")
        self.assertEqual(r.status_code, 200)

    def test_edit_user_actualiza_nombre_y_email(self):
        u = self.crear_usuario()
        self.login()

        r = self.client.post(
            "/edit_user",
            data={
                "nombre": "Nuevo Nombre",
                "email": "nuevonombre@example.com",
                "submit": "Guardar cambios",
            },
            follow_redirects=True
        )
        self.assertEqual(r.status_code, 200)

        db.session.refresh(u)
        self.assertEqual(u.nombre, "Nuevo Nombre")
        self.assertEqual(u.email, "nuevonombre@example.com")
        
    def test_edit_user_no_borra_campos_vacios(self):
        u = self.crear_usuario(nombre="Nombre Original", email="original@example.com")
        self.login(email="original@example.com")

        r = self.client.post(
            "/edit_user",
            data={
                "nombre": "",         
                "email": "",         
                "new_password": "",
            },
            follow_redirects=True
        )
        self.assertEqual(r.status_code, 200)

        db.session.refresh(u)
        self.assertEqual(u.nombre, "Nombre Original")
        self.assertEqual(u.email, "original@example.com")
        
    def test_edit_user_cambia_password(self):
        u = self.crear_usuario(password="oldpass")
        self.login(password="oldpass")

        r = self.client.post(
            "/edit_user",
            data={
                "nombre": "Test",               
                "email": "test@example.com",    
                "new_password": "newpass123",
            },
            follow_redirects=True
        )
        self.assertEqual(r.status_code, 200)

        db.session.refresh(u)
        self.assertTrue(u.check_password("newpass123"))
        
    def test_edit_user_email_duplicado(self):
        u1 = self.crear_usuario(nombre="U1", email="u1@example.com", password="123456")
        self.crear_usuario(nombre="U2", email="u2@example.com", password="123456")

        # login como u1 e intenta poner el email de u2
        self.login(email="u1@example.com", password="123456", follow_redirects=True)

        r = self.client.post(
            "/edit_user",
            data={
                "nombre": "U1",
                "email": "u2@example.com", 
                "new_password": "",
                "submit": "Guardar cambios",
            },
            follow_redirects=True
        )
        self.assertEqual(r.status_code, 200)

        db.session.refresh(u1)
        self.assertEqual(u1.email, "u1@example.com")  
        
        self.assertIn(b"Ya existe un usuario con ese email.", r.data)
        
    def test_edit_user_precarga_datos(self):
        self.crear_usuario(nombre="Alexia", email="alexia@gmail.com", password="123456")
        self.login(email="alexia@gmail.com", password="123456", follow_redirects=True)

        r = self.client.get("/edit_user")
        self.assertEqual(r.status_code, 200)

        self.assertIn(b'value="Alexia"', r.data)
        self.assertIn(b'value="alexia@gmail.com"', r.data)


