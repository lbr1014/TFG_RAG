from flask_wtf import FlaskForm
from wtforms import StringField, SubmitField, PasswordField, BooleanField, TextAreaField
from wtforms.validators import DataRequired, Email, Length, EqualTo, Optional

EMAIL = StringField("Email", validators=[DataRequired(), Email()])
PASSWORD = PasswordField("Contraseña", validators=[DataRequired(), Length(min=6)])
NAME = StringField("Nombre", validators=[DataRequired(), Length(min=2, max=50)])

class LoginForm(FlaskForm):
    email = EMAIL
    password = PASSWORD
    submit = SubmitField("Iniciar sesión")

class SignupForm(FlaskForm):
    nombre = NAME
    email = EMAIL
    password = PASSWORD
    confirm_password = PasswordField("Repite la contraseña", validators=[DataRequired(), EqualTo("password", message="Las contraseñas no coinciden")])
    submit = SubmitField("Crear cuenta")
    
class AdminCreateUserForm(FlaskForm):
    nombre = NAME
    email = EMAIL
    password = PASSWORD
    is_admin = BooleanField("Administrador")
    submit = SubmitField("Crear usuario")
    
class EditUserForm(FlaskForm):
    nombre = StringField("Nombre", validators=[Optional(), Length(min=2, max=50)])
    email = StringField("Email", validators=[Optional(), Email(), Length(max=255)])
    new_password = PasswordField("Nueva contraseña", validators=[Optional(), Length(min=6)])
    submit = SubmitField("Guardar cambios")
    
class RAGQueryForm(FlaskForm):
    question = TextAreaField("Pregunta", validators=[DataRequired(), Length(max=2000)])
    submit = SubmitField("Preguntar")
    
class ForgotPasswordForm(FlaskForm):
    email = StringField("Email", validators=[DataRequired(), Email()])
    submit = SubmitField("Recuperar contraseña")

class ResetPasswordForm(FlaskForm):
    password = PasswordField("Nueva contraseña", validators=[DataRequired(), Length(min=6)])
    confirm_password = PasswordField(
        "Repite la contraseña",
        validators=[DataRequired(), EqualTo("password", message="Las contraseñas no coinciden")]
    )
    submit = SubmitField("Cambiar contraseña")

