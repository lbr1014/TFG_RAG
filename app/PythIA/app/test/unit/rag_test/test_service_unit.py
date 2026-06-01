"""
Autora: Lydia Blanco Ruiz
Script con pruebas unitarias del servicio RAG y de los procesos asíncronos asociados a la ejecución de consultas. 
Su objetivo es verificar la detección automática de tipos documentales y expedientes, la validación de preguntas, 
la persistencia de consultas y fragmentos recuperados, la generación de respuestas mediante el sistema RAG y 
la gestión de errores producidos durante la interacción con Ollama. Además, incluye pruebas del procesamiento 
asíncrono de consultas, comprobando la correcta actualización de estados, cancelaciones, almacenamiento de 
resultados y tratamiento de excepciones. Estas pruebas garantizan el correcto funcionamiento del flujo completo 
de consulta, desde la recepción de la pregunta hasta el almacenamiento del resultado generado.
"""

import asyncio
from unittest.mock import AsyncMock, patch

from flask_login import login_user

from app.main.code.controllers.rag import routes as rag_routes
from app.main.code.extensions import db
from app.main.code.model.consulta import Consulta
from app.main.code.model.consulta_chunk import ConsultaChunk
from app.main.code.model.rag_query_state import RAGQueryState
from app.main.code.services.rag import service
from app.main.code.services.rag.PrototipoRAG import (
    OllamaModelNotFoundError,
    OllamaTimeoutError,
    QueryCancelledError,
)
from app.test.support import BaseAppTestCase


