"""
Autora: Lydia Blanco Ruiz
Script con pruebas unitarias de formularios.
"""

from types import SimpleNamespace

from wtforms.validators import ValidationError

from tests.support import BaseAppTestCase

from app.forms import (
    AdminCreateUserForm,
    EditUserForm,
    EmptyForm,
    ForgotPasswordForm,
    LanguageForm,
    LoginForm,
    PdfUploadForm,
    RAGQueryForm,
    ResetPasswordForm,
    SignupForm,
)
from app.inetrnacionalizacion.tarduccion import t


class FormTestMixin:
    def _form(self, form_class, data=None):
        with self.app.test_request_context("/", method="POST", data=data or {}):
            return form_class()

    def assertFormValid(self, form_class, data=None):
        with self.app.test_request_context("/", method="POST", data=data or {}):
            form = form_class()
            self.assertTrue(form.validate(), form.errors)
            return form

    def assertFormInvalid(self, form_class, data=None, field=None):
        with self.app.test_request_context("/", method="POST", data=data or {}):
            form = form_class()
            self.assertFalse(form.validate())
            if field:
                self.assertIn(field, form.errors)
            return form


class EmptyFormUnitTest(FormTestMixin, BaseAppTestCase):
    def test_empty_form_validates_without_fields(self):
        form = self.assertFormValid(EmptyForm)

        own_fields = [field for field in form if field.type != "CSRFTokenField"]
        self.assertEqual(own_fields, [])


class LanguageFormUnitTest(FormTestMixin, BaseAppTestCase):
    def test_language_form_requires_lang_and_accepts_next_url(self):
        self.assertFormInvalid(LanguageForm, {"next": "/rag"}, "lang")

        form = self.assertFormValid(LanguageForm, {"lang": "en", "next": "/rag"})
        self.assertEqual(form.lang.data, "en")
        self.assertEqual(form.next.data, "/rag")


class PdfUploadFormUnitTest(FormTestMixin, BaseAppTestCase):
    def test_pdf_upload_form_localizes_labels(self):
        form = self._form(PdfUploadForm)

        self.assertEqual(form.files.label.text, t("docs.upload_label"))
        self.assertEqual(form.submit.label.text, t("docs.upload_button"))

    def test_validate_files_requires_at_least_one_file(self):
        field = SimpleNamespace(data=[])

        with self.assertRaises(ValidationError) as raised:
            PdfUploadForm.validate_files(None, field)

        self.assertEqual(str(raised.exception), t("docs.upload_pdf_required"))

    def test_validate_files_rejects_non_pdf_files(self):
        field = SimpleNamespace(data=[SimpleNamespace(filename="notas.txt")])

        with self.assertRaises(ValidationError) as raised:
            PdfUploadForm.validate_files(None, field)

        self.assertEqual(str(raised.exception), t("docs.upload_pdf_invalid"))

    def test_validate_files_accepts_pdf_files_case_insensitively(self):
        field = SimpleNamespace(data=[SimpleNamespace(filename="contrato.PDF")])

        PdfUploadForm.validate_files(None, field)


class LoginFormUnitTest(FormTestMixin, BaseAppTestCase):
    def test_login_form_validates_credentials_shape_and_localizes_messages(self):
        self.assertFormValid(LoginForm, {"email": "user@example.com", "password": "Secreta1"})

        form = self.assertFormInvalid(LoginForm, {"email": "mal-email", "password": "123"}, "email")
        self.assertIn("password", form.errors)
        self.assertEqual(form.email.label.text, t("common.email"))
        self.assertEqual(form.password.label.text, t("common.password"))
        self.assertEqual(form.email.errors[0], t("validation.email"))
        self.assertEqual(form.password.errors[0], t("validation.min_length_6"))


