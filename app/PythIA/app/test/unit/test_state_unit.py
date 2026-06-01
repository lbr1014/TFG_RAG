"""
Autora: Lydia Blanco Ruiz
Script con pruebas unitarias de los sistemas de notificación asociados a las tareas asíncronas de la aplicación. 
Su objetivo es verificar que los correos electrónicos enviados tras la finalización de procesos de actualización 
de la base de datos vectorial y de web scraping contienen correctamente el estado de la operación, las métricas 
de procesamiento obtenidas y los enlaces necesarios para acceder a la gestión documental. Las pruebas cubren 
distintos escenarios de generación de mensajes, construcción de URLs y presentación de información relevante para el usuario.
"""

from unittest.mock import patch

from app.main.code.services.vector_update_state import send_update_finished_email
from app.main.code.services.web_scraping_state import send_scraping_finished_email
from app.test.support import BaseAppTestCase


class VectorUpdateStateNotificationUnitTest(BaseAppTestCase):
    @patch("app.main.code.services.vector_update_state.mail.send")
    def test_send_update_finished_email_uses_frontend_base_url_fallback(self, mock_send):
        """
        Verifica que, cuando no se proporciona una URL explícita, el correo de notificación utiliza correctamente 
        la URL base configurada para construir el enlace de acceso a los documentos.        
        """
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
        """
        Comprueba que el correo electrónico incluye correctamente la URL proporcionada, las métricas de 
        indexación, el identificador de la tarea y el mensaje asociado al resultado de la actualización vectorial.
        """
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
        """
        Verifica que, cuando no existe una URL base configurada ni una URL explícita, el sistema genera 
        correctamente una ruta relativa de acceso a la gestión documental.
        """
        self.app.config["FRONTEND_BASE_URL"] = ""

        send_update_finished_email(
            "user@example.com",
            ok=True,
            message="Vector listo",
            job_id=10,
        )

        msg = mock_send.call_args.args[0]
        self.assertIn("/admin/documents/list", msg.body)
        
class WebScrapingStateNotificationUnitTest(BaseAppTestCase):
    @patch("app.main.code.services.web_scraping_state.mail.send")
    def test_send_scraping_finished_email_includes_scraping_metrics(self, mock_send):
        """
        Verifica que el correo electrónico enviado tras finalizar una tarea de web scraping incluye correctamente el asunto, 
        el mensaje informativo y las métricas relacionadas con el número de documentos extraídos y sincronizados durante el proceso.
        """
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

