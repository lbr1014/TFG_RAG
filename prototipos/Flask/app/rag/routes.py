from flask import Blueprint, render_template, request, jsonify
from flask_login import login_required

from app.forms import RAGQueryForm 
from app.rag.service import rag_answer

rag_bp = Blueprint("rag", __name__, url_prefix="/rag")

@rag_bp.get("/")
@login_required
def rag_page():
    form = RAGQueryForm()
    return render_template("rag.html", form=form)

@rag_bp.post("/ask")
@login_required
def rag_ask():
    form = RAGQueryForm()
    question = form.question.data
    data = rag_answer(question)
    return jsonify(data)
