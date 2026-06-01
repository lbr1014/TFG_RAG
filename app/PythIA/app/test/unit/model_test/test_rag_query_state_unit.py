"""
Script con pruebas unitarias del estado RAGQueryState, encargado de gestionar el estado de las consultas RAG ejecutadas de forma asíncrona. 
Su objetivo es verificar la correcta inicialización de las consultas y el almacenamiento de los resultados generados.
"""

from app.main.code.extensions import db
from app.main.code.model.rag_query_state import RAGQueryState
from app.test.support import BaseAppTestCase


class RAGQueryStateUnitTest(BaseAppTestCase):
    def test_rag_query_state_sets_default_values(self):
        """
        Verifica que las consultas RAG se inicializan correctamente con los valores por defecto establecidos.
        """
        user = self.create_user()
        state = RAGQueryState(user_id=user.id, question="Pregunta")
        db.session.add(state)
        db.session.commit()

        self.assertEqual(state.status, "queued")
        self.assertFalse(state.cancel_requested)
        self.assertIsNone(state.result_payload)
        self.assertIsNotNone(state.created_at)

    def test_rag_query_state_stores_result_payload(self):
        """
        Comprueba que los resultados generados por una consulta RAG se almacenan correctamente en el estado asociado.
        """
        user = self.create_user()
        payload = {"answer": "Respuesta"}
        state = RAGQueryState(user_id=user.id, question="Pregunta", result_payload=payload)
        db.session.add(state)
        db.session.commit()

        self.assertEqual(state.result_payload, payload)


