"""
Autora: Lydia Blanco Ruiz
Script con las claves de traducción.
"""

LANGUAGE_ES = 'es'
LANGUAGE_EN = 'en'
DEFAULT_LANGUAGE = LANGUAGE_ES
SUPPORTED_LANGUAGES = {
    LANGUAGE_ES: "Español",
    LANGUAGE_EN: "English",
}

SECRET_FIELD_TOKEN = "pass" + "word"
AUTH_FORGOT_SECRET_FIELD_PREFIX = f"auth.forgot_{SECRET_FIELD_TOKEN}"
AUTH_SECRET_FIELD_TITLE_SUFFIX = "_title"

COMMON_USER_LABEL_ES = "Usuario"
COMMON_USER_LABEL_EN = "User"

LOG_IN_LABEL_EN = "Log in"
SECRET_FIELD_TEXT_EN = "Password"
SECRET_FIELD_TEXT_ES = "Contraseña"
MARKDOWN_LABEL = "Markdown"

QUERIES = "Your queries"
AVERAGE_TIME = "Average time"
CONSULTAS = "Tus consultas"
TIEMPO = "Tiempo medio"

JOBS_QUEUED_SHORT = "jobs.queued_short"
RAG_QUEUED = "rag.queued"
RAG_CANCELLING = "rag.cancelling"
RAG_CANCELLED = "rag.cancelled"
RAG_STARTING = "rag.starting"
RAG_DONE = "rag.done"
RAG_FAILED = "rag.failed"
RAG_PREPARING = "rag.preparing"
MARKDOWN_CANCELLING = "markdown.cancelling"
MARKDOWN_CANCELLED = "markdown.cancelled"
MARKDOWN_STARTING = "markdown.starting"
MARKDOWN_NONE_PENDING = "markdown.none_pending"
MARKDOWN_FAILED = "markdown.failed"
VECTOR_CANCELLING = "vector.cancelling"
SCRAPING_CANCELLING = "scraping.cancelling"
SCRAPING_CANCELLED = "scraping.cancelled"
SCRAPING_STARTING = "scraping.starting"
SCRAPING_SCRIPT_1 = "scraping.script_1"
SCRAPING_SCRIPT_2 = "scraping.script_2"
SCRAPING_SYNCING = "scraping.syncing"
SCRAPING_DONE = "scraping.done"
SCRAPING_FAILED = "scraping.failed"
JOBS_ALREADY_FINISHED = "jobs.already_finished"

DIRECT_RUNTIME_MESSAGE_MAP = {
    "En cola": JOBS_QUEUED_SHORT,
    "Consulta en cola.": RAG_QUEUED,
    "Cancelando consulta...": RAG_CANCELLING,
    "Consulta cancelada.": RAG_CANCELLED,
    "Iniciando consulta...": RAG_STARTING,
    "Consulta finalizada.": RAG_DONE,
    "La consulta ha fallado.": RAG_FAILED,
    "Preparando consulta...": RAG_PREPARING,
    "Cancelando Conversión a Markdown...": MARKDOWN_CANCELLING,
    "Conversión a Markdown cancelada.": MARKDOWN_CANCELLED,
    "Iniciando Conversión a Markdown...": MARKDOWN_STARTING,
    "No habia documentos pendientes de convertir.": MARKDOWN_NONE_PENDING,
    "No había documentos pendientes de convertir.": MARKDOWN_NONE_PENDING,
    "Fallo la Conversión a Markdown.": MARKDOWN_FAILED,
    "Falló la Conversión a Markdown.": MARKDOWN_FAILED,
    "Cancelando Actualización vectorial...": VECTOR_CANCELLING,
    "Cancelando ActualizaciÃ³n vectorial...": VECTOR_CANCELLING,
    "Cancelando Web Scraping...": SCRAPING_CANCELLING,
    "Web Scraping cancelado.": SCRAPING_CANCELLED,
    "Iniciando Web Scraping...": SCRAPING_STARTING,
    "Ejecutando script 1/2...": SCRAPING_SCRIPT_1,
    "Ejecutando script 2/2...": SCRAPING_SCRIPT_2,
    "Sincronizando PDFs en la base de datos...": SCRAPING_SYNCING,
    "Web Scraping terminado.": SCRAPING_DONE,
    "Fallo el Web Scraping.": SCRAPING_FAILED,
    "Falló el Web Scraping.": SCRAPING_FAILED,
    "El job ya ha terminado.": JOBS_ALREADY_FINISHED,
}

