
"""
Autora: Lydia Blanco Ruiz
Script para definir el blueprint de consultas RAG.
"""

from flask import Blueprint

rag_bp = Blueprint("rag", __name__, url_prefix="/rag")

from . import routes
