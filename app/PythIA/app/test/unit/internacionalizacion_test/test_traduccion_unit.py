"""
Pruebas unitarias para el módulo de internacionalización y traducción.
Su objetivo es verificar el correcto funcionamiento de la gestión de idiomas, la recuperación de traducciones, la localización dinámica de mensajes, 
la traducción de formularios y la inicialización de los componentes de internacionalización dentro de Flask. Las pruebas garantizan que la aplicación pueda mostrar 
correctamente textos y mensajes en distintos idiomas, así como gestionar adecuadamente situaciones en las que faltan traducciones o configuraciones específicas.
"""

import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from flask import g, session

from app.main.code.inetrnacionalizacion import tarduccion
from app.test.support import BaseAppTestCase


class TraduccionUnitTest(BaseAppTestCase):
    def test_normalize_language_accepts_supported_languages_and_defaults(self):
        """
        Verifica que los códigos de idioma válidos se normalizan correctamente y que se utiliza el idioma por defecto cuando se recibe un valor no soportado o nulo
        """
        self.assertEqual(tarduccion.normalize_language("EN"), "en")
        self.assertEqual(tarduccion.normalize_language("xx"), tarduccion.DEFAULT_LANGUAGE)
        self.assertEqual(tarduccion.normalize_language(None), tarduccion.DEFAULT_LANGUAGE)

    def test_translate_for_falls_back_to_default_language_and_formats(self):
        """
        Comprueba que el sistema utiliza correctamente las traducciones de respaldo cuando faltan en el idioma solicitado y que realiza la sustitución de parámetros en los mensajes traducidos
        """
        with patch.dict(
            tarduccion.TRANSLATIONS,
            {"es": {"hello": "Hola {name}"}, "en": {}},
            clear=True,
        ):
            self.assertEqual(tarduccion.translate_for("en", "hello", name="Lydia"), "Hola Lydia")
            self.assertEqual(tarduccion.translate_for("es", "missing.key"), "missing.key")

    def test_translate_for_returns_unformatted_text_when_formatting_fails_and_t_uses_locale(self):
        """
        Verifica que, si falla el formateo de una traducción, se devuelve el texto original, y que la función de traducción utiliza correctamente el idioma activo de la sesión para recuperar las traducciones.
        """
        with patch.dict(
            tarduccion.TRANSLATIONS,
            {"es": {"hello": "Hola {name}"}, "en": {}},
            clear=True,
        ):
            self.assertEqual(tarduccion.translate_for("es", "hello", missing="Lydia"), "Hola {name}")

        with self.app.test_request_context("/"):
            session["lang"] = "en"
            with patch("app.main.code.inetrnacionalizacion.tarduccion.translate_for", return_value="translated") as mock_translate:
                self.assertEqual(tarduccion.t("common.loading"), "translated")
        mock_translate.assert_called_once_with("en", "common.loading")

    def test_get_locale_uses_session_inside_request_context(self):
        """
        Comprueba que el idioma actual se obtiene correctamente desde la sesión del usuario cuando existe un contexto de petición activo.
        """
        with self.app.test_request_context("/"):
            session["lang"] = "en"
            self.assertEqual(tarduccion.get_locale(), "en")

        self.assertEqual(tarduccion.get_locale(), tarduccion.DEFAULT_LANGUAGE)

    def test_localize_runtime_message_translates_known_patterns(self):
        """
        Verifica la traducción dinámica de mensajes generados durante la ejecución de la aplicación, identificando y traduciendo patrones de mensajes conocidos.
        """
        with patch("app.main.code.inetrnacionalizacion.tarduccion.translate_for", side_effect=lambda lang, key, **kwargs: f"{key}:{kwargs}"):
            self.assertEqual(tarduccion.localize_runtime_message("", "en"), "")
            self.assertIn(
                "jobs.queued_short",
                tarduccion.localize_runtime_message("En cola", "en"),
            )
            self.assertIn(
                "markdown.done_stats",
                tarduccion.localize_runtime_message("Conversion completada. 2 documentos convertidos.", "en"),
            )
            self.assertIn(
                "markdown.done_stats_with_failures",
                tarduccion.localize_runtime_message("Conversión completada. 2 documentos convertidos y 1 con error.", "en"),
            )
            self.assertIn(
                "markdown.converting_doc_page",
                tarduccion.localize_runtime_message("Convirtiendo doc.pdf... Pagina 1/3", "en"),
            )
            self.assertIn(
                "markdown.converting_doc",
                tarduccion.localize_runtime_message("Convirtiendo doc.pdf...", "en"),
            )
            self.assertEqual(tarduccion.localize_runtime_message("Sin patron", "en"), "Sin patron")

    def test_localize_form_updates_labels_placeholders_and_validator_messages(self):
        """
        Comprueba que la localización de formularios actualiza correctamente etiquetas, textos de ayuda y mensajes de validación utilizando las traducciones definidas.
        """
        validator = SimpleNamespace(message="old")
        field = SimpleNamespace(
            label=SimpleNamespace(text="old"),
            render_kw=None,
            validators=[validator],
        )
        form = SimpleNamespace(
            nombre=field,
            i18n_fields={"nombre": "common.name"},
            i18n_placeholders={"nombre": "placeholder.key"},
            i18n_validator_messages={"nombre": {"SimpleNamespace": "validation.required"}},
        )

        with patch("app.main.code.inetrnacionalizacion.tarduccion.t", side_effect=lambda key: f"t:{key}"):
            result = tarduccion.localize_form(form)

        self.assertIs(result, form)
        self.assertEqual(field.label.text, "t:common.name")
        self.assertEqual(field.render_kw["placeholder"], "t:placeholder.key")
        self.assertEqual(validator.message, "t:validation.required")

    def test_localize_form_returns_empty_form_and_skips_missing_fields_or_validator_keys(self):
        """
        Verifica que la localización de formularios gestiona correctamente formularios vacíos o configuraciones incompletas sin producir errores.
        """
        validator = SimpleNamespace(message="old")
        field = SimpleNamespace(label=SimpleNamespace(text="old"), render_kw={"class": "input"}, validators=[validator])
        form = SimpleNamespace(
            nombre=field,
            i18n_fields={"missing": "common.name"},
            i18n_placeholders={"nombre": "placeholder.key"},
            i18n_validator_messages={"missing": {"SimpleNamespace": "validation.required"}, "nombre": {}},
        )

        self.assertIsNone(tarduccion.localize_form(None))
        with patch("app.main.code.inetrnacionalizacion.tarduccion.t", side_effect=lambda key: f"t:{key}"):
            result = tarduccion.localize_form(form)

        self.assertIs(result, form)
        self.assertEqual(field.label.text, "old")
        self.assertEqual(field.render_kw, {"class": "input", "placeholder": "t:placeholder.key"})
        self.assertEqual(validator.message, "old")

    def test_get_client_translations_returns_expected_keys(self):
        """
        Comprueba que el conjunto de traducciones enviado al cliente contiene las claves esperadas y el contenido necesario para la interfaz web.
        """
        with patch("app.main.code.inetrnacionalizacion.tarduccion.t", side_effect=lambda key: f"t:{key}"):
            translations = tarduccion.get_client_translations()

        self.assertEqual(translations["common.loading"], "t:common.loading")
        self.assertEqual(translations["process.resume_tracking"], "t:process.resume_tracking")
        self.assertGreater(len(translations), 40)

    def test_init_app_registers_language_hooks_and_route(self):
        """
        Verifica que la inicialización del módulo registra correctamente los hooks y rutas necesarios para la gestión de idiomas en Flask.
        """
        app = MagicMock()
        app.before_request.side_effect = lambda func: func
        app.context_processor.side_effect = lambda func: func
        app.post.return_value = lambda func: func

        tarduccion.init_app(app)

        app.before_request.assert_called_once()
        app.context_processor.assert_called_once()
        app.post.assert_called_once_with("/language")

    def test_init_app_hooks_and_language_route_run_inside_flask_app(self):
        """
        Comprueba el funcionamiento integrado de los mecanismos de internacionalización dentro de la aplicación Flask, incluyendo la selección de idioma y el cambio dinámico de idioma mediante rutas específicas.
        """
        with self.app.test_request_context("/?x=1"):
            session["lang"] = "en"
            self.app.preprocess_request()
            self.assertEqual(g.locale, "en")

        context = {}
        with patch("app.main.code.inetrnacionalizacion.tarduccion.get_client_translations", return_value={"common.loading": "Loading"}):
            self.app.update_template_context(context)
        self.assertIs(context["t"], tarduccion.t)
        self.assertIn("current_locale", context)
        self.assertEqual(context["client_translations"], {"common.loading": "Loading"})

        invalid = self.client.post("/language", data={}, headers={"Referer": "/previous"})
        self.assertEqual(invalid.status_code, 302)
        self.assertEqual(invalid.headers["Location"], "/previous")

        valid = self.client.post("/language", data={"lang": "en", "next": "/target"})
        self.assertEqual(valid.status_code, 302)
        self.assertEqual(valid.headers["Location"], "/target")
        with self.client.session_transaction() as client_session:
            self.assertEqual(client_session["lang"], "en")
            
class TarduccionRuntimeMessagesUnitTest(unittest.TestCase):
    def test_localize_runtime_message_translates_when_message_is_i18n_key(self):
        """
        Verifica que los mensajes de ejecución que corresponden a claves de internacionalización 
        son traducidos correctamente al idioma solicitado utilizando el sistema de traducciones de la aplicación.
        """
        out = tarduccion.localize_runtime_message("common.email", lang="es")
        self.assertNotEqual(out, "common.email")
        self.assertTrue(out)

