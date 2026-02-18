import os
import tempfile
from io import BytesIO
from pathlib import Path
from werkzeug.datastructures import FileStorage

from tests.__init__ import BaseTestCase
from app.extensions import db
from app.documentos import DocumentosService, Documento, sha256_file


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


