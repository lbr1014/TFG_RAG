"""
Autora: Lydia Blanco Ruiz
Script con los formularios Flask-WTF usados por autenticación, administración, documentos y consultas RAG.
"""

from flask_wtf import FlaskForm
from wtforms import BooleanField, HiddenField, MultipleFileField, PasswordField, StringField, SubmitField, TextAreaField
from wtforms.validators import DataRequired, Email, EqualTo, Length, Optional, ValidationError

from .error_handling import PasswordSecurity
from .inetrnacionalizacion.tarduccion import localize_form

EMAIL = "common.email"
PASSWORD = "common.password"
VALIDATION_REQUIRED = "validation.required"
VALIDATION_EMAIL = "validation.email"
CONTRASEÑA = "Contraseña"
NAME = "common.name"
MIN_LENGTH_NAME = "validation.min_length_2"
MIN_LENGTH_PASSWORD = "validation.min_length_8"
VALIDATE_PASSWORD_SECURITY = "validation.password_security"


class LocalizedFlaskForm(FlaskForm):
    """Formulario base que aplica traducciones a etiquetas y validadores.

    Attributes:
        i18n_fields: Mapa ``nombre_campo -> clave de traducción``.
        i18n_placeholders: Mapa ``nombre_campo -> clave de placeholder``.
        i18n_validator_messages: Mapa de mensajes de validadores por campo.
    """

    i18n_fields = {}
    i18n_placeholders = {}
    i18n_validator_messages = {}

    def __init__(self, *args, **kwargs):
        """Inicializa el formulario y localiza sus textos.

        Args:
            *args: Argumentos posicionales aceptados por ``FlaskForm``.
            **kwargs: Argumentos con nombre aceptados por ``FlaskForm``.
        """
        super().__init__(*args, **kwargs)
        localize_form(self)


class EmptyForm(FlaskForm):
    """Formulario CSRF para acciones POST sin campos propios."""


class LanguageForm(FlaskForm):
    """Formulario para cambiar el idioma activo de la sesión.

    Attributes:
        lang: Código del idioma solicitado.
        next: URL de retorno tras guardar el idioma.
    """

    lang = HiddenField(validators=[DataRequired()])
    next = HiddenField()


class PdfUploadForm(LocalizedFlaskForm):
    """Formulario para subir uno o varios documentos PDF.

    Attributes:
        files: Lista de archivos seleccionados por el usuario.
        submit: Botón de envío del formulario.
    """

    i18n_fields = {
        "files": "docs.upload_label",
        "submit": "docs.upload_button",
    }

    files = MultipleFileField("Carga uno o varios PDF")
    submit = SubmitField("Subir documentos")

    def validate_files(self, field):
        """Valida que se haya enviado al menos un archivo con extensión PDF.

        Args:
            field: Campo de archivos recibido por WTForms.

        Raises:
            ValidationError: Si no hay archivos o alguno no usa la extensión
                ``.pdf``.
        """
        files = [item for item in (field.data or []) if item and item.filename]
        if not files:
            raise ValidationError("Selecciona al menos un PDF.")
        invalid = [item.filename for item in files if not item.filename.lower().endswith(".pdf")]
        if invalid:
            raise ValidationError("Solo se admiten archivos PDF.")


class LoginForm(LocalizedFlaskForm):
    """Formulario de inicio de sesión."""

    i18n_fields = {
        "email": EMAIL,
        "password": PASSWORD,
        "submit": "auth.login_submit",
    }
    i18n_validator_messages = {
        "email": {
            "DataRequired": VALIDATION_REQUIRED,
            "Email": VALIDATION_EMAIL,
        },
        "password": {
            "DataRequired": VALIDATION_REQUIRED,
            "Length": "validation.min_length_6",
        },
    }

    email = StringField("Email", validators=[DataRequired(), Email()])
    password = PasswordField(CONTRASEÑA, validators=[DataRequired(), Length(min=6)])
    submit = SubmitField("Iniciar sesión")


class SignupForm(LocalizedFlaskForm):
    """Formulario de registro de nuevos usuarios."""

    i18n_fields = {
        "nombre": NAME,
        "email": EMAIL,
        "password": PASSWORD,
        "confirm_password": "auth.repeat_password",
        "submit": "auth.signup_submit",
    }
    i18n_validator_messages = {
        "nombre": {
            "DataRequired": VALIDATION_REQUIRED,
            "Length": MIN_LENGTH_NAME,
        },
        "email": {
            "DataRequired": VALIDATION_REQUIRED,
            "Email": VALIDATION_EMAIL,
        },
        "password": {
            "DataRequired": VALIDATION_REQUIRED,
            "Length": MIN_LENGTH_PASSWORD,
            "PasswordSecurity": VALIDATE_PASSWORD_SECURITY,
        },
        "confirm_password": {
            "DataRequired": VALIDATION_REQUIRED,
            "EqualTo": "auth.password_mismatch",
        },
    }

    nombre = StringField("Nombre", validators=[DataRequired(), Length(min=2, max=50)])
    email = StringField("Email", validators=[DataRequired(), Email()])
    password = PasswordField(CONTRASEÑA, validators=[DataRequired(), Length(min=8), PasswordSecurity()])
    confirm_password = PasswordField(
        "Repite la contraseña",
        validators=[DataRequired(), EqualTo("password", message="Las contraseñas no coinciden")],
    )
    submit = SubmitField("Crear cuenta")


