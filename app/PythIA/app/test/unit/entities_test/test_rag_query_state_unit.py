from tests.support import BaseAppTestCase

from app.entities.rag_query_state import RAGQueryState
from app.extensions import db


class RAGQueryStateUnitTest(BaseAppTestCase):
    def test_rag_query_state_sets_default_values(self):
        user = self.create_user()
        state = RAGQueryState(user_id=user.id, question="Pregunta")
        db.session.add(state)
        db.session.commit()

        self.assertEqual(state.status, "queued")
        self.assertFalse(state.cancel_requested)
        self.assertIsNone(state.result_payload)
        self.assertIsNotNone(state.created_at)

    def test_rag_query_state_stores_result_payload(self):
        user = self.create_user()
        payload = {"answer": "Respuesta"}
        state = RAGQueryState(user_id=user.id, question="Pregunta", result_payload=payload)
        db.session.add(state)
        db.session.commit()

        self.assertEqual(state.result_payload, payload)
