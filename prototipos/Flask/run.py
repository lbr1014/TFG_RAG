from flask import Flask, render_template, redirect, url_for

from forms import LoginForm, SignupForm

app = Flask(__name__)
app.config["SECRET_KEY"] = "una_clave_cualquiera_118732hfshdfiuhwy!!$%"

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
        email = form.email.data
        password = form.password.data
        
        return redirect(url_for("pag_principal"))
        
    return render_template("login.html", form=form)

@app.route("/singup", methods=["GET", "POST"])
def singup():
    form = SignupForm()
    
    if form.validate_on_submit():
        nombre = form.nombre.data
        email = form.email.data
        password = form.password.data
        
        return redirect(url_for("pag_principal"))
    
    return render_template("singup.html", form=form)

@app.route("/pagina_principal", methods=["GET"])
def pag_principal():
    return render_template("pag_principal.html")

if __name__ == "__main__":
    app.run(debug=True)
