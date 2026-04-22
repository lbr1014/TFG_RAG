from app.test.support import BaseAppTestCase

from app.main.code.model.vector_update_state import VectorUpdateState
from app.main.code.extensions import db


class VectorUpdateStateUnitTest(BaseAppTestCase):
    def test_vector_update_state_sets_default_values(self):
        state = VectorUpdateState()
        db.session.add(state)
        db.session.commit()

        self.assertEqual(state.status, "queued")
        self.assertEqual(state.progress, 0)
        self.assertFalse(state.cancel_requested)
        self.assertIsNotNone(state.created_at)

    def test_vector_update_state_tracks_current_doc_and_error(self):
        state = VectorUpdateState(current_doc="doc.pdf", error="boom")

        self.assertEqual(state.current_doc, "doc.pdf")
        self.assertEqual(state.error, "boom")


