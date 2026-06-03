"""
Autora: Lydia Blanco Ruiz
Script con helpers de internacionalización, incluyendo la función de traducción, localización de formularios y mensajes en tiempo de ejecución.
"""

import re

from flask import g, has_request_context, redirect, request, session, url_for
from flask_login import current_user

from .en import TRANSLATIONS_EN
from .es import TRANSLATIONS_ES
from .keys import (
    DEFAULT_LANGUAGE,
    DIRECT_RUNTIME_MESSAGE_MAP,
    LANGUAGE_EN,
    LANGUAGE_ES,
    SUPPORTED_LANGUAGES,
)

TRANSLATIONS = {
    LANGUAGE_ES: TRANSLATIONS_ES,
    LANGUAGE_EN: TRANSLATIONS_EN,
}


def normalize_language(lang) -> str:
    """
    Normaliza un código de idioma.

    Args:
        lang: Código de idioma recibido desde sesión, formulario o cliente.

    Returns:
        Código soportado por la aplicación o el idioma por defecto.
    """
    lang = (lang or "").lower()
    return lang if lang in SUPPORTED_LANGUAGES else DEFAULT_LANGUAGE


def get_locale() -> str:
    """
    Obtiene el idioma activo desde la petición del usuario o desde el perfil de usuario.

    Returns:
        Código de idioma activo o idioma por defecto si no hay petición.
    """
    if not has_request_context():
        return DEFAULT_LANGUAGE

    if session.get("lang"):
        return normalize_language(session["lang"])

    if current_user.is_authenticated:
        return normalize_language(current_user.language)

    return DEFAULT_LANGUAGE


def translate_for(lang, key, **kwargs) -> str:
    """
    Traduce una clave concreta para un idioma.

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
        except (KeyError, IndexError, ValueError):
            return text
    return text


def t(key, **kwargs) -> str:
    """
    Traduce una clave usando el idioma activo.

    Args:
        key: Clave de traducción.
        **kwargs: Valores usados para formatear la traducción.

    Returns:
        Texto traducido para el idioma activo.
    """
    return translate_for(get_locale(), key, **kwargs)


def localize_runtime_message(message, lang=None) -> str:
    """
    Traduce mensajes persistidos o generados en tiempo de ejecución.

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

    # Si el proceso ha persistido directamente una key de i18n devolvemos su traduccion.
    if message in TRANSLATIONS.get(language, {}) or message in TRANSLATIONS.get(DEFAULT_LANGUAGE, {}):
        return translate_for(language, message)

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


def _get_form_field(form, field_name) -> object | None:
    """
    Obtiene un campo del formulario si existe.

    Args:
        form: Formulario Flask-WTF que contiene los campos.
        field_name: Nombre del campo que se quiere localizar.

    Returns:
        Campo del formulario o ``None`` si no existe.
    """
    return getattr(form, field_name, None)


def _localize_field_labels(form) -> None:
    """
    Traduce las etiquetas configuradas en el formulario.

    Args:
        form: Formulario Flask-WTF con el mapa ``i18n_fields``.
    """
    for field_name, key in getattr(form, "i18n_fields", {}).items():
        field = _get_form_field(form, field_name)
        if field is not None:
            field.label.text = t(key)


def _localize_field_placeholders(form) -> None:
    """
    Traduce los placeholders configurados en el formulario.

    Args:
        form: Formulario Flask-WTF con el mapa ``i18n_placeholders``.
    """
    for field_name, key in getattr(form, "i18n_placeholders", {}).items():
        field = _get_form_field(form, field_name)
        if field is not None:
            render_kw = dict(field.render_kw or {})
            render_kw["placeholder"] = t(key)
            field.render_kw = render_kw


def _localize_validator_messages(form) -> None:
    """
    Traduce los mensajes de los validadores configurados.

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


def localize_form(form) -> object:
    """
    Aplica traducciones a etiquetas, placeholders y validadores.

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