class SignupFormUnitTest(FormTestMixin, BaseAppTestCase):
    def test_signup_form_validates_secure_matching_passwords(self):
        form = self.assertFormValid(
            SignupForm,
            {
                "nombre": "Lydia",
                "email": "lydia@example.com",
                "password": "Segura123",
                "confirm_password": "Segura123",
            },
        )
        self.assertEqual(form.country_code.data, "ES")

        mismatch = self.assertFormInvalid(
            SignupForm,
            {
                "nombre": "Lydia",
                "email": "lydia@example.com",
                "password": "Segura123",
                "confirm_password": "Distinta123",
            },
            "confirm_password",
        )
        self.assertEqual(mismatch.confirm_password.errors[0], t("auth.password_mismatch"))

        weak = self.assertFormInvalid(
            SignupForm,
            {
                "nombre": "Lydia",
                "email": "lydia@example.com",
                "password": "sinmayusculas",
                "confirm_password": "sinmayusculas",
            },
            "password",
        )
        self.assertIn(t("validation.password_security"), weak.password.errors)


class AdminCreateUserFormUnitTest(FormTestMixin, BaseAppTestCase):
    def test_admin_create_user_form_validates_user_data_and_admin_flag(self):
        form = self.assertFormValid(
            AdminCreateUserForm,
            {
                "nombre": "Admin",
                "email": "admin@example.com",
                "password": "Segura123",
                "is_admin": "y",
            },
        )

        self.assertTrue(form.is_admin.data)
        self.assertEqual(form.country_code.data, "ES")
        self.assertEqual(form.is_admin.label.text, t("admin.is_admin"))

        invalid = self.assertFormInvalid(
            AdminCreateUserForm,
            {"nombre": "A", "email": "admin@example.com", "password": "segura"},
        )
        self.assertIn("nombre", invalid.errors)
        self.assertIn("password", invalid.errors)


class EditUserFormUnitTest(FormTestMixin, BaseAppTestCase):
    def test_edit_user_form_accepts_empty_optional_fields_and_validates_values_when_present(self):
        form = self.assertFormValid(EditUserForm, {})

        self.assertEqual(form.country_code.data, "ES")
        self.assertEqual(form.new_password.render_kw["placeholder"], t("user.leave_empty_password"))

        invalid = self.assertFormInvalid(
            EditUserForm,
            {"nombre": "A", "email": "mal-email", "new_password": "debil"},
        )
        self.assertIn("nombre", invalid.errors)
        self.assertIn("email", invalid.errors)
        self.assertIn("new_password", invalid.errors)


class RAGQueryFormUnitTest(FormTestMixin, BaseAppTestCase):
    def test_rag_query_form_requires_question_and_limits_length(self):
        self.assertFormValid(RAGQueryForm, {"question": "Que documentos hay disponibles?"})

        required = self.assertFormInvalid(RAGQueryForm, {"question": ""}, "question")
        self.assertEqual(required.question.errors[0], t("validation.required"))

        too_long = self.assertFormInvalid(RAGQueryForm, {"question": "a" * 2001}, "question")
        self.assertEqual(too_long.question.errors[0], t("validation.max_length_2000"))
        self.assertEqual(too_long.question.render_kw["placeholder"], t("rag.question_placeholder"))


class ForgotPasswordFormUnitTest(FormTestMixin, BaseAppTestCase):
    def test_forgot_password_form_validates_email(self):
        form = self.assertFormValid(ForgotPasswordForm, {"email": "user@example.com"})
        self.assertEqual(form.submit.label.text, t("auth.forgot_password_submit"))

        invalid = self.assertFormInvalid(ForgotPasswordForm, {"email": "mal-email"}, "email")
        self.assertEqual(invalid.email.errors[0], t("validation.email"))


class ResetPasswordFormUnitTest(FormTestMixin, BaseAppTestCase):
    def test_reset_password_form_validates_security_and_confirmation(self):
        self.assertFormValid(
            ResetPasswordForm,
            {"password": "Segura123", "confirm_password": "Segura123"},
        )

        mismatch = self.assertFormInvalid(
            ResetPasswordForm,
            {"password": "Segura123", "confirm_password": "Otra1234"},
            "confirm_password",
        )
        self.assertEqual(mismatch.confirm_password.errors[0], t("auth.password_mismatch"))

        weak = self.assertFormInvalid(
            ResetPasswordForm,
            {"password": "seguraperoSinNumero", "confirm_password": "seguraperoSinNumero"},
            "password",
        )
        self.assertIn(t("validation.password_security"), weak.password.errors)
