from tests.support import BaseAppTestCase

from app.entities.documento import Documento
from app.extensions import db


class DocumentoUnitTest(BaseAppTestCase):
    def test_documento_sets_default_modified_at_and_status(self):
        documento = Documento(nombre="doc.pdf", path="/tmp/doc.pdf", size_bytes=10, hash="hash")
        db.session.add(documento)
        db.session.commit()

        self.assertIsNotNone(documento.modified_at)
        self.assertEqual(documento.status, "cargado")

    def test_documento_preserves_explicit_modified_at(self):
        expected = self.create_document().modified_at

        documento = Documento(
            nombre="explicit.pdf",
            path="/tmp/explicit.pdf",
            size_bytes=20,
            hash="hash-explicit",
            modified_at=expected,
        )

        self.assertEqual(documento.modified_at, expected)
