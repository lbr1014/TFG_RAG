"""
Autora: Lydia Blanco Ruiz
Script para definir el blueprint de administración.
"""

from flask import Blueprint

admin_bp = Blueprint("admin", __name__, url_prefix="/admin")

from . import routes as routes