class RAGServiceUnitTest(BaseAppTestCase):
    def test_normalize_text_handles_none_accents_and_spaces(self):
        """
        Verifica la normalización de texto eliminando acentos, espacios redundantes y gestionando valores nulos.
        """
        self.assertEqual(service.normalize_text(None), "")
        self.assertEqual(service.normalize_text("  Técnico   Ágil\nMunicipal  "), "tecnico agil municipal")

    def test_detect_tipo_documento_distinguishes_admin_and_technical_questions(self):
        """
        Comprueba la detección automática del tipo documental asociado a una consulta distinguiendo entre pliegos 
        administrativos y técnicos.
        """
        self.assertEqual(
            service.detect_tipo_documento("Resume el pliego administrativo del contrato"),
            "administrativo",
        )
        self.assertEqual(
            service.detect_tipo_documento("Que dicen las prescripciones tecnicas?"),
            "tecnico",
        )
        self.assertIsNone(service.detect_tipo_documento("Compara el pliego administrativo y el pliego tecnico"))

    def test_guided_query_profile_retrieval_limits(self):
        """
        Verifica la identificación de perfiles de consulta guiada y la asignación de límites de recuperación
        adecuados para cada tipo de pregunta.
        """
        self.assertEqual(
            service.detect_guided_query_profile("Haz un resumen general y detallado del documento"),
            ("summary", 80),
        )
        self.assertEqual(
            service.detect_guided_query_profile("Dime los importes y presupuestos"),
            ("amounts", 18),
        )
        self.assertEqual(
            service.detect_guided_query_profile("Pregunta libre sin perfil"),
            ("general", 20),
        )
        self.assertEqual(service.normalize_guided_retrieval_k("general", 1), 5)
        self.assertEqual(service.normalize_guided_retrieval_k("criteria", 999), 20)
        self.assertEqual(service.normalize_guided_retrieval_k("summary", 80), 80)

    def test_extract_and_resolve_expediente_edge_cases(self):
        """
        Comprueba la extracción y resolución de números de expediente en situaciones límite o formatos incompletos.
        """
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
        """
        Verifica la detección y resolución correcta de expedientes presentes en preguntas formuladas por el usuario.
        """
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
        """
        Comprueba la validación de preguntas y la generación de mensajes de error localizados 
        cuando la entrada no es válida.
        """
        self.assertIn("answer", service.validate_question(""))
        self.assertIn("answer", service.validate_question("x" * 2001))
        self.assertIsNone(service.validate_question("Pregunta valida"))

    def test_message_error_uses_empty_answer_shape(self):
        """
        Verifica la construcción de respuestas de error utilizando el formato estándar esperado por la aplicación.
        """
        result = service.message_error("Error controlado")

        self.assertEqual(result["answer"], "Error controlado")
        self.assertEqual(result["segment_index"], -1)
        self.assertEqual(result["chunk"], "")

    def test_persist_consulta_saves_fragmentos_and_chunk_links(self):
        """
        Comprueba el almacenamiento de consultas, fragmentos recuperados y relaciones entre consultas y 
        chunks documentales.
        """
        user = self.create_user()
        doc = self.create_document(nombre="rag.pdf")
        chunk = self.create_chunk(document=doc, qdrant_point_id="qid-rag")

        service.persist_consulta(
            "Pregunta",
            {
                "answer": "Respuesta",
                "execution_device": "GPU",
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
        self.assertEqual(consulta.execution_device, "GPU")
        self.assertEqual(consulta.fragmentos[0]["qdrant_point_id"], "qid-rag")
        self.assertEqual(ConsultaChunk.query.one().chunk_id, chunk.id)

    def test_persist_consulta_skips_when_no_owner(self):
        """
        Verifica que no se almacenen consultas cuando no existe un usuario asociado.
        """
        service.persist_consulta("Pregunta", {"answer": "Respuesta"}, 0.5, user_id=None)

        self.assertEqual(Consulta.query.count(), 0)

    def test_persist_consulta_uses_authenticated_current_user_when_user_id_missing(self):
        """
        Comprueba que se utiliza el usuario autenticado cuando no se proporciona explícitamente un identificador de usuario.
        """
        user = self.create_user()

        with self.app.test_request_context("/rag"):
            login_user(user)
            service.persist_consulta("Pregunta", {"answer": "Respuesta", "retrieved": []}, 0.25)

        consulta = Consulta.query.one()
        self.assertEqual(consulta.user_id, user.id)

    def test_rag_answer_persists_result_and_exposes_best_point_id(self):
        """
        Verifica la generación de respuestas RAG, el almacenamiento de resultados y la exposición del identificador 
        del fragmento más relevante recuperado.
        """
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
                "execution_device": "CPU",
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
        self.assertEqual(result["execution_device"], "CPU")
        self.assertEqual(result["qdrant_point_id"], "qid-best")
        self.assertEqual(Consulta.query.count(), 1)
        _, kwargs = mock_obtener.call_args
        self.assertEqual(kwargs["numero_expediente"], "EXP-55")
        self.assertEqual(kwargs["tipo_documento"], "tecnico")

    def test_rag_answer_extracts_doc_type_override_marker(self):
        """
        Comprueba la detección de marcadores explícitos que fuerzan el tipo documental utilizado 
        durante la recuperación de contexto.
        """
        user = self.create_user()
        mock_obtener = AsyncMock(return_value={"answer": "ok", "retrieved": [], "execution_device": "CPU"})

        with patch("app.main.code.services.rag.service.obtener_mejor_chunk", mock_obtener):
            asyncio.run(
                service.rag_answer(
                    "  [doc_type=Administrativo]  Resume el documento  ",
                    user_id=user.id,
                )
            )

        _args, kwargs = mock_obtener.call_args
        self.assertEqual(kwargs["tipo_documento"], "administrativo")
        self.assertEqual(_args[0], "Resume el documento")

    def test_rag_answer_returns_validation_error_without_calling_rag(self):
        """
        Verifica que las consultas inválidas generan errores de validación sin ejecutar el proceso RAG.
        """
        mock_obtener = AsyncMock()

        with patch("app.main.code.services.rag.service.obtener_mejor_chunk", mock_obtener):
            result = asyncio.run(service.rag_answer("", user_id=1))

        self.assertIn("answer", result)
        mock_obtener.assert_not_called()

    def test_rag_answer_reports_status_and_handles_timeout_and_generic_errors(self):
        """
        Comprueba la gestión de estados de ejecución, tiempos de espera y errores inesperados durante la
        generación de respuestas.
        """
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
        """
        Verifica el tratamiento de errores producidos cuando el modelo solicitado no está disponible en Ollama.
        """
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
        """
        Comprueba la propagación correcta de cancelaciones solicitadas durante la ejecución de consultas RAG.
        """
        with patch("app.main.code.services.rag.service.obtener_mejor_chunk", AsyncMock(side_effect=QueryCancelledError("cancelado"))
        ), self.assertRaises(QueryCancelledError):
            asyncio.run(service.rag_answer("Pregunta cancelada", user_id=1))

    def test_try_persist_rolls_back_when_persist_fails(self):
        """
        Verifica que las operaciones de persistencia realizan rollback correctamente cuando se produce un 
        error durante el almacenamiento.
        """
        with patch("app.main.code.services.rag.service.persist_consulta", side_effect=RuntimeError("boom")), patch(
            "app.main.code.services.rag.service.logger.exception"
        ):
            service.try_persist("Pregunta", {"answer": "Respuesta"}, 0.1, user_id=1)

        self.assertEqual(Consulta.query.count(), 0)


class RAGRoutesWorkerUnitTest(BaseAppTestCase):
    def test_run_rag_query_async_returns_when_job_is_missing_or_not_owner(self):
        """
        Verifica que las tareas asíncronas finalizan sin modificaciones cuando el trabajo no existe o no 
        pertenece al usuario indicado.
        """
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
        """
        Comprueba que los trabajos previamente cancelados son marcados correctamente como cancelados antes 
        de iniciar el procesamiento.
        """
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
        """
        Verifica la ejecución completa de una consulta asíncrona, incluyendo actualizaciones de estado, 
        callbacks de progreso y almacenamiento del resultado final.
        """
        user = self.create_user()
        job = RAGQueryState(user_id=user.id, question="Pregunta", status="queued", message="En cola", error="old")
        db.session.add(job)
        db.session.commit()

        async def fake_rag_answer(_question, **kwargs):
            """
            Simula la función de generación de respuestas RAG para probar la ejecución completa de una 
            consulta asíncrona, verificando que se actualizan los estados correctamente, se llaman los 
            callbacks de progreso y se almacena el resultado final sin errores.
            """
            await asyncio.sleep(0)
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
        """
        Comprueba que las actualizaciones de estado son ignoradas cuando el trabajo ya ha finalizado.
        """
        user = self.create_user()
        job = RAGQueryState(user_id=user.id, question="Pregunta", status="queued", message="En cola")
        db.session.add(job)
        db.session.commit()

        async def fake_rag_answer(_question, **kwargs):
            """
            Simula la función de generación de respuestas RAG para probar que las actualizaciones de 
            estado son ignoradas cuando el trabajo ya ha finalizado,
            """
            await asyncio.sleep(0)
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
        """
        Verifica la cancelación de trabajos cuando la solicitud de cancelación se produce
        durante la generación de la respuesta.
        """
        user = self.create_user()
        job = RAGQueryState(user_id=user.id, question="Pregunta", status="queued", message="En cola")
        db.session.add(job)
        db.session.commit()

        async def fake_rag_answer(_question, **_kwargs):
            """
            Simula la función de generación de respuestas RAG para probar la cancelación de trabajos 
            cuando se solicita la cancelación durante la generación de la respuesta,
            """
            await asyncio.sleep(0)
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
        """
        Comprueba la gestión correcta de excepciones provocadas por cancelaciones explícitas de consultas.
        """
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
        """
        Verifica el tratamiento de errores inesperados durante la ejecución de consultas asíncronas y 
        la actualización del estado del trabajo a fallido.
        """
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
