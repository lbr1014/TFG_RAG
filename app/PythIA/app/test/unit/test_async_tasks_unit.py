"""
Autora: Lydia Blanco Ruiz
Script con pruebas unitarias de workers asincronos.
"""

from unittest.mock import AsyncMock, MagicMock, patch

from tests.support import BaseAppTestCase

from app.admin import routes as admin_routes
from app.entities.markdown_conversion_state import MarkdownConversionState
from app.entities.rag_query_state import RAGQueryState
from app.entities.vector_update_state import VectorUpdateState
from app.entities.web_scraping_state import WebScrapingSate
from app.extensions import db
from app.rag.PrototipoRAG import QueryCancelledError
from app.rag.routes import run_rag_query_async


class AsyncTasksUnitTest(BaseAppTestCase):
    def _fresh(self, model, item_id):
        db.session.expire_all()
        return db.session.get(model, item_id)

    def test_run_rag_query_async_marks_job_done_with_result(self):
        user = self.create_user()
        job = RAGQueryState(user_id=user.id, question="Pregunta", status="queued")
        db.session.add(job)
        db.session.commit()

        with patch("app.rag.routes.rag_answer", AsyncMock(return_value={"answer": "ok"})):
            run_rag_query_async(self.app, job.id, user.id)

        refreshed = self._fresh(RAGQueryState, job.id)
        self.assertEqual(refreshed.status, "done")
        self.assertEqual(refreshed.result_payload, {"answer": "ok"})
        self.assertIsNotNone(refreshed.finished_at)

    def test_run_rag_query_async_marks_cancelled_when_cancel_requested_before_start(self):
        user = self.create_user()
        job = RAGQueryState(user_id=user.id, question="Pregunta", status="queued", cancel_requested=True)
        db.session.add(job)
        db.session.commit()

        run_rag_query_async(self.app, job.id, user.id)

        refreshed = self._fresh(RAGQueryState, job.id)
        self.assertEqual(refreshed.status, "cancelled")
        self.assertIsNotNone(refreshed.finished_at)

    def test_run_rag_query_async_handles_cancel_exception(self):
        user = self.create_user()
        job = RAGQueryState(user_id=user.id, question="Pregunta", status="queued")
        db.session.add(job)
        db.session.commit()

        with patch("app.rag.routes.rag_answer", AsyncMock(side_effect=QueryCancelledError("cancelado"))):
            run_rag_query_async(self.app, job.id, user.id)

        refreshed = self._fresh(RAGQueryState, job.id)
        self.assertEqual(refreshed.status, "cancelled")

    def test_run_rag_query_async_marks_failed_on_unexpected_error(self):
        user = self.create_user()
        job = RAGQueryState(user_id=user.id, question="Pregunta", status="queued")
        db.session.add(job)
        db.session.commit()

        with patch("app.rag.routes.rag_answer", AsyncMock(side_effect=RuntimeError("boom"))), patch.object(
            self.app.logger, "exception"
        ):
            run_rag_query_async(self.app, job.id, user.id)

        refreshed = self._fresh(RAGQueryState, job.id)
        self.assertEqual(refreshed.status, "failed")
        self.assertEqual(refreshed.error, "boom")

    @patch("app.admin.routes.send_markdown_finished_email")
    def test_markdown_async_marks_done_and_sends_email(self, mock_send):
        job = MarkdownConversionState(status="queued", progress=0, cancel_requested=False)
        db.session.add(job)
        db.session.commit()
        fake_service = MagicMock()
        fake_service.convert_pending_to_markdown.return_value = {"converted": 1, "failed": 0, "skipped": 2, "total": 1}

        with patch("app.admin.routes.documentos_service", return_value=fake_service):
            admin_routes.markdown_async(self.app, job.id, "admin@example.com", "http://docs.local")

        refreshed = self._fresh(MarkdownConversionState, job.id)
        self.assertEqual(refreshed.status, "done")
        self.assertEqual(refreshed.progress, 100)
        mock_send.assert_called_once()

    def test_markdown_async_marks_pre_cancelled_job(self):
        job = MarkdownConversionState(status="queued", progress=0, cancel_requested=True)
        db.session.add(job)
        db.session.commit()

        admin_routes.markdown_async(self.app, job.id, "admin@example.com", "http://docs.local")

        refreshed = self._fresh(MarkdownConversionState, job.id)
        self.assertEqual(refreshed.status, "cancelled")

    @patch("app.admin.routes.send_update_finished_email")
    def test_documentos_async_marks_done_and_sends_email(self, mock_send):
        job = VectorUpdateState(status="queued", progress=0, cancel_requested=False)
        db.session.add(job)
        db.session.commit()
        fake_service = MagicMock()
        fake_service.update_vector_db.return_value = {"indexed": 2, "failed": 0}

        with patch("app.admin.routes.documentos_service", return_value=fake_service):
            admin_routes.documentos_async(self.app, job.id, "admin@example.com", "http://docs.local")

        refreshed = self._fresh(VectorUpdateState, job.id)
        self.assertEqual(refreshed.status, "done")
        self.assertEqual(refreshed.progress, 100)
        mock_send.assert_called_once()

    def test_documentos_async_marks_failed_on_service_error(self):
        job = VectorUpdateState(status="queued", progress=0, cancel_requested=False)
        db.session.add(job)
        db.session.commit()
        fake_service = MagicMock()
        fake_service.update_vector_db.side_effect = RuntimeError("vector boom")

        with patch("app.admin.routes.documentos_service", return_value=fake_service), patch(
            "app.admin.routes.send_update_finished_email"
        ), patch.object(self.app.logger, "exception"):
            admin_routes.documentos_async(self.app, job.id, "admin@example.com", "http://docs.local")

        refreshed = self._fresh(VectorUpdateState, job.id)
        self.assertEqual(refreshed.status, "failed")
        self.assertEqual(refreshed.error, "vector boom")

    @patch("app.admin.routes.send_scraping_finished_email")
    def test_scraping_async_marks_done_after_scripts_and_sync(self, mock_send):
        job = WebScrapingSate(status="queued", progress=0, cancel_requested=False)
        db.session.add(job)
        db.session.commit()

        with patch("app.admin.routes._run_scraping_script") as mock_run_script, patch(
            "app.admin.routes._sync_scraping_results", return_value=(2, 5)
        ):
            admin_routes.scraping_async(self.app, job.id, "admin@example.com", "http://docs.local")

        refreshed = self._fresh(WebScrapingSate, job.id)
        self.assertEqual(refreshed.status, "done")
        self.assertEqual(refreshed.progress, 100)
        self.assertEqual(mock_run_script.call_count, 2)
        mock_send.assert_called_once()
