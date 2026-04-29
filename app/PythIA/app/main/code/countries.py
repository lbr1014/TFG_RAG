"""
Lista local de paises usada por los formularios y el mapa de estadisticas.
"""

DEFAULT_COUNTRY_CODE = "ES"

COUNTRIES = [
    {"code": "ES", "name": "Espana", "numeric": "724"},
    {"code": "AD", "name": "Andorra", "numeric": "020"},
    {"code": "AR", "name": "Argentina", "numeric": "032"},
    {"code": "BE", "name": "Belgica", "numeric": "056"},
    {"code": "BR", "name": "Brasil", "numeric": "076"},
    {"code": "CA", "name": "Canada", "numeric": "124"},
    {"code": "CH", "name": "Suiza", "numeric": "756"},
    {"code": "CL", "name": "Chile", "numeric": "152"},
    {"code": "CN", "name": "China", "numeric": "156"},
    {"code": "CO", "name": "Colombia", "numeric": "170"},
    {"code": "DE", "name": "Alemania", "numeric": "276"},
    {"code": "EC", "name": "Ecuador", "numeric": "218"},
    {"code": "FR", "name": "Francia", "numeric": "250"},
    {"code": "GB", "name": "Reino Unido", "numeric": "826"},
    {"code": "IE", "name": "Irlanda", "numeric": "372"},
    {"code": "IT", "name": "Italia", "numeric": "380"},
    {"code": "MA", "name": "Marruecos", "numeric": "504"},
    {"code": "MX", "name": "Mexico", "numeric": "484"},
    {"code": "NL", "name": "Paises Bajos", "numeric": "528"},
    {"code": "PE", "name": "Peru", "numeric": "604"},
    {"code": "PT", "name": "Portugal", "numeric": "620"},
    {"code": "US", "name": "Estados Unidos", "numeric": "840"},
    {"code": "UY", "name": "Uruguay", "numeric": "858"},
    {"code": "VE", "name": "Venezuela", "numeric": "862"},
]

COUNTRY_BY_CODE = {country["code"]: country for country in COUNTRIES}
COUNTRY_CHOICES = [(country["code"], country["name"]) for country in COUNTRIES]


def normalize_country_code(code: str | None) -> str:
    """Devuelve un codigo de pais valido o el pais por defecto."""
    code = (code or DEFAULT_COUNTRY_CODE).strip().upper()
    return code if code in COUNTRY_BY_CODE else DEFAULT_COUNTRY_CODE


def country_name_for_code(code: str | None) -> str:
    """Devuelve el nombre visible del pais."""
    return COUNTRY_BY_CODE[normalize_country_code(code)]["name"]


def country_numeric_for_code(code: str | None) -> str:
    """Devuelve el identificador numerico ISO usado por world-atlas."""
    return COUNTRY_BY_CODE[normalize_country_code(code)]["numeric"]
