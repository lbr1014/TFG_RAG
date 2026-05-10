"""
Autora: Lydia Blanco Ruiz
Script para las rutas de autenticación, registro, cierre de sesión y recuperación de contraseña.
"""

from flask import current_app, flash, redirect, render_template, url_for
from flask.typing import ResponseReturnValue
from flask_login import login_required, login_user, logout_user
from flask_mail import Message
from itsdangerous import BadData, URLSafeTimedSerializer

from app.main.code import _flask_session_config_name
from app.main.code.countries import normalize_country_code
from app.main.code.extensions import db, mail
from app.main.code.forms import (
    EmptyForm,
    ForgotPasswordForm,
    LoginForm,
    ResetPasswordForm,
    SignupForm,
)
from app.main.code.inetrnacionalizacion.tarduccion import t

from ...model.user import User
from . import auth_bp

MAIN_PAGE_ENDPOINT = "main.pag_principal"


def _serializer() -> URLSafeTimedSerializer:
    """
    Crea el serializador usado para tokens de recuperación.

    Returns:
        Serializador configurado con la clave secreta de Flask.
    """
    return URLSafeTimedSerializer(current_app.config[_flask_session_config_name()], salt="password-reset")


def generate_reset_token(email: str) -> str:
    """
    Genera un token firmado para recuperar una contraseña.

    Args:
        email: Correo electrónico asociado a la cuenta.

    Returns:
        Token firmado que puede enviarse por correo.
    """
    return _serializer().dumps(email)


def verify_reset_token(token: str, max_age_seconds: int = 3600) -> str | None:
    """
    Valida un token de recuperación de contraseña.

    Args:
        token: Token recibido desde el enlace de recuperación.
        max_age_seconds: Tiempo máximo de validez del token, en segundos.

    Returns:
        Correo electrónico contenido en el token o ``None`` si no es válido.
    """
    try:
        return _serializer().loads(token, max_age=max_age_seconds)
    except BadData:
        return None

@auth_bp.get("/login")
@auth_bp.post("/login")
def login() -> ResponseReturnValue:
    """
    Muestra y procesa el formulario de inicio de sesión.

    Returns:
        Respuesta HTML del formulario o redirección al área principal.
    """
    form = LoginForm()

    if form.validate_on_submit():
        email = form.email.data.lower().strip()
        password = form.password.data

        user = User.get_by_email(email)

        if user and user.check_password(password):
            user.update_last_login()
            db.session.commit()
            login_user(user)
            return redirect(url_for(MAIN_PAGE_ENDPOINT))

        form.password.errors.append(t("auth.invalid_credentials"))

    return render_template("login.html", form=form)

@auth_bp.post("/logout")
@login_required
def logout() -> ResponseReturnValue:
    """
    Cierra la sesión del usuario autenticado mediante POST con CSRF.

    Returns:
        Redirección a la página de inicio o al área principal si el CSRF no es
        válido.
    """
    form = EmptyForm()
    if not form.validate_on_submit():
        return redirect(url_for(MAIN_PAGE_ENDPOINT))
    logout_user()
    return redirect(url_for("main.inicio"))

@auth_bp.get("/signup")
@auth_bp.post("/signup")
def singup() -> ResponseReturnValue:
    """
    Muestra y procesa el formulario de registro.

    Returns:
        Respuesta HTML del formulario o redirección al área principal.
    """
    form = SignupForm()

    if form.validate_on_submit():
        nombre = form.nombre.data.strip()
        email = form.email.data.lower().strip()
        country_code = normalize_country_code(form.country_code.data)
        password = form.password.data

        if User.get_by_email(email):
            form.email.errors.append(t("auth.email_exists"))
            return render_template("singup.html", form=form)

        user = User(nombre=nombre, email=email, country_code=country_code)
        user.set_password(password)
        user.update_last_login()

        db.session.add(user)
        db.session.commit()

        login_user(user)
        return redirect(url_for(MAIN_PAGE_ENDPOINT))

    return render_template("singup.html", form=form)

@auth_bp.get("/forgot-password")
@auth_bp.post("/forgot-password")
def forgot_password() -> ResponseReturnValue:
    """
    Solicita el envío de un enlace de recuperación de contraseña.

    Returns:
        Respuesta HTML del formulario o redirección al login.
    """
    form = ForgotPasswordForm()

    if form.validate_on_submit():
        email = form.email.data.lower().strip()
        user = User.get_by_email(email)

        if user:
            token = generate_reset_token(user.email)
            reset_url = url_for("auth.reset_password", token=token, _external=True)

            msg = Message(
                subject=t("auth.recovery_subject"),
                recipients=[user.email],
            )
            msg.body = t("auth.recovery_body", name=user.nombre, reset_url=reset_url)
            mail.send(msg)

            flash(t("auth.recovery_sent"), "info")

        return redirect(url_for("auth.login"))

    return render_template("forgot_password.html", form=form)


@auth_bp.get("/reset-password/<token>")
@auth_bp.post("/reset-password/<token>")
def reset_password(token: str) -> ResponseReturnValue:
    """
    Restablece la contraseña a partir de un token válido.

    Args:
        token: Token firmado incluido en el enlace de recuperación.

    Returns:
        Respuesta HTML del formulario o redirección al login.
    """
    email = verify_reset_token(token, max_age_seconds=3600)  
    if not email:
        flash(t("auth.invalid_reset_link_expired"), "warning")
        return redirect(url_for("auth.forgot_password"))

    user = User.get_by_email(email)
    if not user:
        flash(t("auth.invalid_reset_link"), "warning")
        return redirect(url_for("auth.forgot_password"))

    form = ResetPasswordForm()
    if form.validate_on_submit():
        user.set_password(form.password.data)
        db.session.commit()
        flash(t("auth.password_changed"), "success")
        return redirect(url_for("auth.login"))

    return render_template("reset_password.html", form=form)
