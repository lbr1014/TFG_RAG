"""
Autora: Lydia Blanco Ruiz
Script con pruebas unitarias de la aplicación.
"""

from io import BytesIO
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from werkzeug.datastructures import FileStorage

from tests.support import BaseAppTestCase

from app.documentos import DocumentosService, JobCancelledError, infer_document_metadata_from_filename, update_sql
from app.entities.documento import Documento
from app.entities.embedding import Embedding
from app.extensions import db


class DocumentosUnitTest(BaseAppTestCase):
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

    def test_save_uploads_persists_only_pdf_files(self):
        service = self._service()
        pdf = FileStorage(stream=BytesIO(b"%PDF-1.4 data"), filename="uno.pdf")
        txt = FileStorage(stream=BytesIO(b"hola"), filename="dos.txt")

        service.save_uploads([pdf, txt])

        docs = Documento.query.all()
        self.assertEqual(len(docs), 1)
        self.assertEqual(docs[0].nombre, "uno.pdf")
        self.assertTrue((self._docs_dir / "uno.pdf").exists())

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

    def test_convert_pending_to_markdown_honors_cancellation(self):
        service = self._service()
        self.create_document(nombre="cancel.pdf")

        with self.assertRaises(JobCancelledError):
            service.convert_pending_to_markdown(should_cancel=lambda: True)

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

    @patch("app.main.routes.qdrant_get_payloads", return_value={"legacy-qid": {"metadata": {"filename": "legacy.pdf"}, "content": "texto"}})
    def test_build_meta_by_consulta_uses_fragmentos_and_legacy_qdrant(self, mock_qdrant):
        from app.main.routes import build_meta_by_consulta

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
