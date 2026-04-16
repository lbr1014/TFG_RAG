"""
Autora: Lydia Blanco Ruiz
Script con pruebas unitarias de las notificaciones de actualizacion vectorial.
"""

from unittest.mock import patch

from tests.support import BaseAppTestCase

from app.vector_update_state import send_update_finished_email


class VectorUpdateStateNotificationUnitTest(BaseAppTestCase):
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
