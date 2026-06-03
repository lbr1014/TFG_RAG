"""
Autora: Lydia Blanco Ruiz
Script para definir el blueprint de autenticación.
"""

from flask import Blueprint

auth_bp = Blueprint("auth", __name__)

from . import routes as routes