def get_client_translations() -> dict[str, str]:
    """
    Obtiene las traducciones que necesita el JavaScript del cliente.

    Returns:
        Diccionario con claves de traducción y textos localizados.
    """
    keys = [
        "common.close",
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
        "rag.view_all_fragments",
        "rag.empty_question",
        "rag.question_too_long",
        "rag.invalid_question",
        "rag.querying",
        "rag.sending",
        "rag.done",
        "rag.cancelled",
        "rag.failed",
        "rag.status_error",
        "rag.unexpected_error",
        "rag.cancel_error",
        "rag.model_usage_empty",
        "rag.fragment_used",
        "rag.evaluation.no_results",
        "rag.evaluation.running",
        "rag.evaluation.failed",
        "rag.evaluation.metric.faithfulness",
        "rag.evaluation.metric.answer_relevancy",
        "rag.evaluation.metric.answer_correctness",
        "rag.evaluation.metric.context_precision",
        "rag.evaluation.metric.context_recall",
        "rag.evaluation.metric.context_relevancy",
        "history.chunks_details",
        "history.best_fragment",
        "history.file",
        "history.title_label",
        "history.segment",
        "history.similarity",
        "history.top_chunks",
        "history.ranking",
        "history.document",
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
        "jobs.done_generic",
        "jobs.cancelled_generic",
        "jobs.failed_generic",
        "docs.no_files_selected",
        "docs.files_selected",
        "tutorial.next",
        "tutorial.prev",
        "tutorial.done",
        "tutorial.progress",
        "tutorial.start.title",
        "tutorial.start.desc",
        "tutorial.nav.home.title",
        "tutorial.nav.home.desc",
        "tutorial.nav.history.title",
        "tutorial.nav.history.desc",
        "tutorial.nav.profile.title",
        "tutorial.nav.profile.desc",
        "tutorial.nav.stats.title",
        "tutorial.nav.stats.desc",
        "tutorial.nav.docs.title",
        "tutorial.nav.docs.desc",
        "tutorial.nav.users.title",
        "tutorial.nav.users.desc",
        "tutorial.nav.theme.title",
        "tutorial.nav.theme.desc",
        "tutorial.nav.i18n.title",
        "tutorial.nav.i18n.desc",
        "tutorial.nav.logout.title",
        "tutorial.nav.logout.desc",
        "tutorial.screen_overview.title",
        "tutorial.screen_overview.desc",
        "tutorial.home.logo.title",
        "tutorial.home.logo.desc",
        "tutorial.home.menu.title",
        "tutorial.home.menu.desc",
        "tutorial.home.rag.title",
        "tutorial.home.rag.desc",
        "tutorial.home.charts.title",
        "tutorial.home.charts.desc",
        "tutorial.home.history_link.title",
        "tutorial.home.history_link.desc",
        "tutorial.history.filter.title",
        "tutorial.history.filter.desc",
        "tutorial.history.apply.title",
        "tutorial.history.apply.desc",
        "tutorial.history.delete.title",
        "tutorial.history.delete.desc",
        "tutorial.stats.user_vs_global.title",
        "tutorial.stats.user_vs_global.desc_admin",
        "tutorial.stats.user_vs_global.desc_user",
        "tutorial.stats.compare.title",
        "tutorial.stats.compare.desc",
        "tutorial.stats.chart_monthly.title",
        "tutorial.stats.chart_monthly.desc",
        "tutorial.stats.chart_calendar.title",
        "tutorial.stats.chart_calendar.desc",
        "tutorial.stats.chart_avg_time.title",
        "tutorial.stats.chart_avg_time.desc",
        "tutorial.stats.chart_weekdays.title",
        "tutorial.stats.chart_weekdays.desc",
        "tutorial.stats.chart_hours.title",
        "tutorial.stats.chart_hours.desc",
        "tutorial.stats.chart_hours_heatmap.title",
        "tutorial.stats.chart_hours_heatmap.desc",
        "tutorial.stats.chart_user_compare.title",
        "tutorial.stats.chart_user_compare.desc",
        "tutorial.stats.chart_locations.title",
        "tutorial.stats.chart_locations.desc",
        "tutorial.stats.ranking.title",
        "tutorial.stats.ranking.desc",
        "tutorial.profile.save.title",
        "tutorial.profile.save.desc",
        "tutorial.profile.delete.title",
        "tutorial.profile.delete.desc",
        "tutorial.rag.models.title",
        "tutorial.rag.models.desc",
        "tutorial.rag.compare.title",
        "tutorial.rag.compare.desc",
        "tutorial.rag.chat_tab.title",
        "tutorial.rag.chat_tab.desc",
        "tutorial.rag.form_tab.title",
        "tutorial.rag.form_tab.desc",
        "tutorial.rag.chat.title",
        "tutorial.rag.chat.desc",
        "tutorial.rag.guided_form.title",
        "tutorial.rag.guided_form.desc",
        "tutorial.rag.ask.title",
        "tutorial.rag.ask.desc",
        "tutorial.rag.answer.title",
        "tutorial.rag.answer.desc",
        "tutorial.rag.fragments.title",
        "tutorial.rag.fragments.desc",
        "tutorial.rag.chat.ask.desc",
        "tutorial.rag.chat.answer.desc",
        "tutorial.rag.chat.fragments.desc",
        "tutorial.rag.form.ask.desc",
        "tutorial.rag.form.answer.desc",
        "tutorial.rag.form.fragments.desc",
        "tutorial.rag.view_all.title",
        "tutorial.rag.view_all.desc",
        "tutorial.model_stats.back.title",
        "tutorial.model_stats.back.desc",
        "tutorial.docs.choose.title",
        "tutorial.docs.choose.desc",
        "tutorial.docs.upload.title",
        "tutorial.docs.upload.desc",
        "tutorial.docs.scraping.title",
        "tutorial.docs.scraping.desc",
        "tutorial.docs.markdown.title",
        "tutorial.docs.markdown.desc",
        "tutorial.docs.vector.title",
        "tutorial.docs.vector.desc",
        "tutorial.docs.filter.title",
        "tutorial.docs.filter.desc",
        "tutorial.docs.apply.title",
        "tutorial.docs.apply.desc",
        "tutorial.docs.delete.title",
        "tutorial.docs.delete.desc",
        "tutorial.users.filter.title",
        "tutorial.users.filter.desc",
        "tutorial.users.apply.title",
        "tutorial.users.apply.desc",
        "tutorial.users.bulk_toggle.title",
        "tutorial.users.bulk_toggle.desc",
        "tutorial.users.bulk_delete.title",
        "tutorial.users.bulk_delete.desc",
        "tutorial.error.no_driver",
        "tutorial.error.no_steps",
        "tutorial.fab_tooltip",
    ]
    return {key: t(key) for key in keys}


