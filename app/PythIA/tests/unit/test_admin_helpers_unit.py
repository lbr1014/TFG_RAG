"""
Autora: Lydia Blanco Ruiz
Script con pruebas unitarias de los helpers de administracion.
"""

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from tests.support import BaseAppTestCase

from app.admin import routes as admin_routes
from app.documentos import JobCancelledError
from app.entities.markdown_conversion_state import MarkdownConversionState
from app.extensions import db


class AdminHelpersUnitTest(BaseAppTestCase):
    def test_fit_job_message_truncates_long_messages(self):
        self.assertIsNone(admin_routes._fit_job_message(None))
        self.assertEqual(admin_routes._fit_job_message("abc", max_length=3), "abc")
        self.assertEqual(admin_routes._fit_job_message("abcdef", max_length=5), "ab...")

    def test_mark_job_helpers_update_common_state(self):
        job = SimpleNamespace(status="queued", progress=0, error="old", message=None, finished_at=None)

        admin_routes._mark_job_running(job, progress=25, message="Procesando")
        self.assertEqual(job.status, "running")
        self.assertEqual(job.progress, 25)
        self.assertIsNone(job.error)

        admin_routes._mark_job_done(job, message="Listo")
        self.assertEqual(job.status, "done")
        self.assertEqual(job.progress, 100)
        self.assertIsNotNone(job.finished_at)

        admin_routes._mark_job_failed(job, RuntimeError("boom"), message="Fallo")
        self.assertEqual(job.status, "failed")
        self.assertEqual(job.error, "boom")

        admin_routes._mark_job_cancelled(job, message="Cancelado")
        self.assertEqual(job.status, "cancelled")
        self.assertIsNone(job.error)

    def test_markdown_done_message_chooses_expected_translation_key(self):
        with patch("app.admin.routes.translate_for", side_effect=lambda lang, key, **kwargs: key):
            self.assertEqual(
                admin_routes._markdown_done_message({"converted": 0, "failed": 0}, "es"),
                "markdown.none_pending",
            )
            self.assertEqual(
                admin_routes._markdown_done_message({"converted": 1, "failed": 2}, "es"),
                "markdown.done_stats_with_failures",
            )
            self.assertEqual(
                admin_routes._markdown_done_message({"converted": 2, "failed": 0}, "es"),
                "markdown.done_stats",
            )

    @patch("app.admin.routes.translate_for", side_effect=lambda lang, key, **kwargs: f"{key}:{kwargs}")
    def test_build_markdown_callbacks_update_progress_message_and_cancel(self, _mock_translate):
        job = MarkdownConversionState(status="running", progress=0, message="Convirtiendo anterior...", cancel_requested=False)
        db.session.add(job)
        db.session.commit()

        should_cancel, on_progress, on_current_doc, on_page_start = admin_routes._build_markdown_callbacks(job, "es")

        self.assertFalse(should_cancel())
        on_progress(1, 4)
        self.assertEqual(job.progress, 25)

        on_current_doc("pliego.pdf")
        self.assertIn("pliego.pdf", job.message)

        on_page_start(1, 2, 1, 4)
        self.assertEqual(job.progress, 12)
        self.assertIn("markdown.converting_doc_page", job.message)

        job.cancel_requested = True
        db.session.commit()
        with self.assertRaises(JobCancelledError):
            on_progress(2, 4)

    def test_send_email_safe_swallows_mail_errors(self):
        send_fn = MagicMock(side_effect=RuntimeError("smtp"))

        with patch.object(self.app.logger, "exception"):
            admin_routes._send_email_safe(send_fn, "No se pudo enviar", to_email="a@example.com")

        send_fn.assert_called_once_with(to_email="a@example.com")
