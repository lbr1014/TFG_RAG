"""
Autora: Lydia Blanco Ruiz
Script con helpers de internacionalización, incluyendo la función de traducción, localización de formularios y mensajes en tiempo de ejecución.
"""

import re

from flask import g, has_request_context, redirect, request, session, url_for
from .español import TRANSLATIONS_ES
from .ingles import TRANSLATIONS_EN
from .keys import LANGUAGE_ES, LANGUAGE_EN, DEFAULT_LANGUAGE, SUPPORTED_LANGUAGES, DIRECT_RUNTIME_MESSAGE_MAP


TRANSLATIONS = {
    LANGUAGE_ES: TRANSLATIONS_ES,
    LANGUAGE_EN: TRANSLATIONS_EN,
}


def normalize_language(lang):
    """Normaliza un código de idioma.

    Args:
        lang: Código de idioma recibido desde sesión, formulario o cliente.

    Returns:
        Código soportado por la aplicación o el idioma por defecto.
    """
    lang = (lang or "").lower()
    return lang if lang in SUPPORTED_LANGUAGES else DEFAULT_LANGUAGE


def get_locale():
    """Obtiene el idioma activo de la petición actual.

    Returns:
        Código de idioma activo o idioma por defecto si no hay petición.
    """
    if has_request_context():
        return normalize_language(session.get("lang"))
    return DEFAULT_LANGUAGE


def translate_for(lang, key, **kwargs):
    """Traduce una clave concreta para un idioma.

    Args:
        lang: Código de idioma solicitado.
        key: Clave de traducción.
        **kwargs: Valores usados para formatear la traducción.

    Returns:
        Texto traducido o la clave original si no existe traducción.
    """
    language = normalize_language(lang)
    text = (
        TRANSLATIONS.get(language, {}).get(key)
        or TRANSLATIONS[DEFAULT_LANGUAGE].get(key)
        or key
    )
    if kwargs:
        try:
            return text.format(**kwargs)
        except Exception:
            return text
    return text


def t(key, **kwargs):
    """Traduce una clave usando el idioma activo.

    Args:
        key: Clave de traducción.
        **kwargs: Valores usados para formatear la traducción.

    Returns:
        Texto traducido para el idioma activo.
    """
    return translate_for(get_locale(), key, **kwargs)


def localize_runtime_message(message, lang=None):
    """Traduce mensajes persistidos o generados en tiempo de ejecución.

    Args:
        message: Mensaje original guardado en base de datos o generado por un
            proceso asíncrono.
        lang: Idioma destino opcional.

    Returns:
        Mensaje localizado si existe una equivalencia conocida.
    """
    if not message:
        return message

    language = normalize_language(lang or get_locale())
    if message in DIRECT_RUNTIME_MESSAGE_MAP:
        return translate_for(language, DIRECT_RUNTIME_MESSAGE_MAP[message])

    markdown_done = re.fullmatch(r"Conversi[oó]n completada\. (\d+) documentos convertidos\.", message)
    if markdown_done:
        return translate_for(language, "markdown.done_stats", count=markdown_done.group(1))

    markdown_done_with_failures = re.fullmatch(
        r"Conversi[oó]n completada\. (\d+) documentos convertidos y (\d+) con error\.",
        message,
    )
    if markdown_done_with_failures:
        return translate_for(
            language,
            "markdown.done_stats_with_failures",
            count=markdown_done_with_failures.group(1),
            failed=markdown_done_with_failures.group(2),
        )

    converting_page = re.fullmatch(r"Convirtiendo (.+)\.\.\. P[aá]gina (\d+)/(\d+)", message)
    if converting_page:
        return translate_for(
            language,
            "markdown.converting_doc_page",
            name=converting_page.group(1),
            page=converting_page.group(2),
            total_pages=converting_page.group(3),
        )

    converting_doc = re.fullmatch(r"Convirtiendo (.+)\.\.\.", message)
    if converting_doc:
        return translate_for(language, "markdown.converting_doc", name=converting_doc.group(1))

    return message


def _get_form_field(form, field_name):
    """Obtiene un campo del formulario si existe.

    Args:
        form: Formulario Flask-WTF que contiene los campos.
        field_name: Nombre del campo que se quiere localizar.

    Returns:
        Campo del formulario o ``None`` si no existe.
    """
    return getattr(form, field_name, None)


