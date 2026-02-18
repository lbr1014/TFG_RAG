import os
import tempfile
from io import BytesIO
from pathlib import Path
from werkzeug.datastructures import FileStorage
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from unittest.mock import patch

from tests.__init__ import BaseTestCase
from app.extensions import db
from app.documentos import DocumentosService, Documento, sha256_file, update_sql
from app.rag.PrototipoRAG import index_pdf, embedding_model
from app.chunk import Chunk
from app.embedding import Embedding

class VectorDocs:
    def __init__(self, _id, content, metadata):
        self.id = _id
        self.content = content
        self.metadata = metadata

class DocumentosModelTest(BaseTestCase):
    def test_crear_documento(self):
        doc = Documento(
           nombre="doc1",
           path = "el_path_del _documento.pdf",
           size_bytes = 2024,
           modified_at = None,
           chunks = 5,
           hash = "200",
           status = "cargado",
           error_message = None
        )
        db.session.add(doc)
        db.session.commit()

        saved = Documento.query.first()
        
        self.assertIsNotNone(saved)
        self.assertEqual(saved.nombre, "doc1")
        self.assertIsNotNone(saved.modified_at)
        
    def test_sha256_file(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            file_path = os.path.join(tmpdir, "doc1.pdf")
            with open(file_path, "wb") as f:
                f.write(b"contenido de prueba")

            h = sha256_file(Path(file_path))

            self.assertIsInstance(h, str)
            self.assertEqual(len(h), 64)
        
    def test_resolve_pdf_path_correct(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            svc = DocumentosService(
                docs_dir=Path(tmpdir),
                index_pliegos_dir=None,
                delete_chunks=lambda x: None,
                count_chunks=lambda x: 0,
            )

            path = svc.resolve_pdf_path("archivo.pdf")

            self.assertEqual(path, Path(tmpdir) / "archivo.pdf")
            
        
    def test_resolve_pdf_path_invalid(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            svc = DocumentosService(
                docs_dir=Path(tmpdir),
                index_pliegos_dir=None,
                delete_chunks=lambda x: None,
                count_chunks=lambda x: 0,
            )

            with self.assertRaises(ValueError) as ctx:
                svc.resolve_pdf_path("archivo.txt")
                
            self.assertEqual(str(ctx.exception), "Extensión no permitida")
            
            with self.assertRaises(ValueError) as ctx:
                svc.resolve_pdf_path("")

            self.assertEqual(str(ctx.exception), "Nombre de archivo inválido")

    def test_list_documents_paginated(self):
        now = datetime.now(ZoneInfo("Europe/Madrid"))

        d1 = Documento(nombre="a.pdf", path="a.pdf", size_bytes=1, hash="h1", status="cargado", modified_at=now - timedelta(days=1))
        d2 = Documento(nombre="b.pdf", path="b.pdf", size_bytes=1, hash="h2", status="cargado", modified_at=now)

        db.session.add_all([d1, d2])
        db.session.commit()

        svc = DocumentosService(Path("."), None, lambda x: None, lambda x: 0)
        page = svc.list_documents_paginated(page=1, per_page=10)

        self.assertEqual([x.nombre for x in page.items], ["b.pdf", "a.pdf"])

    def test_save_uploads(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            svc = DocumentosService(
                docs_dir=Path(tmpdir),
                index_pliegos_dir=None,
                delete_chunks=lambda x: None,
                count_chunks=lambda x: 0,
            )

            fake_file = FileStorage(
                stream=BytesIO(b"contenido pdf"),
                filename="test.pdf",
                content_type="application/pdf",
            )

            svc.save_uploads([fake_file])

            doc = Documento.query.first()

            self.assertTrue(os.path.exists(os.path.join(tmpdir, "test.pdf")))
            self.assertIsNotNone(doc)
            self.assertEqual(doc.nombre, "test.pdf")
            
    def test_save_uploads_invalids(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            svc = DocumentosService(
                docs_dir=Path(tmpdir),
                index_pliegos_dir=None,
                delete_chunks=lambda x: None,
                count_chunks=lambda x: 0,
            )
            file_none = None
            
            file_empty = FileStorage(
                stream=BytesIO(b"contenido"),
                filename="",
                content_type="application/pdf",
            )
            
            file_wrong = FileStorage(
                stream=BytesIO(b"contenido"),
                filename="archivo.txt",
                content_type="text/plain",
            )
            
            svc.save_uploads([file_none, file_empty, file_wrong])
            self.assertEqual(len(os.listdir(tmpdir)), 0)
            self.assertIsNone(Documento.query.first())
            

        
    def test_purge_missing_files(self):
        deleted_called = []

        def fake_delete_chunks(name):
            deleted_called.append(name)

        doc = Documento(
            nombre="ghost.pdf",
            path="ghost.pdf",
            size_bytes=10,
            hash="abc",
            status="cargado",
        )
        db.session.add(doc)
        db.session.commit()

        svc = DocumentosService(
            docs_dir=Path("."),
            index_pliegos_dir=None,
            delete_chunks=fake_delete_chunks,
            count_chunks=lambda x: 0,
        )

        deleted = svc.purge_missing_files()

        self.assertEqual(deleted, 1)
        self.assertEqual(deleted_called, ["ghost.pdf"])
        self.assertIsNone(Documento.query.first())
        
    def test_purge_missing_files_exception(self):
        def fake_delete_chunks(name):
            raise RuntimeError("Error en Qdrant")

        doc = Documento(
            nombre="ghost.pdf",
            path="ghost.pdf",
            size_bytes=10,
            hash="abc",
            status="cargado",
        )
        db.session.add(doc)
        db.session.commit()

        svc = DocumentosService(
            docs_dir=Path("."),
            index_pliegos_dir=None,
            delete_chunks=fake_delete_chunks,
            count_chunks=lambda x: 0,
        )

        deleted = svc.purge_missing_files()

        self.assertEqual(deleted, 1)
        self.assertIsNone(Documento.query.first())

        
    def test_sync_from_folder(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            docs_dir = Path(tmpdir)
            (docs_dir / "uno.pdf").write_bytes(b"pdf1")
            (docs_dir / "dos.pdf").write_bytes(b"pdf2")

            ghost = Documento(nombre="ghost.pdf", path=str(docs_dir / "ghost.pdf"), size_bytes=1, hash="x", status="cargado")
            db.session.add(ghost)
            db.session.commit()

            svc = DocumentosService(docs_dir, None, lambda x: None, lambda x: 0)
            svc.sync_from_folder()

            nombres = sorted([d.nombre for d in Documento.query.all()])
            self.assertEqual(nombres, ["dos.pdf", "uno.pdf"]) 

            for d in Documento.query.all():
                self.assertEqual(d.status, "cargado")
                self.assertTrue(Path(d.path).exists())

    def test_delete_document(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            deleted_called = []

            def fake_delete_chunks(name):
                deleted_called.append(name)

            file_path = os.path.join(tmpdir, "test.pdf")
            with open(file_path, "wb") as f:
                f.write(b"contenido")

            doc = Documento(
                nombre="test.pdf",
                path=file_path,
                size_bytes=10,
                hash="abc",
                status="cargado",
            )
            db.session.add(doc)
            db.session.commit()

            svc = DocumentosService(
                docs_dir=Path(tmpdir),
                index_pliegos_dir=None,
                delete_chunks=fake_delete_chunks,
                count_chunks=lambda x: 0,
            )

            svc.delete_document(doc.id)

            self.assertEqual(deleted_called, ["test.pdf"])
            self.assertFalse(os.path.exists(file_path))
            self.assertIsNone(Documento.query.first())
            
    def test_delete_document_not_found(self):
        svc = DocumentosService(
            docs_dir=Path("."),
            index_pliegos_dir=None,
            delete_chunks=lambda x: None,
            count_chunks=lambda x: 0,
        )
        svc.delete_document(999999)

        self.assertEqual(Documento.query.count(), 0)

    
    def test_delete_document_exception(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            def failing_delete_chunks(name):
                raise RuntimeError("Qdrant down")

            file_path = os.path.join(tmpdir, "test.pdf")
            with open(file_path, "wb") as f:
                f.write(b"contenido")

            doc = Documento(
                nombre="test.pdf",
                path=file_path,
                size_bytes=10,
                hash="abc",
                status="cargado",
            )
            db.session.add(doc)
            db.session.commit()

            svc = DocumentosService(
                docs_dir=Path(tmpdir),
                index_pliegos_dir=None,
                delete_chunks=failing_delete_chunks,
                count_chunks=lambda x: 0,
            )

            with patch.object(Path, "unlink", side_effect=OSError("No se puede borrar")):
                svc.delete_document(doc.id)

            self.assertIsNone(Documento.query.first())
            self.assertTrue(os.path.exists(file_path))


    def test_upsert_and_update(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            docs_dir = Path(tmpdir)
            p = docs_dir / "a.pdf"
            p.write_bytes(b"v1")

            svc = DocumentosService(docs_dir, None, lambda x: None, lambda x: 0)

            svc._upsert_from_path(p, status=None)
            db.session.commit()

            doc = Documento.query.filter_by(path=str(p)).first()
            self.assertIsNotNone(doc)
            self.assertEqual(doc.status, "cargado")

            doc.status = "indexado"
            doc.error_message = "algo"
            db.session.commit()

            p.write_bytes(b"v2")
            svc._upsert_from_path(p, status=None)
            db.session.commit()

            doc2 = Documento.query.filter_by(path=str(p)).first()
            self.assertEqual(doc2.status, "indexado")          
            self.assertEqual(doc2.error_message, "algo")       

            svc._upsert_from_path(p, status="fallido")
            db.session.commit()

            doc3 = Documento.query.filter_by(path=str(p)).first()
            self.assertEqual(doc3.status, "fallido")
            self.assertIsNone(doc3.error_message)
            
    def test_update_vector_db(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            docs_dir = Path(tmpdir)
            pdf = docs_dir / "x.pdf"
            pdf.write_bytes(b"pdf")

            doc = Documento(nombre="x.pdf", path=str(pdf), size_bytes=3, hash="h", status="cargado")
            db.session.add(doc)
            db.session.commit()

            from app.chunk import Chunk
            from app.embedding import Embedding
            ch = Chunk(document_id=doc.id, qdrant_point_id="old", segment_index=0, doc_sha256="sha", n_chars=1)
            db.session.add(ch)
            db.session.commit()
            emb = Embedding(chunk_id=ch.id, model_id="m", embedding_size=3, distance="cosine")
            db.session.add(emb)
            db.session.commit()

            progress_calls = []
            current_calls = []

            def on_progress(i, total): progress_calls.append((i, total))
            def on_current(name): current_calls.append(name)

            vector_docs = [
                VectorDocs("new1", "c1", {"segment_index": 0, "sha256": "sha_new"}),
                VectorDocs("new2", "c2", {"segment_index": 1, "sha256": "sha_new"}),
            ]

            svc = DocumentosService(docs_dir, None, lambda x: None, lambda x: 0)

            with patch("app.rag.PrototipoRAG.index_pdf", return_value=vector_docs), \
                patch("app.rag.PrototipoRAG.embedding_model", type("M", (), {"model_id": "m1", "embedding_size": 384})()):
                svc.update_vector_db(on_progress=on_progress, on_current_doc=on_current)

            doc_db = Documento.query.get(doc.id)
            self.assertEqual(doc_db.status, "indexado")
            self.assertEqual(doc_db.chunks, 2)
            self.assertEqual(current_calls, ["x.pdf"])
            self.assertTrue(progress_calls) 
            self.assertEqual(Embedding.query.count(), 2) 
            self.assertEqual(Chunk.query.filter_by(document_id=doc.id).count(), 2)

    def test_update_vector_db_no_pdf(self):
        doc = Documento(
            nombre="missing.pdf",
            path="missing.pdf",   
            size_bytes=1,
            hash="h",
            status="cargado",
        )
        db.session.add(doc)
        db.session.commit()

        svc = DocumentosService(Path("."), None, lambda x: None, lambda x: 0)
        with patch.object(DocumentosService, "purge_missing_files", return_value=0):
            svc.update_vector_db()

        doc_db = Documento.query.get(doc.id)
        self.assertIsNotNone(doc_db)
        self.assertEqual(doc_db.status, "fallido")
        self.assertIn("PDF no existe en contenedor", doc_db.error_message)

    def test_update_vector_db_failed(self):
         with tempfile.TemporaryDirectory() as tmpdir:
            docs_dir = Path(tmpdir)
            pdf = docs_dir / "x.pdf"
            pdf.write_bytes(b"pdf")  

            doc = Documento(nombre="x.pdf", path=str(pdf), size_bytes=3, hash="h", status="cargado")
            db.session.add(doc)
            db.session.commit()

            svc = DocumentosService(docs_dir, None, lambda x: None, lambda x: 0)

            with patch("app.rag.PrototipoRAG.index_pdf", return_value=[]):
                svc.update_vector_db()

            doc_db = Documento.query.get(doc.id)
            self.assertIsNotNone(doc_db)
            self.assertEqual(doc_db.status, "fallido")
            self.assertIn("index_pdf devolvió 0 chunks", doc_db.error_message)
    
    def test_update_vector_db_failed_delete(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            docs_dir = Path(tmpdir)
            pdf = docs_dir / "x.pdf"
            pdf.write_bytes(b"pdf") 

            doc = Documento(nombre="x.pdf", path=str(pdf), size_bytes=3, hash="h", status="cargado")
            db.session.add(doc)
            db.session.commit()

            def failing_delete_chunks(_name):
                raise RuntimeError("Qdrant down")

            svc = DocumentosService(
                docs_dir=docs_dir,
                index_pliegos_dir=None,
                delete_chunks=failing_delete_chunks,   
                count_chunks=lambda x: 0,
            )

            vector_docs = [
                VectorDocs("new1", "c1", {"segment_index": 0, "sha256": "sha_new"}),
            ]

            fake_model = type("M", (), {"model_id": "m1", "embedding_size": 384})()

            with patch("app.rag.PrototipoRAG.index_pdf", return_value=vector_docs), \
                patch("app.rag.PrototipoRAG.embedding_model", fake_model):
                svc.update_vector_db()

            doc_db = Documento.query.get(doc.id)
            self.assertEqual(doc_db.status, "indexado")  
            self.assertEqual(doc_db.chunks, 1)
    
    def test_update_sql(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            docs_dir = Path(tmpdir)
            pdf = docs_dir / "d.pdf"
            pdf.write_bytes(b"pdf")

            doc = Documento(nombre="d.pdf", path=str(pdf), size_bytes=3, hash="h", status="cargado")
            db.session.add(doc)
            db.session.commit()

            bad1 = VectorDocs("id_bad", "x", {"segment_index": -1, "sha256": "sha"})
            bad2 = VectorDocs("id_bad2", "x", {"segment_index": 0, "sha256": ""})

            ok1 = VectorDocs("id1", "content1", {"segment_index": 0, "sha256": "sha1"})
            ok2 = VectorDocs("id2", "content2", {"segment_index": 0, "sha256": "sha1"})

            with patch("app.rag.PrototipoRAG.embedding_model", type("M", (), {"model_id": "m1", "embedding_size": 384})()):
                update_sql(doc, [bad1, bad2, ok1])
                db.session.commit()

                self.assertEqual(Chunk.query.count(), 1)
                self.assertEqual(Embedding.query.count(), 1)

                c = Chunk.query.first()
                self.assertEqual(c.qdrant_point_id, "id1")
                self.assertEqual(c.n_chars, len("content1"))

                update_sql(doc, [ok2])
                db.session.commit()

                c2 = Chunk.query.first()
                self.assertEqual(c2.qdrant_point_id, "id2")
                self.assertEqual(Chunk.query.count(), 1)
                self.assertEqual(Embedding.query.count(), 1)
