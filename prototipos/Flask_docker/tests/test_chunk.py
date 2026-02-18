from datetime import datetime
from zoneinfo import ZoneInfo
from sqlalchemy.exc import IntegrityError

from tests.__init__ import BaseTestCase
from app.extensions import db
from app.chunk import Chunk
from app.documentos import Documento

class ChunkModelTest(BaseTestCase):
    def crear_documento(self):
        doc = Documento(
           id=10,
           nombre="doc1",
           path = "el_path_del _documento",
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

    def test_init_sin_created_at(self):
        doc = self.crear_documento()

        chunk = Chunk(
            document_id=doc.id,
            qdrant_point_id="123e4567-e89b-12d3-a456-426614174000",
            segment_index=0,
            doc_sha256="hash123",
            n_chars=10,
            n_tokens=3,
        )
        db.session.add(chunk)
        db.session.commit()
        
        self.assertIsInstance(chunk.created_at, datetime)
        self.assertIsNotNone(chunk.created_at)

    def test_init_con_created_at(self):
        doc = self.crear_documento()
        fijo = datetime(2020, 1, 1, 12, 0, tzinfo=ZoneInfo("Europe/Madrid"))

        chunk = Chunk(
            document_id=doc.id,
            qdrant_point_id="123e4567-e89b-12d3-a456-426614174001",
            segment_index=1,
            doc_sha256="hash456",
            created_at=fijo,
        )
        db.session.add(chunk)
        db.session.commit()

        fecha = chunk.created_at.replace(tzinfo=None)
        fijo = fijo.replace(tzinfo=None)
        
        self.assertEqual(fecha, fijo)

    def test_unique_hash(self):
        doc = self.crear_documento()

        c1 = Chunk(
            document_id=doc.id,
            qdrant_point_id="123e4567-e89b-12d3-a456-426614174010",
            segment_index=0,
            doc_sha256="mismo-hash",
        )
        c2 = Chunk(
            document_id=doc.id,
            qdrant_point_id="123e4567-e89b-12d3-a456-426614174011",
            segment_index=0,
            doc_sha256="mismo-hash",
        )

        db.session.add(c1)
        db.session.commit()

        db.session.add(c2)
        with self.assertRaises(IntegrityError):
            db.session.commit()
        db.session.rollback()