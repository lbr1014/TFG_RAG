"""
Script con pruebas unitarias del modelo Documento, encargado de representar los documentos gestionados por la aplicación. 
Las pruebas verifican la gestión de metadatos, la sincronización con archivos PDF, el mantenimiento del contenido Markdown 
y las transiciones entre los distintos estados del ciclo de procesamiento documental.
"""

import os
import tempfile

from app.main.code.extensions import db
from app.main.code.model.documento import STATUS_WITH_MARKDOWN, Documento
from app.test.support import BaseAppTestCase


class DocumentoUnitTest(BaseAppTestCase):
    def test_documento_sets_default_modified_at_and_status(self):
        """
        Verifica que los documentos recién creados reciben correctamente una fecha de modificación y un estado inicial por defecto.
        """
        with tempfile.TemporaryDirectory() as tmpdir:
            pdf_path = os.path.join(tmpdir, "doc.pdf")
            documento = Documento(nombre="doc.pdf", path=pdf_path, size_bytes=10, hash="hash")
            db.session.add(documento)
            db.session.commit()

        self.assertIsNotNone(documento.modified_at)
        self.assertEqual(documento.status, "cargado")

    def test_documento_preserves_explicit_modified_at(self):
        """
        Comprueba que una fecha de modificación proporcionada explícitamente se conserva sin modificaciones.
        """
        expected = self.create_document().modified_at

        with tempfile.TemporaryDirectory() as tmpdir:
            pdf_path = os.path.join(tmpdir, "explicit.pdf")
            documento = Documento(
                nombre="explicit.pdf",
                path=pdf_path,
                size_bytes=20,
                hash="hash-explicit",
                modified_at=expected,
            )

        self.assertEqual(documento.modified_at, expected)

    def test_documento_syncs_from_pdf_path_and_clears_stale_markdown_when_hash_changes(self):
        """
        Verifica la sincronización de metadatos desde un archivo PDF y la eliminación del contenido Markdown obsoleto cuando cambia el hash del documento.
        """
        pdf_path = self._docs_dir / "EXP-1__Pliego_de_prescripciones_tecnicas_1.pdf"
        pdf_path.parent.mkdir(parents=True, exist_ok=True)
        pdf_path.write_bytes(b"%PDF old")
        modified_at = self.create_document().modified_at
        documento = Documento.from_pdf_path(pdf_path, "old-hash", modified_at)

        self.assertEqual(documento.nombre, pdf_path.name)
        self.assertEqual(documento.numero_expediente, "EXP-1")
        self.assertEqual(documento.tipo_documento, "tecnico")

        documento.markdown_content = "# viejo"
        changed = documento.sync_from_pdf_path(pdf_path, "new-hash", modified_at, status="cargado")

        self.assertTrue(changed)
        self.assertIsNone(documento.markdown_content)
        self.assertEqual(documento.status, "cargado")
        self.assertIsNone(documento.error_message)

    def test_documento_markdown_and_vector_state_helpers(self):
        """
        Comprueba el funcionamiento de los métodos auxiliares encargados de actualizar los estados de conversión Markdown, indexación vectorial y gestión de errores.
        """
        documento = self.create_document(status="fallido", error_message="old")

        documento.mark_markdown_available("# Markdown")
        self.assertEqual(documento.markdown_content, "# Markdown")
        self.assertEqual(documento.status, STATUS_WITH_MARKDOWN)
        self.assertIsNone(documento.error_message)

        documento.mark_vector_processing()
        self.assertEqual(documento.status, "procesado")

        documento.mark_indexed(3)
        self.assertEqual(documento.status, "indexado")
        self.assertEqual(documento.chunks, 3)

        documento.mark_failed(RuntimeError("boom"))
        self.assertEqual(documento.status, "fallido")
        self.assertEqual(documento.error_message, "boom")