def _localize_field_labels(form):
    """Traduce las etiquetas configuradas en el formulario.

    Args:
        form: Formulario Flask-WTF con el mapa ``i18n_fields``.
    """
    for field_name, key in getattr(form, "i18n_fields", {}).items():
        field = _get_form_field(form, field_name)
        if field is not None:
            field.label.text = t(key)


def _localize_field_placeholders(form):
    """Traduce los placeholders configurados en el formulario.

    Args:
        form: Formulario Flask-WTF con el mapa ``i18n_placeholders``.
    """
    for field_name, key in getattr(form, "i18n_placeholders", {}).items():
        field = _get_form_field(form, field_name)
        if field is not None:
            render_kw = dict(field.render_kw or {})
            render_kw["placeholder"] = t(key)
            field.render_kw = render_kw


def _localize_validator_messages(form):
    """Traduce los mensajes de los validadores configurados.

    Args:
        form: Formulario Flask-WTF con el mapa ``i18n_validator_messages``.
    """
    for field_name, validator_messages in getattr(form, "i18n_validator_messages", {}).items():
        field = _get_form_field(form, field_name)
        if field is None:
            continue
        for validator in field.validators:
            key = validator_messages.get(type(validator).__name__)
            if key:
                validator.message = t(key)


def localize_form(form):
    """Aplica traducciones a etiquetas, placeholders y validadores.

    Args:
        form: Formulario Flask-WTF con mapas de internacionalización.

    Returns:
        El mismo formulario con sus textos actualizados.
    """
    if not form:
        return form

    _localize_field_labels(form)
    _localize_field_placeholders(form)
    _localize_validator_messages(form)

    return form


def get_client_translations():
    """Obtiene las traducciones que necesita el JavaScript del cliente.

    Returns:
        Diccionario con claves de traducción y textos localizados.
    """
    keys = [
        "common.loading",
        "validation.required",
        "validation.email",
        "validation.min_length_2",
        "validation.min_length_6",
        "validation.min_length_8",
        "validation.max_length_255",
        "validation.max_length_2000",
        "validation.password_security",
        "validation.summary_title",
        "rag.no_answer",
        "rag.no_chunk",
        "rag.empty_question",
        "rag.question_too_long",
        "rag.invalid_question",
        "rag.querying",
        "rag.sending",
        "rag.cancelled",
        "rag.failed",
        "rag.status_error",
        "rag.unexpected_error",
        "rag.cancel_error",
        "vector.updating",
        "vector.updating_doc",
        "vector.done_ui",
        "vector.cancelled_ui",
        "vector.failed_ui",
        "vector.unknown_state",
        "vector.starting_ui",
        "vector.no_job_id",
        "vector.start_error",
        "vector.status_error",
        "markdown.cancelling",
        "markdown.starting_ui",
        "markdown.no_job_id",
        "markdown.start_error",
        "markdown.status_error",
        "markdown.unknown_state",
        "markdown.done_stats",
        "markdown.done_stats_with_failures",
        "markdown.cancelled",
        "markdown.failed",
        "scraping.done_ui",
        "scraping.cancelled",
        "scraping.failed_ui",
        "scraping.unknown_state",
        "scraping.starting_ui",
        "scraping.no_job_id",
        "scraping.start_error",
        "scraping.status_error",
        "process.cancel_error",
        "process.resume_tracking",
    ]
    return {key: t(key) for key in keys}


def init_app(app):
    """Registra helpers de internacionalización en la aplicación Flask.

    Args:
        app: Aplicación Flask donde se registran hooks, context processors y
            la ruta de cambio de idioma.
    """

    @app.before_request
    def _set_language():
        g.locale = get_locale()

    @app.context_processor
    def _inject_i18n():
        return {
            "t": t,
            "current_locale": get_locale(),
            "supported_languages": SUPPORTED_LANGUAGES,
            "client_translations": get_client_translations(),
        }

    @app.post("/language")
    def set_language_route():
        from app.main.code.forms import LanguageForm

        form = LanguageForm()
        if not form.validate_on_submit():
            return redirect(request.referrer or url_for("main.inicio"))

        lang = normalize_language(form.lang.data)
        session["lang"] = lang
        next_url = form.next.data or request.referrer or url_for("main.inicio")
        return redirect(next_url)
