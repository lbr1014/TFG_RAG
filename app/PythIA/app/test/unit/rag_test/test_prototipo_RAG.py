"""
Autora: Lydia Blanco Ruiz
Script con pruebas unitarias para el módulo PrototipoRAG.
Las pruebas verifican la configuración e inicialización de los servicios externos (Qdrant y Ollama), la indexación de documentos PDF y Markdown, 
la gestión de embeddings, la recuperación de contexto, la construcción de filtros y prompts, la administración de colecciones vectoriales, 
la detección de dispositivos de ejecución (CPU/GPU), la gestión de modelos de lenguaje y el tratamiento de errores, cancelaciones y 
tiempos de espera. Su objetivo es garantizar la robustez y el correcto funcionamiento de todos los componentes que intervienen en el 
ciclo completo de indexación, recuperación y generación de respuestas del sistema RAG.
"""

import asyncio
import hashlib
import os
import tempfile
import types
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch
from uuid import uuid4


def _import_prototipo():
    """
    Carga PrototipoRAG por ruta para evitar que los tests de integración interfieran con las pruebas unitarias de este módulo. 
    Los tests de integración instalan un stub de PrototipoRAG para probar el comportamiento del módulo, pero en este test
    se carga el stub por ruta bajo otro nombre para evitar el riesgo de colisión.
    """
    import sys
    from importlib.machinery import SourceFileLoader
    from importlib.util import module_from_spec, spec_from_loader
    from pathlib import Path

    repo_root = Path(__file__).resolve().parents[4]
    module_path = repo_root / "app" / "main" / "code" / "services" / "rag" / "PrototipoRAG.py"
    loader = SourceFileLoader("PrototipoRAG_real_for_tests", str(module_path))
    spec = spec_from_loader(loader.name, loader)
    module = module_from_spec(spec)
    sys.modules[loader.name] = module
    loader.exec_module(module)
    return module


def _import_prototipo_with_env(env: dict[str, str | None]):
    """
    Carga PrototipoRAG configurando temporalmente variables de entorno específicas para verificar distintos escenarios de inicialización.
    """
    old_env: dict[str, str | None] = {k: os.environ.get(k) for k in env}
    try:
        for key, value in env.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value

        import sys
        from importlib.machinery import SourceFileLoader
        from importlib.util import module_from_spec, spec_from_loader
        from pathlib import Path

        repo_root = Path(__file__).resolve().parents[4]
        module_path = repo_root / "app" / "main" / "code" / "services" / "rag" / "PrototipoRAG.py"
        module_name = f"PrototipoRAG_real_for_tests_{uuid4().hex}"
        loader = SourceFileLoader(module_name, str(module_path))
        spec = spec_from_loader(loader.name, loader)
        module = module_from_spec(spec)
        sys.modules[loader.name] = module
        loader.exec_module(module)
        return module
    finally:
        for key, old_value in old_env.items():
            if old_value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = old_value


def _import_prototipo_with_missing_qdrant_http_exceptions():
    """
    Carga PrototipoRAG por ruta bloqueando la importación de qdrant_client.http.exceptions para probar el comportamiento del módulo 
    cuando no están disponibles las excepciones HTTP de Qdrant.
    """
    import builtins
    import sys
    from importlib.machinery import SourceFileLoader
    from importlib.util import module_from_spec, spec_from_loader
    from unittest.mock import patch

    real_import = builtins.__import__

    def import_block_qdrant_http_exceptions(name, *args, **kwargs):
        """
        Bloquea la importación de qdrant_client.http.exceptions para simular su ausencia durante la carga del módulo.
        """
        if name == "qdrant_client.http.exceptions":
            raise ImportError("blocked for test")
        return real_import(name, *args, **kwargs)

    old_exc = sys.modules.pop("qdrant_client.http.exceptions", None)
    old_http = sys.modules.get("qdrant_client.http")
    try:
        if "qdrant_client.http" not in sys.modules:
            http_pkg = types.ModuleType("qdrant_client.http")
            http_pkg.__path__ = []
            sys.modules["qdrant_client.http"] = http_pkg

        repo_root = Path(__file__).resolve().parents[4]
        module_path = repo_root / "app" / "main" / "code" / "services" / "rag" / "PrototipoRAG.py"
        module_name = f"PrototipoRAG_real_missing_qdrant_http_{uuid4().hex}"
        loader = SourceFileLoader(module_name, str(module_path))
        spec = spec_from_loader(loader.name, loader)
        module = module_from_spec(spec)
        sys.modules[loader.name] = module
        with patch("builtins.__import__", side_effect=import_block_qdrant_http_exceptions):
            loader.exec_module(module)
        return module
    finally:
        if old_exc is not None:
            sys.modules["qdrant_client.http.exceptions"] = old_exc
        else:
            sys.modules.pop("qdrant_client.http.exceptions", None)
        if old_http is None:
            sys.modules.pop("qdrant_client.http", None)
        else:
            sys.modules["qdrant_client.http"] = old_http


class PrototipoRAGSmokeUnitTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        """
        Verifica la importación segura del módulo PrototipoRAG y la disponibilidad de sus componentes principales.
        """
        cls.m = _import_prototipo()

    def test_build_metadata_filter_tecnico_and_admin(self):
        """
        Verifica la construcción de filtros de metadatos para documentos técnicos y administrativos.
        """
        self.assertIsNone(self.m.build_metadata_filter())

        tecnico = self.m.build_metadata_filter("EXP", "tecnico")
        self.assertEqual([c.key for c in tecnico.must], ["metadata.numero_expediente"])
        self.assertTrue(tecnico.should)
        self.assertEqual(getattr(tecnico.should[0], "key", None), "metadata.tipo_documento")

        admin = self.m.build_metadata_filter("EXP", "administrativo")
        self.assertEqual([c.key for c in admin.must], ["metadata.numero_expediente"])
        self.assertTrue(admin.should)
        self.assertEqual(getattr(admin.should[0], "key", None), "metadata.tipo_documento")

    def test_service_url_from_env_builds_scheme_and_trims(self):
        """
        Comprueba la generación de URL de servicios a partir de variables de entorno y la normalización de sus formatos.
        """
        module = self.m
        with patch.dict(os.environ, {"X_URL": "host:123", "X_URL_SCHEME": "https"}):
            self.assertEqual(module._service_url_from_env("X_URL", "fallback"), "https://host:123")
        with patch.dict(os.environ, {"X_URL": "http://ready/"}):
            self.assertEqual(module._service_url_from_env("X_URL", "fallback"), "http://ready")
        with patch.dict(os.environ, {}, clear=True):
            self.assertEqual(module._service_url_from_env("X_URL", "fallback"), "http://fallback")

    def test_normalize_tipo_documento_canonicalizes(self):
        """
        Verifica la normalización de los tipos documentales a formatos canónicos internos.
        """
        module = self.m
        self.assertEqual(module._normalize_tipo_documento("TÉCNICO"), "tecnico")
        self.assertEqual(module._normalize_tipo_documento("Tecnica"), "tecnico")
        self.assertEqual(module._normalize_tipo_documento(" ADMINISTRATIVO "), "administrativo")

    def test_normalize_retrieval_k_bounds(self):
        """
        Comprueba la validación y normalización del número de fragmentos recuperados durante las búsquedas RAG.
        """
        self.assertEqual(self.m.normalize_retrieval_k(1), self.m.DEFAULT_RAG_MIN_CHUNKS)
        self.assertEqual(self.m.normalize_retrieval_k(999), 999)

    def test_llm_model_resolution_and_choices(self):
        """
        Verifica la resolución de modelos LLM por defecto y la obtención de modelos disponibles para selección.
        """
        original_default = self.m.settings.DEFAULT_RAG_LLM_MODEL
        original_models = self.m.settings.RAG_LLM_MODELS
        try:
            self.m.settings.DEFAULT_RAG_LLM_MODEL = "llama3:default"
            self.m.settings.RAG_LLM_MODELS = " gemma3:4b , llama3:default, qwen3:4b-instruct , "

            self.assertEqual(self.m.resolve_rag_llm_model(None), "llama3:default")
            self.assertEqual(self.m.resolve_rag_llm_model("   "), "llama3:default")
            self.assertEqual(self.m.resolve_rag_llm_model(" gemma3:4b "), "gemma3:4b")

            available = self.m.get_available_rag_llm_models()
            self.assertEqual(
                available,
                ["llama3:default", "gemma3:4b", "qwen3:4b-instruct"],
            )
            self.assertEqual(
                self.m.get_rag_llm_model_choices(),
                [(m, m) for m in available],
            )
        finally:
            self.m.settings.DEFAULT_RAG_LLM_MODEL = original_default
            self.m.settings.RAG_LLM_MODELS = original_models

    def test_build_rag_prompt_falls_back_to_general_profile(self):
        """
        Comprueba la generación de prompts RAG utilizando perfiles de consulta por defecto cuando no existe un perfil específico.
        """
        module = self.m
        prompt = module.build_rag_prompt("pregunta", ["ctx1", "ctx2"], query_profile="unknown-profile")
        self.assertIn("pregunta", prompt)
        self.assertIn("ctx1", prompt)

    def test_make_qdrant_client_success_none_and_raise(self):
        """
        Verifica la creación del cliente Qdrant y la gestión de errores de conexión o configuración.
        """
        module = self.m

        class _Client:
            def __init__(self):
                """
                Simula un cliente Qdrant con un método get_collections que siempre devuelve una lista vacía,
                indicando que el servicio está operativo.
                """
                self.calls = 0

            def get_collections(self):
                """
                Simula una respuesta exitosa de Qdrant indicando que el servicio está listo.
                """
                self.calls += 1
                return []

        class _ClientSlow(_Client):
            def __init__(self):
                """
                Simula un cliente Qdrant que responde pero tarda en estar listo, provocando múltiples intentos de conexión.
                """
                super().__init__()
                self.calls = 0

            def get_collections(self):
                """
                Simula un cliente Qdrant que responde pero no está listo, provocando múltiples intentos de conexión antes de fallar.
                """
                self.calls += 1
                raise module.httpx.HTTPError("not ready")

        def fake_ctor(**_kwargs):
            """
            Simula la creación exitosa de un cliente Qdrant operativo.
            """
            return _Client()

        def fake_ctor_slow(**_kwargs):
            """
            Simula la creación de un cliente Qdrant que responde pero no está listo, provocando múltiples intentos de conexión antes de fallar.
            """
            return _ClientSlow()

        with patch.object(module, "QDRANT_URL", ""), patch.object(module, "QdrantClient", side_effect=fake_ctor):
            client = module._make_qdrant_client()
        self.assertIsNotNone(client)

        with (
            patch.object(module, "QDRANT_URL", ""),
            patch.object(module, "QdrantClient", side_effect=fake_ctor_slow),
            patch.object(module.time, "sleep", return_value=None),
        ):
            client2 = module._make_qdrant_client()
        self.assertIsNone(client2)

        def fake_ctor_raise(**_kwargs):
            """
            Simula un error de configuración o conexión al intentar crear el cliente Qdrant, provocando una excepción inmediata.
            """
            raise ValueError("bad cfg")

        with (
            patch.object(module, "QDRANT_URL", ""),
            patch.object(module, "QdrantClient", side_effect=fake_ctor_raise),
            self.assertRaises(RuntimeError),
        ):
            module._make_qdrant_client()

    def test_build_qdrant_metadata_filter_and_exists(self):
        """
        Comprueba la construcción de filtros de búsqueda en Qdrant y la detección de documentos existentes mediante metadatos.
        """
        module = self.m

        self.assertIsNone(module.build_qdrant_metadata_filter())
        self.assertIsNone(module.build_qdrant_metadata_filter(filename=""))

        f = module.build_qdrant_metadata_filter(filename="a.pdf", document_id=1)
        self.assertTrue(f.must)

        module.qdrant = MagicMock()
        module.qdrant.scroll.return_value = (["x"], None)
        self.assertTrue(module.qdrant_exists_by_metadata(filename="a.pdf"))
        module.qdrant.scroll.return_value = ([], None)
        self.assertFalse(module.qdrant_exists_by_metadata(filename="a.pdf"))

    def test_close_qdrant_atexit_handler(self):
        """
        Verifica el cierre seguro del cliente Qdrant durante la finalización de la aplicación.
        """
        module = self.m
        fake_qdrant = MagicMock()
        fake_qdrant.close.side_effect = module.httpx.HTTPError("boom")
        module.qdrant = fake_qdrant
        module._close_qdrant()
        self.assertIsNone(module.qdrant)

    def test_qdrant_get_payloads_empty_and_error_paths(self):
        """
        Comprueba la recuperación de metadatos desde Qdrant y el tratamiento de errores asociados.
        """
        module = self.m
        module.qdrant = MagicMock()

        self.assertEqual(module.qdrant_get_payloads([]), {})
        self.assertEqual(module.qdrant_get_payloads(["", None]), {})

        module.qdrant.retrieve.side_effect = ValueError("missing collection")
        self.assertEqual(module.qdrant_get_payloads(["1"]), {})

        module.qdrant.retrieve.side_effect = module.httpx.HTTPError("down")
        self.assertEqual(module.qdrant_get_payloads(["1"]), {})

        module.qdrant.retrieve.side_effect = None
        module.qdrant.retrieve.return_value = [SimpleNamespace(id="1", payload={"a": 1})]
        self.assertEqual(module.qdrant_get_payloads(["1"]), {"1": {"a": 1}})

    def test_qdrant_delete_by_filename_uses_filter_selector(self):
        """
        Verifica la eliminación de documentos indexados utilizando filtros por nombre de archivo.
        """
        module = self.m
        module.qdrant = MagicMock()
        with patch.object(module.VectorBaseDocument, "_ensure_collection"):
            module.qdrant_delete_by_filename("a.pdf")
        module.qdrant.delete.assert_called_once()

    def test_vector_base_document_collection_and_mappings(self):
        """
        Comprueba la creación, almacenamiento, recuperación y búsqueda de documentos vectoriales en Qdrant.
        """
        module = self.m

        # Evita depender del singleton real
        class _Embed:
            model_id = "m"
            embedding_size = 3
            max_input_length = 8
            tokenizer = SimpleNamespace(tokenize=lambda s: s.split())

            def __call__(self, input_text, to_list=True):
                if isinstance(input_text, list):
                    return [[0.0, 0.0, 0.0] for _ in input_text]
                return [0.0, 0.0, 0.0]

        module.embedding_model = _Embed()

        module.qdrant = MagicMock()
        # Fuerza collection missing para que recree
        module.qdrant.get_collection.side_effect = RuntimeError("missing")

        # get_collection_name
        self.assertEqual(module.VectorBaseDocument.get_collection_name(), "vector_base_document")

        # _ensure_collection para crear colección
        module.VectorBaseDocument._ensure_collection()
        module.qdrant.recreate_collection.assert_called_once()

        doc_id = uuid4()
        doc = module.VectorBaseDocument(id=doc_id, content="txt", embedding=[0.1, 0.2, 0.3], metadata={"a": 1})
        point = doc.to_point()
        self.assertEqual(point.id, str(doc_id))
        self.assertEqual(point.payload["metadata"], {"a": 1})
        self.assertEqual(point.payload["model_id"], "m")

        # from_record con payload None
        record = SimpleNamespace(id=doc_id, payload=None)
        restored = module.VectorBaseDocument.from_record(record)
        self.assertEqual(restored.content, "")
        self.assertEqual(restored.metadata, {})

        # save / save_many 
        module.qdrant.upsert.reset_mock()
        with patch.object(module.VectorBaseDocument, "_ensure_collection"):
            doc.save()
            module.VectorBaseDocument.save_many([doc])
        self.assertEqual(module.qdrant.upsert.call_count, 2)

        # bulk_find 
        next_id = str(uuid4())
        module.qdrant.scroll.return_value = ([SimpleNamespace(id=doc_id, payload={"content": "x", "metadata": {}}, vector=None)], next_id)
        with patch.object(module.VectorBaseDocument, "_ensure_collection"):
            docs, off = module.VectorBaseDocument.bulk_find(limit=1, offset=doc_id)
        self.assertEqual(docs[0].content, "x")
        self.assertEqual(str(off), next_id)

        module.qdrant.query_points.return_value = SimpleNamespace(
            points=[SimpleNamespace(id=doc_id, payload={"content": "s", "metadata": {}}, vector=None)]
        )
        with patch.object(module.VectorBaseDocument, "_ensure_collection"):
            res = module.VectorBaseDocument.search([0.1, 0.2, 0.3], limit=1)
        self.assertEqual(res[0].content, "s")

        module.qdrant.query_points.return_value = [
            SimpleNamespace(id=doc_id, payload={"content": "s2", "metadata": {}}, vector=None)
        ]
        with patch.object(module.VectorBaseDocument, "_ensure_collection"):
            res2 = module.VectorBaseDocument.search([0.1, 0.2, 0.3], limit=1)
        self.assertEqual(res2[0].content, "s2")

    def test_lazy_qdrant_client_get_client_and_getattr(self):
        """
        Verifica el funcionamiento del cliente Qdrant diferido y la delegación de llamadas al cliente real.
        """
        module = self.m

        lazy = module.LazyQdrantClient()
        with (
            patch.object(module, "_make_qdrant_client", return_value=None),
            self.assertRaises(RuntimeError),
        ):
            lazy._get_client()

        client = MagicMock()
        client.ping.return_value = "pong"
        lazy._client = client
        self.assertEqual(lazy.ping(), "pong")
        client.ping.assert_called_once()

    def test_index_pdf_success_and_failures(self):
        """
        Comprueba la indexación de documentos PDF y la gestión de errores durante el proceso.
        """
        module = self.m

        class _Page:
            def __init__(self, text):
                """
                Simula una página de un PDF con un método extract_text que devuelve el texto de la página.
                """
                self._text = text

            def extract_text(self):
                """
                Simula la extracción de texto de una página PDF, devolviendo el texto predefinido para esta página.
                """
                return self._text

        class _Reader:
            def __init__(self, meta, pages):
                """
                Simula un lector de PDF con metadatos y páginas, proporcionando acceso a ambos a través de atributos.
                """
                self.metadata = meta
                self.pages = pages

        with (
            patch.object(module, "PdfReader", side_effect=RuntimeError("read")),
            patch.object(module, "timed_block"),
        ):
            self.assertEqual(module.index_pdf(Path("doc.pdf")), [])

        with (
            patch.object(module, "PdfReader", return_value=_Reader({}, [_Page("   ")])),
            patch.object(module, "timed_block"),
        ):
            self.assertEqual(module.index_pdf(Path("doc.pdf")), [])

        with (
            patch.object(module, "PdfReader", return_value=_Reader({"/Title": "T"}, [_Page("texto")])),
            patch.object(module, "timed_block"),
            patch.object(module, "chunk_text", side_effect=RuntimeError("chunk")),
        ):
            self.assertEqual(module.index_pdf(Path("doc.pdf")), [])

        with (
            patch.object(module, "PdfReader", return_value=_Reader({"/Title": "T"}, [_Page("texto")])),
            patch.object(module, "timed_block"),
            patch.object(module, "chunk_text", return_value=["a", "b"]),
            patch.object(module, "embedding_model", return_value=[[1.0]]),
        ):
            self.assertEqual(module.index_pdf(Path("doc.pdf")), [])

        with (
            patch.object(module, "PdfReader", return_value=_Reader({"/Title": "T"}, [_Page("texto")])),
            patch.object(module, "timed_block"),
            patch.object(module, "chunk_text", return_value=["a", "b"]),
            patch.object(module, "embedding_model", return_value=[[1.0], [2.0]]),
            patch.object(module, "pdf_sha256", return_value="sha"),
            patch.object(module.VectorBaseDocument, "save_many") as mock_save_many,
        ):
            docs = module.index_pdf(Path("doc.pdf"), document_id=5, numero_expediente="EXP", tipo_documento="admin")
        self.assertEqual(len(docs), 2)
        self.assertEqual(docs[0].metadata["document_id"], 5)
        self.assertEqual(docs[0].metadata["segment_index"], 0)
        mock_save_many.assert_called_once()

    def test_pdf_sha256_matches_hashlib(self):
        """
        Verifica el cálculo correcto de hashes SHA-256 para documentos PDF.
        """
        module = self.m
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "a.pdf"
            content = b"pdf-bytes"
            p.write_bytes(content)
            expected = hashlib.sha256(content).hexdigest()
            self.assertEqual(module.pdf_sha256(p), expected)

    def test_index_pliegos_dir_counts_new_modified_omitted_and_errors(self):
        """
        Comprueba la indexación masiva de directorios de pliegos y el cálculo de estadísticas de procesamiento.
        """
        module = self.m
        with self.assertRaises(SystemExit):
            module.index_pliegos_dir(Path("missing-dir"))

        with (
            patch.object(module.VectorBaseDocument, "_ensure_collection"),
            patch.object(module, "pdf_sha256", side_effect=lambda p: f"hash-{p.name}"),
            patch.object(module, "qdrant_has_same_hash", side_effect=lambda fn, h: fn == "same.pdf"),
            patch.object(module, "qdrant_has_filename", side_effect=lambda fn: fn in {"same.pdf", "mod.pdf"}),
            patch.object(module, "qdrant_delete_by_filename") as mock_delete,
        ):
            def fake_index_pdf(path, **_kwargs):
                """
                Simula la indexación de PDFs con resultados predefinidos según el nombre del archivo para probar el conteo de estadísticas 
                en la indexación masiva.
                """
                if path.name == "err.pdf":
                    return []
                return [object(), object()]

            with patch.object(module, "index_pdf", side_effect=fake_index_pdf):
                import tempfile

                with tempfile.TemporaryDirectory() as tmp:
                    d = Path(tmp)
                    for name in ("same.pdf", "mod.pdf", "new.pdf", "err.pdf"):
                        (d / name).write_bytes(b"x")
                    summary = module.index_pliegos_dir(d)

        self.assertEqual(summary["pdfs_total"], 4)
        self.assertEqual(summary["pdfs_omitidos"], 1)
        self.assertEqual(summary["pdfs_modificados"], 1)
        self.assertEqual(summary["pdfs_nuevos"], 2)
        self.assertEqual(summary["chunks_guardados"], 4)
        self.assertEqual(summary["pdfs_error_o_sin_texto"], 1)
        mock_delete.assert_called_once_with("mod.pdf")

    def test_index_markdown_empty_success_errors(self):
        """
        Verifica la indexación de contenido Markdown y el tratamiento de errores asociados.
        """
        module = self.m

        self.assertEqual(module.index_markdown("   ", filename="doc.md"), [])

        with patch.object(module, "chunk_text", side_effect=RuntimeError("chunk")):
            self.assertEqual(module.index_markdown("# Hola", filename="doc.md"), [])

        with (
            patch.object(module, "chunk_text", return_value=["a", "b"]),
            patch.object(module, "embedding_model", return_value=[[1.0]]),
        ):
            self.assertEqual(module.index_markdown("# Hola", filename="doc.md"), [])

        with (
            patch.object(module, "chunk_text", return_value=["a", "b"]),
            patch.object(module, "embedding_model", return_value=[[1.0], [2.0]]),
            patch.object(module.VectorBaseDocument, "save_many") as mock_save_many,
        ):
            docs = module.index_markdown(
                "# Hola",
                filename="doc.md",
                document_id=7,
                numero_expediente="EXP",
                tipo_documento="tecnico",
                sha256="sha",
                title="Titulo",
            )
        self.assertEqual(len(docs), 2)
        self.assertEqual(docs[0].metadata["source"], "markdown")
        self.assertEqual(docs[0].metadata["document_id"], 7)
        mock_save_many.assert_called_once()

    def test_qdrant_has_filename_and_same_hash_delegate(self):
        """
        Comprueba la detección de documentos existentes mediante nombre de archivo o hash.
        """
        module = self.m
        with patch.object(module, "qdrant_exists_by_metadata", return_value=True) as mock_exists:
            self.assertTrue(module.qdrant_has_filename("a.pdf"))
            self.assertTrue(module.qdrant_has_same_hash("a.pdf", "sha"))
        self.assertEqual(mock_exists.call_count, 2)

    def test_import_fallback_qdrant_http_exceptions_defines_classes(self):
        """
        Verifica la definición de excepciones alternativas cuando no están disponibles las proporcionadas por Qdrant.
        """
        mod = _import_prototipo_with_missing_qdrant_http_exceptions()
        self.assertTrue(issubclass(mod.ResponseHandlingException, RuntimeError))
        self.assertTrue(issubclass(mod.UnexpectedResponse, RuntimeError))

    def test_ask_ollama_happy_path_cancel_and_timeout(self):
        """
        Comprueba la generación de respuestas mediante Ollama, incluyendo cancelaciones y tiempos de espera.
        """
        module = self.m

        with self.assertRaises(module.QueryCancelledError):
            asyncio.run(module.ask_ollama("prompt", should_cancel=lambda: True))

        class _Resp:
            def __init__(self, lines):
                """
                Simula una respuesta de streaming de Ollama con líneas predefinidas para probar la generación de respuestas y 
                el manejo de cancelaciones.
                """
                self._lines = lines
                self.status_code = 200

            async def __aenter__(self):
                """
                Simula la entrada al contexto de una respuesta HTTP asincrónica, devolviendo el objeto de respuesta para su uso en el 
                bloque with.
                """
                return self

            async def __aexit__(self, *_args):
                """
                Simula la salida del contexto de una respuesta HTTP asincrónica, permitiendo la limpieza de recursos si es necesario.
                """
                return False

            async def aread(self):
                """
                Simula la lectura asincrónica de datos de una respuesta HTTP, devolviendo un bloque de bytes vacío para indicar el 
                final de la transmisión.
                """
                await asyncio.sleep(0)
                return b""

            def raise_for_status(self):
                """
                Simula la verificación del estado de una respuesta HTTP, no lanzando ninguna excepción para indicar un estado exitoso.
                """

            async def aiter_lines(self):
                """
                Simula la iteración asincrónica sobre las líneas de una respuesta HTTP, devolviendo las líneas
                predefinidas para esta respuesta.
                """
                for line in self._lines:
                    yield line

        class _Client:
            def __init__(self, **_kwargs):
                """
                Simula un cliente HTTP asincrónico para Ollama, proporcionando un método de streaming que devuelve una respuesta simulada.
                """

            async def __aenter__(self):
                """
                Simula la entrada al contexto de un cliente HTTP asincrónico, devolviendo el objeto de cliente para su uso en el bloque with.
                """
                return self

            async def __aexit__(self, *_args):
                """
                Simula la salida del contexto de un cliente HTTP asincrónico, permitiendo la limpieza de recursos si es necesario.
                """
                return False

            def stream(self, *_args, **_kwargs):
                """
                Simula el método de streaming de un cliente HTTP asincrónico, devolviendo una respuesta simulada con líneas predefinidas
                para probar la generación de respuestas y el manejo de cancelaciones.
                """
                return _Resp(
                    [
                        '{"response": "Hola ", "done": false}',
                        '{"response": "mundo", "done": true}',
                    ]
                )

        with (
            patch.object(module.httpx, "AsyncClient", _Client),
            patch.object(module, "ensure_ollama_model_available", new_callable=unittest.mock.AsyncMock),
        ):
            answer = asyncio.run(module.ask_ollama("prompt", model="m"))
        self.assertEqual(answer, "Hola mundo")

        class _TimeoutClient(_Client):
            async def __aenter__(self):
                """
                Simula la entrada al contexto de un cliente HTTP asincrónico que tarda en responder, provocando un tiempo de espera.
                """
                raise module.httpx.TimeoutException("slow")

        with (
            patch.object(module.httpx, "AsyncClient", _TimeoutClient),
            patch.object(module, "ensure_ollama_model_available", new_callable=unittest.mock.AsyncMock),
            self.assertRaises(module.OllamaTimeoutError),
        ):
            asyncio.run(module.ask_ollama("prompt", model="m"))

    def test_default_ollama_uses_gpu_auto_setting(self):
        """
        Verifica la configuración automática del uso de GPU por parte de Ollama.
        """
        m = _import_prototipo_with_env({"OLLAMA_NUM_GPU": None})
        self.assertEqual(m.settings.OLLAMA_NUM_GPU, -1)
        self.assertEqual(m.settings.OLLAMA_NUM_GPU_SOURCE, "auto-ollama")

    def test_embedding_execution_backend_cpu_and_cuda_variants(self):
        """
        Comprueba la detección y descripción del dispositivo utilizado para generar embeddings.
        """
        original_device = self.m.settings.RAG_MODEL_DEVICE
        original_torch = getattr(self.m, "torch", None)
        original_ollama_num_gpu = self.m.settings.OLLAMA_NUM_GPU
        original_ollama_num_gpu_source = self.m.settings.OLLAMA_NUM_GPU_SOURCE
        try:
            self.m.settings.RAG_MODEL_DEVICE = "cpu"
            self.assertIn("CPU", self.m._embedding_execution_backend())

            self.m.settings.RAG_MODEL_DEVICE = "cuda:0"
            self.m.torch = None
            self.assertIn("torch no disponible", self.m._embedding_execution_backend())

            class _CudaUnavailable:
                @staticmethod
                def is_available():
                    """
                    Simula un entorno donde CUDA no está disponible, devolviendo False para indicar que no se puede utilizar GPU.
                    """
                    return False

            self.m.torch = SimpleNamespace(cuda=_CudaUnavailable())
            self.assertIn("CUDA no disponible", self.m._embedding_execution_backend())

            class _CudaAvailable:
                @staticmethod
                def is_available():
                    """
                    Simula un entorno donde CUDA está disponible, devolviendo True para indicar que se puede utilizar GPU.
                    """
                    return True

                @staticmethod
                def get_device_name(_index):
                    """
                    Simula la obtención del nombre de un dispositivo CUDA, devolviendo un nombre de GPU ficticio para probar la descripción 
                    del backend de ejecución.
                    """
                    return "Fake GPU"

                @staticmethod
                def device_count():
                    """
                    Simula la obtención del número de dispositivos CUDA disponibles, devolviendo 1 para indicar que hay una GPU disponible.
                    """
                    return 1

            self.m.torch = SimpleNamespace(cuda=_CudaAvailable())
            text = self.m._embedding_execution_backend()
            self.assertIn("Fake GPU", text)

            # Comprobación de GPU con configuración de Ollama
            self.m.settings.OLLAMA_NUM_GPU = 0
            self.m.settings.OLLAMA_NUM_GPU_SOURCE = "env"
            self.assertEqual(self.m.get_ollama_execution_device(), "CPU")
            self.assertIn("CPU (num_gpu=0", self.m._ollama_execution_backend())

            self.m.settings.OLLAMA_NUM_GPU = -1
            self.m.settings.OLLAMA_NUM_GPU_SOURCE = "auto-ollama"
            self.assertEqual(self.m.get_ollama_execution_device(), "GPU_REQ")
            self.assertIn("GPU (num_gpu=-1", self.m._ollama_execution_backend())

            self.m.settings.OLLAMA_NUM_GPU = 2
            self.m.settings.OLLAMA_NUM_GPU_SOURCE = "auto-ollama"
            self.assertEqual(self.m.get_ollama_execution_device(), "GPU")
            self.assertIn("GPU (num_gpu=2", self.m._ollama_execution_backend())

            self.m.settings.OLLAMA_NUM_GPU = -1
            self.m.settings.OLLAMA_NUM_GPU_SOURCE = "env"
            self.assertEqual(self.m.get_ollama_execution_device(), "GPU")
        finally:
            self.m.settings.RAG_MODEL_DEVICE = original_device
            self.m.torch = original_torch
            self.m.settings.OLLAMA_NUM_GPU = original_ollama_num_gpu
            self.m.settings.OLLAMA_NUM_GPU_SOURCE = original_ollama_num_gpu_source

    def test_embedding_model_cuda_helpers_and_retry_to_cpu(self):
        """
        Verifica la recuperación automática ante errores de memoria GPU y el cambio de ejecución a CPU.
        """
        module = self.m
        module.EmbeddingModelSingleton._instance = None

        # _is_cuda_out_of_memory
        self.assertTrue(module.EmbeddingModelSingleton._is_cuda_out_of_memory(RuntimeError("CUDA out of memory")))
        self.assertFalse(module.EmbeddingModelSingleton._is_cuda_out_of_memory(RuntimeError("some other error")))

        original_torch = getattr(module, "torch", None)
        original_device = module.settings.RAG_MODEL_DEVICE
        try:
            class _FakeST:
                def __init__(self, *_args, **_kwargs):
                    """
                    Simula un modelo de embeddings con un tokenizer para probar la recuperación ante errores de memoria GPU y el cambio a CPU.
                    """
                    self.tokenizer = object()

                def eval(self):
                    """
                    Simula la configuración del modelo en modo de evaluación, devolviendo self para permitir el encadenamiento de llamadas.
                    """

            # _clear_cuda_cache: llama a empty_cache y maneja RuntimeError con logger.debug
            empty_cache = MagicMock(side_effect=RuntimeError("fail"))
            module.torch = SimpleNamespace(cuda=SimpleNamespace(empty_cache=empty_cache))
            with (
                patch.object(module.logger, "debug") as mock_debug,
                patch.object(module, "SentenceTransformer", _FakeST),
            ):
                model = module.EmbeddingModelSingleton(model_id="fake-model", device="cuda")
                model._model = SimpleNamespace(to=MagicMock())
                model._clear_cuda_cache()
            mock_debug.assert_called_once()

            module.settings.RAG_MODEL_DEVICE = "cuda"
            model._device = "cuda"
            with patch.object(module.logger, "warning") as mock_warn:
                model._move_to_cpu()
            model._model.to.assert_called_once_with("cpu")
            self.assertEqual(model._device, "cpu")
            self.assertEqual(module.settings.RAG_MODEL_DEVICE, "cpu")
            mock_warn.assert_called_once()

            calls = {"n": 0}

            def encode_side_effect(*_args, **_kwargs):
                """
                Simula un error de memoria GPU en la primera llamada a encode, y una respuesta exitosa en la segunda llamada para probar 
                la recuperación automática y el cambio a CPU.
                """
                calls["n"] += 1
                if calls["n"] == 1:
                    raise RuntimeError("CUDA out of memory")
                return [SimpleNamespace(tolist=lambda: [1.0, 2.0, 3.0])]

            model._device = "cuda"
            model._model = SimpleNamespace(encode=MagicMock(side_effect=encode_side_effect), to=MagicMock(), tokenizer=object())
            with (
                patch.object(model, "_clear_cuda_cache") as mock_clear,
                patch.object(model, "_move_to_cpu") as mock_move,
            ):
                out = model(["x"], to_list=True)
            self.assertEqual(out, [[1.0, 2.0, 3.0]])
            mock_clear.assert_called_once()
            mock_move.assert_called_once()
        finally:
            module.torch = original_torch
            module.settings.RAG_MODEL_DEVICE = original_device
            module.EmbeddingModelSingleton._instance = None

    def test_embedding_model_when_already_cpu(self):
        """
        Comprueba el comportamiento del modelo de embeddings cuando ya se encuentra ejecutándose en CPU.
        """
        module = self.m
        module.EmbeddingModelSingleton._instance = None

        class FakeModel:
            def to(self, _device):
                raise AssertionError("should not move when already cpu")

        model = module.EmbeddingModelSingleton.__new__(module.EmbeddingModelSingleton)
        model._initialized = True
        model._model_id = "fake-model"
        model._device = "cpu"
        model._model = FakeModel()

        model._move_to_cpu()  # debe retornar sin tocar .to()
        self.assertEqual(model.model_id, "fake-model")

    def test_embedding_model_call_raises_when_runtime_error_is_not_cuda_oom(self):
        """
        Verifica la propagación de errores de ejecución que no corresponden a falta de memoria GPU.
        """
        module = self.m
        module.EmbeddingModelSingleton._instance = None

        class FakeModel:
            def encode(self, *_args, **_kwargs):
                raise RuntimeError("boom")

        model = module.EmbeddingModelSingleton.__new__(module.EmbeddingModelSingleton)
        model._initialized = True
        model._model_id = "fake-model"
        model._device = "cuda"
        model._model = FakeModel()

        with self.assertRaises(RuntimeError):
            model("hola", to_list=False)

    def test_embedding_size_property_uses_sentence_embedding_dimension(self):
        """
        Comprueba la obtención correcta de la dimensión de los embeddings generados.
        """
        module = self.m

        class FakeModel:
            def get_sentence_embedding_dimension(self):
                return 7

        singleton = module.EmbeddingModelSingleton.__new__(module.EmbeddingModelSingleton)
        singleton._initialized = True
        singleton._model_id = "m"
        singleton._device = "cpu"
        singleton._model = FakeModel()

        self.assertEqual(singleton.embedding_size, 7)

    def test_format_bytes(self):
        """
        Verifica el formateo legible de tamaños de memoria y almacenamiento.
        """
        self.assertEqual(self.m._format_bytes(-1), "-")
        self.assertEqual(self.m._format_bytes("x"), "-")
        self.assertEqual(self.m._format_bytes(0), "0 B")
        self.assertEqual(self.m._format_bytes(1023), "1023 B")
        self.assertEqual(self.m._format_bytes(1024), "1.0 KB")
        self.assertEqual(self.m._format_bytes(1024 * 1024), "1.0 MB")

    def test_format_ollama_pull_progress(self):
        """
        Comprueba la generación de mensajes de progreso durante la descarga de modelos Ollama.
        """
        msg = self.m._format_ollama_pull_progress(
            "m",
            {"status": "pulling", "digest": "abcdef" * 10, "completed": 512, "total": 1024},
        )
        self.assertIn("m: pulling", msg)
        self.assertIn("50.0%", msg)
        self.assertIn("(512 B / 1.0 KB)", msg)
        # Truncado a 12 chars
        self.assertIn(" abcdefabcdef", msg)

        msg2 = self.m._format_ollama_pull_progress("m", {"completed": 1024})
        self.assertIn("(1.0 KB)", msg2)

        msg3 = self.m._format_ollama_pull_progress("m", {"completed": 9999, "total": 1})
        self.assertIn("100.0%", msg3)

    def test_extract_ollama_chat_piece_parses_response_and_message(self):
        """
        Verifica la extracción de fragmentos de respuesta generados por Ollama durante la conversación.
        """
        module = self.m

        piece, done = module._extract_ollama_chat_piece('{"response":"Hola ","done":false}')
        self.assertEqual(piece, "Hola ")
        self.assertFalse(done)

        piece2, done2 = module._extract_ollama_chat_piece('{"message":{"content":"mundo"},"done":true}')
        self.assertEqual(piece2, "mundo")
        self.assertTrue(done2)

    def test_timeout_to_total_seconds_uses_max_defined(self):
        """
        Comprueba la conversión de configuraciones de timeout a valores numéricos utilizables.
        """
        module = self.m

        t = module.httpx.Timeout(connect=1.0, read=2.0, write=3.0, pool=4.0)
        self.assertEqual(module._timeout_to_total_seconds(t), 4.0)

        t2 = module.httpx.Timeout(connect=None, read=5.0, write=None, pool=None)
        self.assertEqual(module._timeout_to_total_seconds(t2), 5.0)

        # Si todo es None, devuelve None
        t3 = module.httpx.Timeout(connect=None, read=None, write=None, pool=None)
        self.assertIsNone(module._timeout_to_total_seconds(t3))

    def test_normalize_ollama_model_name_strips_and_lowercases(self):
        """
        Verifica la normalización de nombres de modelos Ollama.
        """
        module = self.m
        self.assertEqual(module._normalize_ollama_model_name("  Llama3.1:8B "), "llama3.1:8b")
        self.assertEqual(module._normalize_ollama_model_name(None), "")

    def test_infer_device_from_ollama_ps_payload(self):
        """
        Comprueba la detección del dispositivo utilizado por Ollama a partir de la información de procesos activos.
        """
        module = self.m

        self.assertIsNone(module._infer_device_from_ollama_ps_payload({}, target_model="m"))
        self.assertIsNone(module._infer_device_from_ollama_ps_payload({"models": "x"}, target_model="m"))
        self.assertIsNone(module._infer_device_from_ollama_ps_payload({"models": [1, "x"]}, target_model="m"))

        payload_cpu = {"models": [{"name": "m", "size_vram": 0}]}
        self.assertEqual(module._infer_device_from_ollama_ps_payload(payload_cpu, target_model="m"), "CPU")

        payload_gpu = {"models": [{"model": "m", "size_vram": 123}]}
        self.assertEqual(module._infer_device_from_ollama_ps_payload(payload_gpu, target_model="m"), "GPU")

        payload_bad_vram = {"models": [{"name": "m", "size_vram": "nope"}]}
        self.assertEqual(module._infer_device_from_ollama_ps_payload(payload_bad_vram, target_model="m"), "CPU")

    def test_get_ollama_effective_execution_device_uses_payload_or_fallback(self):
        """
        Verifica la determinación del dispositivo efectivo utilizado por Ollama utilizando información real o mecanismos de respaldo.
        """
        module = self.m
        original_num_gpu = module.settings.OLLAMA_NUM_GPU
        original_source = module.settings.OLLAMA_NUM_GPU_SOURCE
        try:
            module.settings.OLLAMA_NUM_GPU = -1
            module.settings.OLLAMA_NUM_GPU_SOURCE = "auto-ollama"
            self.assertEqual(module.get_ollama_execution_device(), "GPU_REQ")

            with patch.object(module, "_fetch_ollama_ps_payload", side_effect=module.httpx.HTTPError("down")):
                device = asyncio.run(module.get_ollama_effective_execution_device(model_name="m"))
            self.assertEqual(device, "GPU_REQ")

            with patch.object(module, "_fetch_ollama_ps_payload", return_value={"models": [{"name": "m", "size_vram": 0}]}):
                device2 = asyncio.run(module.get_ollama_effective_execution_device(model_name="m"))
            self.assertEqual(device2, "CPU")
        finally:
            module.settings.OLLAMA_NUM_GPU = original_num_gpu
            module.settings.OLLAMA_NUM_GPU_SOURCE = original_source

    def test_fetch_ollama_ps_payload_uses_wait_for_when_timeout_defined(self):
        """
        Comprueba la recuperación de información de procesos Ollama respetando tiempos máximos de espera.
        """
        module = self.m

        class _Resp:
            def __init__(self, payload, content=b"x"):
                """ 
                Simula una respuesta HTTP asincrónica de Ollama con un payload JSON y contenido de respuesta para probar la recuperación de 
                información de procesos y el manejo de tiempos de espera. 
                """
                self._payload = payload
                self.content = content

            def raise_for_status(self):
                """
                Lanza una excepción si el estado de la respuesta indica un error, o no hace nada si el estado es exitoso.
                """

            def json(self):
                """
                Simula la conversión de la respuesta HTTP a JSON, devolviendo el payload predefinido para esta respuesta.
                """
                return self._payload

        class _Client:
            async def __aenter__(self):
                """
                Simula la entrada al contexto de un cliente HTTP asincrónico, devolviendo el objeto de cliente para su uso en el bloque with.
                """
                return self

            async def __aexit__(self, *_args):
                """
                Simula la salida del contexto de un cliente HTTP asincrónico, permitiendo la limpieza de recursos si es necesario.
                """
                return False

            async def get(self, _path):
                """
                Simula la realización de una solicitud GET asincrónica a Ollama, devolviendo una respuesta simulada con un 
                payload vacío para probar la recuperación de información de procesos y el manejo de tiempos de espera.
                """
                await asyncio.sleep(0)
                return _Resp({"models": []})

        async def fake_wait_for(coro, **_kwargs):
            """
            Simula la función asyncio.wait_for para probar la recuperación de información de procesos con tiempos de espera, verificando que se
            respeta el timeout definido y devolviendo el resultado de la corrutina proporcionada.
            """
            return await coro

        timeout = module.httpx.Timeout(connect=None, read=3.0, write=None, pool=None)
        with patch.object(module.httpx, "AsyncClient", return_value=_Client()), patch.object(
            module.asyncio, "wait_for", side_effect=fake_wait_for
        ):
            payload = asyncio.run(module._fetch_ollama_ps_payload(request_timeout=timeout))
        self.assertEqual(payload, {"models": []})

    def test_fetch_ollama_ps_payload_returns_empty_when_no_content(self):
        """
        Verifica el tratamiento de respuestas vacías obtenidas desde Ollama.
        """
        module = self.m

        class _Resp:
            content = b""

            def raise_for_status(self):
                """
                Lanza una excepción si el estado de la respuesta indica un error, o no hace nada si el estado es exitoso.
                """

            def json(self):
                """
                Simula la conversión de la respuesta HTTP a JSON, devolviendo un diccionario vacío para representar la ausencia
                de contenido útil en la respuesta.
                """
                return {"x": 1}

        class _Client:
            async def __aenter__(self):
                """
                Simula la entrada al contexto de un cliente HTTP asincrónico, devolviendo el objeto de cliente para su uso en el bloque with.
                """
                return self

            async def __aexit__(self, *_args):
                """
                Simula la salida del contexto de un cliente HTTP asincrónico, permitiendo la limpieza de recursos si es necesario.
                """
                return False

            async def get(self, _path):
                """
                Simula la realización de una solicitud GET asincrónica a Ollama, devolviendo una respuesta simulada sin contenido para probar el tratamiento de respuestas vacías.
                """
                await asyncio.sleep(0)
                return _Resp()

        timeout = module.httpx.Timeout(connect=None, read=None, write=None, pool=None)
        with patch.object(module.httpx, "AsyncClient", return_value=_Client()):
            payload = asyncio.run(module._fetch_ollama_ps_payload(request_timeout=timeout))
        self.assertEqual(payload, {})

    def test_fetch_ollama_ps_payload_no_timeout_no_wait_for(self):
        """
        Comprueba el comportamiento de recuperación de información cuando no se establecen límites temporales.
        """
        module = self.m

        class _Resp:
            content = b"x"

            def raise_for_status(self):
                """
                Lanza una excepción si el estado de la respuesta indica un error, o no hace nada si el estado es exitoso.
                """

            def json(self):
                """
                Simula la conversión de la respuesta HTTP a JSON, devolviendo un diccionario con una clave "models" vacía para representar 
                la ausencia de modelos activos en Ollama. 
                """
                return {"models": []}

        class _Client:
            async def __aenter__(self):
                """
                Simula la entrada al contexto de un cliente HTTP asincrónico, devolviendo el objeto de cliente para su uso en el bloque with.
                """
                return self

            async def __aexit__(self, *_args):
                """
                Simula la salida del contexto de un cliente HTTP asincrónico, permitiendo la limpieza de recursos si es necesario.
                """
                return False

            async def get(self, _path):
                """
                Simula la realización de una solicitud GET asincrónica a Ollama, devolviendo una respuesta simulada con un payload 
                que indica que no hay modelos activos, y sin respetar ningún tiempo de espera para probar el comportamiento cuando 
                no se establecen límites temporales.
                """
                await asyncio.sleep(0)
                return _Resp()

        timeout = module.httpx.Timeout(connect=None, read=None, write=None, pool=None)
        with (
            patch.object(module.httpx, "AsyncClient", return_value=_Client()),
            patch.object(module.asyncio, "wait_for") as mock_wait_for,
        ):
            payload = asyncio.run(module._fetch_ollama_ps_payload(request_timeout=timeout))
        self.assertEqual(payload, {"models": []})
        mock_wait_for.assert_not_called()

    def test_read_ollama_pull_line_stop_and_timeout(self):
        """
        Verifica la lectura de eventos de descarga de modelos Ollama y la gestión de tiempos de espera.
        """
        module = self.m

        class _ItStop:
            async def __anext__(self):
                """
                Simula un iterador asincrónico que se detiene inmediatamente para probar el manejo de la finalización de la
                transmisión durante la lectura de eventos de descarga de modelos Ollama.
                """
                raise StopAsyncIteration()

        self.assertIsNone(asyncio.run(module._read_ollama_pull_line(_ItStop(), 1.0, "m")))

        class _ItHang:
            async def __anext__(self):
                """
                Simula un iterador asincrónico que se cuelga durante la lectura de eventos de descarga de modelos Ollama.
                """
                await asyncio.sleep(10)
                return "x"

        async def fake_wait_for(*_args, **_kwargs):
            """
            Simula la función asyncio.wait_for para probar la gestión de tiempos de espera durante la lectura de eventos 
            de descarga de modelos Ollama, provocando un tiempo de espera al devolver una excepción de timeout.
            """
            raise asyncio.TimeoutError()

        with (
            patch.object(module.asyncio, "wait_for", side_effect=fake_wait_for),
            self.assertRaises(module.OllamaTimeoutError),
        ):
            asyncio.run(module._read_ollama_pull_line(_ItHang(), 1.5, "m"))

    def test_emit_ollama_pull_progress_logs_and_throttles(self):
        """
        Comprueba la generación controlada de mensajes de progreso evitando exceso de registros.
        """
        module = self.m
        statuses: list[str] = []

        with patch.object(module.logger, "info") as mock_info, patch.object(
            module.time, "monotonic", side_effect=[100.0, 100.5, 101.1, 101.2]
        ):
            # Sin status no cambia ni loguea
            last_progress, last_log_at = module._emit_ollama_pull_progress(
                "m", {}, last_progress="", last_log_at=0.0, log_interval=1.0, on_status=statuses.append
            )
            self.assertEqual(last_progress, "")
            self.assertEqual(last_log_at, 0.0)

            payload = {"status": "pulling", "completed": 0, "total": 100}
            last_progress, last_log_at = module._emit_ollama_pull_progress(
                "m",
                payload,
                last_progress=last_progress,
                last_log_at=last_log_at,
                log_interval=1.0,
                on_status=statuses.append,
            )
            self.assertTrue(last_progress)
            # La primera vez que se llama a `time.monotonic()` es cuando se procesa este primer payload con status.
            self.assertEqual(last_log_at, 100.0)

            # Mismo progreso y todavía dentro del intervalo (no loguea)
            module._emit_ollama_pull_progress(
                "m",
                payload,
                last_progress=last_progress,
                last_log_at=last_log_at,
                log_interval=10.0,
                on_status=statuses.append,
            )

            done_payload = {"status": "success", "done": True, "completed": 100, "total": 100}
            module._emit_ollama_pull_progress(
                "m",
                done_payload,
                last_progress=last_progress,
                last_log_at=last_log_at,
                log_interval=10.0,
                on_status=statuses.append,
            )

        # 1 log por el primer progreso y 1 por done=True
        self.assertGreaterEqual(mock_info.call_count, 2)
        self.assertGreaterEqual(len(statuses), 2)

    def test_process_ollama_pull_payload_raises_on_error_and_delegates(self):
        """
        Verifica el procesamiento de eventos de descarga y la gestión de errores recibidos desde Ollama.
        """
        module = self.m

        with self.assertRaises(module.OllamaModelNotFoundError):
            module._process_ollama_pull_payload(
                "m",
                '{"error":"model not found"}',
                last_progress="",
                last_log_at=0.0,
                log_interval=1.0,
            )

        with patch.object(module, "_emit_ollama_pull_progress", return_value=("p", 1.0)) as mock_emit:
            out = module._process_ollama_pull_payload(
                "m",
                '{"status":"pulling","completed":1,"total":10}',
                last_progress="x",
                last_log_at=0.0,
                log_interval=2.0,
                on_status=None,
            )
        self.assertEqual(out, ("p", 1.0))
        args = mock_emit.call_args.args
        self.assertEqual(args[0], "m")
        self.assertEqual(args[1]["status"], "pulling")

    def test_ensure_ollama_model_available_happy_path_and_errors(self):
        """
        Comprueba la verificación y descarga automática de modelos Ollama cuando no están disponibles localmente.
        """
        module = self.m

        class _Resp:
            def __init__(self, status_code: int, text: str = "", body: bytes = b""):
                """
                Simula una respuesta HTTP asincrónica de Ollama con un código de estado, texto y cuerpo para probar la verificación 
                y descarga automática de modelos.
                """
                self.status_code = status_code
                self.text = text
                self._body = body

            def raise_for_status(self):
                """
                Simula la verificación del estado de una respuesta HTTP asincrónica, lanzando una excepción si el código de estado 
                indica un error.
                """
                req = module.httpx.Request("POST", "http://ollama/api/show")
                resp = module.httpx.Response(self.status_code, request=req, content=self._body)
                raise module.httpx.HTTPStatusError("error", request=req, response=resp)

        class _PullOK:
            def __init__(self, lines: list[str]):
                """
                Simula una respuesta de streaming HTTP asincrónica de Ollama durante la descarga de un modelo, proporcionando líneas 
                predefinidas para probar el seguimiento del progreso y la gestión de eventos.
                """
                self._lines = lines
                self.status_code = 200

            async def __aenter__(self):
                """
                Simula la entrada al contexto de una respuesta de streaming HTTP asincrónica de Ollama, devolviendo el objeto de respuesta 
                para su uso en el bloque with.
                """
                return self

            async def __aexit__(self, *_args):
                """
                Simula la salida del contexto de una respuesta de streaming HTTP asincrónica de Ollama, permitiendo la limpieza de recursos 
                si es necesario.
                """
                return False

            def raise_for_status(self):
                """
                Simula la verificación del estado de una respuesta de streaming HTTP asincrónica de Ollama, no lanzando ninguna excepción 
                ya que el estado es exitoso.
                """

            async def aread(self):
                """
                Simula la lectura asincrónica del cuerpo de una respuesta de streaming HTTP de Ollama, devolviendo un cuerpo vacío 
                para representar la ausencia de contenido adicional en la respuesta.
                """
                await asyncio.sleep(0)
                return b""

            async def aiter_lines(self):
                """
                Simula la iteración asincrónica sobre las líneas de una respuesta de streaming HTTP de Ollama, devolviendo las líneas 
                predefinidas para probar el seguimiento del progreso y la gestión de eventos durante la descarga de un modelo.
                """
                for line in self._lines:
                    yield line

        class _PullFail(_PullOK):
            def __init__(self, body: bytes):
                """
                Simula una respuesta de streaming HTTP asincrónica de Ollama que falla durante la descarga de un modelo, proporcionando un cuerpo
                predefinido para representar el error y probar la gestión de errores durante la descarga.
                """
                super().__init__(lines=[])
                self._body = body

            def raise_for_status(self):
                """
                Simula la verificación del estado de una respuesta de streaming HTTP asincrónica de Ollama que falla, l
                anzando una excepción con el cuerpo predefinido para representar el error.
                """
                req = module.httpx.Request("POST", "http://ollama/api/pull")
                resp = module.httpx.Response(404, request=req, content=b"")
                raise module.httpx.HTTPStatusError("error", request=req, response=resp)

            async def aread(self):
                """
                Simula la lectura asincrónica del cuerpo de una respuesta de streaming HTTP de Ollama que falla, 
                devolviendo el cuerpo predefinido para representar el error.
                """
                await asyncio.sleep(0)
                return self._body

        class _Client:
            def __init__(self, show_resp, pull_resp=None):
                """
                Simula un cliente HTTP asincrónico para interactuar con Ollama, proporcionando respuestas predefinidas para las solicitudes 
                de verificación y descarga de modelos para probar la verificación y descarga automática de modelos.
                """
                self._show = show_resp
                self._pull = pull_resp

            async def post(self, *_args, **_kwargs):
                """
                Simula la realización de una solicitud POST asincrónica a Ollama, devolviendo una respuesta predefinida para la verificación 
                de la disponibilidad del modelo.
                """
                await asyncio.sleep(0)
                return self._show

            def stream(self, *_args, **_kwargs):
                """
                Simula la realización de una solicitud de streaming asincrónica a Ollama para la descarga de un modelo, devolviendo 
                una respuesta predefinida para probar el seguimiento del progreso y la gestión de eventos durante la descarga.
                """
                return self._pull

        original_total = module.settings.OLLAMA_PULL_TIMEOUT_SECONDS
        original_idle = module.settings.OLLAMA_PULL_IDLE_TIMEOUT_SECONDS
        original_interval = module.settings.OLLAMA_PULL_LOG_INTERVAL_SECONDS
        try:
            module.settings.OLLAMA_PULL_TIMEOUT_SECONDS = 0
            module.settings.OLLAMA_PULL_IDLE_TIMEOUT_SECONDS = 0
            module.settings.OLLAMA_PULL_LOG_INTERVAL_SECONDS = 0

            asyncio.run(module.ensure_ollama_model_available(_Client(_Resp(200)), "m"))

            # 500 (RuntimeError)
            with self.assertRaises(RuntimeError):
                asyncio.run(module.ensure_ollama_model_available(_Client(_Resp(500, text="boom")), "m"))

            # 404 (pull + progreso)
            statuses: list[str] = []
            lines = [
                '{"status":"pulling","completed":0,"total":100}',
                '{"status":"pulling","completed":50,"total":100}',
                '{"status":"success","completed":100,"total":100,"done":true}',
            ]
            asyncio.run(
                module.ensure_ollama_model_available(
                    _Client(_Resp(404), pull_resp=_PullOK(lines)),
                    "m",
                    on_status=statuses.append,
                )
            )
            self.assertTrue(any("Descargando modelo m" in s for s in statuses))
            self.assertTrue(any("m: pulling" in s for s in statuses))
            self.assertTrue(any("m: success" in s for s in statuses))

            # OllamaModelNotFoundError
            with self.assertRaises(module.OllamaModelNotFoundError):
                asyncio.run(
                    module.ensure_ollama_model_available(
                        _Client(_Resp(404), pull_resp=_PullFail(b'{"error":"not found"}')),
                        "missing",
                    )
                )
        finally:
            module.settings.OLLAMA_PULL_TIMEOUT_SECONDS = original_total
            module.settings.OLLAMA_PULL_IDLE_TIMEOUT_SECONDS = original_idle
            module.settings.OLLAMA_PULL_LOG_INTERVAL_SECONDS = original_interval

    def test_ensure_ollama_model_available_total_timeout_expires(self):
        """
        Verifica la gestión de tiempos máximos de espera durante la descarga de modelos.
        """
        module = self.m

        class _ShowResp:
            """ 
            Simula una respuesta HTTP asincrónica de Ollama para la verificación de la disponibilidad de un modelo, devolviendo un 
            código de estado 404 para representar que el modelo no está disponible localmente. 
            """
            status_code = 404
            text = ""

        class _PullResp:
            """
            Simula una respuesta de streaming HTTP asincrónica de Ollama durante la descarga de un modelo, proporcionando líneas que 
            indican progreso pero sin completar la descarga para probar la gestión de tiempos máximos de espera.
            """
            status_code = 200

            async def __aenter__(self):
                """
                Simula la entrada al contexto de una respuesta de streaming HTTP asincrónica de Ollama, devolviendo el objeto de respuesta 
                para su uso en el bloque with.
                """
                return self

            async def __aexit__(self, *_args):
                """
                Simula la salida del contexto de una respuesta de streaming HTTP asincrónica de Ollama, permitiendo la limpieza de recursos 
                si es necesario.
                """
                return False

            def raise_for_status(self):
                """
                Simula la verificación del estado de una respuesta de streaming HTTP asincrónica de Ollama, no lanzando ninguna excepción
                """

            async def aread(self):
                """
                Simula la lectura asincrónica del cuerpo de una respuesta de streaming HTTP de Ollama, devolviendo un cuerpo vacío para 
                representar la ausencia de contenido adicional en la respuesta.
                """
                await asyncio.sleep(0)
                return b""

            async def aiter_lines(self):
                """
                Simula la iteración asincrónica sobre las líneas de una respuesta de streaming HTTP de Ollama, devolviendo líneas que indican
                progreso pero sin completar la descarga para probar la gestión de tiempos máximos de espera.
                """
                while True:
                    yield '{"status":"pulling","completed":0,"total":100}'

        class _Client:
            async def post(self, *_args, **_kwargs):
                """
                Simula la realización de una solicitud POST asincrónica a Ollama para la verificación de la disponibilidad de un modelo,
                devolviendo una respuesta con código de estado 404 para representar que el modelo no está disponible localmente.
                """
                await asyncio.sleep(0)
                return _ShowResp()

            def stream(self, *_args, **_kwargs):
                """
                Simula la realización de una solicitud de streaming asincrónica a Ollama para la descarga de un modelo, devolviendo 
                una respuesta que indica progreso pero sin completar la descarga para probar la gestión de tiempos máximos de espera.
                """
                return _PullResp()

        original_total = module.settings.OLLAMA_PULL_TIMEOUT_SECONDS
        original_idle = module.settings.OLLAMA_PULL_IDLE_TIMEOUT_SECONDS
        try:
            module.settings.OLLAMA_PULL_TIMEOUT_SECONDS = 1
            module.settings.OLLAMA_PULL_IDLE_TIMEOUT_SECONDS = 0
            mono = iter([0.0, 2.0, 2.0, 2.0])
            with patch.object(module, "time", SimpleNamespace(monotonic=lambda: next(mono))
            ), self.assertRaises(module.OllamaTimeoutError):
                asyncio.run(module.ensure_ollama_model_available(_Client(), "m"))
        finally:
            module.settings.OLLAMA_PULL_TIMEOUT_SECONDS = original_total
            module.settings.OLLAMA_PULL_IDLE_TIMEOUT_SECONDS = original_idle

    def test_ensure_ollama_model_ready_opens_client_and_delegates(self):
        """
        Comprueba la preparación previa de modelos Ollama antes de ejecutar consultas.
        """
        module = self.m

        class _Client:
            def __init__(self, **kwargs):
                """
                Simula un cliente HTTP asincrónico para interactuar con Ollama, almacenando los argumentos proporcionados para verificar 
                la apertura del cliente durante la preparación de modelos.
                """
                self.kwargs = kwargs

            async def __aenter__(self):
                """
                Simula la entrada al contexto de un cliente HTTP asincrónico, devolviendo el objeto de cliente para su uso en el bloque with.
                """
                return self

            async def __aexit__(self, *_args):
                """
                Simula la salida del contexto de un cliente HTTP asincrónico, permitiendo la limpieza de recursos si es necesario.
                """
                return False

        with (
            patch.object(module.httpx, "AsyncClient", _Client),
            patch.object(module, "ensure_ollama_model_available", new_callable=unittest.mock.AsyncMock) as mock_ensure,
        ):
            asyncio.run(module.ensure_ollama_model_ready("m"))
        mock_ensure.assert_awaited_once()

    def test_chunk_text_skips_bad_token_lines_and_overlaps(self):
        """
        Verifica la fragmentación de texto y la gestión de errores durante la tokenización.
        """
        module = self.m

        class _Tok:
            def tokenize(self, text):
                """
                Simula un tokenizador que divide el texto en tokens, pero lanza un error si encuentra una línea específica para 
                probar la gestión de errores durante la fragmentación de texto.
                """
                if text == "BAD":
                    raise RuntimeError("token error")
                return text.split()

        module.embedding_model = SimpleNamespace(tokenizer=_Tok(), max_input_length=5)
        text = "uno dos\nBAD\ntres cuatro\ncinco seis\nsiete"
        chunks = module.chunk_text(text, overlap_ratio=0.5)
        # No debe fallar y debe ignorar BAD
        self.assertTrue(chunks)
        self.assertTrue(all("BAD" not in c for c in chunks))

    def test_recuperacion_chunk_con_scores_filters_by_similarity(self):
        """
        Comprueba la recuperación de fragmentos relevantes aplicando filtros de similitud.
        """
        qdrant = MagicMock()
        module = self.m
        module.qdrant = qdrant

        good = SimpleNamespace(id=uuid4(), payload={"content": "ok"}, score=0.51)
        bad = SimpleNamespace(id=uuid4(), payload={"content": "low"}, score=0.5)
        qdrant.query_points.return_value = SimpleNamespace(points=[good, bad])

        class _Embed:
            """
            Simula un modelo de embedding que devuelve vectores de tamaño fijo para probar la recuperación de fragmentos relevantes 
            aplicando filtros de similitud.
            """
            embedding_size = 3
            model_id = "m"
            max_input_length = 8
            tokenizer = SimpleNamespace(tokenize=lambda s: s.split())

            def __call__(self, _text, to_list=True):
                """
                Simula la generación de embeddings para un texto dado, devolviendo un vector de tamaño fijo para probar la 
                recuperación de fragmentos relevantes aplicando filtros de similitud.
                """
                return [0.0, 0.0, 0.0]

        module.embedding_model = _Embed()

        with patch.object(module.VectorBaseDocument, "_ensure_collection"):
            out = module.recuperacion_chunk_con_scores("pregunta")
        self.assertEqual(out, [good])

    def test_obtener_mejor_chunk_does_not_import_flask_package_for_resource_priority(self):
        """
        Verifica la obtención de respuestas RAG utilizando fragmentos recuperados y mecanismos de prioridad de recursos.
        """
        qpoint = SimpleNamespace(id=uuid4(), score=0.75, payload={"content": "ctx", "metadata": {}})

        async def fake_ask(_prompt, **_kwargs):
            """
            Simula la función de consulta a Ollama para probar la obtención de respuestas RAG utilizando fragmentos recuperados y
            mecanismos de prioridad de recursos, devolviendo una respuesta predefinida después de una breve espera para representar 
            el procesamiento de la consulta.
            """
            await asyncio.sleep(0)
            return "respuesta"

        resource_priority = types.ModuleType("app.main.code.services.resource_priority")

        class _AsyncNullContext:
            async def __aenter__(self):
                """
                Simula un contexto asincrónico nulo para probar la obtención de respuestas RAG utilizando fragmentos recuperados y 
                mecanismos de prioridad de recursos, devolviendo None para representar la ausencia de acciones específicas durante el contexto.
                """

            async def __aexit__(self, *_args):
                """
                Simula la salida de un contexto asincrónico nulo para probar la obtención de respuestas RAG utilizando fragmentos recuperados 
                y mecanismos de prioridad de recursos, devolviendo False para indicar que no se ha manejado ninguna excepción durante la salida 
                del contexto.
                """
                return False

        resource_priority.rag_priority_async = lambda *_args, **_kwargs: _AsyncNullContext()

        statuses = []
        with patch.object(self.m, "recuperacion_chunk_con_scores", return_value=[qpoint]), patch.object(
            self.m,
            "ensure_ollama_model_ready",
            new_callable=unittest.mock.AsyncMock,
        ), patch.object(self.m, "ask_ollama", side_effect=fake_ask), patch.dict(
            "sys.modules",
            {"app.main.code.services.resource_priority": resource_priority},
        ):
            res = asyncio.run(self.m.obtener_mejor_chunk(" pregunta ", on_status=statuses.append, tipo_documento="tecnico"))

        self.assertEqual(res["answer"], "respuesta")
        self.assertTrue(statuses)

    def test_raise_helpers_cover_all_raise_paths(self):
        """
        Comprueba los distintos mecanismos auxiliares de generación de excepciones del sistema.
        """
        module = self.m

        with self.assertRaises(module.QueryCancelledError):
            module._raise_if_query_cancelled(lambda: True)

        module._raise_if_query_cancelled(lambda: False)
        module._raise_if_query_cancelled(None)

        req = module.httpx.Request("POST", "http://ollama/api/show")

        # _raise_for_ollama_show_status
        module._raise_for_ollama_show_status(module.httpx.Response(200, request=req), "m")
        module._raise_for_ollama_show_status(module.httpx.Response(404, request=req), "m")

        # _raise_for_ollama_show_status
        with self.assertRaises(RuntimeError) as ctx:
            module._raise_for_ollama_show_status(
                module.httpx.Response(500, request=req, content=b"boom"),
                "m",
            )
        self.assertIn("HTTP 500", str(ctx.exception))

        async def run_chat_status(resp):
            """ 
            Simula la ejecución de la función de verificación de estado de chat de Ollama para probar los distintos caminos de generación 
            de excepciones, devolviendo el resultado de la función para una respuesta dada. 
            """
            return await module._raise_for_ollama_chat_status(resp, "m")

        # _raise_for_ollama_chat_status
        with self.assertRaises(module.OllamaModelNotFoundError):
            asyncio.run(
                run_chat_status(module.httpx.Response(404, request=req, content=b"model not found"))
            )

        # _raise_for_ollama_chat_status
        with self.assertRaises(RuntimeError) as ctx:
            asyncio.run(
                run_chat_status(module.httpx.Response(500, request=req, content=b"ollama down"))
            )
        self.assertIn("HTTP 500", str(ctx.exception))

        # _raise_for_ollama_chat_status
        with self.assertRaises(module.httpx.HTTPStatusError):
            asyncio.run(run_chat_status(module.httpx.Response(500, request=req, content=b"")))

    def test_exceptions_query_cancel_timeout_and_model_not_found(self):
        """
        Verifica la gestión de cancelaciones, tiempos de espera y modelos inexistentes.
        """
        module = self.m

        # _ollama_pull_read_timeout(total_timeout, idle_timeout, elapsed)
        self.assertIsNone(module._ollama_pull_read_timeout(total_timeout=0, idle_timeout=0, elapsed=0))
        self.assertEqual(module._ollama_pull_read_timeout(total_timeout=0, idle_timeout=5, elapsed=999), 5)

        self.assertEqual(module._ollama_pull_read_timeout(total_timeout=10, idle_timeout=0, elapsed=3), 7)
        self.assertEqual(module._ollama_pull_read_timeout(total_timeout=10, idle_timeout=-1, elapsed=1000), 0.1)

        self.assertEqual(module._ollama_pull_read_timeout(total_timeout=10, idle_timeout=2, elapsed=3), 2)
        self.assertEqual(module._ollama_pull_read_timeout(total_timeout=10, idle_timeout=20, elapsed=3), 7)

    def test_timed_block_logs_elapsed_seconds(self):
        """
        Comprueba el registro de tiempos de ejecución mediante bloques temporizados.
        """
        values = iter([10.0, 10.125])

        def fake_perf_counter():
            """
            Simula la función time.perf_counter para probar el registro de tiempos de ejecución mediante bloques temporizados, 
            devolviendo valores predefinidos para representar el tiempo transcurrido durante la ejecución del bloque.
            """
            return next(values)

        with (
            patch.object(self.m.time, "perf_counter", side_effect=fake_perf_counter),
            patch.object(self.m.logger, "info") as mock_info,
            self.m.timed_block("bloque"),
        ):
            # solo se comprueba que se loguee el tiempo correcto al salir.
            pass

        mock_info.assert_called_once()
        args = mock_info.call_args.args
        self.assertEqual(args[0], "Tiempo %s: %.3f s")
        self.assertEqual(args[1], "bloque")
        self.assertAlmostEqual(args[2], 0.125, places=6)


if __name__ == "__main__":
    unittest.main()
