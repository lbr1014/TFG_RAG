from flask_wtf import FlaskForm
from wtforms import BooleanField, PasswordField, StringField, SubmitField, TextAreaField
from wtforms.validators import DataRequired, Email, EqualTo, Length, Optional

from .inetrnacionalizacion.tarduccion import localize_form


class LocalizedFlaskForm(FlaskForm):
    i18n_fields = {}
    i18n_placeholders = {}
    i18n_validator_messages = {}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        localize_form(self)


class LoginForm(LocalizedFlaskForm):
    i18n_fields = {
        "email": "common.email",
        "password": "common.password",
        "submit": "auth.login_submit",
    }

    email = StringField("Email", validators=[DataRequired(), Email()])
    password = PasswordField("Contraseña", validators=[DataRequired(), Length(min=6)])
    submit = SubmitField("Iniciar sesión")


class SignupForm(LocalizedFlaskForm):
    i18n_fields = {
        "nombre": "common.name",
        "email": "common.email",
        "password": "common.password",
        "confirm_password": "auth.repeat_password",
        "submit": "auth.signup_submit",
    }
    i18n_validator_messages = {
        "confirm_password": {"EqualTo": "auth.password_mismatch"},
    }

    nombre = StringField("Nombre", validators=[DataRequired(), Length(min=2, max=50)])
    email = StringField("Email", validators=[DataRequired(), Email()])
    password = PasswordField("Contraseña", validators=[DataRequired(), Length(min=6)])
    confirm_password = PasswordField(
        "Repite la contraseña",
        validators=[DataRequired(), EqualTo("password", message="Las contraseñas no coinciden")],
    )
    submit = SubmitField("Crear cuenta")


class AdminCreateUserForm(LocalizedFlaskForm):
    i18n_fields = {
        "nombre": "common.name",
        "email": "common.email",
        "password": "common.password",
        "is_admin": "admin.is_admin",
        "submit": "admin.create_user_submit",
    }

    nombre = StringField("Nombre", validators=[DataRequired(), Length(min=2, max=50)])
    email = StringField("Email", validators=[DataRequired(), Email()])
    password = PasswordField("Contraseña", validators=[DataRequired(), Length(min=6)])
    is_admin = BooleanField("Administrador")
    submit = SubmitField("Crear usuario")


class EditUserForm(LocalizedFlaskForm):
    i18n_fields = {
        "nombre": "common.name",
        "email": "common.email",
        "new_password": "auth.new_password",
        "submit": "common.save_changes",
    }
    i18n_placeholders = {
        "new_password": "user.leave_empty_password",
    }

    nombre = StringField("Nombre", validators=[Optional(), Length(min=2, max=50)])
    email = StringField("Email", validators=[Optional(), Email(), Length(max=255)])
    new_password = PasswordField("Nueva contraseña", validators=[Optional(), Length(min=6)])
    submit = SubmitField("Guardar cambios")


class RAGQueryForm(LocalizedFlaskForm):
    i18n_fields = {
        "question": "rag.question_label",
        "submit": "rag.ask_button",
    }
    i18n_placeholders = {
        "question": "rag.question_placeholder",
    }

    question = TextAreaField("Pregunta", validators=[DataRequired(), Length(max=2000)])
    submit = SubmitField("Preguntar")


class ForgotPasswordForm(LocalizedFlaskForm):
    i18n_fields = {
        "email": "common.email",
        "submit": "auth.forgot_password_submit",
    }

    email = StringField("Email", validators=[DataRequired(), Email()])
    submit = SubmitField("Recuperar contraseña")


class ResetPasswordForm(LocalizedFlaskForm):
    i18n_fields = {
        "password": "auth.new_password",
        "confirm_password": "auth.repeat_password",
        "submit": "auth.reset_password_submit",
    }

    i18n_validator_messages = {
        "confirm_password": {"EqualTo": "auth.password_mismatch"},
    }

    password = PasswordField("Nueva contraseña", validators=[DataRequired(), Length(min=6)])
    confirm_password = PasswordField(
        "Repite la contraseña",
        validators=[DataRequired(), EqualTo("password", message="Las contraseñas no coinciden")],
    )
    submit = SubmitField("Cambiar contraseña")
