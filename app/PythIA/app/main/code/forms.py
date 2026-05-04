"""
Autora: Lydia Blanco Ruiz
Script con los formularios Flask-WTF usados por autenticación, administración, documentos y consultas RAG.
"""

from flask_wtf import FlaskForm
from wtforms import BooleanField, HiddenField, MultipleFileField, PasswordField, SelectField, StringField, SubmitField, TextAreaField
from wtforms.validators import DataRequired, Email, EqualTo, Length, Optional, ValidationError

from .countries import COUNTRY_CHOICES, DEFAULT_COUNTRY_CODE
from .error_handling import PasswordSecurity
from .inetrnacionalizacion.tarduccion import localize_form, t

# Constantes para claves de traducción de campos comunes
"""str: Clave de traducción para el campo email."""
EMAIL = "common.email"

"""str: Clave de traducción para el campo contraseña."""
PASSWORD = "common.password"

"""str: Clave de traducción para mensaje de campo requerido."""
VALIDATION_REQUIRED = "validation.required"

"""str: Clave de traducción para mensaje de email inválido."""
VALIDATION_EMAIL = "validation.email"

"""str: Texto español para contraseña (fallback)."""
CONTRASEÑA = "Contraseña"

"""str: Clave de traducción para el campo nombre."""
NAME = "common.name"

"""str: Clave de traducción para validación de longitud mínima de nombre."""
MIN_LENGTH_NAME = "validation.min_length_2"

"""str: Clave de traducción para validación de longitud mínima de contraseña."""
MIN_LENGTH_PASSWRD = "validation.min_length_8"

"""str: Clave de traducción para validación de seguridad de contraseña."""
VALIDATE_PASSWRD_SECURITY = "validation.password_security"


class LocalizedFlaskForm(FlaskForm):
    """
    Formulario base que aplica traducciones a etiquetas y validadores.

    Esta clase base extiende FlaskForm para proporcionar internacionalización
    automática de etiquetas de campos, placeholders y mensajes de validación
    usando el sistema de traducción de la aplicación.

    Attributes:
        i18n_fields (dict): Mapa ``nombre_campo -> clave de traducción`` para etiquetas.
        i18n_placeholders (dict): Mapa ``nombre_campo -> clave de placeholder`` para placeholders.
        i18n_validator_messages (dict): Mapa de mensajes de validadores por campo.
    """

    i18n_fields = {}
    i18n_placeholders = {}
    i18n_validator_messages = {}

    def __init__(self, *args, **kwargs):
        """
        Inicializa el formulario y localiza sus textos.

        Aplica automáticamente las traducciones configuradas en los atributos
        de clase i18n_* al formulario y sus campos.

        Args:
            *args: Argumentos posicionales aceptados por ``FlaskForm``.
            **kwargs: Argumentos con nombre aceptados por ``FlaskForm``.
        """
        super().__init__(*args, **kwargs)
        localize_form(self)


class EmptyForm(FlaskForm):
    """
    Formulario CSRF para acciones POST sin campos propios.

    Se utiliza para proteger acciones que requieren validación CSRF pero no
    necesitan campos adicionales del usuario, como eliminaciones o acciones
    de estado.
    """


class LanguageForm(FlaskForm):
    """
    Formulario para cambiar el idioma activo de la sesión.

    Permite al usuario seleccionar un idioma diferente para la interfaz,
    guardando la preferencia en la sesión de Flask.

    Attributes:
        lang (HiddenField): Código del idioma solicitado (ej: 'es', 'en').
        next (HiddenField): URL de retorno tras guardar el idioma.
    """

    lang = HiddenField(validators=[DataRequired()])
    next = HiddenField()


class PdfUploadForm(LocalizedFlaskForm):
    """
    Formulario para subir uno o varios documentos PDF.

    Gestiona la carga de archivos PDF para su procesamiento y almacenamiento
    en el sistema de documentos. Incluye validación personalizada para asegurar
    que solo se acepten archivos con extensión .pdf.

    Attributes:
        files (MultipleFileField): Lista de archivos seleccionados por el usuario.
        submit (SubmitField): Botón de envío del formulario.
    """

    i18n_fields = {
        "files": "docs.upload_label",
        "submit": "docs.upload_button",
    }

    files = MultipleFileField("Carga uno o varios PDF")
    submit = SubmitField("Subir documentos")

    def validate_files(self, field):
        """
        Valida que se haya enviado al menos un archivo con extensión PDF.

        Realiza validaciones personalizadas sobre el campo de archivos:
        - Verifica que se haya seleccionado al menos un archivo
        - Confirma que todos los archivos tengan extensión .pdf

        Args:
            field (MultipleFileField): Campo de archivos recibido por WTForms.

        Raises:
            ValidationError: Si no hay archivos o alguno no usa la extensión ``.pdf``.
        """
        files = [item for item in (field.data or []) if item and item.filename]
        if not files:
            raise ValidationError(t("docs.upload_pdf_required"))
        invalid = [item.filename for item in files if not item.filename.lower().endswith(".pdf")]
        if invalid:
            raise ValidationError(t("docs.upload_pdf_invalid"))


