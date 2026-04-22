"""
Autora: Lydia Blanco Ruiz
Script con pruebas unitarias del servicio RAG.
"""

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from flask_login import login_user

from app.test.support import BaseAppTestCase

from app.main.code.model.consulta import Consulta
from app.main.code.model.consulta_chunk import ConsultaChunk
from app.main.code.model.rag_query_state import RAGQueryState
from app.main.code.extensions import db
from app.main.code.controllers.rag import routes as rag_routes
from app.main.code.services.rag import service
from app.main.code.services.rag.PrototipoRAG import OllamaModelNotFoundError, OllamaTimeoutError, QueryCancelledError


class RAGServiceUnitTest(BaseAppTestCase):
    def test_normalize_text_handles_none_accents_and_spaces(self):
        self.assertEqual(service.normalize_text(None), "")
        self.assertEqual(service.normalize_text("  Técnico   Ágil\nMunicipal  "), "tecnico agil municipal")

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

    def test_extract_and_resolve_expediente_edge_cases(self):
        self.assertIsNone(service.extract_expediente_candidate("sin mencion de expediente"))
        self.assertIsNone(service.resolve_numero_expediente("pregunta sin expediente"))
        self.assertEqual(
            service.extract_expediente_candidate("expediente EXP-1 sobre pliegos"),
            "EXP-1",
        )
        self.assertEqual(
            service.resolve_numero_expediente("expediente ABC-2026"),
            "ABC-2026",
        )

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

    def test_message_error_uses_empty_answer_shape(self):
        result = service.message_error("Error controlado")

        self.assertEqual(result["answer"], "Error controlado")
        self.assertEqual(result["segment_index"], -1)
        self.assertEqual(result["chunk"], "")

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

    def test_build_fragmento_without_chunk_uses_item_defaults_and_metadata(self):
        fragmento = service.build_fragmento(
            {
                "ranking": "2",
                "similitud": "0.5",
                "qdrant_point_id": "qid-item",
                "chunk": None,
                "metadata": {"title": "Titulo"},
                "document_id": 7,
                "doc_sha256": "sha-item",
                "segment_index": 3,
                "filename": "doc.pdf",
            },
            None,
        )

        self.assertEqual(fragmento["ranking"], 2)
        self.assertEqual(fragmento["similitud"], 0.5)
        self.assertEqual(fragmento["chunk"], "")
        self.assertEqual(fragmento["metadata"]["document_id"], 7)
        self.assertEqual(fragmento["metadata"]["filename"], "doc.pdf")

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

    def test_persist_consulta_skips_when_no_owner(self):
        service.persist_consulta("Pregunta", {"answer": "Respuesta"}, 0.5, user_id=None)

        self.assertEqual(Consulta.query.count(), 0)

    def test_persist_consulta_uses_authenticated_current_user_when_user_id_missing(self):
        user = self.create_user()

        with self.app.test_request_context("/rag"):
            login_user(user)
            service.persist_consulta("Pregunta", {"answer": "Respuesta", "retrieved": []}, 0.25)

        consulta = Consulta.query.one()
        self.assertEqual(consulta.user_id, user.id)

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

        with patch("app.main.code.services.rag.service.obtener_mejor_chunk", mock_obtener):
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

    def test_rag_answer_returns_validation_error_without_calling_rag(self):
        mock_obtener = AsyncMock()

        with patch("app.main.code.services.rag.service.obtener_mejor_chunk", mock_obtener):
            result = asyncio.run(service.rag_answer("", user_id=1))

        self.assertIn("answer", result)
        mock_obtener.assert_not_called()

    def test_rag_answer_reports_status_and_handles_timeout_and_generic_errors(self):
        user = self.create_user()
        status_calls = []

        with patch("app.main.code.services.rag.service.obtener_mejor_chunk", AsyncMock(side_effect=OllamaTimeoutError("timeout"))), patch(
            "app.main.code.services.rag.service.translate_for", side_effect=lambda lang, key, **kwargs: key
        ), patch("app.main.code.services.rag.service.logger.warning") as mock_warning:
            timeout_result = asyncio.run(
                service.rag_answer("Pregunta timeout", on_status=status_calls.append, user_id=user.id)
            )

        self.assertEqual(status_calls, ["rag.preparing"])
        self.assertEqual(timeout_result["answer"], "rag.timeout_error")
        mock_warning.assert_called_once()

        with patch("app.main.code.services.rag.service.obtener_mejor_chunk", AsyncMock(side_effect=RuntimeError("boom"))), patch(
            "app.main.code.services.rag.service.translate_for", side_effect=lambda lang, key, **kwargs: key
        ), patch("app.main.code.services.rag.service.logger.exception") as mock_exception:
            error_result = asyncio.run(service.rag_answer("Pregunta error", user_id=user.id))

        self.assertEqual(error_result["answer"], "rag.system_error")
        mock_exception.assert_called_once()

    def test_rag_answer_handles_ollama_model_not_found_error(self):
        user = self.create_user()

        with patch(
            "app.main.code.services.rag.service.obtener_mejor_chunk",
            AsyncMock(side_effect=OllamaModelNotFoundError("missing")),
        ), patch(
            "app.main.code.services.rag.service.translate_for",
            side_effect=lambda lang, key, **kwargs: key,
        ), patch("app.main.code.services.rag.service.logger.warning") as mock_warning:
            result = asyncio.run(service.rag_answer("Pregunta modelo", user_id=user.id))

        self.assertEqual(result["answer"], "rag.model_not_found_error")
        mock_warning.assert_called_once()

    def test_rag_answer_propagates_query_cancelled_error(self):
        with patch("app.main.code.services.rag.service.obtener_mejor_chunk", AsyncMock(side_effect=QueryCancelledError("cancelado"))):
            with self.assertRaises(QueryCancelledError):
                asyncio.run(service.rag_answer("Pregunta cancelada", user_id=1))

    def test_try_persist_rolls_back_when_persist_fails(self):
        with patch("app.main.code.services.rag.service.persist_consulta", side_effect=RuntimeError("boom")), patch(
            "app.main.code.services.rag.service.logger.exception"
        ):
            service.try_persist("Pregunta", {"answer": "Respuesta"}, 0.1, user_id=1)

        self.assertEqual(Consulta.query.count(), 0)

    def test_qdrant_search_with_scores_returns_points_or_raw_response(self):
        qdrant = MagicMock()
        qdrant.query_points.return_value = SimpleNamespace(points=["p1", "p2"])

        self.assertEqual(service.qdrant_search_with_scores(qdrant, "collection", [0.1], limit=3), ["p1", "p2"])
        qdrant.query_points.assert_called_once_with(
            collection_name="collection",
            query=[0.1],
            limit=3,
            with_payload=True,
            with_vectors=False,
        )

        raw_response = ["raw"]
        qdrant.query_points.return_value = raw_response
        self.assertIs(service.qdrant_search_with_scores(qdrant, "collection", [0.2]), raw_response)


