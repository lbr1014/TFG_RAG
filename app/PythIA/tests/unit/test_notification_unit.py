"""
Autora: Lydia Blanco Ruiz
Script con pruebas unitarias de notificaciones de procesos asincronos.
"""

from unittest.mock import patch

from tests.support import BaseAppTestCase

from app.markdown_conversion_state import send_markdown_finished_email
from app.vector_update_state import send_update_finished_email
from app.web_scraping_state import send_scraping_finished_email


class NotificationUnitTest(BaseAppTestCase):
    @patch("app.markdown_conversion_state.mail.send")
    def test_send_markdown_finished_email_includes_metrics_and_url(self, mock_send):
        send_markdown_finished_email(
            "user@example.com",
            ok=True,
            message="Markdown listo",
            job_id=7,
            docs_url="http://localhost/admin/documents/list",
            converted_docs=2,
            skipped_docs=1,
        )

        msg = mock_send.call_args.args[0]
        self.assertEqual(msg.recipients, ["user@example.com"])
        self.assertIn("Conversi", msg.subject)
        self.assertIn("Documentos convertidos: 2", msg.body)
        self.assertIn("http://localhost/admin/documents/list", msg.body)

    @patch("app.vector_update_state.mail.send")
    def test_send_update_finished_email_uses_frontend_base_url_fallback(self, mock_send):
        self.app.config["FRONTEND_BASE_URL"] = "http://frontend.local/"

        send_update_finished_email(
            "user@example.com",
            ok=False,
            message="Vector fallo",
            job_id=8,
            indexed_docs=None,
            failed_docs=None,
        )

        msg = mock_send.call_args.args[0]
        self.assertIn("fallida", msg.subject)
        self.assertIn("Sin m", msg.body)
        self.assertIn("http://frontend.local/admin/documents/list", msg.body)

    @patch("app.web_scraping_state.mail.send")
    def test_send_scraping_finished_email_includes_scraping_metrics(self, mock_send):
        send_scraping_finished_email(
            "user@example.com",
            ok=True,
            message="Scraping listo",
            job_id=9,
            extracted_docs=3,
            synced_total_docs=5,
        )

        msg = mock_send.call_args.args[0]
        self.assertIn("Web scraping finalizado", msg.subject)
        self.assertIn("Documentos extra", msg.body)
        self.assertIn("Documentos sincronizados", msg.body)