class AdminCreateUserForm(LocalizedFlaskForm):
    """Formulario de administración para crear usuarios."""

    i18n_fields = {
        "nombre": NAME,
        "email": EMAIL,
        "password": PASSWORD,
        "is_admin": "admin.is_admin",
        "submit": "admin.create_user_submit",
    }
    i18n_validator_messages = {
        "nombre": {
            "DataRequired": VALIDATION_REQUIRED,
            "Length": MIN_LENGTH_NAME,
        },
        "email": {
            "DataRequired": VALIDATION_REQUIRED,
            "Email": VALIDATION_EMAIL,
        },
        "password": {
            "DataRequired": VALIDATION_REQUIRED,
            "Length": MIN_LENGTH_PASSWORD,
            "PasswordSecurity": VALIDATE_PASSWORD_SECURITY,
        },
    }

    nombre = StringField("Nombre", validators=[DataRequired(), Length(min=2, max=50)])
    email = StringField("Email", validators=[DataRequired(), Email()])
    password = PasswordField(CONTRASEÑA, validators=[DataRequired(), Length(min=8), PasswordSecurity()])
    is_admin = BooleanField("Administrador")
    submit = SubmitField("Crear usuario")


class EditUserForm(LocalizedFlaskForm):
    """Formulario para editar los datos del usuario autenticado."""

    i18n_fields = {
        "nombre": NAME,
        "email": EMAIL,
        "new_password": "auth.new_password",
        "submit": "common.save_changes",
    }
    i18n_placeholders = {
        "new_password": "user.leave_empty_password",
    }
    i18n_validator_messages = {
        "nombre": {
            "Length": MIN_LENGTH_NAME,
        },
        "email": {
            "Email": VALIDATION_EMAIL,
            "Length": "validation.max_length_255",
        },
        "new_password": {
            "Length": MIN_LENGTH_PASSWORD,
            "PasswordSecurity": VALIDATE_PASSWORD_SECURITY,
        },
    }

    nombre = StringField("Nombre", validators=[Optional(), Length(min=2, max=50)])
    email = StringField("Email", validators=[Optional(), Email(), Length(max=255)])
    new_password = PasswordField("Nueva contraseña", validators=[Optional(), Length(min=8), PasswordSecurity()])
    submit = SubmitField("Guardar cambios")


class RAGQueryForm(LocalizedFlaskForm):
    """Formulario para enviar preguntas al sistema RAG."""

    i18n_fields = {
        "question": "rag.question_label",
        "submit": "rag.ask_button",
    }
    i18n_placeholders = {
        "question": "rag.question_placeholder",
    }
    i18n_validator_messages = {
        "question": {
            "DataRequired": VALIDATION_REQUIRED,
            "Length": "validation.max_length_2000",
        },
    }

    question = TextAreaField("Pregunta", validators=[DataRequired(), Length(max=2000)])
    submit = SubmitField("Preguntar")


class ForgotPasswordForm(LocalizedFlaskForm):
    """Formulario para solicitar un enlace de recuperación de contraseña."""

    i18n_fields = {
        "email": EMAIL,
        "submit": "auth.forgot_password_submit",
    }
    i18n_validator_messages = {
        "email": {
            "DataRequired": VALIDATION_REQUIRED,
            "Email": VALIDATION_EMAIL,
        },
    }

    email = StringField("Email", validators=[DataRequired(), Email()])
    submit = SubmitField("Recuperar contraseña")


class ResetPasswordForm(LocalizedFlaskForm):
    """Formulario para guardar una nueva contraseña tras validar el token."""

    i18n_fields = {
        "password": "auth.new_password",
        "confirm_password": "auth.repeat_password",
        "submit": "auth.reset_password_submit",
    }
    i18n_validator_messages = {
        "password": {
            "DataRequired": VALIDATION_REQUIRED,
            "Length": MIN_LENGTH_PASSWORD,
            "PasswordSecurity": VALIDATE_PASSWORD_SECURITY,
        },
        "confirm_password": {
            "DataRequired": VALIDATION_REQUIRED,
            "EqualTo": "auth.password_mismatch",
        },
    }

    password = PasswordField("Nueva contraseña", validators=[DataRequired(), Length(min=8), PasswordSecurity()])
    confirm_password = PasswordField(
        "Repite la contraseña",
        validators=[DataRequired(), EqualTo("password", message="Las contraseñas no coinciden")],
    )
    submit = SubmitField("Cambiar contraseña")
