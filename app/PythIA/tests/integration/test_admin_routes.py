"""
Autora: Lydia Blanco Ruiz
Script con pruebas de integración de las rutas de la aplicación.
"""

from io import BytesIO
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from tests.support import BaseAppTestCase

from app.extensions import db
from app.entities.markdown_conversion_state import MarkdownConversionState
from app.entities.user import User
from app.entities.vector_update_state import VectorUpdateState
from app.entities.web_scraping_state import WebScrapingSate


class AdminRoutesIntegrationTest(BaseAppTestCase):
    def setUp(self):
        super().setUp()
        self.admin = self.create_user(email="admin@example.com", is_admin=True)
        self.login(self.admin.email)

    def test_admin_can_toggle_and_delete_users(self):
        user = self.create_user(email="user@example.com", is_admin=False)

        toggle = self.client.post(f"/admin/users/{user.id}", follow_redirects=False)
        self.assertEqual(toggle.status_code, 302)
        db.session.refresh(user)
        self.assertTrue(user.is_admin)

        delete = self.client.post(f"/admin/users/{user.id}/delete", follow_redirects=False)
        self.assertEqual(delete.status_code, 302)
        self.assertIsNone(db.session.get(User, user.id))

    def test_admin_documents_list_uses_service_pagination(self):
        fake_service = MagicMock()
        fake_service.list_documents_paginated.return_value = SimpleNamespace(items=[], page=1, pages=1, total=0)
        fake_service.get_markdown_status_map.return_value = {}
        fake_service.count_pending_markdown.return_value = 0

        with patch("app.admin.routes.documentos_service", return_value=fake_service):
            response = self.client.get("/admin/documents/list?page=1")

        self.assertEqual(response.status_code, 200)
        fake_service.sync_from_folder.assert_called_once()
        fake_service.purge_missing_files.assert_called_once()
        fake_service.list_documents_paginated.assert_called_once_with(1, 10)

    def test_admin_upload_documents_delegates_to_service(self):
        fake_service = MagicMock()

        with patch("app.admin.routes.documentos_service", return_value=fake_service):
            response = self.client.post(
                "/admin/documents/upload",
                data={"files": (BytesIO(b"%PDF-1.4"), "nuevo.pdf")},
                content_type="multipart/form-data",
                follow_redirects=False,
            )

        self.assertEqual(response.status_code, 302)
        fake_service.save_uploads.assert_called_once()

    @patch("app.admin.routes.executor.submit")
    def test_admin_vector_update_creates_queued_job(self, mock_submit):
        response = self.client.post("/admin/vector-db/update")

        self.assertEqual(response.status_code, 202)
        job_id = response.get_json()["job_id"]
        job = db.session.get(VectorUpdateState, job_id)
        self.assertIsNotNone(job)
        self.assertEqual(job.status, "queued")
        mock_submit.assert_called_once()

    def test_admin_can_view_and_download_markdown_from_document_row(self):
        doc = self.create_document(nombre="pliego.pdf")
        doc.markdown_content = "# Markdown"
        db.session.commit()

        view_response = self.client.get(f"/admin/documents/{doc.id}/view?format=markdown")
        download_response = self.client.get(f"/admin/documents/{doc.id}/download?format=markdown")

        self.assertEqual(view_response.status_code, 200)
        self.assertEqual(view_response.data.decode("utf-8"), "# Markdown")
        self.assertEqual(download_response.status_code, 200)
        self.assertEqual(download_response.data.decode("utf-8"), "# Markdown")
        self.assertIn('filename="pliego.md"', download_response.headers["Content-Disposition"])

    def test_admin_can_create_user_from_admin_form(self):
        response = self.client.post(
            "/admin/users/add",
            data={
                "nombre": "Usuario creado",
                "email": "creado@example.com",
                "password": "Segura123",
                "is_admin": "y",
            },
            follow_redirects=False,
        )

        self.assertEqual(response.status_code, 302)
        created = User.get_by_email("creado@example.com")
        self.assertIsNotNone(created)
        self.assertTrue(created.is_admin)

    @patch("app.admin.routes.markdown_executor.submit")
    def test_admin_markdown_convert_creates_queued_job(self, mock_submit):
        response = self.client.post("/admin/documents/markdown/convert")

        self.assertEqual(response.status_code, 202)
        job = db.session.get(MarkdownConversionState, response.get_json()["job_id"])
        self.assertIsNotNone(job)
        self.assertEqual(job.status, "queued")
        self.assertEqual(job.progress, 0)
        mock_submit.assert_called_once()

    def test_admin_markdown_status_and_cancel_queued_job(self):
        job = MarkdownConversionState(status="queued", progress=10, message="En cola", cancel_requested=False)
        db.session.add(job)
        db.session.commit()

        status = self.client.get(f"/admin/documents/markdown/status/{job.id}")
        self.assertEqual(status.status_code, 200)
        self.assertEqual(status.get_json()["status"], "queued")

        cancelled = self.client.post(f"/admin/documents/markdown/cancel/{job.id}")
        self.assertEqual(cancelled.status_code, 202)
        db.session.refresh(job)
        self.assertTrue(job.cancel_requested)
        self.assertEqual(job.status, "cancelled")

    def test_admin_vector_status_and_cancel_queued_job(self):
        job = VectorUpdateState(status="queued", progress=5, current_doc="uno.pdf", cancel_requested=False)
        db.session.add(job)
        db.session.commit()

        status = self.client.get(f"/admin/vector-db/status/{job.id}")
        self.assertEqual(status.status_code, 200)
        self.assertEqual(status.get_json()["current_doc"], "uno.pdf")

        cancelled = self.client.post(f"/admin/vector-db/cancel/{job.id}")
        self.assertEqual(cancelled.status_code, 202)
        db.session.refresh(job)
        self.assertTrue(job.cancel_requested)
        self.assertEqual(job.status, "cancelled")

    @patch("app.admin.routes.executor.submit")
    def test_admin_web_scraping_creates_queued_job(self, mock_submit):
        response = self.client.post("/admin/documents/web_scraping")

        self.assertEqual(response.status_code, 202)
        job = db.session.get(WebScrapingSate, response.get_json()["job_id"])
        self.assertIsNotNone(job)
        self.assertEqual(job.status, "queued")
        mock_submit.assert_called_once()

    def test_admin_web_scraping_status_and_cancel_queued_job(self):
        job = WebScrapingSate(status="queued", progress=20, message="En cola", cancel_requested=False)
        db.session.add(job)
        db.session.commit()

        status = self.client.get(f"/admin/documents/web_scraping/status/{job.id}")
        self.assertEqual(status.status_code, 200)
        self.assertEqual(status.get_json()["progress"], 20)

        cancelled = self.client.post(f"/admin/documents/web_scraping/cancel/{job.id}")
        self.assertEqual(cancelled.status_code, 202)
        db.session.refresh(job)
        self.assertTrue(job.cancel_requested)
        self.assertEqual(job.status, "cancelled")

    def test_admin_delete_document_delegates_to_service(self):
        fake_service = MagicMock()

        with patch("app.admin.routes.documentos_service", return_value=fake_service):
            response = self.client.post("/admin/documents/123/delete", follow_redirects=False)

        self.assertEqual(response.status_code, 302)
        fake_service.delete_document.assert_called_once_with(123)

    def test_admin_can_view_and_download_pdf_from_document_row(self):
        doc = self.create_document(nombre="pliego-original.pdf")

        view_response = self.client.get(f"/admin/documents/{doc.id}/view")
        download_response = self.client.get(f"/admin/documents/{doc.id}/download")

        self.assertEqual(view_response.status_code, 200)
        self.assertEqual(view_response.mimetype, "application/pdf")
        self.assertEqual(download_response.status_code, 200)
        self.assertIn("pliego-original.pdf", download_response.headers["Content-Disposition"])
        view_response.close()
        download_response.close()
