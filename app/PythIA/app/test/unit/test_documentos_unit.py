"""
Autora: Lydia Blanco Ruiz
Script con pruebas unitarias de la aplicación.
"""

from io import BytesIO
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from werkzeug.datastructures import FileStorage
from app.test.support import BaseAppTestCase

from app.main.code.services.documentos import (
    STATUS_WITH_MARKDOWN,
    DocumentosService,
    JobCancelledError,
    _normalize_text,
    infer_document_metadata_from_filename,
    update_sql,
)
from app.main.code.model.chunk import Chunk
from app.main.code.model.documento import Documento
from app.main.code.model.embedding import Embedding
from app.main.code.extensions import db


class DocumentosServiceUnitTest(BaseAppTestCase):
    def _service(self) -> DocumentosService:
        return DocumentosService(
            self._docs_dir,
            index_pliegos_dir=lambda path: {},
            delete_chunks=MagicMock(),
            markdown_converter=MagicMock(),
        )

    def test_infer_document_metadata_from_filename(self):
        expediente, tipo = infer_document_metadata_from_filename("EXP-123__Pliego_de_clausulas_administrativas_1.pdf")
        self.assertEqual(expediente, "EXP-123")
        self.assertEqual(tipo, "administrativo")

        expediente, tipo = infer_document_metadata_from_filename("EXP-123__Pliego_de_prescripciones_tecnicas_2.pdf")
        self.assertEqual(expediente, "EXP-123")
        self.assertEqual(tipo, "tecnico")

        self.assertEqual(infer_document_metadata_from_filename("sin_metadatos.pdf"), (None, None))
        self.assertEqual(infer_document_metadata_from_filename("EXP-123__Anexo_general.pdf"), ("EXP-123", None))
        self.assertEqual(_normalize_text("  Ágil   Técnico  "), "agil   tecnico")

    def test_resolve_pdf_path_rejects_empty_or_non_pdf_names(self):
        service = self._service()

        with self.assertRaises(ValueError):
            service.resolve_pdf_path("")
        with self.assertRaises(ValueError):
            service.resolve_pdf_path("documento.txt")

    def test_is_pdf_upload_rejects_missing_or_non_seekable_streams(self):
        service = self._service()
        no_stream = SimpleNamespace(filename="archivo.pdf")
        non_seekable = MagicMock()
        non_seekable.seekable.return_value = False
        bad_storage = SimpleNamespace(filename="archivo.pdf", stream=non_seekable)

        self.assertFalse(service._is_pdf_upload(no_stream))
        self.assertFalse(service._is_pdf_upload(bad_storage))

    def test_save_uploads_persists_only_pdf_files(self):
        service = self._service()
        pdf = FileStorage(stream=BytesIO(b"%PDF-1.4 data"), filename="uno.pdf")
        txt = FileStorage(stream=BytesIO(b"hola"), filename="dos.txt")

        service.save_uploads([pdf, txt])

        docs = Documento.query.all()
        self.assertEqual(len(docs), 1)
        self.assertEqual(docs[0].nombre, "uno.pdf")
        self.assertTrue((self._docs_dir / "uno.pdf").exists())

    def test_save_uploads_skips_empty_items_and_empty_filenames(self):
        service = self._service()
        empty_name = FileStorage(stream=BytesIO(b"%PDF-1.4 data"), filename="")

        saved = service.save_uploads([None, empty_name])

        self.assertEqual(saved, 0)
        self.assertEqual(Documento.query.count(), 0)

    def test_list_documents_paginated_and_markdown_helpers(self):
        service = self._service()
        first = self.create_document(nombre="first.pdf")
        second = self.create_document(nombre="second.pdf")
        second.markdown_content = "# Markdown"
        db.session.commit()

        pagination = service.list_documents_paginated(page=1, per_page=1)
        status_map = service.get_markdown_status_map([first, second])

        self.assertEqual(len(pagination.items), 1)
        self.assertEqual(status_map, {first.id: False, second.id: True})
        self.assertEqual(service.count_pending_markdown([first, second]), 1)
        self.assertEqual(service.count_pending_markdown(), 1)

    def test_delete_document_removes_record_and_files(self):
        service = self._service()
        doc = self.create_document(nombre="borrar.pdf")
        doc.markdown_content = "contenido"
        service.delete_chunks = MagicMock()
        self.create_chunk(document=doc)

        service.delete_document(doc.id)

        self.assertIsNone(db.session.get(Documento, doc.id))
        self.assertFalse(Path(doc.path).exists())
        service.delete_chunks.assert_called_once_with("borrar.pdf")

    def test_clear_markdown_content_delegates_to_document(self):
        service = self._service()
        doc = self.create_document(nombre="markdown-clear.pdf", status="markdown_generado")
        doc.markdown_content = "# contenido"

        service.clear_markdown_content(doc)

        self.assertIsNone(doc.markdown_content)

    def test_delete_document_handles_missing_doc_and_cleanup_errors(self):
        service = self._service()
        service.delete_document(9999)

        doc = self.create_document(nombre="cleanup-errors.pdf")
        service.delete_chunks = MagicMock(side_effect=RuntimeError("remote error"))

        with patch("app.main.code.services.documentos.Path.exists", side_effect=RuntimeError("fs error")):
            service.delete_document(doc.id)

        self.assertIsNone(db.session.get(Documento, doc.id))

    def test_has_markdown_uses_document_attribute(self):
        service = self._service()
        doc = self.create_document(nombre="detectable.pdf")
        self.assertFalse(service.has_markdown(doc))

        doc.markdown_content = "# Convertido"
        self.assertTrue(service.has_markdown(doc))

    def test_convert_document_to_markdown_persists_content_in_same_row(self):
        service = self._service()
        doc = self.create_document(nombre="restaurar.pdf")
        service.markdown_converter = MagicMock(return_value="# Markdown")

        converted = service.convert_document_to_markdown(doc)

        self.assertTrue(converted)
        self.assertEqual(doc.markdown_content, "# Markdown")
        self.assertEqual(doc.status, "con markdown")

    def test_convert_document_to_markdown_skips_existing_markdown_and_keeps_indexed_status(self):
        service = self._service()
        doc = self.create_document(nombre="ya-indexado.pdf", status="indexado")
        doc.markdown_content = "# Ya"
        doc.error_message = "old"
        db.session.commit()

        converted = service.convert_document_to_markdown(doc)

        self.assertFalse(converted)
        self.assertEqual(doc.status, "indexado")
        self.assertIsNone(doc.error_message)

    def test_convert_document_to_markdown_marks_existing_non_indexed_markdown(self):
        service = self._service()
        doc = self.create_document(nombre="ya-con-markdown.pdf", status="cargado")
        doc.markdown_content = "# Ya"
        db.session.commit()

        converted = service.convert_document_to_markdown(doc)

        self.assertFalse(converted)
        self.assertEqual(doc.status, STATUS_WITH_MARKDOWN)

    def test_status_for_existing_markdown_keeps_indexed_or_empty_markdown_status(self):
        service = self._service()

        self.assertEqual(service._status_for_existing_markdown("indexado", "# Markdown"), "indexado")
        self.assertEqual(service._status_for_existing_markdown("cargado", None), "cargado")

    def test_convert_document_to_markdown_raises_without_converter_or_missing_pdf(self):
        service = self._service()
        doc = self.create_document(nombre="sin-converter.pdf")
        service.markdown_converter = None

        with self.assertRaises(RuntimeError):
            service.convert_document_to_markdown(doc)

        service.markdown_converter = MagicMock(return_value="# Nunca")
        Path(doc.path).unlink()
        with self.assertRaises(FileNotFoundError):
            service.convert_document_to_markdown(doc)

    def test_sync_from_folder_creates_or_updates_document_metadata(self):
        service = self._service()
        pdf_path = self._docs_dir / "EXP-9__Pliego_de_prescripciones_tecnicas_1.pdf"
        pdf_path.parent.mkdir(parents=True, exist_ok=True)
        pdf_path.write_bytes(b"%PDF-1.4 primera")

        service.sync_from_folder()
        doc = Documento.query.one()
        self.assertEqual(doc.nombre, pdf_path.name)
        self.assertEqual(doc.numero_expediente, "EXP-9")
        self.assertEqual(doc.tipo_documento, "tecnico")

        doc.markdown_content = "# antiguo"
        db.session.commit()
        pdf_path.write_bytes(b"%PDF-1.4 segunda")
        service.sync_from_folder()

        db.session.refresh(doc)
        self.assertIsNone(doc.markdown_content)

    def test_sync_from_folder_preserves_indexed_and_marks_existing_markdown(self):
        service = self._service()
        indexed_path = self._docs_dir / "indexed.pdf"
        indexed_path.write_bytes(b"%PDF-1.4 indexed")
        service.sync_from_folder()
        indexed = Documento.query.one()
        indexed.markdown_content = "# Indexed"
        indexed.status = "indexado"
        db.session.commit()
        service.sync_from_folder()
        db.session.refresh(indexed)
        self.assertEqual(indexed.status, "indexado")

        markdown_path = self._docs_dir / "markdown.pdf"
        markdown_path.write_bytes(b"%PDF-1.4 markdown")
        service.sync_from_folder()
        markdown = Documento.query.filter_by(nombre="markdown.pdf").one()
        markdown.markdown_content = "# Markdown"
        markdown.status = "cargado"
        db.session.commit()
        service.sync_from_folder()
        db.session.refresh(markdown)
        self.assertEqual(markdown.status, STATUS_WITH_MARKDOWN)

    def test_upsert_existing_document_with_markdown_uses_markdown_status_for_non_indexed_base(self):
        service = self._service()
        pdf_path = self._docs_dir / "existing-markdown.pdf"
        pdf_path.write_bytes(b"%PDF-1.4 same")
        service._upsert_from_path(pdf_path, status="cargado")
        db.session.commit()
        doc = Documento.query.one()
        doc.markdown_content = "# Existing"
        doc.status = "fallido"
        doc.error_message = "old"
        db.session.commit()

        service._upsert_from_path(pdf_path, status="cargado")

        self.assertEqual(doc.status, STATUS_WITH_MARKDOWN)
        self.assertIsNone(doc.error_message)

    def test_purge_missing_files_removes_records_relations_and_remote_chunks(self):
        service = self._service()
        doc = self.create_document(nombre="missing.pdf")
        chunk = self.create_chunk(document=doc)
        db.session.add(
            Embedding(
                chunk_id=chunk.id,
                model_id="test-embedding-model",
                embedding_size=3,
                distance="cosine",
            )
        )
        db.session.commit()
        Path(doc.path).unlink()

        deleted = service.purge_missing_files()

        self.assertEqual(deleted, 1)
        self.assertIsNone(db.session.get(Documento, doc.id))
        service.delete_chunks.assert_called_once_with("missing.pdf")

    def test_purge_missing_files_ignores_remote_delete_errors_and_existing_files(self):
        service = self._service()
        existing = self.create_document(nombre="existing.pdf")
        missing = self.create_document(nombre="missing-error.pdf")
        Path(missing.path).unlink()
        service.delete_chunks = MagicMock(side_effect=RuntimeError("remote error"))

        deleted = service.purge_missing_files()

        self.assertEqual(deleted, 1)
        self.assertIsNotNone(db.session.get(Documento, existing.id))
        self.assertIsNone(db.session.get(Documento, missing.id))

    def test_collect_pending_markdown_docs_updates_stale_existing_status(self):
        service = self._service()
        stale = self.create_document(nombre="stale.pdf", status="cargado")
        stale.markdown_content = "# Stale"
        pending = self.create_document(nombre="pending-collect.pdf")
        db.session.commit()

        pending_docs, skipped = service._collect_pending_markdown_docs()

        self.assertEqual(pending_docs, [pending])
        self.assertEqual(skipped, 1)
        self.assertEqual(stale.status, STATUS_WITH_MARKDOWN)
        self.assertIsNone(stale.error_message)

    def test_build_markdown_page_callback_wraps_progress_arguments(self):
        service = self._service()
        calls = []

        self.assertIsNone(service._build_markdown_page_callback(None, 1, 2))
        callback = service._build_markdown_page_callback(lambda *args: calls.append(args), 2, 5)
        callback(3, 9)

        self.assertEqual(calls, [(2, 5, 3, 9)])

    def test_process_pending_markdown_doc_propagates_cancellation(self):
        service = self._service()
        doc = self.create_document(nombre="cancel-process.pdf")

        with patch.object(service, "convert_document_to_markdown", side_effect=JobCancelledError("cancelado")):
            with self.assertRaises(JobCancelledError):
                service._process_pending_markdown_doc(doc, 1, 1)

    def test_convert_pending_to_markdown_reports_converted_failed_and_skipped(self):
        service = self._service()
        ready = self.create_document(nombre="ready.pdf")
        ready.markdown_content = "# Ready"
        pending = self.create_document(nombre="pending.pdf", hash="hash-pending")
        failing = self.create_document(nombre="failing.pdf", hash="hash-failing")
        db.session.commit()
        service.markdown_converter = MagicMock(side_effect=lambda path, on_page_start=None: None if path.name == failing.nombre else "# OK")
        progress_calls = []
        current_docs = []

        stats = service.convert_pending_to_markdown(
            on_progress=lambda i, total: progress_calls.append((i, total)),
            on_current_doc=current_docs.append,
        )

        self.assertEqual(stats, {"converted": 1, "failed": 1, "skipped": 1, "total": 2})
        self.assertIn(pending.nombre, current_docs)
        self.assertEqual(progress_calls[0], (0, 2))

    def test_convert_pending_to_markdown_counts_skipped_from_existing_doc_during_processing(self):
        service = self._service()
        doc = self.create_document(nombre="skipped-during-processing.pdf")

        with patch.object(service, "convert_document_to_markdown", return_value=False):
            stats = service.convert_pending_to_markdown()

        self.assertEqual(stats, {"converted": 0, "failed": 0, "skipped": 1, "total": 1})

    def test_convert_pending_to_markdown_honors_cancellation(self):
        service = self._service()
        self.create_document(nombre="cancel.pdf")

        with self.assertRaises(JobCancelledError):
            service.convert_pending_to_markdown(should_cancel=lambda: True)

    def test_prepare_document_for_vector_update_clears_relations_and_tolerates_remote_errors(self):
        service = self._service()
        doc = self.create_document(nombre="prepare-vector.pdf", status="fallido", error_message="old")
        chunk = self.create_chunk(document=doc)
        self.link_consulta_chunk(self.create_consulta(self.create_user()), chunk)
        db.session.add(Embedding(chunk_id=chunk.id, model_id="test", embedding_size=3, distance="cosine"))
        db.session.commit()
        service.delete_chunks = MagicMock(side_effect=RuntimeError("remote error"))

        pdf_path = service._prepare_document_for_vector_update(doc)

        self.assertEqual(pdf_path, Path(doc.path))
        self.assertEqual(doc.status, "procesado")
        self.assertIsNone(doc.error_message)
        self.assertEqual(Chunk.query.filter_by(document_id=doc.id).count(), 0)
        self.assertEqual(Embedding.query.count(), 0)

    def test_prepare_document_for_vector_update_raises_when_pdf_missing(self):
        service = self._service()
        doc = self.create_document(nombre="missing-vector.pdf")
        Path(doc.path).unlink()

        with self.assertRaises(FileNotFoundError):
            service._prepare_document_for_vector_update(doc)

    def test_index_vector_document_updates_status_and_rejects_empty_chunks(self):
        service = self._service()
        doc = self.create_document(nombre="index-vector.pdf", numero_expediente="EXP-1", tipo_documento="tecnico")
        vector_doc = SimpleNamespace(id="qid-new", content="Texto", metadata={"segment_index": 0, "sha256": "sha-new"})
        index_pdf = MagicMock(return_value=[vector_doc])

        indexed = service._index_vector_document(doc, index_pdf)

        self.assertEqual(indexed, 1)
        self.assertEqual(doc.chunks, 1)
        self.assertEqual(doc.status, "indexado")
        index_pdf.assert_called_once_with(
            Path(doc.path),
            document_id=doc.id,
            numero_expediente="EXP-1",
            tipo_documento="tecnico",
        )

        empty_doc = self.create_document(nombre="empty-vector.pdf")
        with self.assertRaises(RuntimeError):
            service._index_vector_document(empty_doc, MagicMock(return_value=[]))

    def test_mark_vector_update_failed_rolls_back_and_stores_error(self):
        service = self._service()
        doc = self.create_document(nombre="failed-vector.pdf")

        service._mark_vector_update_failed(doc, RuntimeError("boom"))

        self.assertEqual(doc.status, "fallido")
        self.assertEqual(doc.error_message, "boom")

    def test_update_vector_db_indexes_fails_reports_progress_and_honors_cancellation(self):
        service = self._service()
        ok = self.create_document(nombre="ok-vector.pdf")
        failing = self.create_document(nombre="failing-vector.pdf", status=STATUS_WITH_MARKDOWN)
        ignored = self.create_document(nombre="ignored-vector.pdf", status="indexado")
        progress_calls = []
        current_docs = []

        def fake_index(doc, _index_pdf):
            if doc.id == failing.id:
                raise RuntimeError("boom")
            doc.status = "indexado"
            db.session.commit()
            return 1

        with patch.object(service, "_index_vector_document", side_effect=fake_index):
            stats = service.update_vector_db(
                on_progress=lambda i, total: progress_calls.append((i, total)),
                on_current_doc=current_docs.append,
            )

        self.assertEqual(stats, {"total": 2, "indexed": 1, "failed": 1})
        self.assertEqual(progress_calls, [(0, 2), (1, 2)])
        self.assertIn(ok.nombre, current_docs)
        self.assertIn(failing.nombre, current_docs)
        self.assertEqual(failing.status, "fallido")
        self.assertEqual(ignored.status, "indexado")

        cancel_doc = self.create_document(nombre="cancel-vector.pdf")
        with self.assertRaises(JobCancelledError):
            service.update_vector_db(should_cancel=lambda: True)

    def test_update_sql_creates_chunks_and_embedding_metadata(self):
        doc = self.create_document(nombre="vector.pdf")
        vector_doc = SimpleNamespace(
            id="qid-vector",
            content="Contenido vectorial",
            metadata={
                "segment_index": 3,
                "sha256": "sha-vector",
                "numero_expediente": "EXP-1",
                "tipo_documento": "administrativo",
            },
        )

        update_sql(doc, [vector_doc])
        db.session.commit()

        chunk = doc.chunks_meta[0]
        self.assertEqual(chunk.qdrant_point_id, "qid-vector")
        self.assertEqual(chunk.numero_expediente, "EXP-1")
        self.assertEqual(Embedding.query.filter_by(chunk_id=chunk.id).count(), 1)

    def test_update_sql_skips_invalid_vectors_and_updates_existing_chunk_without_duplicate_embedding(self):
        doc = self.create_document(nombre="vector-existing.pdf")
        chunk = self.create_chunk(document=doc, qdrant_point_id="old-qid", doc_sha256="sha-existing", segment_index=5)
        db.session.add(
            Embedding(
                chunk_id=chunk.id,
                model_id="test-embedding-model",
                embedding_size=3,
                distance="cosine",
            )
        )
        db.session.commit()
        valid_update = SimpleNamespace(
            id="new-qid",
            content="Nuevo contenido",
            metadata={"segment_index": 5, "doc_sha256": "sha-existing", "tipo_documento": "tecnico"},
        )
        invalid_segment = SimpleNamespace(id="bad-seg", content="x", metadata={"segment_index": -1, "sha256": "bad"})
        missing_sha = SimpleNamespace(id="bad-sha", content="x", metadata={"segment_index": 6})

        update_sql(doc, [invalid_segment, missing_sha, valid_update])
        db.session.commit()
        db.session.refresh(chunk)

        self.assertEqual(Chunk.query.filter_by(document_id=doc.id).count(), 1)
        self.assertEqual(chunk.qdrant_point_id, "new-qid")
        self.assertEqual(chunk.n_chars, len("Nuevo contenido"))
        self.assertEqual(chunk.tipo_documento, "tecnico")
        self.assertEqual(Embedding.query.filter_by(chunk_id=chunk.id).count(), 1)

    @patch("app.main.code.controllers.main.routes.qdrant_get_payloads", return_value={"legacy-qid": {"metadata": {"filename": "legacy.pdf"}, "content": "texto"}})
    def test_build_meta_by_consulta_uses_fragmentos_and_legacy_qdrant(self, mock_qdrant):
        from app.main.code.controllers.main.routes import build_meta_by_consulta

        user = self.create_user()
        consulta_saved = self.create_consulta(
            user,
            fragmentos=[{"ranking": 1, "qdrant_point_id": "saved-qid", "metadata": {"filename": "saved.pdf"}, "chunk": "guardado"}],
        )
        consulta_legacy = self.create_consulta(user, pregunta="legacy")
        chunk = self.create_chunk(qdrant_point_id="legacy-qid")
        self.link_consulta_chunk(consulta_legacy, chunk)

        meta = build_meta_by_consulta([consulta_saved, consulta_legacy])

        self.assertEqual(meta[consulta_saved.id]["metadata"]["filename"], "saved.pdf")
        self.assertEqual(meta[consulta_legacy.id]["metadata"]["filename"], "legacy.pdf")
        mock_qdrant.assert_called_once()
