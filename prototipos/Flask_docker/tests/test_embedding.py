from datetime import datetime
from zoneinfo import ZoneInfo
from sqlalchemy.exc import IntegrityError

from tests.__init__ import BaseTestCase
from app.extensions import db
from app.documentos import Documento
from app.chunk import Chunk
from app.embedding import Embedding


class EmbeddingModelTest(BaseTestCase):
    def crear_documento(self):
        doc = Documento(
            nombre="doc1.pdf",
            path="doc1.pdf",
            size_bytes=123,
            hash="h1",
            status="cargado",
        )
        db.session.add(doc)
        db.session.commit()
        return doc

    def crear_chunk(self, doc: Documento, seg: int = 0, sha: str = "sha1", qid: str = "qid-1"):
        c = Chunk(
            document_id=doc.id,
            qdrant_point_id=qid,
            segment_index=seg,
            doc_sha256=sha,
            n_chars=10,
            n_tokens=3,
        )
        db.session.add(c)
        db.session.commit()
        return c

    def test_init_sin_created_at(self):
        doc = self.crear_documento()
        chunk = self.crear_chunk(doc)

        e = Embedding(
            chunk_id=chunk.id,
            model_id="m1",
            embedding_size=384,
            distance="cosine",
        )
        db.session.add(e)
        db.session.commit()

        self.assertIsInstance(e.created_at, datetime)
        self.assertIsNotNone(e.created_at)

    def test_init_con_created_at(self):
        doc = self.crear_documento()
        chunk = self.crear_chunk(doc)

        fijo = datetime(2020, 1, 1, 12, 0, tzinfo=ZoneInfo("Europe/Madrid"))

        e = Embedding(
            chunk_id=chunk.id,
            model_id="m1",
            embedding_size=384,
            distance="cosine",
            created_at=fijo,
        )
        db.session.add(e)
        db.session.commit()

        self.assertEqual(e.created_at.replace(tzinfo=None), fijo.replace(tzinfo=None))

    def test_unique(self):
        doc = self.crear_documento()
        chunk = self.crear_chunk(doc)

        e1 = Embedding(chunk_id=chunk.id, model_id="m1", embedding_size=384, distance="cosine")
        db.session.add(e1)
        db.session.commit()

        e2 = Embedding(chunk_id=chunk.id, model_id="m2", embedding_size=768, distance="cosine")
        db.session.add(e2)
        with self.assertRaises(IntegrityError):
            db.session.commit()
        db.session.rollback()

    def test_chunk_embedding(self):
        doc = self.crear_documento()
        chunk = self.crear_chunk(doc)

        e = Embedding(chunk_id=chunk.id, model_id="m1", embedding_size=384, distance="cosine")
        db.session.add(e)
        db.session.commit()

        refreshed = Chunk.query.get(chunk.id)
        self.assertIsNotNone(refreshed.embedding_meta)
        self.assertEqual(refreshed.embedding_meta.id, e.id)

    def test_cascade_delete(self):
        doc = self.crear_documento()
        chunk = self.crear_chunk(doc)

        e = Embedding(chunk_id=chunk.id, model_id="m1", embedding_size=384, distance="cosine")
        db.session.add(e)
        db.session.commit()

        emb_id = e.id

        db.session.delete(chunk)
        db.session.commit()

        self.assertIsNone(Embedding.query.get(emb_id))
