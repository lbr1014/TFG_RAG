"""
Autora: Lydia Blanco Ruiz
Script con pruebas unitarias para generar_preguntas_ARES, encargado de generar automáticamente preguntas, respuestas y evidencias a partir de los documentos indexados en el 
sistema RAG para construir conjuntos de evaluación destinados a ARES. Las pruebas verifican la limpieza y filtrado de fragmentos documentales, la generación de preguntas mediante LLM, 
la validación de calidad de las preguntas generadas, la eliminación de duplicados, la gestión de la paginación de documentos y la creación del fichero final de preguntas.
"""

import asyncio
import importlib
import json
import sys
import types
from types import SimpleNamespace
from unittest.mock import patch

from app.test.support import BaseAppTestCase


def _install_fake_prototipo_rag(*, chunks=None, ollama_payload=None):
    """
    Crea una versión simulada del módulo PrototipoRAG para controlar la recuperación de documentos y la generación de preguntas durante las pruebas.
    """
    module = types.ModuleType("app.main.code.services.rag.PrototipoRAG")

    class VectorBaseDocument:
        """
        Implementación simulada del repositorio documental utilizada para proporcionar conjuntos controlados de fragmentos durante las pruebas.
        """
        @staticmethod
        def bulk_find(limit=100, offset=None):
            """
            Simula la recuperación paginada de fragmentos documentales almacenados en la base vectorial.
            """
            items = chunks or []
            start = int(offset or 0)
            batch = items[start : start + limit]
            next_offset = None if start + limit >= len(items) else start + limit
            return batch, next_offset

    async def ask_ollama(_prompt, model=None):
        """
        Simula una llamada al modelo de lenguaje devolviendo una respuesta predefinida en formato texto o JSON según la configuración de la prueba.
        """
        await asyncio.sleep(0)
        if isinstance(ollama_payload, str):
            return ollama_payload
        return json.dumps(ollama_payload or [], ensure_ascii=False)

    module.VectorBaseDocument = VectorBaseDocument
    module.ask_ollama = ask_ollama
    return module


