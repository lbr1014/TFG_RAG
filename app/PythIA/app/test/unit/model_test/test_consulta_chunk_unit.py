"""
Script con pruebas unitarias del modelo ConsultaChunk, encargado de representar la relación entre una consulta realizada por un usuario y 
los fragmentos de documentos recuperados durante el proceso de búsqueda semántica. Su objetivo es verificar la correcta asociación entre consultas y 
fragmentos, así como el almacenamiento de métricas relevantes como la similitud obtenida y la posición de cada fragmento dentro del ranking de resultados.
"""

from app.main.code.extensions import db
from app.main.code.model.consulta_chunk import ConsultaChunk
from app.test.support import BaseAppTestCase


class ConsultaChunkUnitTest(BaseAppTestCase):
    def test_consulta_chunk_links_consulta_and_chunk(self):
        """
        Verifica que la relación entre una consulta y un fragmento documental se almacena correctamente y que las asociaciones entre ambos objetos funcionan adecuadamente.
        """
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
        """
        Comprueba que los valores de similitud y posición en el ranking se almacenan correctamente dentro de la relación entre consulta y fragmento.
        """
        user = self.create_user()
        consulta = self.create_consulta(user)
        chunk = self.create_chunk()

        link = ConsultaChunk(consulta_id=consulta.id, chunk_id=chunk.id, similitud=0.42, ranking=3)

        self.assertEqual(link.similitud, 0.42)
        self.assertEqual(link.ranking, 3)


