"""
Autora: Lydia Blanco Ruiz
Script con pruebas de integracion de las rutas RAG.
"""

from unittest.mock import patch

from tests.support import BaseAppTestCase

from app.entities.rag_query_state import RAGQueryState
from app.extensions import db


class RAGRoutesIntegrationTest(BaseAppTestCase):
    def setUp(self):
        super().setUp()
        self.user = self.create_user(email="rag@example.com")
        self.login(self.user.email)

    def test_rag_page_requires_login_and_renders_for_authenticated_user(self):
        response = self.client.get("/rag/")

        self.assertEqual(response.status_code, 200)
        self.assertIn(b"<form", response.data)

    @patch("app.rag.routes.executor.submit")
    def test_rag_ask_creates_queued_job(self, mock_submit):
        response = self.client.post("/rag/ask", data={"question": "Que dice el pliego?"})

        self.assertEqual(response.status_code, 202)
        job_id = response.get_json()["job_id"]
        job = db.session.get(RAGQueryState, job_id)
        self.assertEqual(job.user_id, self.user.id)
        self.assertEqual(job.status, "queued")
        mock_submit.assert_called_once()

    @patch("app.rag.routes.executor.submit")
    def test_rag_ask_reuses_active_job_for_same_user(self, mock_submit):
        active_job = RAGQueryState(user_id=self.user.id, question="Anterior", status="running")
        db.session.add(active_job)
        db.session.commit()

        response = self.client.post("/rag/ask", data={"question": "Nueva pregunta"})

        self.assertEqual(response.status_code, 202)
        self.assertEqual(response.get_json()["job_id"], active_job.id)
        self.assertTrue(response.get_json()["reused"])
        mock_submit.assert_not_called()

    def test_rag_status_only_allows_owner(self):
        owner = self.create_user(email="owner-rag@example.com")
        job = RAGQueryState(
            user_id=owner.id,
            question="Privada",
            status="done",
            message="Lista",
            result_payload={"answer": "ok"},
        )
        db.session.add(job)
        db.session.commit()

        forbidden = self.client.get(f"/rag/status/{job.id}")
        self.assertEqual(forbidden.status_code, 404)

        self.login(owner.email)
        allowed = self.client.get(f"/rag/status/{job.id}")
        self.assertEqual(allowed.status_code, 200)
        self.assertEqual(allowed.get_json()["result"], {"answer": "ok"})

    def test_rag_cancel_marks_queued_job_as_cancelled(self):
        job = RAGQueryState(user_id=self.user.id, question="Cancelar", status="queued", message="En cola")
        db.session.add(job)
        db.session.commit()

        response = self.client.post(f"/rag/cancel/{job.id}")

        self.assertEqual(response.status_code, 202)
        db.session.refresh(job)
        self.assertTrue(job.cancel_requested)
        self.assertEqual(job.status, "cancelled")
        self.assertIsNotNone(job.finished_at)

    def test_rag_cancel_finished_job_is_idempotent(self):
        job = RAGQueryState(user_id=self.user.id, question="Hecha", status="done", message="Lista")
        db.session.add(job)
        db.session.commit()

        response = self.client.post(f"/rag/cancel/{job.id}")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json()["status"], "done")
