from unittest.mock import patch
from sqlalchemy.exc import SQLAlchemyError

from tests.__init__ import BaseTestCase
from app.extensions import db
from app.usuario import User
from app.documentos import Documento
from app.chunk import Chunk
from app.rag.service import (
    rag_answer,
    validate_question,
    message_error,
    try_persist,
    persist_consulta,
    find_chunk,
    qdrant_search_with_scores,
)
from app.consulta import Consulta
from app.consultaChunk import ConsultaChunk

class _QResWithPoints:
    def __init__(self, points):
        self.points = points

class _FakeQdrant:
    def __init__(self, result):
        self._result = result
        self.calls = []

    def query_points(self, **kwargs):
        self.calls.append(kwargs)
        return self._result

class RagServiceTest(BaseTestCase):
    def crear_documento(self):
        doc = Documento(
           nombre="doc1",
           path = "el_path_del _documento.pdf",
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
            qdrant_point_id="qid-1",
            segment_index=segment_index,
            doc_sha256=doc_sha256,
            n_chars=10,
            n_tokens=3,
        )
        db.session.add(chunk)
        db.session.commit()
        return chunk
    
    def tearDown(self):
        ConsultaChunk.query.delete()
        Consulta.query.delete()
        db.session.commit()
        super().tearDown()

    
    def test_question_empty(self):
        out = validate_question("")
        self.assertIsNotNone(out)
        self.assertEqual(out["answer"], "Escribe una pregunta.")

    def test_question_too_long(self):
        out = validate_question("a" * 2001)
        self.assertIsNotNone(out)
        self.assertIn("demasiado larga", out["answer"])

    def test_question_correcta(self):
        out = validate_question("hola")
        self.assertIsNone(out)
        
    def test_message_error_shape(self):
        out = message_error("x")
        self.assertEqual(out["answer"], "x")
        self.assertEqual(out["title"], "")
        self.assertEqual(out["filename"], "")
        self.assertEqual(out["segment_index"], -1)
        self.assertEqual(out["chunk"], "")
        
    def test_find_chunk_by_qdrant_point_id(self):
        ch = self.crear_chunk()
        item = {"qdrant_point_id": "qid-1"}
        found = find_chunk(item)
        self.assertIsNotNone(found)
        self.assertEqual(found.id, ch.id)
    
    def test_find_chunk_by_document(self):
        ch = self.crear_chunk(segment_index=7, doc_sha256="sha-xx")
        item = {
            "qdrant_point_id": "",
            "document_id": ch.document_id,
            "doc_sha256": "sha-xx",
            "segment_index": 7,
        }
        found = find_chunk(item)
        self.assertIsNotNone(found)
        self.assertEqual(found.id, ch.id)
        
    def test_not_found_chunk(self):
        item = {"qdrant_point_id": "nope"}
        found = find_chunk(item)
        self.assertIsNone(found)
        
    def test_exception_path(self):
        with patch("app.rag.service.obtener_mejor_chunk", side_effect=Exception("boom")), \
            patch("app.rag.service.try_persist") as mock_persist:
            out = rag_answer("hola")

        self.assertIn("Ha ocurrido un error", out["answer"])
        self.assertEqual(out["qdrant_point_id"], "")
        self.assertIn("elapsed_s", out)
        mock_persist.assert_called_once()
        
    def test_persist_consulta(self):
        self.user = self.crear_usuario(email="u@example.com", password="pw123456")
        ch = self.crear_chunk()

        data = {
            "answer": "respuesta",
            "retrieved": [
                {"qdrant_point_id": "qid-1", "similitud": 0.9, "ranking": 1},
            ],
        }

        fake_user = type("U", (), {"is_authenticated": True, "id": self.user.id})()

        with patch("app.rag.service.current_user", fake_user):
            persist_consulta("pregunta", data, 0.5)

        c = Consulta.query.first()
        self.assertIsNotNone(c)
        self.assertEqual(c.user_id, self.user.id)
        self.assertEqual(c.pregunta, "pregunta")
        self.assertEqual(c.respuesta, "respuesta")

        rel = ConsultaChunk.query.first()
        self.assertIsNotNone(rel)
        self.assertEqual(rel.consulta_id, c.id)
        self.assertEqual(rel.chunk_id, ch.id)
        self.assertEqual(rel.ranking, 1)
        
    def test_persist_consulta_10_items(self):
        self.user = self.crear_usuario(email="u@example.com", password="pw123456")
        doc = self.crear_documento()
        db.session.add(doc)
        db.session.commit()

        for i in range(12):
            db.session.add(
                Chunk(
                    document_id=doc.id,
                    qdrant_point_id=f"qid-{i}",
                    segment_index=i,
                    doc_sha256="sha",
                    n_chars=10,
                    n_tokens=3,
                )
            )
        db.session.commit()

        retrieved = [{"qdrant_point_id": f"qid-{i}", "similitud": 0.1, "ranking": i + 1} for i in range(12)]
        data = {"answer": "r", "retrieved": retrieved}

        fake_user = type("U", (), {"is_authenticated": True, "id": self.user.id})()
        with patch("app.rag.service.current_user", fake_user):
            persist_consulta("p", data, 0.1)

        self.assertEqual(ConsultaChunk.query.count(), 10)
        
    def test_persist_rollback(self):
        with patch("app.rag.service.persist_consulta", side_effect=Exception("boom")), \
             patch.object(db.session, "rollback") as rb:
            try_persist("p", {"answer": "a"}, 0.1)
            rb.assert_called_once()
            
    def test_rag_answer_invalid_question(self):
        with patch("app.rag.service.obtener_mejor_chunk") as mock_engine:
            out = rag_answer("")
            self.assertEqual(out["answer"], "Escribe una pregunta.")
            mock_engine.assert_not_called()

    def test_rag_answer_correct_question(self):
        engine_out = {
            "answer": "ok",
            "title": "t",
            "filename": "f.pdf",
            "segment_index": 2,
            "chunk": "texto",
            "retrieved": [{"qdrant_point_id": "point-1", "ranking": 1}],
        }

        with patch("app.rag.service.obtener_mejor_chunk", return_value=engine_out), \
             patch("app.rag.service.try_persist") as mock_persist:
            out = rag_answer(" hola ")

        self.assertEqual(out["answer"], "ok")
        self.assertIn("elapsed_s", out)
        self.assertEqual(out["qdrant_point_id"], "point-1")
        mock_persist.assert_called_once()
        
    def test_not_authenticated(self):
        data = {"answer": "r", "retrieved": [{"qdrant_point_id": "qid-1", "ranking": 1}]}

        fake_user = type("U", (), {"is_authenticated": False, "id": 999})()

        with patch("app.rag.service.current_user", fake_user):
            persist_consulta("pregunta", data, 0.1)

        self.assertEqual(Consulta.query.count(), 0)
        self.assertEqual(ConsultaChunk.query.count(), 0)

    def test_search_with_scores(self):
        points = ["p1", "p2"]
        q = _FakeQdrant(_QResWithPoints(points))

        out = qdrant_search_with_scores(q, "col", [0.1, 0.2], limit=2)

        self.assertEqual(out, points)
        self.assertEqual(q.calls[0]["collection_name"], "col")
        self.assertEqual(q.calls[0]["limit"], 2)
        self.assertTrue(q.calls[0]["with_payload"])
        self.assertFalse(q.calls[0]["with_vectors"])
        
        raw = ["already_points"]
        q = _FakeQdrant(raw)

        out = qdrant_search_with_scores(q, "col", [0.1], limit=1)

        self.assertEqual(out, raw)
        
    def test_persist_consulta_chunk_not_found(self):
        self.user = self.crear_usuario(email="u@example.com", password="pw123456")
        ch = self.crear_chunk() 

        data = {
            "answer": "respuesta",
            "retrieved": [
                {"qdrant_point_id": "no-existe", "similitud": 0.1, "ranking": 1},  
                {"qdrant_point_id": "qid-1", "similitud": 0.9, "ranking": 2},      
            ],
        }

        fake_user = type("U", (), {"is_authenticated": True, "id": self.user.id})()

        with patch("app.rag.service.current_user", fake_user), \
            patch("app.rag.service.find_chunk", side_effect=[None, ch]):

            persist_consulta("pregunta", data, 0.5)

        c = Consulta.query.first()
        self.assertIsNotNone(c)

        self.assertEqual(ConsultaChunk.query.count(), 1)
        rel = ConsultaChunk.query.first()
        self.assertEqual(rel.chunk_id, ch.id)
        self.assertEqual(rel.ranking, 2)
