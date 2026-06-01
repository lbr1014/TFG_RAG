"""
Pruebas unitarias del estado WebScrapingState, encargado de almacenar el estado de las tareas de extracción automática de documentos mediante 
web scraping. Las pruebas verifican la correcta inicialización de los trabajos y el almacenamiento de mensajes y errores asociados a su ejecución.
"""

from app.main.code.extensions import db
from app.main.code.model.web_scraping_state import WebScrapingSate
from app.test.support import BaseAppTestCase


class WebScrapingSateUnitTest(BaseAppTestCase):
    def test_web_scraping_state_sets_default_values(self):
        """
        Verifica que las tareas de scraping se inicializan correctamente con los valores por defecto establecidos.
        """
        state = WebScrapingSate()
        db.session.add(state)
        db.session.commit()

        self.assertEqual(state.status, "queued")
        self.assertEqual(state.progress, 0)
        self.assertFalse(state.cancel_requested)
        self.assertIsNotNone(state.created_at)

    def test_web_scraping_state_accepts_status_message_and_error(self):
        """
        Comprueba que el modelo almacena correctamente estados personalizados, mensajes informativos y detalles de error.
        """
        state = WebScrapingSate(status="failed", message="Fallo", error="boom")

        self.assertEqual(state.status, "failed")
        self.assertEqual(state.message, "Fallo")
        self.assertEqual(state.error, "boom")


