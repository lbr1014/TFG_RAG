from flask import render_template, redirect, url_for, flash, current_app
from flask_login import login_user, logout_user, login_required
from flask_mail import Message
from itsdangerous import URLSafeTimedSerializer
from . import auth_bp
from ..forms import LoginForm, SignupForm, ForgotPasswordForm, ResetPasswordForm
from ..usuario import User
from ..extensions import db, mail

def _serializer() -> URLSafeTimedSerializer:
    return URLSafeTimedSerializer(current_app.config["SECRET_KEY"], salt="password-reset")

def generate_reset_token(email: str) -> str:
    return _serializer().dumps(email)

def verify_reset_token(token: str, max_age_seconds: int = 3600) -> str | None:
    try:
        return _serializer().loads(token, max_age=max_age_seconds)
    except Exception:
        return None

@auth_bp.route("/login", methods=["GET", "POST"])
def login():
    form = LoginForm()

    if form.validate_on_submit():
        email = form.email.data.lower().strip()
        password = form.password.data

        user = User.get_by_email(email)

        if user and user.check_password(password):
            user.update_last_login()
            db.session.commit()
            login_user(user)
            return redirect(url_for("main.pag_principal"))

        form.password.errors.append("Email o contraseña incorrectos.")

    return render_template("login.html", form=form)

@auth_bp.route("/logout")
@login_required
def logout():
    logout_user()
    return redirect(url_for("main.inicio"))

@auth_bp.route("/singup", methods=["GET", "POST"])
def singup():
    form = SignupForm()

    if form.validate_on_submit():
        nombre = form.nombre.data.strip()
        email = form.email.data.lower().strip()
        password = form.password.data

        if User.get_by_email(email):
            form.email.errors.append("Ya existe un usuario con ese email.")
            return render_template("singup.html", form=form)

        user = User(nombre=nombre, email=email)
        user.set_password(password)
        user.update_last_login()

        db.session.add(user)
        db.session.commit()

        login_user(user)
        return redirect(url_for("main.pag_principal"))

    return render_template("singup.html", form=form)

@auth_bp.route("/forgot-password", methods=["GET", "POST"])
def forgot_password():
    form = ForgotPasswordForm()

    if form.validate_on_submit():
        email = form.email.data.lower().strip()
        user = User.get_by_email(email)

        if user:
            token = generate_reset_token(user.email)
            reset_url = url_for("auth.reset_password", token=token, _external=True)

            msg = Message(
                subject="Recuperación de contraseña",
                recipients=[user.email],
            )
            msg.body = f"""Hola {user.nombre},

            Has solicitado recuperar tu contraseña.
            Abre este enlace para crear una nueva:

            {reset_url}

            Si no lo has solicitado tú, ignora este correo.
            """
            mail.send(msg)

            flash("Si el email existe, hemos enviado un enlace para recuperar la contraseña.", "info")

        return redirect(url_for("auth.login"))

    return render_template("forgot_password.html", form=form)


@auth_bp.route("/reset-password/<token>", methods=["GET", "POST"])
def reset_password(token: str):
    email = verify_reset_token(token, max_age_seconds=3600)  
    if not email:
        flash("El enlace de recuperación no es válido o ha caducado.", "warning")
        return redirect(url_for("auth.forgot_password"))

    user = User.get_by_email(email)
    if not user:
        flash("El enlace de recuperación no es válido.", "warning")
        return redirect(url_for("auth.forgot_password"))

    form = ResetPasswordForm()
    if form.validate_on_submit():
        user.set_password(form.password.data)
        db.session.commit()
        flash("Contraseña cambiada. Ya puedes iniciar sesión.", "success")
        return redirect(url_for("auth.login"))

    return render_template("reset_password.html", form=form)