class GenerarPreguntasARESUnitTest(BaseAppTestCase):
    def _module(self, *, chunks=None, ollama_payload=None):
        """
        Importa dinámicamente el módulo de generación de preguntas utilizando implementaciones simuladas del sistema RAG para ejecutar las pruebas de forma aislada.
        """
        fake = _install_fake_prototipo_rag(chunks=chunks, ollama_payload=ollama_payload)
        with patch.dict(sys.modules, {"app.main.code.services.rag.PrototipoRAG": fake}):
            sys.modules.pop("app.main.code.services.evaluation.generar_preguntas_ARES", None)
            return importlib.import_module("app.main.code.services.evaluation.generar_preguntas_ARES")

    def test_clean_chunk_and_good_chunk_thresholds(self):
        """
        Verifica la limpieza de fragmentos documentales y la validación de longitud y calidad mínima exigida para que puedan utilizarse como fuente de generación de preguntas.
        """
        m = self._module()
        self.assertEqual(m.clean_chunk("  hola \n mundo\t"), "hola mundo")
        self.assertFalse(m.good_chunk(""))
        self.assertFalse(m.good_chunk("x" * 499))
        self.assertFalse(m.good_chunk("x" * 4001))
        self.assertFalse(m.good_chunk(("a " * 600) + ("Pagina " * 6)))
        self.assertTrue(m.good_chunk("a" * 600))

    def test_iter_chunks_paginates_until_offset_none(self):
        """
        Comprueba la recuperación paginada de fragmentos documentales hasta procesar la totalidad de los registros disponibles.
        """
        docs = [SimpleNamespace(content=f"c{i}") for i in range(5)]
        m = self._module(chunks=docs)
        out = m.iter_chunks(limit_total=10, batch=2)
        self.assertEqual([d.content for d in out], [f"c{i}" for i in range(5)])

    def test_iter_chunks_stops_when_empty_batch(self):
        """
        Verifica que el proceso de recuperación finaliza correctamente cuando no existen más fragmentos disponibles.
        """
        m = self._module(chunks=[])
        out = m.iter_chunks(limit_total=10, batch=2)
        self.assertEqual(out, [])

    def test_generate_qas_for_chunk_parses_json_list_of_dicts(self):
        """
        Comprueba la generación de preguntas, respuestas y evidencias a partir de un fragmento documental, validando además el tratamiento de respuestas JSON inválidas o mal formadas.
        """
        m = self._module(ollama_payload=[{"question": "q", "answer": "a", "evidence": "e"}, "bad", 1])
        out = m.generate_qas_for_chunk("chunk" * 200, n=2, model="fake")
        self.assertEqual(out, [{"question": "q", "answer": "a", "evidence": "e"}])

        m = self._module(ollama_payload="not-json")
        self.assertEqual(m.generate_qas_for_chunk("chunk" * 200), [])

        m = self._module(ollama_payload={"not": "a list"})
        self.assertEqual(m.generate_qas_for_chunk("chunk" * 200), [])

    def test_pass_quality_requires_min_words_and_evidence_in_chunk(self):
        """
        Verifica que las preguntas generadas cumplen los criterios mínimos de calidad, incluyendo longitud suficiente y presencia de la evidencia dentro del fragmento original.
        """
        m = self._module()
        chunk = "Este es el texto base con evidencia literal."
        self.assertFalse(m.pass_quality("", "a", "e", chunk))
        self.assertFalse(m.pass_quality("una dos tres cuatro cinco", "a", "e", chunk))
        self.assertFalse(m.pass_quality("una dos tres cuatro cinco seis", "a", "NO", chunk))
        self.assertTrue(m.pass_quality("una dos tres cuatro cinco seis", "a", "evidencia literal", chunk))

    def test_accumulate_questions_dedup_and_stops_at_target(self):
        """
        Comprueba la acumulación progresiva de preguntas evitando duplicados y deteniendo el proceso cuando se alcanza el número objetivo configurado.
        """
        chunk = ("texto " * 200) + "evidencia A"
        m = self._module(
            ollama_payload=[
                {"question": "una dos tres cuatro cinco seis", "answer": "A", "evidence": "evidencia A"}
            ]
        )

        with patch.dict("os.environ", {"ARES_NUM_QUESTIONS": "1", "ARES_MAX_SOURCE_CHUNKS": "10", "ARES_QAS_PER_CHUNK": "2"}):
            out = m._accumulate_questions([chunk, chunk])

        self.assertEqual(len(out), 1)
        self.assertEqual(out[0]["question"], "una dos tres cuatro cinco seis")

    def test_try_add_question_skips_duplicates_and_low_quality(self):
        """
        Verifica que las preguntas duplicadas o de baja calidad son descartadas antes de incorporarse al conjunto de evaluación.
        """
        m = self._module()
        questions = []
        seen = set()
        chunk = "Texto con evidencia literal."
        item = {"question": "una dos tres cuatro cinco seis", "answer": "A", "evidence": "evidencia literal"}

        m._try_add_question(questions=questions, seen=seen, chunk=chunk, item=item)
        self.assertEqual(len(questions), 1)

        # duplicado -> return temprano
        m._try_add_question(questions=questions, seen=seen, chunk=chunk, item=item)
        self.assertEqual(len(questions), 1)

        # mala calidad (evidence no está en chunk) -> return temprano
        bad_item = {"question": "otra pregunta con seis palabras exactas", "answer": "A", "evidence": "NO"}
        m._try_add_question(questions=questions, seen=seen, chunk=chunk, item=bad_item)
        self.assertEqual(len(questions), 1)

    def test_accumulate_questions_prints_every_10_chunks_and_returns_when_under_target(self):
        """
        Comprueba el comportamiento del proceso de generación cuando no se alcanza el número objetivo de preguntas debido a la ausencia de resultados válidos.
        """
        chunk = ("texto " * 200) + "evidencia A"
        m = self._module(ollama_payload=[])
        chunks = [chunk for _ in range(10)]

        with patch.dict("os.environ", {"ARES_NUM_QUESTIONS": "5", "ARES_MAX_SOURCE_CHUNKS": "10", "ARES_QAS_PER_CHUNK": "1"}):
            out = m._accumulate_questions(chunks)

        self.assertEqual(out, [])

    def test_main_skips_when_questions_file_exists(self):
        """
        Verifica que la generación de preguntas no se ejecuta cuando ya existe un fichero de salida y no se ha solicitado regenerarlo.
        """
        m = self._module()
        questions_path = self._tmpdir / "questions.json"
        questions_path.write_text("[]", encoding="utf-8")

        with patch.object(m, "QUESTIONS_PATH", questions_path), patch.object(m, "FORCE_REGENERATE", False):
            m.main()

    def test_build_shuffle_rng_uses_seed_when_configured(self):
        """
        Comprueba que la aleatorización de fragmentos utiliza una semilla reproducible cuando esta se encuentra configurada.
        """
        m = self._module()
        with patch.dict("os.environ", {"ARES_SHUFFLE_SEED": "123"}):
            rng = m._build_shuffle_rng()
        self.assertEqual(rng.randint(0, 1000), m.random.Random(123).randint(0, 1000))

    def test_main_generates_questions_file(self):
        """
        Verifica la generación completa del fichero de preguntas a partir de los documentos disponibles y de las respuestas generadas por el modelo.
        """
        chunk = ("texto " * 200) + "evidencia A"
        docs = [SimpleNamespace(content=chunk)]
        m = self._module(chunks=docs, ollama_payload=[{"question": "una dos tres cuatro cinco seis", "answer": "A", "evidence": "evidencia A"}])
        out_path = self._tmpdir / "questions_out.json"

        with patch.object(m, "QUESTIONS_PATH", out_path), patch.object(m, "FORCE_REGENERATE", True), patch.dict(
            "os.environ", {"ARES_NUM_QUESTIONS": "1", "ARES_MAX_SOURCE_CHUNKS": "10", "ARES_QAS_PER_CHUNK": "1"}
        ):
            m.main()

        self.assertTrue(out_path.exists())

    def test_main_raises_system_exit_when_no_questions_generated(self):
        """
        Comprueba que el proceso finaliza con error cuando no es posible generar ninguna pregunta válida para el conjunto de evaluación.
        """
        chunk = ("texto " * 200) + "sin evidencia"
        docs = [SimpleNamespace(content=chunk)]
        m = self._module(chunks=docs, ollama_payload=[])
        out_path = self._tmpdir / "questions_empty.json"

        with patch.object(m, "QUESTIONS_PATH", out_path), patch.object(m, "FORCE_REGENERATE", True), patch.dict(
            "os.environ", {"ARES_NUM_QUESTIONS": "1", "ARES_MAX_SOURCE_CHUNKS": "1", "ARES_QAS_PER_CHUNK": "1"}
        ), self.assertRaises(SystemExit):
            m.main()
