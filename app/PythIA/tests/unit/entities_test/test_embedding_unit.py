from tests.support import BaseAppTestCase

from app.entities.embedding import Embedding
from app.extensions import db


class EmbeddingUnitTest(BaseAppTestCase):
    def test_embedding_sets_default_created_at_and_distance(self):
        chunk = self.create_chunk()
        embedding = Embedding(chunk_id=chunk.id, model_id="model", embedding_size=3)
        db.session.add(embedding)
        db.session.commit()

        self.assertIsNotNone(embedding.created_at)
        self.assertEqual(embedding.distance, "cosine")
        self.assertEqual(chunk.embedding_meta.id, embedding.id)

    def test_embedding_preserves_custom_distance(self):
        embedding = Embedding(chunk_id=1, model_id="model", embedding_size=4, distance="dot")

        self.assertEqual(embedding.distance, "dot")
