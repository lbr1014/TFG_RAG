"""
Autora: Lydia Blanco Ruiz
Script con pruebas de integracion de las rutas RAG.
"""

from unittest.mock import MagicMock, patch

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

    def test_rag_ask_rejects_invalid_form(self):
        response = self.client.post("/rag/ask", data={"question": ""})

        self.assertEqual(response.status_code, 400)
        self.assertIn("error", response.get_json())

    @patch("app.rag.routes.validate_question", return_value={"answer": "Pregunta no valida"})
    def test_rag_ask_rejects_service_validation_error(self, _mock_validate_question):
        response = self.client.post("/rag/ask", data={"question": "Pregunta formalmente valida"})

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.get_json()["error"], "Pregunta no valida")

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

    @patch("app.rag.routes.EmptyForm")
    def test_rag_cancel_rejects_invalid_form(self, mock_empty_form):
        form = MagicMock()
        form.validate_on_submit.return_value = False
        mock_empty_form.return_value = form
        job = RAGQueryState(user_id=self.user.id, question="Cancelar", status="queued", message="En cola")
        db.session.add(job)
        db.session.commit()

        response = self.client.post(f"/rag/cancel/{job.id}")

        self.assertEqual(response.status_code, 400)
        self.assertIn("error", response.get_json())

    def test_rag_cancel_running_job_keeps_running_and_requests_cancel(self):
        job = RAGQueryState(user_id=self.user.id, question="Cancelar", status="running", message="Procesando")
        db.session.add(job)
        db.session.commit()

        response = self.client.post(f"/rag/cancel/{job.id}")

        self.assertEqual(response.status_code, 202)
        db.session.refresh(job)
        self.assertTrue(job.cancel_requested)
        self.assertEqual(job.status, "running")
        self.assertIsNone(job.finished_at)

    def test_rag_cancel_finished_job_is_idempotent(self):
        job = RAGQueryState(user_id=self.user.id, question="Hecha", status="done", message="Lista")
        db.session.add(job)
        db.session.commit()

        response = self.client.post(f"/rag/cancel/{job.id}")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json()["status"], "done")
