from tests.support import BaseAppTestCase

from app.entities.web_scraping_state import WebScrapingSate
from app.extensions import db


class WebScrapingSateUnitTest(BaseAppTestCase):
    def test_web_scraping_state_sets_default_values(self):
        state = WebScrapingSate()
        db.session.add(state)
        db.session.commit()

        self.assertEqual(state.status, "queued")
        self.assertEqual(state.progress, 0)
        self.assertFalse(state.cancel_requested)
        self.assertIsNotNone(state.created_at)

    def test_web_scraping_state_accepts_status_message_and_error(self):
        state = WebScrapingSate(status="failed", message="Fallo", error="boom")

        self.assertEqual(state.status, "failed")
        self.assertEqual(state.message, "Fallo")
        self.assertEqual(state.error, "boom")