class RAGRoutesWorkerUnitTest(BaseAppTestCase):
    def test_run_rag_query_async_returns_when_job_is_missing_or_not_owner(self):
        user = self.create_user()
        job = RAGQueryState(user_id=user.id, question="Pregunta", status="queued", message="En cola")
        db.session.add(job)
        db.session.commit()

        rag_routes.run_rag_query_async(self.app, job.id + 100, user.id)
        rag_routes.run_rag_query_async(self.app, job.id, user.id + 1)

        db.session.expire_all()
        stored_job = db.session.get(RAGQueryState, job.id)
        self.assertEqual(stored_job.status, "queued")
        self.assertEqual(stored_job.message, "En cola")

    def test_run_rag_query_async_marks_pre_cancelled_job(self):
        user = self.create_user()
        job = RAGQueryState(
            user_id=user.id,
            question="Pregunta",
            status="queued",
            message="En cola",
            cancel_requested=True,
        )
        db.session.add(job)
        db.session.commit()

        rag_routes.run_rag_query_async(self.app, job.id, user.id)

        db.session.expire_all()
        stored_job = db.session.get(RAGQueryState, job.id)
        self.assertEqual(stored_job.status, "cancelled")
        self.assertIsNotNone(stored_job.finished_at)

    def test_run_rag_query_async_uses_callbacks_and_marks_done(self):
        user = self.create_user()
        job = RAGQueryState(user_id=user.id, question="Pregunta", status="queued", message="En cola", error="old")
        db.session.add(job)
        db.session.commit()

        async def fake_rag_answer(_question, **kwargs):
            self.assertFalse(kwargs["should_cancel"]())
            kwargs["on_status"]("Procesando")
            return {"answer": "Respuesta"}

        with patch("app.main.code.controllers.rag.routes.rag_answer", AsyncMock(side_effect=fake_rag_answer)) as mock_rag_answer:
            rag_routes.run_rag_query_async(self.app, job.id, user.id, lang="es")

        db.session.expire_all()
        stored_job = db.session.get(RAGQueryState, job.id)
        self.assertEqual(stored_job.status, "done")
        self.assertEqual(stored_job.result_payload, {"answer": "Respuesta"})
        self.assertIsNone(stored_job.error)
        self.assertIsNotNone(stored_job.started_at)
        self.assertIsNotNone(stored_job.finished_at)
        mock_rag_answer.assert_awaited_once()

    def test_run_rag_query_async_ignores_status_callback_for_finished_job(self):
        user = self.create_user()
        job = RAGQueryState(user_id=user.id, question="Pregunta", status="queued", message="En cola")
        db.session.add(job)
        db.session.commit()

        async def fake_rag_answer(_question, **kwargs):
            current_job = db.session.get(RAGQueryState, job.id)
            current_job.status = "done"
            current_job.message = "Ya terminado"
            db.session.commit()
            kwargs["on_status"]("No debe escribirse")
            return {"answer": "Respuesta"}

        with patch("app.main.code.controllers.rag.routes.rag_answer", AsyncMock(side_effect=fake_rag_answer)):
            rag_routes.run_rag_query_async(self.app, job.id, user.id)

        db.session.expire_all()
        stored_job = db.session.get(RAGQueryState, job.id)
        self.assertEqual(stored_job.status, "done")
        self.assertNotEqual(stored_job.message, "No debe escribirse")

    def test_run_rag_query_async_cancels_after_answer_if_requested(self):
        user = self.create_user()
        job = RAGQueryState(user_id=user.id, question="Pregunta", status="queued", message="En cola")
        db.session.add(job)
        db.session.commit()

        async def fake_rag_answer(_question, **_kwargs):
            current_job = db.session.get(RAGQueryState, job.id)
            current_job.cancel_requested = True
            db.session.commit()
            return {"answer": "Respuesta"}

        with patch("app.main.code.controllers.rag.routes.rag_answer", AsyncMock(side_effect=fake_rag_answer)):
            rag_routes.run_rag_query_async(self.app, job.id, user.id)

        db.session.expire_all()
        stored_job = db.session.get(RAGQueryState, job.id)
        self.assertEqual(stored_job.status, "cancelled")
        self.assertIsNone(stored_job.result_payload)
        self.assertIsNotNone(stored_job.finished_at)

    def test_run_rag_query_async_handles_query_cancelled_error(self):
        user = self.create_user()
        job = RAGQueryState(user_id=user.id, question="Pregunta", status="queued", message="En cola")
        db.session.add(job)
        db.session.commit()

        with patch("app.main.code.controllers.rag.routes.rag_answer", AsyncMock(side_effect=QueryCancelledError("cancelado"))):
            rag_routes.run_rag_query_async(self.app, job.id, user.id)

        db.session.expire_all()
        stored_job = db.session.get(RAGQueryState, job.id)
        self.assertEqual(stored_job.status, "cancelled")
        self.assertIsNotNone(stored_job.finished_at)

    def test_run_rag_query_async_handles_unexpected_error(self):
        user = self.create_user()
        job = RAGQueryState(user_id=user.id, question="Pregunta", status="queued", message="En cola")
        db.session.add(job)
        db.session.commit()

        with patch("app.main.code.controllers.rag.routes.rag_answer", AsyncMock(side_effect=RuntimeError("boom"))), patch.object(
            self.app.logger,
            "exception",
        ) as mock_exception:
            rag_routes.run_rag_query_async(self.app, job.id, user.id)

        db.session.expire_all()
        stored_job = db.session.get(RAGQueryState, job.id)
        self.assertEqual(stored_job.status, "failed")
        self.assertEqual(stored_job.error, "boom")
        self.assertIsNotNone(stored_job.finished_at)
        mock_exception.assert_called_once_with("Error en run_rag_query_async")
