"""
Script con pruebas unitarias del modelo Chunk, utilizado para representar los fragmentos de texto almacenados durante el proceso de indexación documental. 
Su objetivo es verificar la correcta creación de los fragmentos, su asociación con los documentos de origen y la gestión adecuada de los campos temporales 
utilizados para el seguimiento y almacenamiento de la información.
"""

from app.main.code.extensions import db
from app.main.code.model.chunk import Chunk
from app.test.support import BaseAppTestCase


class ChunkUnitTest(BaseAppTestCase):
    def test_chunk_sets_default_created_at_and_links_document(self):
        """
        VVerifica que, al crear un fragmento sin especificar fecha de creación, se asigna automáticamente una marca temporal válida y 
        se establece correctamente la relación con el documento al que pertenece.
        """
        document = self.create_document(nombre="chunk.pdf")
        chunk = Chunk(document_id=document.id, qdrant_point_id="qid", segment_index=1, doc_sha256="sha")
        db.session.add(chunk)
        db.session.commit()

        self.assertIsNotNone(chunk.created_at)
        self.assertEqual(chunk.document.id, document.id)
        self.assertEqual(document.chunks_meta[0].id, chunk.id)

    def test_chunk_preserves_explicit_created_at(self):
        """
        Comprueba que, cuando se proporciona explícitamente una fecha de creación al fragmento, esta se conserva sin ser modificada por el modelo.
        """
        created_at = self.create_document().modified_at
        chunk = Chunk(
            document_id=1,
            qdrant_point_id="qid-explicit",
            segment_index=2,
            doc_sha256="sha",
            created_at=created_at,
        )

        self.assertEqual(chunk.created_at, created_at)