class LoginForm(LocalizedFlaskForm):
    """
    Formulario de inicio de sesión de usuarios existentes.

    Gestiona la autenticación de usuarios mediante email y contraseña.
    Incluye validaciones de formato de email y longitud mínima de contraseña.
    """

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
    """
    Formulario de registro de nuevos usuarios.

    Gestiona la creación de cuentas de usuario con validaciones de seguridad
    de contraseña, confirmación de contraseña y unicidad de email.
    """

    i18n_fields = {
        "nombre": NAME,
        "email": EMAIL,
        "country_code": "common.country",
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
            "Length": MIN_LENGTH_PASSWRD,
            "PasswordSecurity": VALIDATE_PASSWRD_SECURITY,
        },
        "confirm_password": {
            "DataRequired": VALIDATION_REQUIRED,
            "EqualTo": "auth.password_mismatch",
        },
    }

    nombre = StringField("Nombre", validators=[DataRequired(), Length(min=2, max=50)])
    email = StringField("Email", validators=[DataRequired(), Email()])
    country_code = SelectField("Pais", choices=COUNTRY_CHOICES, default=DEFAULT_COUNTRY_CODE, validators=[Optional()])
    password = PasswordField(CONTRASEÑA, validators=[DataRequired(), Length(min=8), PasswordSecurity()])
    confirm_password = PasswordField(
        "Repite la contraseña",
        validators=[DataRequired(), EqualTo("password", message="Las contraseñas no coinciden")],
    )
    submit = SubmitField("Crear cuenta")


class AdminCreateUserForm(LocalizedFlaskForm):
    """
    Formulario de administración para crear usuarios.

    Permite a los administradores crear cuentas de usuario con la posibilidad
    de asignar privilegios de administrador. Incluye todas las validaciones
    de seguridad aplicables.
    """

    i18n_fields = {
        "nombre": NAME,
        "email": EMAIL,
        "country_code": "common.country",
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
            "Length": MIN_LENGTH_PASSWRD,
            "PasswordSecurity": VALIDATE_PASSWRD_SECURITY,
        },
    }

    nombre = StringField("Nombre", validators=[DataRequired(), Length(min=2, max=50)])
    email = StringField("Email", validators=[DataRequired(), Email()])
    password = PasswordField(CONTRASEÑA, validators=[DataRequired(), Length(min=8), PasswordSecurity()])
    country_code = SelectField("Pais", choices=COUNTRY_CHOICES, default=DEFAULT_COUNTRY_CODE, validators=[Optional()])
    is_admin = BooleanField("Administrador")
    submit = SubmitField("Crear usuario")


class EditUserForm(LocalizedFlaskForm):
    """
    Formulario para editar los datos del usuario autenticado.

    Permite modificar nombre, email y contraseña del usuario actual.
    Los campos son opcionales para permitir actualizaciones parciales.
    """

    i18n_fields = {
        "nombre": NAME,
        "email": EMAIL,
        "country_code": "common.country",
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
            "Length": MIN_LENGTH_PASSWRD,
            "PasswordSecurity": VALIDATE_PASSWRD_SECURITY,
        },
    }

    nombre = StringField("Nombre", validators=[Optional(), Length(min=2, max=50)])
    email = StringField("Email", validators=[Optional(), Email(), Length(max=255)])
    country_code = SelectField("Pais", choices=COUNTRY_CHOICES, default=DEFAULT_COUNTRY_CODE, validators=[Optional()])
    new_password = PasswordField("Nueva contraseña", validators=[Optional(), Length(min=8), PasswordSecurity()])
    submit = SubmitField("Guardar cambios")


class RAGQueryForm(LocalizedFlaskForm):
    """
    Formulario para enviar preguntas al sistema RAG.

    Gestiona las consultas de usuarios al sistema de Retrieval-Augmented
    Generation, con límite de longitud para optimizar el procesamiento.
    """

    i18n_fields = {
        "model": "rag.model_label",
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
    model = SelectField("Modelo", choices=[], validators=[Optional(), Length(max=255)])
    submit = SubmitField("Preguntar")


class RAGDefaultQueryForm(LocalizedFlaskForm):
    """
    Formulario guiado para construir consultas frecuentes al sistema RAG.
    """

    i18n_fields = {
        "expediente": "rag_default.expediente_label",
        "summary": "rag_default.summary_label",
        "doc_type": "rag_default.doc_type_label",
        "question_kind": "rag_default.question_kind_label",
        "model": "rag.model_label",
        "question": "rag.question_label",
        "submit": "rag.ask_button",
    }
    i18n_validator_messages = {
        "question": {
            "DataRequired": VALIDATION_REQUIRED,
            "Length": "validation.max_length_2000",
        },
    }

    expediente = SelectField("Expediente", choices=[], validators=[Optional(), Length(max=255)])
    summary = BooleanField("Resumen del documento")
    doc_type = SelectField("Tipo de documento", choices=[], validators=[Optional(), Length(max=30)])
    question_kind = SelectField("Pregunta tipo", choices=[], validators=[Optional(), Length(max=60)])
    question = HiddenField("Pregunta", validators=[DataRequired(), Length(max=2000)])
    model = SelectField("Modelo", choices=[], validators=[Optional(), Length(max=255)])
    submit = SubmitField("Preguntar")


class ForgotPasswordForm(LocalizedFlaskForm):
    """
    Formulario para solicitar un enlace de recuperación de contraseña.

    Inicia el proceso de recuperación de contraseña enviando un email
    con un token de restablecimiento al usuario.
    """

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
    """
    Formulario para guardar una nueva contraseña tras validar el token.

    Completa el proceso de recuperación de contraseña permitiendo al usuario
    establecer una nueva contraseña segura tras verificar el token enviado por email.
    """

    i18n_fields = {
        "password": "auth.new_password",
        "confirm_password": "auth.repeat_password",
        "submit": "auth.reset_password_submit",
    }
    i18n_validator_messages = {
        "password": {
            "DataRequired": VALIDATION_REQUIRED,
            "Length": MIN_LENGTH_PASSWRD,
            "PasswordSecurity": VALIDATE_PASSWRD_SECURITY,
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
