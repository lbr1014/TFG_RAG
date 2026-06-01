"""
Script con pruebas unitarias del modelo Embedding, encargado de almacenar los vectores generados a partir de los fragmentos documentales. 
Su objetivo es verificar la correcta creación de embeddings, su asociación con los fragmentos correspondientes y la configuración de las métricas 
de distancia utilizadas en las búsquedas vectoriales.
"""

from app.main.code.extensions import db
from app.main.code.model.embedding import Embedding
from app.test.support import BaseAppTestCase


class EmbeddingUnitTest(BaseAppTestCase):
    def test_embedding_sets_default_created_at_and_distance(self):
        """
        Verifica que los embeddings reciben correctamente una fecha de creación y utilizan la métrica de distancia por defecto.
        """
        chunk = self.create_chunk()
        embedding = Embedding(chunk_id=chunk.id, model_id="model", embedding_size=3)
        db.session.add(embedding)
        db.session.commit()

        self.assertIsNotNone(embedding.created_at)
        self.assertEqual(embedding.distance, "cosine")
        self.assertEqual(chunk.embedding_meta.id, embedding.id)

    def test_embedding_preserves_custom_distance(self):
        """
        Comprueba que una métrica de distancia especificada explícitamente se almacena correctamente.
        """
        embedding = Embedding(chunk_id=1, model_id="model", embedding_size=4, distance="dot")

        self.assertEqual(embedding.distance, "dot")


