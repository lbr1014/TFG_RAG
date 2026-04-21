"""
Autora: Lydia Blanco Ruiz
Script para exportar las utilidades de internacionalización de la aplicación.
"""

from .tarduccion import (
    DEFAULT_LANGUAGE,
    SUPPORTED_LANGUAGES,
    TRANSLATIONS,
    get_client_translations,
    get_locale,
    init_app,
    localize_form,
    localize_runtime_message,
    normalize_language,
    t,
    translate_for,
)
