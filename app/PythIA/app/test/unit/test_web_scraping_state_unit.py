"""
Autora: Lydia Blanco Ruiz
Script con pruebas unitarias de las notificaciones de web scraping.
"""

from unittest.mock import patch

from tests.support import BaseAppTestCase

from app.web_scraping_state import send_scraping_finished_email


class WebScrapingStateNotificationUnitTest(BaseAppTestCase):
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
