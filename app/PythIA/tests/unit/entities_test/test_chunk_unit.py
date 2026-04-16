from tests.support import BaseAppTestCase

from app.entities.chunk import Chunk
from app.extensions import db


class ChunkUnitTest(BaseAppTestCase):
    def test_chunk_sets_default_created_at_and_links_document(self):
        document = self.create_document(nombre="chunk.pdf")
        chunk = Chunk(document_id=document.id, qdrant_point_id="qid", segment_index=1, doc_sha256="sha")
        db.session.add(chunk)
        db.session.commit()

        self.assertIsNotNone(chunk.created_at)
        self.assertEqual(chunk.document.id, document.id)
        self.assertEqual(document.chunks_meta[0].id, chunk.id)

    def test_chunk_preserves_explicit_created_at(self):
        created_at = self.create_document().modified_at
        chunk = Chunk(
            document_id=1,
            qdrant_point_id="qid-explicit",
            segment_index=2,
            doc_sha256="sha",
            created_at=created_at,
        )

        self.assertEqual(chunk.created_at, created_at)
