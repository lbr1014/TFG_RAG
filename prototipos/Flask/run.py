from flask import Flask, render_template, redirect, url_for, abort  
from flask_login import LoginManager, login_user, logout_user, login_required, current_user
from flask_sqlalchemy import SQLAlchemy
from functools import wraps
import os

from extensions import db, login_manager, migrate
from forms import LoginForm, SignupForm, AdminCreateUserForm
from usuario import User

app = Flask(__name__)
app.config["SECRET_KEY"] = "una_clave_cualquiera_118732hfshdfiuhwy!!$%"
basedir = os.path.abspath(os.path.dirname(__file__))
app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite:///" + os.path.join(basedir, "app.db")
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False

# init extensions
db.init_app(app)
migrate.init_app(app, db)
login_manager.init_app(app)
login_manager.login_view = "login"
login_manager.login_message = "Debes iniciar sesión para acceder a esta página."

@login_manager.user_loader
def load_user(user_id: str):
    return User.get_by_id(int(user_id))

def admin_required(view_func):
    @wraps(view_func)
    def wrapper(*args, **kwargs):
        if not current_user.is_authenticated:
            return login_manager.unauthorized()
        if not current_user.is_admin:
            abort(403)
        return view_func(*args, **kwargs)
    return wrapper

@app.route("/")
def inicio():
    return render_template(
        "index.html",
        titulo="Implementación de un RAG sobre las licitaciones del estado",
        autor="Autora: Lydia Blanco Ruiz"
    )
    
@app.route("/login", methods=["GET", "POST"])
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
            return redirect(url_for("pag_principal"))

        form.password.errors.append("Email o contraseña incorrectos.")
        
    return render_template("login.html", form=form)

@app.route("/logout")
@login_required
def logout():
    logout_user()

    return redirect(url_for("inicio"))

@app.route("/singup", methods=["GET", "POST"])
def singup():
    form = SignupForm()
    
    if form.validate_on_submit():
        nombre = form.nombre.data.strip()
        email = form.email.data.lower().strip()
        password = form.password.data
        
        if User.get_by_email(email):
            form.email.errors.append("Ya existe un usuario con ese email.")
            return render_template("singup.html", form=form)
        
        # Se crea el usuario
        user = User(nombre=nombre, email=email)
        user.set_password(password)
        user.update_last_login() 

        db.session.add(user)
        db.session.commit()
        
        login_user(user)
        return redirect(url_for("pag_principal"))
    
    return render_template("singup.html", form=form)

@app.route("/pagina_principal")
@login_required
def pag_principal():
    return render_template("pag_principal.html", user=current_user)

@app.route("/admin/users")
@login_required
@admin_required
def users():
    users = User.query.order_by(User.id.asc()).all()
    return render_template("users.html", users=users)

@app.route("/admin/users/<int:user_id>", methods=["POST"])
@login_required
@admin_required
def admin_change_type(user_id):
    user = User.get_by_id(user_id)
    if not user:
        abort(404)

    # Evita que el admin se quite a sí mismo el admin
    if user.id == current_user.id:
        abort(400)

    user.change_admin()
    db.session.commit()
    return redirect(url_for("users"))

@app.route("/admin/users/<int:user_id>/delete", methods=["POST"])
@login_required
@admin_required
def admin_delete_user(user_id):
    user = User.get_by_id(user_id)
    if not user:
        abort(404)

    # Evita borrarse a sí mismo
    if user.id == current_user.id:
        abort(400)

    db.session.delete(user)
    db.session.commit()
    return redirect(url_for("users"))

@app.route("/admin/users/new", methods=["GET", "POST"])
@login_required
@admin_required
def admin_create_user():
    form = AdminCreateUserForm()

    if form.validate_on_submit():
        nombre = form.nombre.data.strip()
        email = form.email.data.lower().strip()
        password = form.password.data
        is_admin = form.is_admin.data

        if User.get_by_email(email):
            form.email.errors.append("Ya existe un usuario con ese email.")
            return render_template("admin_create_user.html", form=form)

        user = User(nombre=nombre, email=email)
        user.set_password(password)
        user.is_admin = is_admin

        db.session.add(user)
        db.session.commit()

        return redirect(url_for("users"))

    return render_template("admin_create_user.html", form=form)


if __name__ == "__main__":
    app.run(debug=True)
