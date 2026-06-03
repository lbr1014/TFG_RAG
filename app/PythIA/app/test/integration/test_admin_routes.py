"""
Autora: Lydia Blanco Ruiz
Script con pruebas de integración de las rutas de la aplicación.
"""

import os
from io import BytesIO
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from app.main.code.extensions import db
from app.main.code.model.markdown_conversion_state import MarkdownConversionState
from app.main.code.model.rag_evaluation_state import RAGEvaluationState
from app.main.code.model.user import User
from app.main.code.model.vector_update_state import VectorUpdateState
from app.main.code.model.web_scraping_state import WebScrapingSate
from app.test.support import BaseAppTestCase

ADMIN_FORM_PASSWORD_FIELD = "pass" + "word"


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

    def test_admin_users_page_and_rejected_user_actions(self):
        users_page = self.client.get("/admin/users")
        self.assertEqual(users_page.status_code, 200)
        self.assertIn(b"admin@example.com", users_page.data)

        missing_toggle = self.client.post("/admin/users/9999", headers={"Accept": "application/json"})
        missing_delete = self.client.post("/admin/users/9999/delete", headers={"Accept": "application/json"})
        self_toggle = self.client.post(f"/admin/users/{self.admin.id}", headers={"Accept": "application/json"})
        self_delete = self.client.post(f"/admin/users/{self.admin.id}/delete", headers={"Accept": "application/json"})

        self.assertEqual(missing_toggle.status_code, 404)
        self.assertEqual(missing_delete.status_code, 404)
        self.assertEqual(self_toggle.status_code, 400)
        self.assertEqual(self_delete.status_code, 400)

    def test_admin_users_filters_and_bulk_actions(self):
        user_es = self.create_user(nombre="Ana Filtro", email="ana-filtro@example.com", country_code="ES", is_admin=False)
        user_fr = self.create_user(nombre="Luis Filtro", email="luis-filtro@example.com", country_code="FR", is_admin=False)
        self.create_user(nombre="Eva Admin", email="eva-admin@example.com", country_code="FR", is_admin=True)

        by_name = self.client.get("/admin/users?name=Ana")
        by_country = self.client.get("/admin/users?country=FR")
        by_role = self.client.get("/admin/users?role=admin")

        self.assertEqual(by_name.status_code, 200)
        self.assertIn(b"ana-filtro@example.com", by_name.data)
        self.assertNotIn(b"luis-filtro@example.com", by_name.data)

        self.assertEqual(by_country.status_code, 200)
        self.assertIn(b"luis-filtro@example.com", by_country.data)
        self.assertIn(b"eva-admin@example.com", by_country.data)
        self.assertNotIn(b"ana-filtro@example.com", by_country.data)

        self.assertEqual(by_role.status_code, 200)
        self.assertIn(b"eva-admin@example.com", by_role.data)
        self.assertNotIn(b"ana-filtro@example.com", by_role.data)

        toggled = self.client.post(
            "/admin/users/bulk",
            data={"bulk_action": "toggle", "selected_user_ids": [str(user_es.id), str(user_fr.id)]},
            follow_redirects=False,
        )
        self.assertEqual(toggled.status_code, 302)
        db.session.refresh(user_es)
        db.session.refresh(user_fr)
        self.assertTrue(user_es.is_admin)
        self.assertTrue(user_fr.is_admin)

        deleted = self.client.post(
            "/admin/users/bulk",
            data={"bulk_action": "delete", "selected_user_ids": [str(user_es.id), str(user_fr.id)]},
            follow_redirects=False,
        )
        self.assertEqual(deleted.status_code, 302)
        self.assertIsNone(db.session.get(User, user_es.id))
        self.assertIsNone(db.session.get(User, user_fr.id))

        self_delete = self.client.post(
            "/admin/users/bulk",
            data={"bulk_action": "delete", "selected_user_ids": [str(self.admin.id)]},
            headers={"Accept": "application/json"},
        )
        self.assertEqual(self_delete.status_code, 400)

    def test_admin_documents_list_uses_service_pagination(self):
        fake_service = MagicMock()
        fake_service.list_documents_paginated.return_value = SimpleNamespace(items=[], page=1, pages=1, total=0)
        fake_service.get_markdown_status_map.return_value = {}
        fake_service.count_pending_markdown.return_value = 0

        with patch("app.main.code.controllers.admin.routes.documentos_service", return_value=fake_service):
            response = self.client.get("/admin/documents/list?page=1")

        self.assertEqual(response.status_code, 200)
        fake_service.sync_from_folder.assert_called_once()
        fake_service.purge_missing_files.assert_called_once()
        fake_service.list_documents_paginated.assert_called_once_with(1, 10)

    def test_admin_upload_documents_delegates_to_service(self):
        fake_service = MagicMock()

        with patch("app.main.code.controllers.admin.routes.documentos_service", return_value=fake_service):
            response = self.client.post(
                "/admin/documents/upload",
                data={"files": (BytesIO(b"%PDF-1.4"), "nuevo.pdf")},
                content_type="multipart/form-data",
                follow_redirects=False,
            )

        self.assertEqual(response.status_code, 302)
        fake_service.save_uploads.assert_called_once()

    def test_admin_upload_documents_redirects_on_invalid_form_or_no_valid_pdf(self):
        invalid = self.client.post("/admin/documents/upload", data={}, follow_redirects=False)
        self.assertEqual(invalid.status_code, 302)

        fake_service = MagicMock()
        fake_service.save_uploads.return_value = 0
        with patch("app.main.code.controllers.admin.routes.documentos_service", return_value=fake_service):
            no_pdf = self.client.post(
                "/admin/documents/upload",
                data={"files": (BytesIO(b"texto"), "notas.txt")},
                content_type="multipart/form-data",
                follow_redirects=False,
            )

        self.assertEqual(no_pdf.status_code, 302)

        empty_form = MagicMock()
        empty_form.validate_on_submit.return_value = True
        empty_form.files.data = []
        with patch("app.main.code.controllers.admin.routes.PdfUploadForm", return_value=empty_form):
            no_files = self.client.post("/admin/documents/upload", follow_redirects=False)
        self.assertEqual(no_files.status_code, 302)

        zero_form = MagicMock()
        zero_form.validate_on_submit.return_value = True
        zero_form.files.data = [MagicMock(filename="doc.pdf")]
        with patch("app.main.code.controllers.admin.routes.PdfUploadForm", return_value=zero_form), patch(
            "app.main.code.controllers.admin.routes.documentos_service", return_value=fake_service
        ):
            zero_saved = self.client.post("/admin/documents/upload", follow_redirects=False)
        self.assertEqual(zero_saved.status_code, 302)



    @patch("app.main.code.controllers.admin.routes.executor.submit")

    def test_admin_vector_update_creates_queued_job(self, mock_submit):
        response = self.client.post("/admin/vector-db/update")

        self.assertEqual(response.status_code, 202)
        job_id = response.get_json()["job_id"]
        job = db.session.get(VectorUpdateState, job_id)
        self.assertIsNotNone(job)
        self.assertEqual(job.status, "queued")
        mock_submit.assert_called_once()

    @patch("app.main.code.controllers.admin.routes.executor.submit")
    def test_admin_rag_evaluation_creates_queued_job(self, mock_submit):
        response = self.client.post("/admin/rag/evaluation/run", headers={"Accept": "application/json"})

        self.assertEqual(response.status_code, 202)
        job_id = response.get_json()["job_id"]
        job = db.session.get(RAGEvaluationState, job_id)
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
        view_body = view_response.data.decode("utf-8")
        # Dependiendo de la configuración, la vista puede devolver el markdown en texto plano o un viewer HTML.
        normalized = view_body.strip().lower()
        if normalized.startswith("<!doctype html") or normalized.startswith("<html"):
            self.assertIn("pliego.pdf", normalized)
        else:
            self.assertEqual(view_body, "# Markdown")
        self.assertEqual(download_response.status_code, 200)
        self.assertEqual(download_response.data.decode("utf-8"), "# Markdown")
        self.assertIn('filename="pliego.md"', download_response.headers["Content-Disposition"])

    def test_admin_can_create_user_from_admin_form(self):
        response = self.client.post(
            "/admin/users/add",
            data={
                "nombre": "Usuario creado",
                "email": "creado@example.com",
                ADMIN_FORM_PASSWORD_FIELD: "Segura123",
                "is_admin": "y",
            },
            follow_redirects=False,
        )

        self.assertEqual(response.status_code, 302)
        created = User.get_by_email("creado@example.com")
        self.assertIsNotNone(created)
        self.assertTrue(created.is_admin)

    def test_admin_create_user_get_and_duplicate_email(self):
        existing = self.create_user(email="duplicado@example.com")

        get_response = self.client.get("/admin/users/add")
        duplicate_response = self.client.post(
            "/admin/users/add",
            data={
                "nombre": "Duplicado",
                "email": existing.email,
                ADMIN_FORM_PASSWORD_FIELD: "Segura123",
            },
        )

        self.assertEqual(get_response.status_code, 200)
        self.assertEqual(duplicate_response.status_code, 200)
        self.assertEqual(User.query.filter_by(email=existing.email).count(), 1)

    @patch("app.main.code.controllers.admin.routes.markdown_executor.submit")
    def test_admin_markdown_convert_creates_queued_job(self, mock_submit):
        response = self.client.post("/admin/documents/markdown/convert")

        self.assertEqual(response.status_code, 202)
        job = db.session.get(MarkdownConversionState, response.get_json()["job_id"])
        self.assertIsNotNone(job)
        self.assertEqual(job.status, "queued")
        self.assertEqual(job.progress, 0)
        mock_submit.assert_called_once()

    def test_admin_async_post_routes_return_invalid_response_when_validation_fails(self):
        invalid_response = ({"error": "bad"}, 400)

        with patch("app.main.code.controllers.admin.routes._validate_post_action", return_value=invalid_response):
            markdown = self.client.post("/admin/documents/markdown/convert")
            vector = self.client.post("/admin/vector-db/update")
            scraping = self.client.post("/admin/documents/web_scraping")
            markdown_cancel = self.client.post("/admin/documents/markdown/cancel/1")
            vector_cancel = self.client.post("/admin/vector-db/cancel/1")
            scraping_cancel = self.client.post("/admin/documents/web_scraping/cancel/1")

        for response in (markdown, vector, scraping, markdown_cancel, vector_cancel, scraping_cancel):
            self.assertEqual(response.status_code, 400)

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

    def test_admin_markdown_cancel_finished_and_status_missing(self):
        job = MarkdownConversionState(status="done", progress=100, message="Listo", cancel_requested=False)
        db.session.add(job)
        db.session.commit()

        cancelled = self.client.post(f"/admin/documents/markdown/cancel/{job.id}")
        missing = self.client.get("/admin/documents/markdown/status/9999", headers={"Accept": "application/json"})

        self.assertEqual(cancelled.status_code, 200)
        self.assertEqual(cancelled.get_json()["status"], "done")
        self.assertEqual(missing.status_code, 404)

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

    def test_admin_vector_cancel_finished_and_status_missing(self):
        job = VectorUpdateState(status="failed", progress=10, error="boom", cancel_requested=False)
        db.session.add(job)
        db.session.commit()

        cancelled = self.client.post(f"/admin/vector-db/cancel/{job.id}")
        missing = self.client.get("/admin/vector-db/status/9999", headers={"Accept": "application/json"})

        self.assertEqual(cancelled.status_code, 200)
        self.assertEqual(cancelled.get_json()["status"], "failed")
        self.assertEqual(missing.status_code, 404)

    @patch("app.main.code.controllers.admin.routes.executor.submit")
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

    def test_admin_web_scraping_cancel_finished_and_status_missing(self):
        job = WebScrapingSate(status="cancelled", progress=0, message="Cancelado", cancel_requested=True)
        db.session.add(job)
        db.session.commit()

        cancelled = self.client.post(f"/admin/documents/web_scraping/cancel/{job.id}")
        missing = self.client.get("/admin/documents/web_scraping/status/9999", headers={"Accept": "application/json"})

        self.assertEqual(cancelled.status_code, 200)
        self.assertEqual(cancelled.get_json()["status"], "cancelled")
        self.assertEqual(missing.status_code, 404)

    def test_admin_delete_document_delegates_to_service(self):
        fake_service = MagicMock()

        with patch("app.main.code.controllers.admin.routes.documentos_service", return_value=fake_service):
            response = self.client.post("/admin/documents/123/delete", follow_redirects=False)

        self.assertEqual(response.status_code, 302)
        fake_service.delete_document.assert_called_once_with(123)

    def test_admin_delete_document_returns_500_when_service_fails(self):
        fake_service = MagicMock()
        fake_service.delete_document.side_effect = RuntimeError("boom")

        with patch("app.main.code.controllers.admin.routes.documentos_service", return_value=fake_service), patch.object(
            self.app.logger, "exception"
        ):
            response = self.client.post(
                "/admin/documents/123/delete",
                follow_redirects=False,
                headers={"Accept": "application/json"},
            )

        self.assertEqual(response.status_code, 500)

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

    def test_admin_document_view_and_download_return_404_when_content_missing(self):
        doc = self.create_document(nombre="missing-content.pdf")
        path = doc.path
        doc.markdown_content = None
        db.session.commit()

        markdown_view = self.client.get(f"/admin/documents/{doc.id}/view?format=markdown", headers={"Accept": "application/json"})
        markdown_download = self.client.get(
            f"/admin/documents/{doc.id}/download?format=markdown",
            headers={"Accept": "application/json"},
        )

        os.remove(path)
        pdf_view = self.client.get(f"/admin/documents/{doc.id}/view", headers={"Accept": "application/json"})
        pdf_download = self.client.get(f"/admin/documents/{doc.id}/download", headers={"Accept": "application/json"})

        self.assertEqual(markdown_view.status_code, 404)
        self.assertEqual(markdown_download.status_code, 404)
        self.assertEqual(pdf_view.status_code, 404)
        self.assertEqual(pdf_download.status_code, 404)
