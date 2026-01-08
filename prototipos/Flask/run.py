from flask import Flask, render_template

app = Flask(__name__)

@app.route("/")
def inicio():
    return render_template(
        "index.html",
        titulo="Implementación de un RAG sobre las licitacioens del estado",
        autor="Autora: Lydia Blanco Ruiz"
    )

if __name__ == "__main__":
    app.run(debug=True)
