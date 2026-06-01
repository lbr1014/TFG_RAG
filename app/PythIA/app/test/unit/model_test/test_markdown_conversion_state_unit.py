"""
Script con pruebas unitarias del estado MarkdownConversionState, utilizado para monitorizar el estado de las tareas de conversión de documentos a Markdown.
Las pruebas verifican la correcta inicialización de los estados y el almacenamiento de información de progreso durante la ejecución.
"""

from app.main.code.extensions import db
from app.main.code.model.markdown_conversion_state import MarkdownConversionState
from app.test.support import BaseAppTestCase


class MarkdownConversionStateUnitTest(BaseAppTestCase):
    def test_markdown_conversion_state_sets_default_values(self):
        """
        Verifica que las tareas de conversión Markdown se inicializan con los valores predeterminados esperados.
        """
        state = MarkdownConversionState()
        db.session.add(state)
        db.session.commit()

        self.assertEqual(state.status, "queued")
        self.assertEqual(state.progress, 0)
        self.assertFalse(state.cancel_requested)
        self.assertIsNotNone(state.created_at)

    def test_markdown_conversion_state_accepts_running_fields(self):
        """
        Comprueba que el modelo almacena correctamente el estado, progreso y mensajes durante una conversión en ejecución.
        """
        state = MarkdownConversionState(status="running", progress=45, message="Procesando")

        self.assertEqual(state.status, "running")
        self.assertEqual(state.progress, 45)
        self.assertEqual(state.message, "Procesando")


