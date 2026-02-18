import uuid
from sqlalchemy.exc import IntegrityError

from tests.__init__ import BaseTestCase
from app.extensions import db
from app.usuario import User
from app.consulta import Consulta
from app.chunk import Chunk
from app.documentos import Documento
from app.consultaChunk import ConsultaChunk

class ConsultaChunkModelTest(BaseTestCase):
    def crear_usuario(self):
        u = User(
            nombre ="testuser",
            email="testuser@example.com",
            password_hash="huiawfh"
        )
        db.session.add(u)
        db.session.commit()
        return u
    
    def crear_consulta(self):
        u = self.crear_usuario()

        consulta = Consulta(
            user_id=u.id,
            pregunta="¿Caracteristicas de los pliegos administrativos?",
            respuesta="Los pliegos administrativos son...",
            tiempo_respuestas=0.25,
        )
        db.session.add(consulta)
        db.session.commit()
        return consulta
    
    def crear_documento(self):
        doc = Documento(
           nombre="doc1",
           path = f"el_path_del _documento/{uuid.uuid4()}.pdf",
           size_bytes = 2024,
           modified_at = None,
           chunks = 5,
           hash = "200",
           status = "cargado",
           error_message = None
        )
        db.session.add(doc)
        db.session.commit()
        return doc
    
    def crear_chunk(self, segment_index=0, doc_sha256="h"):
        doc = self.crear_documento()
        chunk = Chunk(
            document_id=doc.id,
            qdrant_point_id=str(uuid.uuid4()),
            segment_index=segment_index,
            doc_sha256=doc_sha256,
            n_chars=10,
            n_tokens=3,
        )
        db.session.add(chunk)
        db.session.commit()
        return chunk
    
    def test_relacion_consulta_chunk(self):
        consulta = self.crear_consulta()
        chunk = self.crear_chunk(segment_index=0, doc_sha256="a")

        cc = ConsultaChunk(
            consulta_id=consulta.id,
            chunk_id=chunk.id,
            similitud=0.85,
            ranking=1,
        )
        db.session.add(cc)
        db.session.commit()

        self.assertIsNotNone(cc.consulta)
        self.assertIsNotNone(cc.chunk)
        self.assertEqual(cc.consulta.id, consulta.id)
        self.assertEqual(cc.chunk.id, chunk.id)

        self.assertEqual(len(consulta.consultaChunks), 1)
        self.assertEqual(consulta.consultaChunks[0].chunk_id, chunk.id)

    def test_pk_compuesta(self):
        consulta = self.crear_consulta()
        chunk = self.crear_chunk(segment_index=0, doc_sha256="b")

        cc1 = ConsultaChunk(
            consulta_id=consulta.id,
            chunk_id=chunk.id,
            similitud=0.9,
            ranking=1,
        )
        db.session.add(cc1)
        db.session.commit()

        cc2 = ConsultaChunk(
            consulta_id=consulta.id,
            chunk_id=chunk.id,
            similitud=0.8,
            ranking=2,  
        )
        db.session.add(cc2)
        with self.assertRaises(IntegrityError):
            db.session.commit()
        db.session.rollback()

    def test_unique_constraint_ranking(self):
        consulta = self.crear_consulta()
        chunk1 = self.crear_chunk(segment_index=0, doc_sha256="c")
        chunk2 = self.crear_chunk(segment_index=1, doc_sha256="c")

        cc1 = ConsultaChunk(
            consulta_id=consulta.id,
            chunk_id=chunk1.id,
            similitud=0.9,
            ranking=1,
        )
        db.session.add(cc1)
        db.session.commit()

        cc2 = ConsultaChunk(
            consulta_id=consulta.id,
            chunk_id=chunk2.id,
            similitud=0.88,
            ranking=1,
        )
        db.session.add(cc2)
        with self.assertRaises(IntegrityError):
            db.session.commit()
        db.session.rollback()

    def test_campos_obligatorios(self):
        consulta = self.crear_consulta()
        chunk = self.crear_chunk(segment_index=0, doc_sha256="d")

        cc = ConsultaChunk(
            consulta_id=consulta.id,
            chunk_id=chunk.id,
            similitud=None,
            ranking=None,
        )
        db.session.add(cc)
        with self.assertRaises(IntegrityError):
            db.session.commit()
        db.session.rollback()

    def test_cascade_delete_consulta(self):
        consulta = self.crear_consulta()
        chunk = self.crear_chunk(segment_index=0, doc_sha256="e")

        cc = ConsultaChunk(
            consulta_id=consulta.id,
            chunk_id=chunk.id,
            similitud=0.9,
            ranking=1,
        )
        db.session.add(cc)
        db.session.commit()

        db.session.delete(consulta)
        db.session.commit()

        existe = db.session.get(ConsultaChunk, (consulta.id, chunk.id))
        self.assertIsNone(existe)

    def test_cascade_delete_chunk(self):
        consulta = self.crear_consulta()
        chunk = self.crear_chunk(segment_index=0, doc_sha256="f")

        cc = ConsultaChunk(
            consulta_id=consulta.id,
            chunk_id=chunk.id,
            similitud=0.9,
            ranking=1,
        )
        db.session.add(cc)
        db.session.commit()

        db.session.delete(chunk)
        db.session.commit()

        existe = db.session.get(ConsultaChunk, (consulta.id, chunk.id))
        self.assertIsNone(existe)
    