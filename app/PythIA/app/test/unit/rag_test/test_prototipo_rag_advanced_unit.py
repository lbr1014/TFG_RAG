"""
Autora: Lydia Blanco Ruiz
Script con pruebas unitarias avanzadas del módulo PrototipoRAG, orientadas a cubrir ramas de ejecución poco frecuentes relacionados con la configuración del entorno,
la recuperación de información, la interacción con Ollama, la generación de embeddings y la indexación documental. Las pruebas verifican mecanismos de recuperación ante errores, 
tratamiento de respuestas anómalas, validación de filtros de búsqueda, gestión de tiempos de espera y funcionamiento de utilidades internas empleadas por el sistema RAG.
"""

import asyncio
import os
import sys
import types
import unittest
from importlib.machinery import SourceFileLoader
from importlib.util import module_from_spec, spec_from_loader
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from uuid import uuid4


def _import_real_prototipo_with_env(env: dict[str, str | None]):
    """
    Carga dinámicamente el módulo PrototipoRAG utilizando distintas configuraciones de variables de entorno para validar su comportamiento bajo diferentes escenarios de inicialización.
    """
    old_env = {k: os.environ.get(k) for k in env}
    try:
        for k, v in env.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        repo_root = Path(__file__).resolve().parents[4]
        module_path = repo_root / "app" / "main" / "code" / "services" / "rag" / "PrototipoRAG.py"
        module_name = f"PrototipoRAG_real_full_{uuid4().hex}"
        loader = SourceFileLoader(module_name, str(module_path))
        spec = spec_from_loader(loader.name, loader)
        module = module_from_spec(spec)
        sys.modules[loader.name] = module
        # Evita que `sentence_transformers` intente tocar red en import/uso indirecto.
        old_sentence = sys.modules.get("sentence_transformers")
        fake_sentence = types.ModuleType("sentence_transformers")

        class SentenceTransformer:
            """
            Implementación simulada de SentenceTransformer utilizada durante las pruebas para evitar la descarga de modelos o el acceso a recursos externos.
            """
            
            def __init__(self, *args, **kwargs):
                """ 
                Inicializa el modelo simulado con valores predefinidos para la longitud máxima de secuencia y el tokenizador.
                """
                self.max_seq_length = 512
                self.tokenizer = object()

            def eval(self):
                """
                Simula el paso del modelo a modo evaluación devolviendo la propia instancia.
                """
                return self

            def encode(self, *_a, **_k):
                """
                Devuelve un embedding fijo utilizado para las pruebas unitarias.
                """
                return [0.0, 0.0, 0.0]

            def get_sentence_embedding_dimension(self):
                """
                Devuelve la dimensión de los embeddings generados por el modelo simulado.
                """
                return 3

        fake_sentence.SentenceTransformer = SentenceTransformer
        sys.modules["sentence_transformers"] = fake_sentence
        loader.exec_module(module)
        if old_sentence is None:
            sys.modules.pop("sentence_transformers", None)
        else:
            sys.modules["sentence_transformers"] = old_sentence
        return module
    finally:
        for k, v in old_env.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v


