from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from flask import g, session

from app.test.support import BaseAppTestCase

from app.main.code.inetrnacionalizacion import tarduccion

class TraduccionUnitTest(BaseAppTestCase):
    def test_normalize_language_accepts_supported_languages_and_defaults(self):
        self.assertEqual(tarduccion.normalize_language("EN"), "en")
        self.assertEqual(tarduccion.normalize_language("xx"), tarduccion.DEFAULT_LANGUAGE)
        self.assertEqual(tarduccion.normalize_language(None), tarduccion.DEFAULT_LANGUAGE)

    def test_translate_for_falls_back_to_default_language_and_formats(self):
        with patch.dict(
            tarduccion.TRANSLATIONS,
            {"es": {"hello": "Hola {name}"}, "en": {}},
            clear=True,
        ):
            self.assertEqual(tarduccion.translate_for("en", "hello", name="Lydia"), "Hola Lydia")
            self.assertEqual(tarduccion.translate_for("es", "missing.key"), "missing.key")

    def test_translate_for_returns_unformatted_text_when_formatting_fails_and_t_uses_locale(self):
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
        with self.app.test_request_context("/"):
            session["lang"] = "en"
            self.assertEqual(tarduccion.get_locale(), "en")

        self.assertEqual(tarduccion.get_locale(), tarduccion.DEFAULT_LANGUAGE)

    def test_localize_runtime_message_translates_known_patterns(self):
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
        with patch("app.main.code.inetrnacionalizacion.tarduccion.t", side_effect=lambda key: f"t:{key}"):
            translations = tarduccion.get_client_translations()

        self.assertEqual(translations["common.loading"], "t:common.loading")
        self.assertEqual(translations["process.resume_tracking"], "t:process.resume_tracking")
        self.assertGreater(len(translations), 40)

    def test_init_app_registers_language_hooks_and_route(self):
        app = MagicMock()
        app.before_request.side_effect = lambda func: func
        app.context_processor.side_effect = lambda func: func
        app.post.return_value = lambda func: func

        tarduccion.init_app(app)

        app.before_request.assert_called_once()
        app.context_processor.assert_called_once()
        app.post.assert_called_once_with("/language")

    def test_init_app_hooks_and_language_route_run_inside_flask_app(self):
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
