"""
Autora: Lydia Blanco Ruiz
Script con helpers relacionados con países para formularios, filtros y estadísticas. Incluye:
- Lista de países: `pycountry` (ISO 3166-1).
- Nombres localizados: `Babel` (territories), según el idioma activo ("es", "en").
Si `pycountry`/`Babel` no están disponibles en un entorno concreto, se usa un
fallback mínimo para no romper los formularios.
"""

from __future__ import annotations

from functools import lru_cache

DEFAULT_COUNTRY_CODE = "ES"

try:
    import pycountry
except ImportError:
    pycountry = None

try:
    from babel import Locale
    from babel.core import UnknownLocaleError
except ImportError:
    Locale = None

    class UnknownLocaleError(Exception):  
        pass



_FALLBACK_COUNTRIES: list[dict[str, str]] = [
    {"code": "ES", "name_es": "España", "name_en": "Spain", "numeric": "724"},
    {"code": "US", "name_es": "Estados Unidos", "name_en": "United States", "numeric": "840"},
    {"code": "GB", "name_es": "Reino Unido", "name_en": "United Kingdom", "numeric": "826"},
    {"code": "FR", "name_es": "Francia", "name_en": "France", "numeric": "250"},
    {"code": "DE", "name_es": "Alemania", "name_en": "Germany", "numeric": "276"},
]
_FALLBACK_BY_CODE = {country["code"]: country for country in _FALLBACK_COUNTRIES}


def _normalize_lang(lang: str | None) -> str:
    language = (lang or "es").strip().lower()
    if not language:
        language = "es"
    return language.replace("_", "-")


@lru_cache(maxsize=8)
def _territory_names_for_lang(lang: str) -> dict[str, str]:
    if Locale is None:  
        return {}
    try:
        locale = Locale.parse(lang, sep="-")
    except (ValueError, UnknownLocaleError):
        locale = Locale.parse("es", sep="-")
    territories = locale.territories or {}
    return {code.upper(): name for code, name in territories.items() if isinstance(code, str)}


@lru_cache(maxsize=1)
def _all_country_codes() -> set[str]:
    if pycountry is None:  
        return set(_FALLBACK_BY_CODE.keys())
    return {c.alpha_2 for c in pycountry.countries if getattr(c, "alpha_2", None)}


def _build_country_by_code() -> dict[str, str]:
    """
    Mantiene compatibilidad con el contrato anterior (dict por código).

    Se usa principalmente para validaciones tipo `if code in COUNTRY_BY_CODE:`.
    """
    return {code: code for code in _all_country_codes()}


def country_choices(lang: str | None = None) -> list[tuple[str, str]]:
    """
    Devuelve las opciones de país localizadas para formularios.

    Args:
        lang: Idioma para los nombres de los países (ej. "es", "en", "es-ES").

    Returns:
        Lista de tuplas (codigo_pais, nombre_pais) con nombres localizados.
    """
    language = _normalize_lang(lang)
    territory_names = _territory_names_for_lang(language)

    if pycountry is None:  
        base = language.split("-", 1)[0]
        choices = [
            (country["code"], country.get(f"name_{base}") or country["name_es"])
            for country in _FALLBACK_COUNTRIES
        ]
        return sorted(choices, key=lambda x: x[1].casefold())

    choices: list[tuple[str, str]] = []
    for country in pycountry.countries:
        code = getattr(country, "alpha_2", None)
        if not code:
            continue
        code = code.upper()
        name = territory_names.get(code) or getattr(country, "name", code)
        choices.append((code, name))

    return sorted(choices, key=lambda x: x[1].casefold())


def normalize_country_code(code: str | None) -> str:
    """
    Devuelve un código de país válido o el país por defecto.

    Args:
        code: Código ISO 3166-1 alpha-2.

    Returns:
        Código normalizado o `DEFAULT_COUNTRY_CODE` si no es válido.
    """
    value = (code or DEFAULT_COUNTRY_CODE).strip().upper()
    return value if value in _all_country_codes() else DEFAULT_COUNTRY_CODE


def country_name_for_code(code: str | None, lang: str | None = None) -> str:
    """
    Devuelve el nombre visible del país para un código.

    Args:
        code: Código ISO 3166-1 alpha-2.
        lang: Idioma del nombre (ej. "es", "en").

    Returns:
        Nombre del país localizado cuando sea posible.
    """
    normalized = normalize_country_code(code)
    language = _normalize_lang(lang)

    territory_names = _territory_names_for_lang(language)
    name = territory_names.get(normalized)
    if name:
        return name

    if pycountry is not None:
        c = pycountry.countries.get(alpha_2=normalized)
        if c and getattr(c, "name", None):
            return c.name

    fallback = _FALLBACK_BY_CODE.get(normalized) or _FALLBACK_BY_CODE[DEFAULT_COUNTRY_CODE]
    base = language.split("-", 1)[0]
    return fallback.get(f"name_{base}") or fallback["name_es"]


def country_numeric_for_code(code: str | None) -> str:
    """
    Devuelve el identificador numérico ISO usado por world-atlas.

    Args:
        code: Código ISO 3166-1 alpha-2.

    Returns:
        Identificador numérico ISO (3 dígitos).
    """
    normalized = normalize_country_code(code)

    if pycountry is not None:
        c = pycountry.countries.get(alpha_2=normalized)
        numeric = getattr(c, "numeric", None) if c else None
        if numeric:
            return str(numeric).zfill(3)

    fallback = _FALLBACK_BY_CODE.get(normalized) or _FALLBACK_BY_CODE[DEFAULT_COUNTRY_CODE]
    return fallback["numeric"]


# Mantener compatibilidad con imports existentes (forms.py).
COUNTRY_CHOICES = country_choices("es")

# Mantener compatibilidad con imports existentes (controllers/admin/routes.py).
COUNTRY_BY_CODE = _build_country_by_code()