class PrototipoRAGFullCoverageUnitTest(unittest.TestCase):
    def test_settings_branch_env_num_gpu_overrides_default(self):
        """
        Verifica que la configuración del número de GPU utilizadas por Ollama puede sobrescribirse mediante variables de entorno.
        """
        m = _import_real_prototipo_with_env({"OLLAMA_NUM_GPU": "0"})
        self.assertEqual(m.settings.OLLAMA_NUM_GPU, 0)
        self.assertEqual(m.settings.OLLAMA_NUM_GPU_SOURCE, "env")

    def test_infer_device_from_ps_payload_value_error(self):
        """
        Comprueba la detección del dispositivo de ejecución cuando Ollama devuelve valores de memoria de vídeo no válidos.
        """
        m = _import_real_prototipo_with_env({})
        payload = {"models": [{"name": "m", "size_vram": "x"}]}
        self.assertEqual(m._infer_device_from_ollama_ps_payload(payload, target_model="m"), "CPU")

    def test_infer_device_from_ps_payload_type_error_branch(self):
        """
        Verifica la gestión de tipos de datos inesperados durante la detección automática del dispositivo de ejecución.
        """
        m = _import_real_prototipo_with_env({})
        payload = {"models": [{"name": "m", "size_vram": object()}]}
        self.assertEqual(m._infer_device_from_ollama_ps_payload(payload, target_model="m"), "CPU")

    def test_embedding_call_to_list_false_hits_return_emb(self):
        """
        Comprueba la obtención directa de embeddings cuando no se solicita la conversión explícita a listas.
        """
        m = _import_real_prototipo_with_env({})

        class FakeModel:
            """
            Implementación simulada de un modelo de embeddings utilizada para comprobar el comportamiento de `EmbeddingModelSingleton` cuando la
            conversión explícita a listas no es requerida.
            """
            max_seq_length = 10
            tokenizer = object()

            def get_sentence_embedding_dimension(self):
                """
                Devuelve una dimensión fija de embedding utilizada durante la prueba.
                """
                return 3

            def encode(self, *_args, **_kwargs):
                """
                Simula la generación de embeddings devolviendo un vector fijo de prueba.
                """
                return [1.0, 2.0, 3.0]

        singleton = m.EmbeddingModelSingleton.__new__(m.EmbeddingModelSingleton)
        singleton._initialized = True
        singleton._model_id = "fake"
        singleton._device = "cpu"
        singleton._model = FakeModel()

        self.assertEqual(singleton("hola", to_list=False), [1.0, 2.0, 3.0])

    def test_qdrant_exists_by_metadata_returns_false_when_filter_none(self):
        """
        Verifica que la búsqueda por metadatos devuelve correctamente un resultado negativo cuando no es posible construir el filtro de consulta.
        """
        m = _import_real_prototipo_with_env({})
        with patch.object(m, "build_qdrant_metadata_filter", return_value=None):
            self.assertFalse(m.qdrant_exists_by_metadata(filename="a.pdf"))

    def test_normalize_tipo_documento_none_and_empty(self):
        """
        Comprueba la normalización de tipos documentales cuando se reciben valores vacíos o nulos.
        """
        m = _import_real_prototipo_with_env({})
        self.assertEqual(m._normalize_tipo_documento(None), "")
        self.assertEqual(m._normalize_tipo_documento("  "), "")

    def test_build_metadata_filter_includes_min_should_when_available(self):
        """
        Verifica la construcción de filtros de metadatos incluyendo condiciones opcionales de coincidencia cuando están soportadas por Qdrant.
        """
        m = _import_real_prototipo_with_env({})
        filt = m.build_metadata_filter(numero_expediente="EXP", tipo_documento="tecnico")
        self.assertIsNotNone(filt)
        self.assertTrue(getattr(filt, "should", None))

    def test_build_metadata_filter_tipo_without_should_returns_must_only(self):
        """
        Comprueba la generación de filtros documentales cuando no existen reglas de coincidencia opcionales asociadas al tipo documental.
        """
        m = _import_real_prototipo_with_env({})
        filt = m.build_metadata_filter(numero_expediente="EXP", tipo_documento="otro")
        self.assertIsNotNone(filt)

    def test_build_metadata_filter_includes_document_id_condition(self):
        """
        Verifica que los filtros incorporan correctamente restricciones asociadas al identificador documental.
        """
        m = _import_real_prototipo_with_env({})
        filt = m.build_metadata_filter(document_id=7)
        self.assertIsNotNone(filt)
        must = list(getattr(filt, "must", []) or [])
        # Debe existir una condición con key metadata.document_id
        self.assertTrue(any(getattr(cond, "key", None) == "metadata.document_id" for cond in must))

    def test_recuperacion_chunk_maps_from_record(self):
        """
        Comprueba la conversión de registros recuperados desde Qdrant a documentos internos del sistema.
        """
        m = _import_real_prototipo_with_env({})
        point = SimpleNamespace(id="1", score=0.5, payload={"content": "c", "metadata": {}})
        with patch.object(m, "recuperacion_chunk_con_scores", return_value=[point]), patch.object(
            m.VectorBaseDocument, "from_record", return_value="DOC"
        ):
            self.assertEqual(m.recuperacion_chunk("q"), ["DOC"])

    def test_recuperacion_chunk_con_scores_handles_recoverable_error(self):
        """
        Verifica la gestión de errores recuperables durante los procesos de búsqueda vectorial.
        """
        m = _import_real_prototipo_with_env({})
        m.QDRANT_RECOVERABLE_ERRORS = (RuntimeError,)
        with patch.object(m, "embedding_model", return_value=[0.0, 0.0, 0.0]), patch.object(
            m, "_qdrant_query_points_with_optional_tipo_fallback", side_effect=RuntimeError("down")
        ):
            self.assertEqual(m.recuperacion_chunk_con_scores("q"), [])

    def test_obtener_chunk_de_query_returns_none_when_no_docs(self):
        """
        Comprueba el comportamiento del sistema cuando una consulta no devuelve documentos relevantes.
        """
        m = _import_real_prototipo_with_env({})
        with patch.object(m, "recuperacion_chunk", return_value=[]):
            self.assertIsNone(m.obtener_chunk_de_query("pregunta"))

    def test_obtener_chunk_de_query_maps_metadata_and_content(self):
        """
        Verifica la construcción de la información devuelta al usuario a partir de los metadatos y contenido de los fragmentos recuperados.
        """
        m = _import_real_prototipo_with_env({})

        doc = SimpleNamespace(
            content="CHUNK",
            metadata={"title": "T", "filename": "f.pdf", "segment_index": 2},
        )
        with patch.object(m, "recuperacion_chunk", return_value=[doc]):
            out = m.obtener_chunk_de_query("pregunta", numero_expediente="E", tipo_documento="tecnico")
        self.assertEqual(
            out,
            {"title": "T", "filename": "f.pdf", "segment_index": 2, "chunk": "CHUNK"},
        )

    def test_ask_ollama_skips_empty_stream_lines(self):
        """
        Comprueba que las respuestas en streaming de Ollama ignoran correctamente líneas vacías durante el procesamiento.
        """
        import asyncio

        m = _import_real_prototipo_with_env({})

        class _Resp:
            """
            Simula la respuesta en streaming devuelta por Ollama. Genera una línea vacía seguida de un fragmento JSON válido para comprobar que las líneas
            sin contenido son ignoradas durante el procesamiento.
            """
            async def __aenter__(self):
                """
                Simula la entrada en un contexto asíncrono de respuestas HTTP.
                """
                return self

            async def __aexit__(self, *_a):
                """
                Simula la salida del contexto asíncrono de respuesta HTTP.
                """
                return False

            async def aiter_lines(self):
                """
                Simula la recepción de datos en streaming devolviendo primero una línea vacía y posteriormente un mensaje JSON válido generado por el modelo.
                """
                yield ""
                yield '{"message":{"content":"hola"},"done":true}'

        class _Client:
            """
            Cliente HTTP asíncrono simulado utilizado para interceptar las llamadas a Ollama durante la prueba.
            """
            async def __aenter__(self):
                """
                Simula la entrada en el contexto asíncrono del cliente HTTP.
                """
                return self

            async def __aexit__(self, *_a):
                """
                Simula la salida del contexto asíncrono del cliente HTTP.
                """
                return False

            def stream(self, *_args, **_kwargs):
                """
                Devuelve una respuesta simulada en streaming para la petición realizada.
                """
                return _Resp()

        async def _fake_ensure(*_a, **_k):
            """
            Simula la comprobación de disponibilidad del modelo Ollama sin realizar ninguna operación real sobre el servidor.
            """
            await asyncio.sleep(0.01)

        async def _fake_raise(*_a, **_k):
            """
            Simula la validación del estado de la respuesta HTTP sin generar excepciones.
            """
            await asyncio.sleep(0.01)

        with patch.object(m.httpx, "AsyncClient", return_value=_Client()), patch.object(
            m, "ensure_ollama_model_available", new=_fake_ensure
        ), patch.object(m, "_raise_for_ollama_chat_status", new=_fake_raise), patch.object(
            m, "resolve_rag_llm_model", return_value="m"
        ):
            out = asyncio.run(m.ask_ollama("p"))

        self.assertEqual(out, "hola")

    def test_to_jsonable_converts_list_items_recursively(self):
        """
        Verifica la conversión recursiva de listas a formatos serializables compatibles con JSON.
        """
        m = _import_real_prototipo_with_env({})
        self.assertEqual(m._to_jsonable([1, float("inf"), "x"]), [1, None, "x"])

    def test_build_metadata_filter_sets_min_should_when_qmodels_supports_it(self):
        """
        Comprueba la utilización de estructuras avanzadas de filtrado cuando la versión de Qdrant soporta condiciones de coincidencia mínima.
        """
        m = _import_real_prototipo_with_env({})

        class _Filter:
            """
            Implementación simulada de un filtro de Qdrant utilizada para almacenar dinámicamente los parámetros generados por la función bajo prueba.
            """
            def __init__(self, **kwargs):
                """
                Inicializa el filtro asignando dinámicamente los atributos recibidos.
                """
                for k, v in kwargs.items():
                    setattr(self, k, v)

        class _FieldCondition:
            """
            Representa una condición de filtrado asociada a un campo de metadatos.
            """
            def __init__(self, key=None, match=None):
                """
                Inicializa la condición indicando el campo a evaluar y el criterio de coincidencia asociado.
                """
                self.key = key
                self.match = match

        class _MatchValue:
            """
            Simula una condición de coincidencia exacta sobre un valor de metadato.
            """
            def __init__(self, value=None):
                """
                Inicializa el valor utilizado en la comparación.
                """
                self.value = value

        class _MinShould:
            """
            Simula la estructura de coincidencia mínima soportada por versiones recientes de Qdrant.
            """
            def __init__(self, conditions=None, min_count=None):
                """
                Inicializa el conjunto de condiciones alternativas y el número mínimo de coincidencias requeridas.
                """
                self.conditions = conditions
                self.min_count = min_count

        fake_qmodels = SimpleNamespace(
            Filter=_Filter,
            FieldCondition=_FieldCondition,
            MatchValue=_MatchValue,
            MinShould=_MinShould,
        )

        with patch.object(m, "qmodels", fake_qmodels):
            filt = m.build_metadata_filter(numero_expediente="EXP", tipo_documento="administrativo")

        self.assertIsNotNone(filt)
        self.assertIsNotNone(getattr(filt, "min_should", None))
        self.assertEqual(filt.min_should.min_count, 1)

    def test_ensure_ollama_model_available_skips_empty_pull_lines(self):
        """
        Verifica la gestión de respuestas vacías durante la descarga automática de modelos Ollama.
        """
        import asyncio

        m = _import_real_prototipo_with_env({})

        async def _fake_read(_it, _timeout, _model):
            """
            Simula la lectura de eventos de progreso durante la descarga de un modelo Ollama. La primera llamada devuelve una línea vacía y las siguientes
            indican el fin de la transmisión.
            """
            await asyncio.sleep(0.01)
            if not hasattr(_fake_read, "n"):
                _fake_read.n = 0
            _fake_read.n += 1
            return "" if _fake_read.n == 1 else None

        class _Resp:
            """
            Simula la respuesta HTTP recibida durante la descarga de un modelo desde Ollama mediante streaming.
            """
            async def __aenter__(self):
                """
                Simula la entrada en un contexto asíncrono de respuesta HTTP.
                """
                return self

            async def __aexit__(self, *_a):
                """
                Simula la salida del contexto asíncrono de respuesta HTTP.
                """
                return False

            def raise_for_status(self):
                """
                Simula una respuesta HTTP correcta sin generar excepciones.
                """

            async def aread(self):
                """
                Simula la lectura completa del cuerpo de la respuesta HTTP.
                """
                await asyncio.sleep(0.1)
                return b""

            def aiter_lines(self):
                """
                Simula un flujo continuo de líneas JSON durante el proceso de descarga.
                """
                async def _it():
                    while True:
                        yield "{}"

                return _it()

        class _Client:
            """
            Cliente HTTP simulado utilizado para interceptar las peticiones a Ollama durante la comprobación y descarga automática de modelos.
            """
            async def post(self, *_a, **_k):
                """
                Simula una consulta al servidor Ollama indicando que el modelo solicitado no está disponible localmente.
                """
                await asyncio.sleep(0.1)
                return SimpleNamespace(status_code=404)

            def stream(self, *_a, **_k):
                """
                Devuelve una respuesta simulada en streaming para el proceso de descarga.
                """
                return _Resp()

        with patch.object(m, "_read_ollama_pull_line", new=_fake_read), patch.object(
            m, "_process_ollama_pull_payload"
        ) as mock_process, patch.object(m, "_raise_for_ollama_show_status", return_value=None):
            asyncio.run(m.ensure_ollama_model_available(_Client(), "m"))

        mock_process.assert_not_called()

    def test_filter_points_by_similarity_returns_filtered_when_any_above_threshold(self):
        """
        Comprueba el filtrado de resultados recuperados utilizando umbrales mínimos de similitud.
        """
        m = _import_real_prototipo_with_env({})
        points = [SimpleNamespace(score=0.95), SimpleNamespace(score=0.1)]
        out = m._filter_points_by_similarity(points, min_similarity=0.9, k=10)
        self.assertEqual(out, [points[0]])

    def test_filter_points_by_similarity_returns_points_when_threshold_is_none(self):
        """
        Verifica que no se aplica filtrado cuando no se especifica un umbral de similitud.
        """
        m = _import_real_prototipo_with_env({})
        points = [SimpleNamespace(score=0.1)]
        self.assertIs(m._filter_points_by_similarity(points, min_similarity=None, k=1), points)

    def test_ask_rag_llm_no_timeout_path(self):
        """
        Comprueba la generación de respuestas RAG cuando no existe un límite temporal de ejecución configurado.
        """
        m = _import_real_prototipo_with_env({})
        m.settings.OLLAMA_GENERATION_TIMEOUT_SECONDS = None

        async def fake_ask(_prompt, **_kwargs):
            """
            Simula una llamada asíncrona al modelo de lenguaje devolviendo una respuesta fija tras un pequeño retardo.
            """
            await asyncio.sleep(0.1)
            return "ok"

        # Sustituye resource_priority con un contexto async vacío
        resource_priority = types.ModuleType("app.main.code.services.resource_priority")

        class _Ctx:
            """
            Contexto asíncrono simulado utilizado para reemplazar el mecanismo de gestión de prioridades de recursos durante la ejecución de consultas RAG.
            """
            async def __aenter__(self):
                """
                Simula la adquisición de recursos necesarios para la ejecución de una consulta RAG.
                """

            async def __aexit__(self, *_args):
                """
                Simula la liberación de los recursos asociados a la consulta RAG.
                """
                return False

        resource_priority.rag_priority_async = lambda *_a, **_k: _Ctx()

        with patch.dict(sys.modules, {"app.main.code.services.resource_priority": resource_priority}), patch.object(
            m, "ask_ollama", side_effect=fake_ask
        ):
            out = asyncio.run(m.ask_rag_llm("q", ["c"]))
        self.assertEqual(out, "ok")

    def test_ask_rag_llm_timeout_raises_ollama_timeout_error(self):
        """
        Verifica la generación de excepciones específicas cuando se supera el tiempo máximo permitido para la generación de respuestas.
        """
        m = _import_real_prototipo_with_env({})
        m.settings.OLLAMA_GENERATION_TIMEOUT_SECONDS = 0.01

        async def fake_ask(_prompt, **_kwargs):
            """
            Simula una generación de respuesta lenta cuya duración excede el tiempo límite configurado para la inferencia.
            """
            await asyncio.sleep(0.1)
            return "late"

        resource_priority = types.ModuleType("app.main.code.services.resource_priority")

        class _Ctx:
            """
            Contexto asíncrono simulado utilizado para reemplazar el sistema de gestión de prioridades durante la ejecución de consultas RAG.
            """
            async def __aenter__(self):
                """
                Simula la adquisición de los recursos necesarios para la ejecución de la consulta.
                """

            async def __aexit__(self, *_args):
                """
                Simula la liberación de los recursos asociados a la consulta.
                """
                return False

        resource_priority.rag_priority_async = lambda *_a, **_k: _Ctx()

        with patch.dict(sys.modules, {"app.main.code.services.resource_priority": resource_priority}), patch.object(
            m, "ask_ollama", side_effect=fake_ask
        ), self.assertRaises(m.OllamaTimeoutError):
                asyncio.run(m.ask_rag_llm("q", ["c"]))

    def test_to_jsonable_item_success_path(self):
        """
        Comprueba la conversión correcta de objetos que implementan métodos de extracción de valores simples.
        """
        m = _import_real_prototipo_with_env({})

        class WithItem:
            """
            Objeto simulado que implementa el método `item` para representar tipos de datos escalares compatibles con bibliotecas numéricas.
            """
            def item(self):
                """
                Devuelve un valor escalar utilizado para comprobar la conversión a un formato serializable.
                """
                return 3.0

        self.assertEqual(m._to_jsonable(WithItem()), 3.0)

    def test_empty_rag_result_and_build_retrieved_score_parsing(self):
        """
        Verifica la construcción de resultados vacíos y el tratamiento de puntuaciones inválidas devueltas por el sistema de recuperación.
        """
        m = _import_real_prototipo_with_env({})
        empty = m._empty_rag_result(model_name="m", query_profile="general", retrieval_k=3, min_similarity=None, numero_expediente=None, tipo_documento=None)
        self.assertEqual(empty["segment_index"], -1)

        points = [
            SimpleNamespace(
                id="1",
                score="bad",
                payload={"content": "c", "metadata": {"document_id": 1}},
            ),
            SimpleNamespace(
                id="2",
                score=float("nan"),
                payload={"content": "c2", "metadata": {}},
            ),
        ]
        retrieved, contexts = m._build_retrieved_and_context(points)
        self.assertEqual(len(retrieved), 2)
        self.assertTrue(contexts)

    def test_index_pdf_chunks_empty_branch_and_chunking_exception(self):
        """
        Comprueba la gestión de documentos PDF que no generan fragmentos válidos o producen errores durante la segmentación del contenido.
        """
        m = _import_real_prototipo_with_env({})

        class FakeReader:
            """
            Implementación simulada de un lector PDF utilizada para proporcionar contenido textual controlado durante las pruebas de indexación.
            """
            def __init__(self):
                """
                Inicializa un documento PDF simulado con metadatos vacíos y una única página que contiene texto de prueba.
                """
                self.metadata = {}
                self.pages = [SimpleNamespace(extract_text=lambda: "texto")]

        pdf = Path("fake.pdf")
        with patch.object(m, "PdfReader", return_value=FakeReader()), patch.object(m, "pdf_sha256", return_value="h"), patch.object(
            m, "chunk_text", return_value=[]
        ):
            self.assertEqual(m.index_pdf(pdf), [])

        with patch.object(m, "PdfReader", return_value=FakeReader()), patch.object(m, "pdf_sha256", return_value="h"), patch.object(
            m, "chunk_text", side_effect=RuntimeError("chunk")
        ):
            self.assertEqual(m.index_pdf(pdf), [])

    def test_index_markdown_empty_chunks_and_mismatch_vectors(self):
        """
        Verifica el comportamiento de la indexación Markdown cuando no se generan fragmentos o existe inconsistencia entre fragmentos y embeddings.
        """
        m = _import_real_prototipo_with_env({})
        with patch.object(m, "chunk_text", return_value=[]):
            self.assertEqual(m.index_markdown("texto", filename="doc.md", sha256="h", document_id=1), [])
        with patch.object(m, "chunk_text", return_value=["c1", "c2"]), patch.object(m, "embedding_model", return_value=[[0.0]]):
            self.assertEqual(m.index_markdown("texto", filename="doc.md", sha256="h", document_id=1), [])

    def test_obtener_mejor_chunk_returns_empty_when_no_points(self):
        """
        Comprueba la construcción de respuestas vacías cuando no existen fragmentos relevantes para responder una consulta.
        """
        m = _import_real_prototipo_with_env({})

        # `obtener_mejor_chunk` prepara el modelo Ollama incluso si no hay puntos (en tests se evita red).
        with patch.object(m, "recuperacion_chunk_con_scores", return_value=[]), patch.object(
            m,
            "ensure_ollama_model_ready",
            new_callable=__import__("unittest").mock.AsyncMock,
        ), patch.object(
            m,
            "ask_rag_llm",
            new_callable=__import__("unittest").mock.AsyncMock,
        ):
            res = asyncio.run(m.obtener_mejor_chunk("pregunta", query_profile="general", retrieval_k=3))
        self.assertEqual(res["segment_index"], -1)
        self.assertEqual(res["retrieved"], [])

    def test_filter_points_by_similarity_empty_points_path(self):
        """
        Verifica que el filtrado de similitud gestiona correctamente listas vacías de resultados recuperados.
        """
        m = _import_real_prototipo_with_env({})
        self.assertEqual(m._filter_points_by_similarity([], min_similarity=0.5, k=3), [])

    def test_main_guard_executes(self):
        """
        Comprueba la ejecución correcta del punto de entrada del módulo y la llamada a los procesos de indexación desde línea de comandos.
        """
        m = _import_real_prototipo_with_env({})
        with patch.object(m, "index_pliegos_dir", return_value={"ok": True}), patch.object(m.logging, "basicConfig"):
            self.assertEqual(m.cli_main(Path("missing-dir")), {"ok": True})
            self.assertEqual(m.cli_main(), {"ok": True})
