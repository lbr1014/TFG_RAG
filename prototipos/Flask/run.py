from flask import Flask, render_template, redirect, url_for, session  
from flask_login import LoginManager, login_user, logout_user, login_required, current_user

from forms import LoginForm, SignupForm
from usuario import User

app = Flask(__name__)
app.config["SECRET_KEY"] = "una_clave_cualquiera_118732hfshdfiuhwy!!$%"

# --- Flask-Login setup ---
login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = "login"   
login_manager.login_message = "Debes iniciar sesión para acceder a esta página."

USERS_BY_ID = {}
USERS_BY_EMAIL = {}

@login_manager.user_loader
def load_user(user_id: str):
    return USERS_BY_ID.get(user_id)

@app.route("/")
def inicio():
    return render_template(
        "index.html",
        titulo="Implementación de un RAG sobre las licitacioens del estado",
        autor="Autora: Lydia Blanco Ruiz"
    )
    
@app.route("/login", methods=["GET", "POST"])
def login():
    form = LoginForm()

    if form.validate_on_submit():
        email = form.email.data.lower().strip()
        password = form.password.data

        user = USERS_BY_EMAIL.get(email)

        if user and user.check_password(password):
            user.update_last_login()
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
        email = form.email.data.strip()
        password = form.password.data
        
        if email in USERS_BY_EMAIL:
            form.email.errors.append("Ya existe un usuario con ese email.")
            return render_template("singup.html", form=form)
        
        # Se crea el usuario (id incremental)
        new_id = str(len(USERS_BY_ID) + 1)
        user = User.create(user_id=new_id, nombre=nombre, email=email, password_plain=password)

        USERS_BY_ID[user.id] = user
        USERS_BY_EMAIL[user.email] = user
        login_user(user)
        
        return redirect(url_for("pag_principal"))
    
    return render_template("singup.html", form=form)

@app.route("/pagina_principal", methods=["GET"])
def pag_principal():
    return render_template("pag_principal.html", user=current_user)

if __name__ == "__main__":
    app.run(debug=True)
