"""
Autora: Lydia Blanco Ruiz
Script con pruebas unitarias de las notificaciones de actualizacion vectorial.
"""

from unittest.mock import patch

from app.test.support import BaseAppTestCase

from app.main.code.services.vector_update_state import send_update_finished_email


class VectorUpdateStateNotificationUnitTest(BaseAppTestCase):
    @patch("app.main.code.services.vector_update_state.mail.send")
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

    @patch("app.main.code.services.vector_update_state.mail.send")
    def test_send_update_finished_email_uses_explicit_url_and_metrics(self, mock_send):
        send_update_finished_email(
            "user@example.com",
            ok=True,
            message="Vector listo",
            job_id=9,
            docs_url="http://docs.local/list",
            indexed_docs=3,
            failed_docs=1,
        )

        msg = mock_send.call_args.args[0]
        self.assertIn("finalizada", msg.subject)
        self.assertEqual(msg.recipients, ["user@example.com"])
        self.assertIn("Vector listo", msg.body)
        self.assertIn("Job ID: 9", msg.body)
        self.assertIn("Documentos indexados: 3", msg.body)
        self.assertIn("Documentos con error: 1", msg.body)
        self.assertIn("http://docs.local/list", msg.body)

    @patch("app.main.code.services.vector_update_state.mail.send")
    def test_send_update_finished_email_uses_relative_fallback_without_frontend_base_url(self, mock_send):
        self.app.config["FRONTEND_BASE_URL"] = ""

        send_update_finished_email(
            "user@example.com",
            ok=True,
            message="Vector listo",
            job_id=10,
        )

        msg = mock_send.call_args.args[0]
        self.assertIn("/admin/documents/list", msg.body)
