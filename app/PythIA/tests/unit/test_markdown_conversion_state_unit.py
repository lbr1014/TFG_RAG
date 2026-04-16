"""
Autora: Lydia Blanco Ruiz
Script con pruebas unitarias de las notificaciones de conversion Markdown.
"""

from unittest.mock import patch

from tests.support import BaseAppTestCase

from app.markdown_conversion_state import send_markdown_finished_email


class MarkdownConversionStateNotificationUnitTest(BaseAppTestCase):
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