def init_app(app) -> None:
    """
    Registra helpers de internacionalización en la aplicación Flask.

    Args:
        app: Aplicación Flask donde se registran hooks, context processors y
            la ruta de cambio de idioma.
    """

    @app.before_request
    def _set_language() -> None:
        """
        Establece el idioma activo en el objeto global de Flask.
        """
        g.locale = get_locale()

    @app.context_processor
    def _inject_i18n() -> dict[str, object]:
        """
            Inyecta funciones y variables de internacionalización en el contexto de las plantillas.

        Returns:
            dict[str, object]: Diccionario con la función de traducción 't', el idioma actual, los idiomas soportados
                y las traducciones para el cliente.
        """
        return {
            "t": t,
            "current_locale": get_locale(),
            "supported_languages": SUPPORTED_LANGUAGES,
            "client_translations": get_client_translations(),
        }

    @app.post("/language")
    def set_language_route() -> object:
        """
        Maneja la solicitud para cambiar el idioma de la aplicación.

        Returns:
            Redirige a la página anterior o a la página de inicio después de actualizar el idioma en la sesión. 
        """
        from app.main.code.forms import LanguageForm

        form = LanguageForm()
        if not form.validate_on_submit():
            return redirect(request.referrer or url_for("main.inicio"))

        lang = normalize_language(form.lang.data)
        session["lang"] = lang
        next_url = form.next.data or request.referrer or url_for("main.inicio")
        return redirect(next_url)
