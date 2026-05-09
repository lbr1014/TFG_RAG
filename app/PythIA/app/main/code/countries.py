"""
Lista local de paises usada por los formularios y el mapa de estadisticas.
"""

DEFAULT_COUNTRY_CODE = "ES"

COUNTRIES = [
    {"code": "ES", "name_es": "España", "name_en": "Spain", "numeric": "724"},
    {"code": "AD", "name_es": "Andorra", "name_en": "Andorra", "numeric": "020"},
    {"code": "AR", "name_es": "Argentina", "name_en": "Argentina", "numeric": "032"},
    {"code": "BE", "name_es": "Bélgica", "name_en": "Belgium", "numeric": "056"},
    {"code": "BR", "name_es": "Brasil", "name_en": "Brazil", "numeric": "076"},
    {"code": "CA", "name_es": "Canadá", "name_en": "Canada", "numeric": "124"},
    {"code": "CH", "name_es": "Suiza", "name_en": "Switzerland", "numeric": "756"},
    {"code": "CL", "name_es": "Chile", "name_en": "Chile", "numeric": "152"},
    {"code": "CN", "name_es": "China", "name_en": "China", "numeric": "156"},
    {"code": "CO", "name_es": "Colombia", "name_en": "Colombia", "numeric": "170"},
    {"code": "DE", "name_es": "Alemania", "name_en": "Germany", "numeric": "276"},
    {"code": "EC", "name_es": "Ecuador", "name_en": "Ecuador", "numeric": "218"},
    {"code": "FR", "name_es": "Francia", "name_en": "France", "numeric": "250"},
    {"code": "GB", "name_es": "Reino Unido", "name_en": "United Kingdom", "numeric": "826"},
    {"code": "IE", "name_es": "Irlanda", "name_en": "Ireland", "numeric": "372"},
    {"code": "IT", "name_es": "Italia", "name_en": "Italy", "numeric": "380"},
    {"code": "MA", "name_es": "Marruecos", "name_en": "Morocco", "numeric": "504"},
    {"code": "MX", "name_es": "México", "name_en": "Mexico", "numeric": "484"},
    {"code": "NL", "name_es": "Países Bajos", "name_en": "Netherlands", "numeric": "528"},
    {"code": "PE", "name_es": "Perú", "name_en": "Peru", "numeric": "604"},
    {"code": "PT", "name_es": "Portugal", "name_en": "Portugal", "numeric": "620"},
    {"code": "US", "name_es": "Estados Unidos", "name_en": "United States", "numeric": "840"},
    {"code": "UY", "name_es": "Uruguay", "name_en": "Uruguay", "numeric": "858"},
    {"code": "VE", "name_es": "Venezuela", "name_en": "Venezuela", "numeric": "862"},
]

COUNTRY_BY_CODE = {country["code"]: country for country in COUNTRIES}
COUNTRY_CHOICES = [(country["code"], country["name_es"]) for country in COUNTRIES]


def _country_name(country: dict, lang: str | None = None) -> str:
    """Devuelve el nombre del pais segun el idioma activo."""
    language = (lang or "es").lower()
    return country.get(f"name_{language}") or country["name_es"]


def country_choices(lang: str | None = None) -> list[tuple[str, str]]:
    """Devuelve las opciones de pais localizadas para formularios."""
    return [(country["code"], _country_name(country, lang)) for country in COUNTRIES]


def normalize_country_code(code: str | None) -> str:
    """Devuelve un codigo de pais valido o el pais por defecto."""
    code = (code or DEFAULT_COUNTRY_CODE).strip().upper()
    return code if code in COUNTRY_BY_CODE else DEFAULT_COUNTRY_CODE


def country_name_for_code(code: str | None, lang: str | None = None) -> str:
    """Devuelve el nombre visible del pais."""
    return _country_name(COUNTRY_BY_CODE[normalize_country_code(code)], lang)


def country_numeric_for_code(code: str | None) -> str:
    """Devuelve el identificador numerico ISO usado por world-atlas."""
    return COUNTRY_BY_CODE[normalize_country_code(code)]["numeric"]
