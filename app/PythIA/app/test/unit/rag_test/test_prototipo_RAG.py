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
    # Los tests de integración instalan un stub de PrototipoRAG para probar el comportamiento del módulo, lo cargamos por ruta bajo otro nombre.
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
    Carga PrototipoRAG por ruta forzando el fallback del try/except:
    `from qdrant_client.http.exceptions import ...`.
    """
    import builtins
    import sys
    from importlib.machinery import SourceFileLoader
    from importlib.util import module_from_spec, spec_from_loader
    from unittest.mock import patch

    real_import = builtins.__import__

    def import_block_qdrant_http_exceptions(name, *args, **kwargs):
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
        cls.m = _import_prototipo()

    def test_build_metadata_filter_tecnico_and_admin_include_missing_tipo(self):
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
        module = self.m
        with patch.dict(os.environ, {"X_URL": "host:123", "X_URL_SCHEME": "https"}):
            self.assertEqual(module._service_url_from_env("X_URL", "fallback"), "https://host:123")
        with patch.dict(os.environ, {"X_URL": "http://ready/"}):
            self.assertEqual(module._service_url_from_env("X_URL", "fallback"), "http://ready")
        with patch.dict(os.environ, {}, clear=True):
            self.assertEqual(module._service_url_from_env("X_URL", "fallback"), "http://fallback")

    def test_normalize_tipo_documento_canonicalizes(self):
        module = self.m
        self.assertEqual(module._normalize_tipo_documento("TÉCNICO"), "tecnico")
        self.assertEqual(module._normalize_tipo_documento("Tecnica"), "tecnico")
        self.assertEqual(module._normalize_tipo_documento(" ADMINISTRATIVO "), "administrativo")

    def test_normalize_retrieval_k_bounds(self):
        self.assertEqual(self.m.normalize_retrieval_k(1), self.m.DEFAULT_RAG_MIN_CHUNKS)
        self.assertEqual(self.m.normalize_retrieval_k(999), 999)

    def test_llm_model_resolution_and_choices(self):
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
        module = self.m
        prompt = module.build_rag_prompt("pregunta", ["ctx1", "ctx2"], query_profile="unknown-profile")
        self.assertIn("pregunta", prompt)
        self.assertIn("ctx1", prompt)

    def test_make_qdrant_client_success_none_and_raise(self):
        module = self.m

        class _Client:
            def __init__(self):
                self.calls = 0

            def get_collections(self):
                self.calls += 1
                return []

        class _ClientSlow(_Client):
            def __init__(self):
                super().__init__()
                self.calls = 0

            def get_collections(self):
                self.calls += 1
                raise module.httpx.HTTPError("not ready")

        def fake_ctor(**_kwargs):
            return _Client()

        def fake_ctor_slow(**_kwargs):
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
            raise ValueError("bad cfg")

        with (
            patch.object(module, "QDRANT_URL", ""),
            patch.object(module, "QdrantClient", side_effect=fake_ctor_raise),
            self.assertRaises(RuntimeError),
        ):
            module._make_qdrant_client()

    def test_build_qdrant_metadata_filter_and_exists(self):
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
        module = self.m
        fake_qdrant = MagicMock()
        fake_qdrant.close.side_effect = module.httpx.HTTPError("boom")
        module.qdrant = fake_qdrant
        module._close_qdrant()
        self.assertIsNone(module.qdrant)

    def test_qdrant_get_payloads_empty_and_error_paths(self):
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
        module = self.m
        module.qdrant = MagicMock()
        with patch.object(module.VectorBaseDocument, "_ensure_collection"):
            module.qdrant_delete_by_filename("a.pdf")
        module.qdrant.delete.assert_called_once()

    def test_vector_base_document_collection_and_mappings(self):
        module = self.m

        # evita depender del singleton real
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
        # fuerza collection missing para que recree
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

        # save / save_many upsert
        module.qdrant.upsert.reset_mock()
        with patch.object(module.VectorBaseDocument, "_ensure_collection"):
            doc.save()
            module.VectorBaseDocument.save_many([doc])
        self.assertEqual(module.qdrant.upsert.call_count, 2)

        # bulk_find (next offset convertido a UUID)
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
        module = self.m

        class _Page:
            def __init__(self, text):
                self._text = text

            def extract_text(self):
                return self._text

        class _Reader:
            def __init__(self, meta, pages):
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
        module = self.m
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "a.pdf"
            content = b"pdf-bytes"
            p.write_bytes(content)
            expected = hashlib.sha256(content).hexdigest()
            self.assertEqual(module.pdf_sha256(p), expected)

    def test_index_pliegos_dir_counts_new_modified_omitted_and_errors(self):
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

    def test_index_markdown_empty_and_success_and_errors(self):
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
        module = self.m
        with patch.object(module, "qdrant_exists_by_metadata", return_value=True) as mock_exists:
            self.assertTrue(module.qdrant_has_filename("a.pdf"))
            self.assertTrue(module.qdrant_has_same_hash("a.pdf", "sha"))
        self.assertEqual(mock_exists.call_count, 2)

    def test_import_fallback_qdrant_http_exceptions_defines_classes(self):
        mod = _import_prototipo_with_missing_qdrant_http_exceptions()
        self.assertTrue(issubclass(mod.ResponseHandlingException, RuntimeError))
        self.assertTrue(issubclass(mod.UnexpectedResponse, RuntimeError))

    def test_ask_ollama_happy_path_cancel_and_timeout(self):
        module = self.m

        with self.assertRaises(module.QueryCancelledError):
            asyncio.run(module.ask_ollama("prompt", should_cancel=lambda: True))

        class _Resp:
            def __init__(self, lines):
                self._lines = lines
                self.status_code = 200

            async def __aenter__(self):
                return self

            async def __aexit__(self, *_args):
                return False

            async def aread(self):
                await asyncio.sleep(0)
                return b""

            def raise_for_status(self):
                return None

            async def aiter_lines(self):
                for line in self._lines:
                    yield line

        class _Client:
            def __init__(self, **_kwargs):
                # para cubrir el caso de que se intente usar el cliente para otra cosa que no sea el streaming de ask_ollama
                pass

            async def __aenter__(self):
                return self

            async def __aexit__(self, *_args):
                return False

            def stream(self, *_args, **_kwargs):
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
                raise module.httpx.TimeoutException("slow")

        with (
            patch.object(module.httpx, "AsyncClient", _TimeoutClient),
            patch.object(module, "ensure_ollama_model_available", new_callable=unittest.mock.AsyncMock),
            self.assertRaises(module.OllamaTimeoutError),
        ):
            asyncio.run(module.ask_ollama("prompt", model="m"))

    def test_default_ollama_uses_gpu_auto_setting(self):
        m = _import_prototipo_with_env({"OLLAMA_NUM_GPU": None})
        self.assertEqual(m.settings.OLLAMA_NUM_GPU, -1)
        self.assertEqual(m.settings.OLLAMA_NUM_GPU_SOURCE, "auto-ollama")

    def test_embedding_execution_backend_cpu_and_cuda_variants(self):
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
                    return False

            self.m.torch = SimpleNamespace(cuda=_CudaUnavailable())
            self.assertIn("CUDA no disponible", self.m._embedding_execution_backend())

            class _CudaAvailable:
                @staticmethod
                def is_available():
                    return True

                @staticmethod
                def get_device_name(_index):
                    return "Fake GPU"

                @staticmethod
                def device_count():
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

    def test_embedding_model_cuda_oom_helpers_and_retry_to_cpu(self):
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
                    self.tokenizer = object()

                def eval(self):
                    return None

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

    def test_format_bytes(self):
        self.assertEqual(self.m._format_bytes(-1), "-")
        self.assertEqual(self.m._format_bytes("x"), "-")
        self.assertEqual(self.m._format_bytes(0), "0 B")
        self.assertEqual(self.m._format_bytes(1023), "1023 B")
        self.assertEqual(self.m._format_bytes(1024), "1.0 KB")
        self.assertEqual(self.m._format_bytes(1024 * 1024), "1.0 MB")

    def test_format_ollama_pull_progress(self):
        msg = self.m._format_ollama_pull_progress(
            "m",
            {"status": "pulling", "digest": "abcdef" * 10, "completed": 512, "total": 1024},
        )
        self.assertIn("m: pulling", msg)
        self.assertIn("50.0%", msg)
        self.assertIn("(512 B / 1.0 KB)", msg)
        # digest truncado a 12 chars
        self.assertIn(" abcdefabcdef", msg)

        msg2 = self.m._format_ollama_pull_progress("m", {"completed": 1024})
        self.assertIn("(1.0 KB)", msg2)

        msg3 = self.m._format_ollama_pull_progress("m", {"completed": 9999, "total": 1})
        self.assertIn("100.0%", msg3)

    def test_extract_ollama_chat_piece_parses_response_and_message(self):
        module = self.m

        piece, done = module._extract_ollama_chat_piece('{"response":"Hola ","done":false}')
        self.assertEqual(piece, "Hola ")
        self.assertFalse(done)

        piece2, done2 = module._extract_ollama_chat_piece('{"message":{"content":"mundo"},"done":true}')
        self.assertEqual(piece2, "mundo")
        self.assertTrue(done2)

    def test_timeout_to_total_seconds_uses_max_defined(self):
        module = self.m

        t = module.httpx.Timeout(connect=1.0, read=2.0, write=3.0, pool=4.0)
        self.assertEqual(module._timeout_to_total_seconds(t), 4.0)

        t2 = module.httpx.Timeout(connect=None, read=5.0, write=None, pool=None)
        self.assertEqual(module._timeout_to_total_seconds(t2), 5.0)

        # Si todo es None, devuelve None
        t3 = module.httpx.Timeout(connect=None, read=None, write=None, pool=None)
        self.assertIsNone(module._timeout_to_total_seconds(t3))

    def test_normalize_ollama_model_name_strips_and_lowercases(self):
        module = self.m
        self.assertEqual(module._normalize_ollama_model_name("  Llama3.1:8B "), "llama3.1:8b")
        self.assertEqual(module._normalize_ollama_model_name(None), "")

    def test_infer_device_from_ollama_ps_payload(self):
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
        module = self.m

        class _Resp:
            def __init__(self, payload, content=b"x"):
                self._payload = payload
                self.content = content

            def raise_for_status(self):
                return None

            def json(self):
                return self._payload

        class _Client:
            async def __aenter__(self):
                return self

            async def __aexit__(self, *_args):
                return False

            async def get(self, _path):
                await asyncio.sleep(0)
                return _Resp({"models": []})

        async def fake_wait_for(coro, timeout):
            self.assertEqual(timeout, 3.0)
            return await coro

        timeout = module.httpx.Timeout(connect=None, read=3.0, write=None, pool=None)
        with patch.object(module.httpx, "AsyncClient", return_value=_Client()), patch.object(
            module.asyncio, "wait_for", side_effect=fake_wait_for
        ):
            payload = asyncio.run(module._fetch_ollama_ps_payload(request_timeout=timeout))
        self.assertEqual(payload, {"models": []})

    def test_fetch_ollama_ps_payload_returns_empty_when_no_content(self):
        module = self.m

        class _Resp:
            content = b""

            def raise_for_status(self):
                return None

            def json(self):
                return {"x": 1}

        class _Client:
            async def __aenter__(self):
                return self

            async def __aexit__(self, *_args):
                return False

            async def get(self, _path):
                await asyncio.sleep(0)
                return _Resp()

        timeout = module.httpx.Timeout(connect=None, read=None, write=None, pool=None)
        with patch.object(module.httpx, "AsyncClient", return_value=_Client()):
            payload = asyncio.run(module._fetch_ollama_ps_payload(request_timeout=timeout))
        self.assertEqual(payload, {})

    def test_fetch_ollama_ps_payload_no_timeout_no_wait_for(self):
        module = self.m

        class _Resp:
            content = b"x"

            def raise_for_status(self):
                return None

            def json(self):
                return {"models": []}

        class _Client:
            async def __aenter__(self):
                return self

            async def __aexit__(self, *_args):
                return False

            async def get(self, _path):
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
        module = self.m

        class _ItStop:
            async def __anext__(self):
                raise StopAsyncIteration()

        self.assertIsNone(asyncio.run(module._read_ollama_pull_line(_ItStop(), 1.0, "m")))

        class _ItHang:
            async def __anext__(self):
                await asyncio.sleep(10)
                return "x"

        async def fake_wait_for(*_args, **_kwargs):
            raise asyncio.TimeoutError()

        with (
            patch.object(module.asyncio, "wait_for", side_effect=fake_wait_for),
            self.assertRaises(module.OllamaTimeoutError),
        ):
            asyncio.run(module._read_ollama_pull_line(_ItHang(), 1.5, "m"))

    def test_emit_ollama_pull_progress_logs_and_throttles(self):
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
        module = self.m

        class _Resp:
            def __init__(self, status_code: int, text: str = "", body: bytes = b""):
                self.status_code = status_code
                self.text = text
                self._body = body

            def raise_for_status(self):
                req = module.httpx.Request("POST", "http://ollama/api/show")
                resp = module.httpx.Response(self.status_code, request=req, content=self._body)
                raise module.httpx.HTTPStatusError("error", request=req, response=resp)

        class _PullOK:
            def __init__(self, lines: list[str]):
                self._lines = lines
                self.status_code = 200

            async def __aenter__(self):
                return self

            async def __aexit__(self, *_args):
                return False

            def raise_for_status(self):
                return None

            async def aread(self):
                await asyncio.sleep(0)
                return b""

            async def aiter_lines(self):
                for line in self._lines:
                    yield line

        class _PullFail(_PullOK):
            def __init__(self, body: bytes):
                super().__init__(lines=[])
                self._body = body

            def raise_for_status(self):
                req = module.httpx.Request("POST", "http://ollama/api/pull")
                resp = module.httpx.Response(404, request=req, content=b"")
                raise module.httpx.HTTPStatusError("error", request=req, response=resp)

            async def aread(self):
                await asyncio.sleep(0)
                return self._body

        class _Client:
            def __init__(self, show_resp, pull_resp=None):
                self._show = show_resp
                self._pull = pull_resp

            async def post(self, *_args, **_kwargs):
                await asyncio.sleep(0)
                return self._show

            def stream(self, *_args, **_kwargs):
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
        module = self.m

        class _ShowResp:
            status_code = 404
            text = ""

        class _PullResp:
            status_code = 200

            async def __aenter__(self):
                return self

            async def __aexit__(self, *_args):
                return False

            def raise_for_status(self):
                return None

            async def aread(self):
                await asyncio.sleep(0)
                return b""

            async def aiter_lines(self):
                while True:
                    yield '{"status":"pulling","completed":0,"total":100}'

        class _Client:
            async def post(self, *_args, **_kwargs):
                await asyncio.sleep(0)
                return _ShowResp()

            def stream(self, *_args, **_kwargs):
                return _PullResp()

        original_total = module.settings.OLLAMA_PULL_TIMEOUT_SECONDS
        original_idle = module.settings.OLLAMA_PULL_IDLE_TIMEOUT_SECONDS
        try:
            module.settings.OLLAMA_PULL_TIMEOUT_SECONDS = 1
            module.settings.OLLAMA_PULL_IDLE_TIMEOUT_SECONDS = 0
            mono = iter([0.0, 2.0, 2.0, 2.0])
            with patch.object(module, "time", SimpleNamespace(monotonic=lambda: next(mono))):
                with self.assertRaises(module.OllamaTimeoutError):
                    asyncio.run(module.ensure_ollama_model_available(_Client(), "m"))
        finally:
            module.settings.OLLAMA_PULL_TIMEOUT_SECONDS = original_total
            module.settings.OLLAMA_PULL_IDLE_TIMEOUT_SECONDS = original_idle

    def test_ensure_ollama_model_ready_opens_client_and_delegates(self):
        module = self.m

        class _Client:
            def __init__(self, **kwargs):
                self.kwargs = kwargs

            async def __aenter__(self):
                return self

            async def __aexit__(self, *_args):
                return False

        with (
            patch.object(module.httpx, "AsyncClient", _Client),
            patch.object(module, "ensure_ollama_model_available", new_callable=unittest.mock.AsyncMock) as mock_ensure,
        ):
            asyncio.run(module.ensure_ollama_model_ready("m"))
        mock_ensure.assert_awaited_once()

    def test_chunk_text_skips_bad_token_lines_and_overlaps(self):
        module = self.m

        class _Tok:
            def tokenize(self, text):
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
        qdrant = MagicMock()
        module = self.m
        module.qdrant = qdrant

        good = SimpleNamespace(id=uuid4(), payload={"content": "ok"}, score=0.51)
        bad = SimpleNamespace(id=uuid4(), payload={"content": "low"}, score=0.5)
        qdrant.query_points.return_value = SimpleNamespace(points=[good, bad])

        class _Embed:
            embedding_size = 3
            model_id = "m"
            max_input_length = 8
            tokenizer = SimpleNamespace(tokenize=lambda s: s.split())

            def __call__(self, _text, to_list=True):
                return [0.0, 0.0, 0.0]

        module.embedding_model = _Embed()

        with patch.object(module.VectorBaseDocument, "_ensure_collection"):
            out = module.recuperacion_chunk_con_scores("pregunta")
        self.assertEqual(out, [good])

    def test_obtener_mejor_chunk_does_not_import_flask_package_for_resource_priority(self):
        qpoint = SimpleNamespace(id=uuid4(), score=0.75, payload={"content": "ctx", "metadata": {}})

        async def fake_ask(_prompt, **_kwargs):
            await asyncio.sleep(0)
            return "respuesta"

        resource_priority = types.ModuleType("app.main.code.services.resource_priority")

        class _AsyncNullContext:
            async def __aenter__(self):
                return None

            async def __aexit__(self, *_args):
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
        module = self.m

        # _ollama_pull_read_timeout(total_timeout, idle_timeout, elapsed)
        self.assertIsNone(module._ollama_pull_read_timeout(total_timeout=0, idle_timeout=0, elapsed=0))
        self.assertEqual(module._ollama_pull_read_timeout(total_timeout=0, idle_timeout=5, elapsed=999), 5)

        self.assertEqual(module._ollama_pull_read_timeout(total_timeout=10, idle_timeout=0, elapsed=3), 7)
        self.assertEqual(module._ollama_pull_read_timeout(total_timeout=10, idle_timeout=-1, elapsed=1000), 0.1)

        self.assertEqual(module._ollama_pull_read_timeout(total_timeout=10, idle_timeout=2, elapsed=3), 2)
        self.assertEqual(module._ollama_pull_read_timeout(total_timeout=10, idle_timeout=20, elapsed=3), 7)

    def test_timed_block_logs_elapsed_seconds(self):
        values = iter([10.0, 10.125])

        def fake_perf_counter():
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
