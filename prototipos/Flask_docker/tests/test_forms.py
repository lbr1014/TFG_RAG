from werkzeug.datastructures import MultiDict

from tests.__init__ import BaseTestCase
from app.forms import LoginForm, SignupForm, AdminCreateUserForm



class FormsTest(BaseTestCase):
    # Construir el form dentro de un request context POST
    def hacer_form(self, FormClass, data: dict):
        with self.app.test_request_context(
            method="POST",
            data=data,
        ):
            form = FormClass(formdata=MultiDict(data))
            ok = form.validate()
            return ok, form

    # ---------- LoginForm ----------
    def test_form_login_valido(self):
        ok, form = self.hacer_form(
            LoginForm,
            {"email": "test@example.com", "password": "123456"},
        )
        self.assertTrue(ok, f"Errores: {form.errors}")

    def test_form_login_email_invalido(self):
        ok, form = self.hacer_form(
            LoginForm,
            {"email": "no-es-email", "password": "123456"},
        )
        self.assertFalse(ok)
        self.assertIn("email", form.errors)

    def test_form_login_password_corta(self):
        ok, form = self.hacer_form(
            LoginForm,
            {"email": "test@example.com", "password": "123"},
        )
        self.assertFalse(ok)
        self.assertIn("password", form.errors)

    def test_form_login_campos_obligatorios(self):
        ok, form = self.hacer_form(LoginForm, {"email": "", "password": ""})
        self.assertFalse(ok)
        self.assertIn("email", form.errors)
        self.assertIn("password", form.errors)

    # ---------- SignupForm ----------
    def test_form_signup_valido(self):
        ok, form = self.hacer_form(
            SignupForm,
            {
                "nombre": "Lydia",
                "email": "lydia@example.com",
                "password": "123456",
                "confirm_password": "123456",
            },
        )
        self.assertTrue(ok, f"Errores: {form.errors}")

    def test_form_signup_passwords_no_coinciden(self):
        ok, form = self.hacer_form(
            SignupForm,
            {
                "nombre": "Lydia",
                "email": "lydia@example.com",
                "password": "123456",
                "confirm_password": "654321",
            },
        )
        self.assertFalse(ok)
        self.assertIn("confirm_password", form.errors)

    def test_form_signup_nombre_demasiado_corto(self):
        ok, form = self.hacer_form(
            SignupForm,
            {
                "nombre": "A",
                "email": "a@example.com",
                "password": "123456",
                "confirm_password": "123456",
            },
        )
        self.assertFalse(ok)
        self.assertIn("nombre", form.errors)

    def test_form_signup_password_corta(self):
        ok, form = self.hacer_form(
            SignupForm,
            {
                "nombre": "Lydia",
                "email": "lydia@example.com",
                "password": "123",
                "confirm_password": "123",
            },
        )
        self.assertFalse(ok)
        self.assertIn("password", form.errors)

    # ---------- AdminCreateUserForm ----------
    def test_form_admin_crear_usuario_valido(self):
        # Admin
        ok, form = self.hacer_form(
            AdminCreateUserForm,
            {
                "nombre": "Admin User",
                "email": "adminuser@example.com",
                "password": "123456",
                "is_admin": "y",
            },
        )
        self.assertTrue(ok, f"Errores: {form.errors}")
        self.assertTrue(form.is_admin.data)
        
        # Usuario normal
        ok, form = self.hacer_form(
            AdminCreateUserForm,
            {
                "nombre": "Admin User",
                "email": "adminuser@example.com",
                "password": "123456",
            },
        )
        self.assertTrue(ok, f"Errores: {form.errors}")
        self.assertFalse(form.is_admin.data)
        
    def test_form_admin_crear_usuario_email_invalido(self):
        ok, form = self.hacer_form(
            AdminCreateUserForm,
            {
                "nombre": "Admin User",
                "email": "invalido",
                "password": "123456",
            },
        )
        self.assertFalse(ok)
        self.assertIn("email", form.errors)
        
    def test_form_admin_nombre_demasiado_corto(self):
        ok, form = self.hacer_form(
            SignupForm,
            {
                "nombre": "A",
                "email": "a@example.com",
                "password": "123456",
            },
        )
        self.assertFalse(ok)
        self.assertIn("nombre", form.errors)
