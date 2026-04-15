"""
Autora: Lydia Blanco Ruiz
Script con pruebas unitarias del servicio RAG.
"""

import asyncio
from unittest.mock import AsyncMock, patch

from tests.support import BaseAppTestCase

from app.entities.consulta import Consulta
from app.entities.consulta_chunk import ConsultaChunk
from app.rag import service


class RAGServiceUnitTest(BaseAppTestCase):
    def test_detect_tipo_documento_distinguishes_admin_and_technical_questions(self):
        self.assertEqual(
            service.detect_tipo_documento("Resume el pliego administrativo del contrato"),
            "administrativo",
        )
        self.assertEqual(
            service.detect_tipo_documento("Que dicen las prescripciones tecnicas?"),
            "tecnico",
        )
        self.assertIsNone(service.detect_tipo_documento("Compara el pliego administrativo y el pliego tecnico"))

    def test_extract_and_resolve_expediente_candidate(self):
        doc = self.create_document(numero_expediente="EXP/2026-001")
        self.create_chunk(document=doc, numero_expediente="EXP/2026-001")

        self.assertEqual(
            service.extract_expediente_candidate('Busca el expediente "EXP/2026-001"'),
            "EXP/2026-001",
        )
        self.assertEqual(
            service.resolve_numero_expediente("Dame el expediente EXP 2026 001"),
            "EXP/2026-001",
        )
        self.assertIsNone(service.extract_expediente_candidate(""))

    def test_validate_question_returns_localized_errors(self):
        self.assertIn("answer", service.validate_question(""))
        self.assertIn("answer", service.validate_question("x" * 2001))
        self.assertIsNone(service.validate_question("Pregunta valida"))

    def test_find_chunk_uses_qdrant_id_and_document_fallback(self):
        doc = self.create_document(nombre="fallback.pdf")
        chunk = self.create_chunk(document=doc, qdrant_point_id="qid-real", doc_sha256="sha", segment_index=4)

        self.assertEqual(service.find_chunk({"qdrant_point_id": "qid-real"}).id, chunk.id)
        self.assertEqual(
            service.find_chunk({"document_id": doc.id, "doc_sha256": "sha", "segment_index": 4}).id,
            chunk.id,
        )
        self.assertIsNone(service.find_chunk({"qdrant_point_id": "missing"}))

    def test_build_fragmento_merges_retrieved_and_database_metadata(self):
        doc = self.create_document(nombre="meta.pdf", hash="hash-meta")
        chunk = self.create_chunk(document=doc, qdrant_point_id="qid-meta", doc_sha256="sha-meta", segment_index=2)

        fragmento = service.build_fragmento(
            {
                "ranking": 1,
                "similitud": 0.75,
                "qdrant_point_id": "qid-meta",
                "chunk": "Texto recuperado",
                "metadata": {"filename": "meta.pdf"},
            },
            chunk,
        )

        self.assertEqual(fragmento["ranking"], 1)
        self.assertEqual(fragmento["metadata"]["document_name"], "meta.pdf")
        self.assertEqual(fragmento["metadata"]["doc_sha256"], "sha-meta")
        self.assertEqual(fragmento["chunk"], "Texto recuperado")

    def test_persist_consulta_saves_fragmentos_and_chunk_links(self):
        user = self.create_user()
        doc = self.create_document(nombre="rag.pdf")
        chunk = self.create_chunk(document=doc, qdrant_point_id="qid-rag")

        service.persist_consulta(
            "Pregunta",
            {
                "answer": "Respuesta",
                "retrieved": [
                    {
                        "ranking": 1,
                        "similitud": 0.91,
                        "qdrant_point_id": "qid-rag",
                        "chunk": "Fragmento",
                    }
                ],
            },
            0.5,
            user_id=user.id,
        )

        consulta = Consulta.query.one()
        self.assertEqual(consulta.user_id, user.id)
        self.assertEqual(consulta.fragmentos[0]["qdrant_point_id"], "qid-rag")
        self.assertEqual(ConsultaChunk.query.one().chunk_id, chunk.id)

    def test_rag_answer_persists_result_and_exposes_best_point_id(self):
        user = self.create_user()
        doc = self.create_document(numero_expediente="EXP-55", tipo_documento="tecnico")
        self.create_chunk(
            document=doc,
            qdrant_point_id="qid-best",
            numero_expediente="EXP-55",
            tipo_documento="tecnico",
        )
        mock_obtener = AsyncMock(
            return_value={
                "answer": "Respuesta final",
                "retrieved": [
                    {
                        "ranking": 1,
                        "similitud": 0.88,
                        "qdrant_point_id": "qid-best",
                        "chunk": "Fragmento final",
                    }
                ],
            }
        )

        with patch("app.rag.service.obtener_mejor_chunk", mock_obtener):
            result = asyncio.run(
                service.rag_answer(
                    "Consulta el expediente EXP-55 del pliego tecnico",
                    user_id=user.id,
                )
            )

        self.assertEqual(result["answer"], "Respuesta final")
        self.assertEqual(result["qdrant_point_id"], "qid-best")
        self.assertEqual(Consulta.query.count(), 1)
        _, kwargs = mock_obtener.call_args
        self.assertEqual(kwargs["numero_expediente"], "EXP-55")
        self.assertEqual(kwargs["tipo_documento"], "tecnico")

    def test_try_persist_rolls_back_when_persist_fails(self):
        with patch("app.rag.service.persist_consulta", side_effect=RuntimeError("boom")), patch(
            "app.rag.service.logger.exception"
        ):
            service.try_persist("Pregunta", {"answer": "Respuesta"}, 0.1, user_id=1)

        self.assertEqual(Consulta.query.count(), 0)
