"""
Autora: Lydia Blanco Ruiz
Script con decoradores de autorización para proteger vistas de administración.
"""

from functools import wraps
from flask import abort
from flask_login import current_user
from app.main.code.extensions import login_manager


def admin_required(view_func):
    """Exige que el usuario autenticado sea administrador.

    Args:
        view_func: Vista Flask que se quiere proteger.

    Returns:
        La vista envuelta con la comprobación de permisos.
    """

    @wraps(view_func)
    def wrapper(*args, **kwargs):
        """Comprueba autenticación y permisos antes de ejecutar la vista.

        Args:
            *args: Argumentos posicionales de la vista original.
            **kwargs: Argumentos con nombre de la vista original.

        Returns:
            La respuesta de la vista original si el usuario tiene permisos.
        """
        if not current_user.is_authenticated:
            return login_manager.unauthorized()
        if not current_user.is_admin:
            abort(403)
        return view_func(*args, **kwargs)
    return wrapper
