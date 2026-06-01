"""
Pruebas unitarias del estado VectorUpdateState, utilizado para monitorizar las tareas de actualización de la base de datos vectorial. 
Su objetivo es verificar la correcta gestión del estado, progreso, documentos procesados y errores durante la indexación.
"""

from app.main.code.extensions import db
from app.main.code.model.vector_update_state import VectorUpdateState
from app.test.support import BaseAppTestCase


class VectorUpdateStateUnitTest(BaseAppTestCase):
    def test_vector_update_state_sets_default_values(self):
        """
        Verifica que las tareas de actualización vectorial se crean con los valores predeterminados esperados.
        """
        state = VectorUpdateState()
        db.session.add(state)
        db.session.commit()

        self.assertEqual(state.status, "queued")
        self.assertEqual(state.progress, 0)
        self.assertFalse(state.cancel_requested)
        self.assertIsNotNone(state.created_at)

    def test_vector_update_state_tracks_current_doc_and_error(self):
        """
        Comprueba que el modelo registra correctamente el documento que se está procesando y los errores producidos durante la ejecución.
        """
        state = VectorUpdateState(current_doc="doc.pdf", error="boom")

        self.assertEqual(state.current_doc, "doc.pdf")
        self.assertEqual(state.error, "boom")

        state.set_current_doc("otro.pdf")
        self.assertEqual(state.current_doc, "otro.pdf")


