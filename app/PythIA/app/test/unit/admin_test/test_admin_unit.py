"""
Autora: Lydia Blanco Ruiz
Script con pruebas unitarias de los métodos de administracion.
"""

import subprocess
import tempfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from app.test.support import BaseAppTestCase

from app.main.code.controllers.admin import routes as admin_routes
from app.main.code.services.documentos import JobCancelledError
from app.main.code.model.markdown_conversion_state import MarkdownConversionState
from app.main.code.model.vector_update_state import VectorUpdateState
from app.main.code.model.web_scraping_state import WebScrapingSate
from app.main.code.extensions import db


class AdminRoutesUnitTest(BaseAppTestCase):
    def test_fit_job_message_truncates_long_messages(self):
        self.assertIsNone(admin_routes._fit_job_message(None))
        self.assertEqual(admin_routes._fit_job_message("abc", max_length=3), "abc")
        self.assertEqual(admin_routes._fit_job_message("abcdef", max_length=3), "abc")
        self.assertEqual(admin_routes._fit_job_message("abcdef", max_length=5), "ab...")

    def test_validate_post_action_returns_none_when_form_is_valid(self):
        with patch("app.main.code.controllers.admin.routes.EmptyForm") as mock_form_class:
            mock_form_class.return_value.validate_on_submit.return_value = True

            self.assertIsNone(admin_routes._validate_post_action())

    def test_validate_post_action_returns_json_or_aborts_when_invalid(self):
        with patch("app.main.code.controllers.admin.routes.EmptyForm") as mock_form_class, patch(
            "app.main.code.controllers.admin.routes.t", return_value="bad request"
        ):
            mock_form_class.return_value.validate_on_submit.return_value = False

            response, status = admin_routes._validate_post_action(json_response=True)

        self.assertEqual(status, 400)
        self.assertEqual(response.get_json(), {"error": "bad request"})

        with patch("app.main.code.controllers.admin.routes.EmptyForm") as mock_form_class:
            mock_form_class.return_value.validate_on_submit.return_value = False
            with self.assertRaises(Exception) as raised:
                admin_routes._validate_post_action()

        self.assertEqual(getattr(raised.exception, "code", None), 400)

    def test_mark_job_helpers_update_common_state(self):
        job = SimpleNamespace(status="queued", progress=0, error="old", message=None, finished_at=None)

        admin_routes._set_job_progress(job, 1, 0)
        self.assertEqual(job.progress, 100)

        admin_routes._mark_job_running(job, progress=25, message="Procesando")
        self.assertEqual(job.status, "running")
        self.assertEqual(job.progress, 25)
        self.assertIsNone(job.error)

        admin_routes._mark_job_done(job, message="Listo")
        self.assertEqual(job.status, "done")
        self.assertEqual(job.progress, 100)
        self.assertIsNotNone(job.finished_at)

        admin_routes._mark_job_failed(job, RuntimeError("boom"), message="Fallo")
        self.assertEqual(job.status, "failed")
        self.assertEqual(job.error, "boom")

        admin_routes._mark_job_cancelled(job, message="Cancelado")
        self.assertEqual(job.status, "cancelled")
        self.assertIsNone(job.error)

    def test_job_should_cancel_falls_back_to_cancel_requested_flag(self):
        job = SimpleNamespace(cancel_requested=True)

        with patch.object(admin_routes.db.session, "refresh") as mock_refresh:
            self.assertTrue(admin_routes._job_should_cancel(job))

        mock_refresh.assert_called_once_with(job)

    def test_markdown_done_message_chooses_expected_translation_key(self):
        with patch("app.main.code.controllers.admin.routes.translate_for", side_effect=lambda lang, key, **kwargs: key):
            self.assertEqual(
                admin_routes._markdown_done_message({"converted": 0, "failed": 0}, "es"),
                "markdown.none_pending",
            )
            self.assertEqual(
                admin_routes._markdown_done_message({"converted": 1, "failed": 2}, "es"),
                "markdown.done_stats_with_failures",
            )
            self.assertEqual(
                admin_routes._markdown_done_message({"converted": 2, "failed": 0}, "es"),
                "markdown.done_stats",
            )

    @patch("app.main.code.controllers.admin.routes.translate_for", side_effect=lambda lang, key, **kwargs: f"{key}:{kwargs}")
    def test_build_markdown_callbacks_update_progress_message_and_cancel(self, _mock_translate):
        job = MarkdownConversionState(status="running", progress=0, message="Convirtiendo anterior...", cancel_requested=False)
        db.session.add(job)
        db.session.commit()

        should_cancel, on_progress, on_current_doc, on_page_start = admin_routes._build_markdown_callbacks(job, "es")

        self.assertFalse(should_cancel())
        on_progress(1, 4)
        self.assertEqual(job.progress, 25)

        on_current_doc("pliego.pdf")
        self.assertIn("pliego.pdf", job.message)

        on_page_start(1, 2, 1, 4)
        self.assertEqual(job.progress, 12)
        self.assertIn("markdown.converting_doc_page", job.message)

        job.cancel_requested = True
        db.session.commit()
        with self.assertRaises(JobCancelledError):
            on_progress(2, 4)

    def test_send_email_safe_swallows_mail_errors(self):
        send_fn = MagicMock(side_effect=RuntimeError("smtp"))

        with patch.object(self.app.logger, "exception"):
            admin_routes._send_email_safe(send_fn, "No se pudo enviar", to_email="a@example.com")

        send_fn.assert_called_once_with(to_email="a@example.com")

    def test_path_and_service_helpers_use_app_config_and_dependencies(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            self.app.config["DOCS_DIR"] = str(Path(tmpdir) / "docs")

            base = admin_routes.pliegos_dir()
            self.assertTrue(base.exists())

            with patch("app.main.code.controllers.admin.routes.DocumentosService") as mock_service:
                result = admin_routes.documentos_service()

            self.assertIs(result, mock_service.return_value)
            mock_service.assert_called_once()
            self.assertEqual(mock_service.call_args.args[0], base)

        with self.app.test_request_context("/admin/documents/list", base_url="http://localhost/"):
            self.assertEqual(admin_routes.documents_page_url(), "http://localhost/admin/documents/list")

    def test_convert_pdf_to_markdown_delegates_to_processor(self):
        callback = MagicMock()
        with patch("app.main.code.services.markdown.Conversion_markdown.process_pdf", return_value="# md") as mock_process:
            result = admin_routes.convert_pdf_to_markdown(Path("doc.pdf"), on_page_start=callback)

        self.assertEqual(result, "# md")
        mock_process.assert_called_once_with(Path("doc.pdf"), on_page_start=callback)

    def test_markdown_cancel_finish_and_exception_helpers_update_job_and_email(self):
        job = MarkdownConversionState(status="running", progress=10, message="old", cancel_requested=True)
        db.session.add(job)
        db.session.commit()

        with patch("app.main.code.controllers.admin.routes.translate_for", side_effect=lambda lang, key, **kwargs: key):
            admin_routes._cancel_markdown_job(job, "es")

        self.assertEqual(job.status, "cancelled")

        job = MarkdownConversionState(status="running", progress=10)
        db.session.add(job)
        db.session.commit()
        with patch("app.main.code.controllers.admin.routes._send_email_safe") as mock_email, patch(
            "app.main.code.controllers.admin.routes.translate_for", side_effect=lambda lang, key, **kwargs: key
        ):
            admin_routes._finish_markdown_job(
                job,
                {"converted": 2, "failed": 0, "skipped": 1},
                "admin@example.com",
                "http://docs",
                "es",
            )

        self.assertEqual(job.status, "done")
        mock_email.assert_called_once()

        failed = MarkdownConversionState(status="running", progress=10)
        db.session.add(failed)
        db.session.commit()
        with patch.object(self.app.logger, "exception") as mock_logger, patch(
            "app.main.code.controllers.admin.routes._send_email_safe"
        ) as mock_email, patch("app.main.code.controllers.admin.routes.translate_for", side_effect=lambda lang, key, **kwargs: key):
            admin_routes._handle_markdown_exception(
                self.app,
                failed.id,
                "admin@example.com",
                "http://docs",
                "es",
                RuntimeError("boom"),
            )

        self.assertEqual(failed.status, "failed")
        self.assertEqual(failed.error, "boom")
        mock_email.assert_called_once()
        mock_logger.assert_called_once()

    def test_markdown_page_base_message_strips_page_suffixes_or_uses_default(self):
        with patch("app.main.code.controllers.admin.routes.translate_for", return_value="Convirtiendo documento..."):
            self.assertEqual(
                admin_routes._markdown_page_base_message(SimpleNamespace(message=None), "es"),
                "Convirtiendo documento...",
            )

        self.assertEqual(
            admin_routes._markdown_page_base_message(SimpleNamespace(message="Convirtiendo doc... Page 1/2"), "es"),
            "Convirtiendo doc...",
        )

    def test_scraping_context_finish_and_exception_helpers(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            self.app.config["DOCS_DIR"] = str(Path(tmpdir) / "docs")
            base, scraper_dir, script_1, script_2, root, env = admin_routes._build_scraping_context()

        self.assertEqual(base.name, "docs")
        self.assertEqual(scraper_dir.name, "web_scraping")
        self.assertEqual(script_1.name, "PliegosPlaywrightAsincrono.py")
        self.assertEqual(script_2.name, "DescargarPliegos.py")
        self.assertEqual(root, Path(self.app.root_path))
        self.assertIn("PLIEGOS_DEST", env)

        job = WebScrapingSate(status="running", progress=10)
        db.session.add(job)
        db.session.commit()
        with patch("app.main.code.controllers.admin.routes._send_email_safe") as mock_email, patch(
            "app.main.code.controllers.admin.routes.translate_for", side_effect=lambda lang, key, **kwargs: key
        ):
            admin_routes._finish_scraping_job(job, "admin@example.com", "http://docs", "es", 2, 5)

        self.assertEqual(job.status, "done")
        mock_email.assert_called_once()

        failed = WebScrapingSate(status="running", progress=10)
        db.session.add(failed)
        db.session.commit()
        with patch.object(self.app.logger, "exception") as mock_logger, patch(
            "app.main.code.controllers.admin.routes._send_email_safe"
        ) as mock_email, patch("app.main.code.controllers.admin.routes.translate_for", side_effect=lambda lang, key, **kwargs: key):
            admin_routes._handle_scraping_exception(
                self.app,
                failed.id,
                "admin@example.com",
                "http://docs",
                "es",
                RuntimeError("scraping boom"),
            )

        self.assertEqual(failed.status, "failed")
        self.assertEqual(failed.error, "scraping boom")
        mock_email.assert_called_once()
        mock_logger.assert_called_once()

    def test_execute_subprocess_with_cancellation_success_failure_and_cancel(self):
        proc = MagicMock()
        proc.poll.side_effect = [None, 0]
        proc.wait.side_effect = [subprocess.TimeoutExpired("cmd", 1), None]
        with patch("app.main.code.controllers.admin.routes.subprocess.Popen", return_value=proc) as mock_popen:
            admin_routes._execute_subprocess_with_cancellation(Path("script.py"), Path("."), {}, lambda: False, "es")

        mock_popen.assert_called_once()

        proc = MagicMock()
        proc.poll.return_value = 7
        with patch("app.main.code.controllers.admin.routes.subprocess.Popen", return_value=proc):
            with self.assertRaises(subprocess.CalledProcessError):
                admin_routes._execute_subprocess_with_cancellation(Path("bad.py"), Path("."), {}, lambda: False, "es")

        proc = MagicMock()
        proc.wait.side_effect = [subprocess.TimeoutExpired("cmd", 10), None]
        with patch("app.main.code.controllers.admin.routes.subprocess.Popen", return_value=proc), patch(
            "app.main.code.controllers.admin.routes.translate_for", return_value="cancelado"
        ):
            with self.assertRaises(JobCancelledError):
                admin_routes._execute_subprocess_with_cancellation(Path("slow.py"), Path("."), {}, lambda: True, "es")

        proc.terminate.assert_called_once()
        proc.kill.assert_called_once()

    def test_run_scraping_script_updates_job_or_raises_when_cancelled(self):
        job = WebScrapingSate(status="running", progress=0, cancel_requested=False)
        db.session.add(job)
        db.session.commit()

        with patch("app.main.code.controllers.admin.routes._execute_subprocess_with_cancellation") as mock_execute:
            admin_routes._run_scraping_script(
                job,
                Path("script.py"),
                Path("."),
                {},
                lambda: False,
                "es",
                progress=50,
                message="Ejecutando",
            )

        self.assertEqual(job.progress, 50)
        self.assertEqual(job.message, "Ejecutando")
        mock_execute.assert_called_once()

        with patch("app.main.code.controllers.admin.routes.translate_for", return_value="cancelado"):
            with self.assertRaises(JobCancelledError):
                admin_routes._run_scraping_script(job, Path("script.py"), Path("."), {}, lambda: True, "es")

    def test_sync_scraping_results_counts_new_files_and_honors_cancellation(self):
        job = WebScrapingSate(status="running", progress=0, cancel_requested=False)
        db.session.add(job)
        db.session.commit()

        with tempfile.TemporaryDirectory() as tmpdir:
            base = Path(tmpdir)
            (base / "old.pdf").write_bytes(b"%PDF")

            fake_service = MagicMock()
            fake_service.sync_from_folder.side_effect = lambda: (base / "new.pdf").write_bytes(b"%PDF")
            with patch("app.main.code.controllers.admin.routes.documentos_service", return_value=fake_service), patch(
                "app.main.code.controllers.admin.routes.translate_for", side_effect=lambda lang, key, **kwargs: key
            ):
                extracted, total = admin_routes._sync_scraping_results(job, base, "es", lambda: False)

        self.assertEqual((extracted, total), (1, 2))
        self.assertEqual(job.progress, 90)

        with patch("app.main.code.controllers.admin.routes.translate_for", return_value="cancelado"):
            with self.assertRaises(JobCancelledError):
                admin_routes._sync_scraping_results(job, Path("."), "es", lambda: True)

        with tempfile.TemporaryDirectory() as tmpdir:
            base = Path(tmpdir)
            fake_service = MagicMock()
            with patch("app.main.code.controllers.admin.routes.documentos_service", return_value=fake_service), patch(
                "app.main.code.controllers.admin.routes.translate_for", return_value="cancelado"
            ):
                should_cancel = MagicMock(side_effect=[False, True])
                with self.assertRaises(JobCancelledError):
                    admin_routes._sync_scraping_results(job, base, "es", should_cancel)

    @patch("app.main.code.controllers.admin.routes.send_markdown_finished_email")
    def test_markdown_async_marks_done_and_handles_cancellation_and_errors(self, mock_send):
        job = MarkdownConversionState(status="queued", progress=0, cancel_requested=False)
        db.session.add(job)
        db.session.commit()
        fake_service = MagicMock()
        fake_service.convert_pending_to_markdown.return_value = {"converted": 1, "failed": 0, "skipped": 0, "total": 1}

        with patch("app.main.code.controllers.admin.routes.documentos_service", return_value=fake_service):
            admin_routes.markdown_async(self.app, job.id, "admin@example.com", "http://docs.local")

        db.session.expire_all()
        refreshed = db.session.get(MarkdownConversionState, job.id)
        self.assertEqual(refreshed.status, "done")
        mock_send.assert_called_once()

        precancelled = MarkdownConversionState(status="queued", progress=0, cancel_requested=True)
        db.session.add(precancelled)
        db.session.commit()

        admin_routes.markdown_async(self.app, precancelled.id, "admin@example.com", "http://docs.local")
        db.session.expire_all()
        self.assertEqual(db.session.get(MarkdownConversionState, precancelled.id).status, "cancelled")

        cancelled = MarkdownConversionState(status="queued", progress=0, cancel_requested=False)
        db.session.add(cancelled)
        db.session.commit()
        fake_service.convert_pending_to_markdown.side_effect = JobCancelledError("cancelado")

        with patch("app.main.code.controllers.admin.routes.documentos_service", return_value=fake_service):
            admin_routes.markdown_async(self.app, cancelled.id, "admin@example.com", "http://docs.local")

        db.session.expire_all()
        self.assertEqual(db.session.get(MarkdownConversionState, cancelled.id).status, "cancelled")

        failed = MarkdownConversionState(status="queued", progress=0, cancel_requested=False)
        db.session.add(failed)
        db.session.commit()
        fake_service.convert_pending_to_markdown.side_effect = RuntimeError("boom")

        with patch("app.main.code.controllers.admin.routes.documentos_service", return_value=fake_service), patch.object(self.app.logger, "exception"):
            admin_routes.markdown_async(self.app, failed.id, "admin@example.com", "http://docs.local")

        db.session.expire_all()
        self.assertEqual(db.session.get(MarkdownConversionState, failed.id).status, "failed")

        cancel_after_service = MarkdownConversionState(status="queued", progress=0, cancel_requested=False)
        db.session.add(cancel_after_service)
        db.session.commit()

        def mark_cancelled_after_start(**_kwargs):
            db.session.get(MarkdownConversionState, cancel_after_service.id).cancel_requested = True
            db.session.commit()
            return {"converted": 0, "failed": 0, "skipped": 0, "total": 0}

        fake_service.convert_pending_to_markdown.side_effect = mark_cancelled_after_start
        with patch("app.main.code.controllers.admin.routes.documentos_service", return_value=fake_service):
            admin_routes.markdown_async(self.app, cancel_after_service.id, "admin@example.com", "http://docs.local")
        db.session.expire_all()
        self.assertEqual(db.session.get(MarkdownConversionState, cancel_after_service.id).status, "cancelled")

        admin_routes.markdown_async(self.app, 9999, "admin@example.com", "http://docs.local")

        with patch.object(self.app.logger, "exception"):
            with self.assertRaises(RuntimeError):
                admin_routes._handle_markdown_exception(
                    self.app,
                    9999,
                    "admin@example.com",
                    "http://docs.local",
                    "es",
                    RuntimeError("missing job"),
                )

    @patch("app.main.code.controllers.admin.routes.send_update_finished_email")
    def test_documentos_async_marks_done_cancelled_and_failed(self, mock_send):
        job = VectorUpdateState(status="queued", progress=0, cancel_requested=False)
        db.session.add(job)
        db.session.commit()

        def update_vector_db(on_progress, on_current_doc, should_cancel):
            on_current_doc("doc.pdf")
            on_progress(1, 2)
            self.assertFalse(should_cancel())
            return {"indexed": 2, "failed": 0}

        fake_service = MagicMock()
        fake_service.update_vector_db.side_effect = update_vector_db
        with patch("app.main.code.controllers.admin.routes.documentos_service", return_value=fake_service):
            admin_routes.documentos_async(self.app, job.id, "admin@example.com", "http://docs.local")

        db.session.expire_all()
        refreshed = db.session.get(VectorUpdateState, job.id)
        self.assertEqual(refreshed.status, "done")
        self.assertEqual(refreshed.current_doc, "doc.pdf")
        self.assertEqual(refreshed.progress, 100)
        mock_send.assert_called_once()

        precancelled = VectorUpdateState(status="queued", progress=0, cancel_requested=True)
        db.session.add(precancelled)
        db.session.commit()
        admin_routes.documentos_async(self.app, precancelled.id, "admin@example.com", "http://docs.local")
        db.session.expire_all()
        self.assertEqual(db.session.get(VectorUpdateState, precancelled.id).status, "cancelled")

        cancelled = VectorUpdateState(status="queued", progress=0, cancel_requested=False)
        db.session.add(cancelled)
        db.session.commit()
        fake_service.update_vector_db.side_effect = JobCancelledError("cancelado")
        with patch("app.main.code.controllers.admin.routes.documentos_service", return_value=fake_service):
            admin_routes.documentos_async(self.app, cancelled.id, "admin@example.com", "http://docs.local")
        db.session.expire_all()
        self.assertEqual(db.session.get(VectorUpdateState, cancelled.id).status, "cancelled")

        failed = VectorUpdateState(status="queued", progress=0, cancel_requested=False)
        db.session.add(failed)
        db.session.commit()
        fake_service.update_vector_db.side_effect = RuntimeError("vector boom")
        with patch("app.main.code.controllers.admin.routes.documentos_service", return_value=fake_service), patch.object(self.app.logger, "exception"):
            admin_routes.documentos_async(self.app, failed.id, "admin@example.com", "http://docs.local")
        db.session.expire_all()
        self.assertEqual(db.session.get(VectorUpdateState, failed.id).status, "failed")

        cancel_in_current_doc = VectorUpdateState(status="queued", progress=0, cancel_requested=False)
        db.session.add(cancel_in_current_doc)
        db.session.commit()

        def cancel_on_current_doc(on_progress, on_current_doc, should_cancel):
            db.session.get(VectorUpdateState, cancel_in_current_doc.id).cancel_requested = True
            db.session.commit()
            on_current_doc("cancel.pdf")

        fake_service.update_vector_db.side_effect = cancel_on_current_doc
        with patch("app.main.code.controllers.admin.routes.documentos_service", return_value=fake_service):
            admin_routes.documentos_async(self.app, cancel_in_current_doc.id, "admin@example.com", "http://docs.local")
        db.session.expire_all()
        self.assertEqual(db.session.get(VectorUpdateState, cancel_in_current_doc.id).status, "cancelled")

        cancel_in_progress = VectorUpdateState(status="queued", progress=0, cancel_requested=False)
        db.session.add(cancel_in_progress)
        db.session.commit()

        def cancel_on_progress(on_progress, on_current_doc, should_cancel):
            db.session.get(VectorUpdateState, cancel_in_progress.id).cancel_requested = True
            db.session.commit()
            on_progress(1, 2)

        fake_service.update_vector_db.side_effect = cancel_on_progress
        with patch("app.main.code.controllers.admin.routes.documentos_service", return_value=fake_service):
            admin_routes.documentos_async(self.app, cancel_in_progress.id, "admin@example.com", "http://docs.local")
        db.session.expire_all()
        self.assertEqual(db.session.get(VectorUpdateState, cancel_in_progress.id).status, "cancelled")

        cancel_after_service = VectorUpdateState(status="queued", progress=0, cancel_requested=False)
        db.session.add(cancel_after_service)
        db.session.commit()

        def cancel_after_vector_update(on_progress, on_current_doc, should_cancel):
            db.session.get(VectorUpdateState, cancel_after_service.id).cancel_requested = True
            db.session.commit()
            return {"indexed": 0, "failed": 0}

        fake_service.update_vector_db.side_effect = cancel_after_vector_update
        with patch("app.main.code.controllers.admin.routes.documentos_service", return_value=fake_service):
            admin_routes.documentos_async(self.app, cancel_after_service.id, "admin@example.com", "http://docs.local")
        db.session.expire_all()
        self.assertEqual(db.session.get(VectorUpdateState, cancel_after_service.id).status, "cancelled")

        deleted = VectorUpdateState(status="queued", progress=0, cancel_requested=False)
        db.session.add(deleted)
        db.session.commit()
        deleted_id = deleted.id

        def delete_then_fail(on_progress, on_current_doc, should_cancel):
            db.session.delete(db.session.get(VectorUpdateState, deleted_id))
            db.session.commit()
            raise RuntimeError("deleted job")

        fake_service.update_vector_db.side_effect = delete_then_fail
        with patch("app.main.code.controllers.admin.routes.documentos_service", return_value=fake_service), patch.object(self.app.logger, "exception"):
            with self.assertRaises(RuntimeError):
                admin_routes.documentos_async(self.app, deleted_id, "admin@example.com", "http://docs.local")

        admin_routes.documentos_async(self.app, 9999, "admin@example.com", "http://docs.local")

    @patch("app.main.code.controllers.admin.routes.send_scraping_finished_email")
    def test_scraping_async_marks_done_cancelled_and_failed(self, mock_send):
        job = WebScrapingSate(status="queued", progress=0, cancel_requested=False)
        db.session.add(job)
        db.session.commit()

        with tempfile.TemporaryDirectory() as tmpdir:
            base = Path(tmpdir)
            with patch(
                "app.main.code.controllers.admin.routes._build_scraping_context",
                return_value=(base, Path("."), Path("one.py"), Path("two.py"), Path("."), {}),
            ), patch("app.main.code.controllers.admin.routes._run_scraping_script") as mock_run, patch(
                "app.main.code.controllers.admin.routes._sync_scraping_results", return_value=(3, 4)
            ):
                admin_routes.scraping_async(self.app, job.id, "admin@example.com", "http://docs.local")

        db.session.expire_all()
        refreshed = db.session.get(WebScrapingSate, job.id)
        self.assertEqual(refreshed.status, "done")
        self.assertEqual(mock_run.call_count, 2)
        mock_send.assert_called_once()

        precancelled = WebScrapingSate(status="queued", progress=0, cancel_requested=True)
        db.session.add(precancelled)
        db.session.commit()
        admin_routes.scraping_async(self.app, precancelled.id, "admin@example.com", "http://docs.local")
        db.session.expire_all()
        self.assertEqual(db.session.get(WebScrapingSate, precancelled.id).status, "cancelled")

        cancelled = WebScrapingSate(status="queued", progress=0, cancel_requested=False)
        db.session.add(cancelled)
        db.session.commit()
        with patch("app.main.code.controllers.admin.routes._build_scraping_context", return_value=(Path("."), Path("."), Path("one.py"), Path("two.py"), Path("."), {})), patch(
            "app.main.code.controllers.admin.routes._run_scraping_script", side_effect=JobCancelledError("cancelado")
        ):
            admin_routes.scraping_async(self.app, cancelled.id, "admin@example.com", "http://docs.local")
        db.session.expire_all()
        self.assertEqual(db.session.get(WebScrapingSate, cancelled.id).status, "cancelled")

        failed = WebScrapingSate(status="queued", progress=0, cancel_requested=False)
        db.session.add(failed)
        db.session.commit()
        with patch("app.main.code.controllers.admin.routes._build_scraping_context", side_effect=RuntimeError("scraping boom")), patch.object(
            self.app.logger, "exception"
        ):
            admin_routes.scraping_async(self.app, failed.id, "admin@example.com", "http://docs.local")
        db.session.expire_all()
        self.assertEqual(db.session.get(WebScrapingSate, failed.id).status, "failed")

        callback_job = WebScrapingSate(status="queued", progress=0, cancel_requested=False)
        db.session.add(callback_job)
        db.session.commit()

        def inspect_should_cancel(_job, _script, _cwd, _env, should_cancel, _lang, **_kwargs):
            self.assertFalse(should_cancel())

        with patch(
            "app.main.code.controllers.admin.routes._build_scraping_context",
            return_value=(Path("."), Path("."), Path("one.py"), Path("two.py"), Path("."), {}),
        ), patch("app.main.code.controllers.admin.routes._run_scraping_script", side_effect=inspect_should_cancel), patch(
            "app.main.code.controllers.admin.routes._sync_scraping_results", return_value=(0, 0)
        ):
            admin_routes.scraping_async(self.app, callback_job.id, "admin@example.com", "http://docs.local")

        admin_routes.scraping_async(self.app, 9999, "admin@example.com", "http://docs.local")

        with patch.object(self.app.logger, "exception"):
            with self.assertRaises(RuntimeError):
                admin_routes._handle_scraping_exception(
                    self.app,
                    9999,
                    "admin@example.com",
                    "http://docs.local",
                    "es",
                    RuntimeError("missing scraping job"),
                )
