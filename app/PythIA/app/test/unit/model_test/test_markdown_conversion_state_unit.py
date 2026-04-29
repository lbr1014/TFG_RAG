from app.test.support import BaseAppTestCase

from app.main.code.model.markdown_conversion_state import MarkdownConversionState
from app.main.code.extensions import db


class MarkdownConversionStateUnitTest(BaseAppTestCase):
    def test_markdown_conversion_state_sets_default_values(self):
        state = MarkdownConversionState()
        db.session.add(state)
        db.session.commit()

        self.assertEqual(state.status, "queued")
        self.assertEqual(state.progress, 0)
        self.assertFalse(state.cancel_requested)
        self.assertIsNotNone(state.created_at)

    def test_markdown_conversion_state_accepts_running_fields(self):
        state = MarkdownConversionState(status="running", progress=45, message="Procesando")

        self.assertEqual(state.status, "running")
        self.assertEqual(state.progress, 45)
        self.assertEqual(state.message, "Procesando")


