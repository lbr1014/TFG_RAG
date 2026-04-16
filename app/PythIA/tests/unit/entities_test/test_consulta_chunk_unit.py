from tests.support import BaseAppTestCase

from app.entities.consulta_chunk import ConsultaChunk
from app.extensions import db


class ConsultaChunkUnitTest(BaseAppTestCase):
    def test_consulta_chunk_links_consulta_and_chunk(self):
        user = self.create_user()
        consulta = self.create_consulta(user)
        chunk = self.create_chunk()

        link = ConsultaChunk(consulta_id=consulta.id, chunk_id=chunk.id, similitud=0.8, ranking=1)
        db.session.add(link)
        db.session.commit()

        self.assertEqual(link.consulta.id, consulta.id)
        self.assertEqual(link.chunk.id, chunk.id)
        self.assertEqual(consulta.consultaChunks[0].ranking, 1)

    def test_consulta_chunk_stores_score_and_ranking(self):
        user = self.create_user()
        consulta = self.create_consulta(user)
        chunk = self.create_chunk()

        link = ConsultaChunk(consulta_id=consulta.id, chunk_id=chunk.id, similitud=0.42, ranking=3)

        self.assertEqual(link.similitud, 0.42)
        self.assertEqual(link.ranking, 3)
