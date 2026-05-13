import asyncio
import importlib
import os
import runpy
import sys
import tempfile
import types
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch
from uuid import UUID, uuid4


class _FakeArray:
    def __init__(self, values):
        self.values = values

    def tolist(self):
        return self.values


class _FakeTokenizer:
    def tokenize(self, text):
        if text == "BAD":
            raise RuntimeError("token error")
        return text.split()


class _FakeSentenceTransformer:
    fail_cuda_oom_once = False
    def __init__(self, model_id, device="cpu", cache_folder=None):
        self.model_id = model_id
        self.device = device
        self.cache_folder = cache_folder
        self.max_seq_length = 8
        self.tokenizer = _FakeTokenizer()
        self.eval_called = False

    def eval(self):
        self.eval_called = True
    def to(self, device):
        self.device = device
        return self

    def get_sentence_embedding_dimension(self):
        return 3

    def encode(self, input_text, **_kwargs):
        if self.device != "cpu" and self.fail_cuda_oom_once:
            self.fail_cuda_oom_once = False
            raise RuntimeError("CUDA error: out of memory")
        if isinstance(input_text, list):
            return [_FakeArray([float(i), float(i + 1), float(i + 2)]) for i, _ in enumerate(input_text)]
        return _FakeArray([1.0, 2.0, 3.0])


class _FakeCuda:
    available = False

    @classmethod
    def is_available(cls):
        return cls.available

    @staticmethod
    def get_device_name(_index):
        return "Fake GPU"

    @staticmethod
    def device_count():
        return 2

    @staticmethod
    def empty_cache():
        return None

class _FakeQdrantClient:
    fail_init = False
    fail_get_collections_times = 0
    instances = []

    def __init__(self, **kwargs):
        if self.fail_init:
            raise RuntimeError("init failed")
        self.kwargs = kwargs
        self.closed = False
        self.collections_checked = 0
        self.collections = {}
        self.scroll_result = ([], None)
        self.retrieve_result = []
        self.query_result = []
        self.deleted = []
        self.upserts = []
        _FakeQdrantClient.instances.append(self)

    def get_collections(self):
        self.collections_checked += 1
        if self.collections_checked <= _FakeQdrantClient.fail_get_collections_times:
            raise RuntimeError("not ready")
        return []

    def close(self):
        self.closed = True

    def get_collection(self, name):
        if name not in self.collections:
            raise RuntimeError("missing")
        return self.collections[name]

    def recreate_collection(self, collection_name, vectors_config):
        self.collections[collection_name] = vectors_config

    def scroll(self, **_kwargs):
        return self.scroll_result

    def retrieve(self, **_kwargs):
        return self.retrieve_result

    def delete(self, **kwargs):
        self.deleted.append(kwargs)

    def upsert(self, **kwargs):
        self.upserts.append(kwargs)

    def query_points(self, **_kwargs):
        return self.query_result


def _install_fake_dependencies(cuda_available=False):
    _FakeCuda.available = cuda_available
    _FakeQdrantClient.fail_init = False
    _FakeQdrantClient.fail_get_collections_times = 0
    _FakeQdrantClient.instances = []

    sentence_transformers = types.ModuleType("sentence_transformers")
    sentence_transformers.SentenceTransformer = _FakeSentenceTransformer

    qdrant_client = types.ModuleType("qdrant_client")
    qdrant_client.QdrantClient = _FakeQdrantClient

    qmodels = types.ModuleType("qdrant_client.models")

    class _Model:
        def __init__(self, **kwargs):
            self.__dict__.update(kwargs)

    class Distance:
        COSINE = "Cosine"

    qmodels.Filter = _Model
    qmodels.FieldCondition = _Model
    qmodels.MatchValue = _Model
    qmodels.FilterSelector = _Model
    qmodels.VectorParams = _Model
    qmodels.PointStruct = _Model
    qmodels.Distance = Distance
    qmodels.ScoredPoint = _Model
    qmodels.Record = _Model
    qdrant_client.models = qmodels

    torch = types.ModuleType("torch")
    torch.cuda = _FakeCuda

    sys.modules["sentence_transformers"] = sentence_transformers
    sys.modules["qdrant_client"] = qdrant_client
    sys.modules["qdrant_client.models"] = qmodels
    sys.modules["torch"] = torch


def _load_module(cuda_available=False, env=None):
    old_env = {}
    env = env or {}
    for key, value in env.items():
        old_env[key] = os.environ.get(key)
        if value is None:
            os.environ.pop(key, None)
        else:
            os.environ[key] = value
    _install_fake_dependencies(cuda_available=cuda_available)
    sys.modules.pop("app.main.code.services.rag.PrototipoRAG", None)
    try:
        return importlib.import_module("app.main.code.services.rag.PrototipoRAG")
    finally:
        for key, value in old_env.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


def _load_module_without_torch(env=None):
    real_import = __import__
    old_env = {}
    env = env or {}
    old_torch = sys.modules.pop("torch", None)

    def import_without_torch(name, *args, **kwargs):
        if name == "torch":
            raise ImportError("torch missing")
        return real_import(name, *args, **kwargs)

    for key, value in env.items():
        old_env[key] = os.environ.get(key)
        if value is None:
            os.environ.pop(key, None)
        else:
            os.environ[key] = value
    _install_fake_dependencies()
    sys.modules.pop("torch", None)
    sys.modules.pop("app.main.code.services.rag.PrototipoRAG", None)
    try:
        with patch("builtins.__import__", side_effect=import_without_torch):
            return importlib.import_module("app.main.code.services.rag.PrototipoRAG")
    finally:
        for key, value in old_env.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
        if old_torch is None:
            sys.modules.pop("torch", None)
        else:
            sys.modules["torch"] = old_torch


class _AsyncStream:
    def __init__(self, lines=None, exc=None):
        self.lines = lines or []
        self.exc = exc
        self.status_code = 200
        self.text = ""

    async def __aenter__(self):
        if self.exc:
            raise self.exc
        return self

    async def __aexit__(self, *_args):
        return False

    def raise_for_status(self):
        return None

    async def aiter_lines(self):
        for line in self.lines:
            yield line


class _FailingAsyncStream(_AsyncStream):
    def __init__(self, module, status_code=500, body=b"boom"):
        super().__init__([])
        self.module = module
        self.status_code = status_code
        self.body = body

    def raise_for_status(self):
        request = self.module.httpx.Request("POST", "http://ollama/api")
        response = self.module.httpx.Response(self.status_code, request=request)
        raise self.module.httpx.HTTPStatusError("error", request=request, response=response)

    async def aread(self):
        return self.body


class _AsyncClient:
    stream_obj = _AsyncStream([])
    created = []

    def __init__(self, **kwargs):
        self.kwargs = kwargs
        _AsyncClient.created.append(self)

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_args):
        return False

    async def post(self, *_args, **_kwargs):
        return SimpleNamespace(status_code=200, text="", raise_for_status=lambda: None)

    def stream(self, *_args, **kwargs):
        self.stream_kwargs = kwargs
        return self.stream_obj


class PrototipoRAGUnitTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.module = _load_module()
        _load_module(cuda_available=True)
        _load_module(env={"OLLAMA_NUM_GPU": "3", "OLLAMA_READ_TIMEOUT_SECONDS": "5", "QDRANT_URL": "http://qdrant.local"})
        cls.module = _load_module()

    def setUp(self):
        self.m = self.module
        self.m.qdrant = _FakeQdrantClient()
        self.m.EmbeddingModelSingleton._instance = None
        self.m.embedding_model = self.m.EmbeddingModelSingleton()

    def test_embedding_error_helpers_cover_cpu_and_debug_paths(self):
        model = self.m.EmbeddingModelSingleton(model_id="fake-model", device="cpu")
        model._move_to_cpu()
        self.assertEqual(model._device, "cpu")

        bad_cuda = SimpleNamespace(empty_cache=MagicMock(side_effect=RuntimeError("cache")))
        original_torch = self.m.torch
        try:
            self.m.torch = SimpleNamespace(cuda=bad_cuda)
            with patch.object(self.m.logger, "debug") as mock_debug:
                model._clear_cuda_cache()
        finally:
            self.m.torch = original_torch

        mock_debug.assert_called_once()

    def test_embedding_call_reraises_non_cuda_errors(self):
        model = self.m.EmbeddingModelSingleton(model_id="fake-model", device="cuda")
        model._model.encode = MagicMock(side_effect=RuntimeError("fallo generico"))

        with self.assertRaises(RuntimeError):
            model("texto")

    def test_lazy_embedding_and_qdrant_helpers(self):
        lazy_embedding = self.m.LazyEmbeddingModel()
        fake_embedding = MagicMock(return_value=[1.0])

        with patch.object(lazy_embedding, "_get_instance", return_value=fake_embedding):
            self.assertEqual(lazy_embedding("texto"), [1.0])

        lazy_qdrant = self.m.LazyQdrantClient()
        with patch.object(self.m, "_make_qdrant_client", return_value=None):
            with self.assertRaises(RuntimeError):
                lazy_qdrant._get_client()

        closeable = MagicMock()
        closeable.ping.return_value = "pong"
        lazy_qdrant._client = closeable
        self.assertEqual(lazy_qdrant.ping(), "pong")
        lazy_qdrant.close()
        closeable.close.assert_called_once_with()
        self.assertIsNone(lazy_qdrant._client)

    def test_main_block_runs_with_empty_pliegos_directory(self):
        pliegos_dir = Path(self.m.__file__).parent / "pliegos"
        pliegos_dir.mkdir(exist_ok=True)

        _install_fake_dependencies()
        old_module = sys.modules.pop("app.main.code.services.rag.PrototipoRAG", None)
        try:
            runpy.run_module("app.main.code.services.rag.PrototipoRAG", run_name="__main__")
        finally:
            sys.modules["app.main.code.services.rag.PrototipoRAG"] = old_module or self.m

    def test_service_urls_and_backend_descriptions(self):
        with patch.dict(os.environ, {"X_SERVICE": "host:123", "X_SERVICE_SCHEME": "https"}):
            self.assertEqual(self.m._service_url_from_env("X_SERVICE", "fallback"), "https://host:123")
        with patch.dict(os.environ, {"X_SERVICE": "http://ready/"}):
            self.assertEqual(self.m._service_url_from_env("X_SERVICE", "fallback"), "http://ready")

        self.m.settings.RAG_MODEL_DEVICE = "cpu"
        self.assertEqual(self.m._embedding_execution_backend(), "CPU (cpu)")
        self.m.settings.RAG_MODEL_DEVICE = "cuda:0"
        self.m.torch = None
        self.assertIn("torch no disponible", self.m._embedding_execution_backend())
        self.m.torch = sys.modules["torch"]
        _FakeCuda.available = False
        self.assertIn("CUDA no disponible", self.m._embedding_execution_backend())
        _FakeCuda.available = True
        self.assertIn("Fake GPU", self.m._embedding_execution_backend())

        self.m.settings.OLLAMA_NUM_GPU = -1
        self.m.settings.OLLAMA_NUM_GPU_SOURCE = "auto"
        self.assertIn("all layers", self.m._ollama_execution_backend())
        self.m.settings.OLLAMA_NUM_GPU = 2
        self.assertIn("num_gpu=2", self.m._ollama_execution_backend())
        self.assertEqual(self.m.get_ollama_execution_device(), "GPU")
        self.m.settings.OLLAMA_NUM_GPU = 0
        self.assertIn("CPU", self.m._ollama_execution_backend())
        self.assertEqual(self.m.get_ollama_execution_device(), "CPU")

    def test_rag_model_choices_and_pull_progress_formatting(self):
        original_default = self.m.settings.DEFAULT_RAG_LLM_MODEL
        original_models = self.m.settings.RAG_LLM_MODELS
        try:
            self.m.settings.DEFAULT_RAG_LLM_MODEL = "llama"
            self.m.settings.RAG_LLM_MODELS = " llama, gemma , qwen, gemma "

            self.assertEqual(self.m.resolve_rag_llm_model(" gemma "), "gemma")
            self.assertEqual(self.m.resolve_rag_llm_model(" "), "llama")
            self.assertEqual(self.m.get_available_rag_llm_models(), ["llama", "gemma", "qwen"])
            self.assertEqual(
                self.m.get_rag_llm_model_choices(),
                [("llama", "llama"), ("gemma", "gemma"), ("qwen", "qwen")],
            )
        finally:
            self.m.settings.DEFAULT_RAG_LLM_MODEL = original_default
            self.m.settings.RAG_LLM_MODELS = original_models

        self.assertEqual(self.m._format_bytes(None), "-")
        self.assertEqual(self.m._format_bytes(-1), "-")
        self.assertEqual(self.m._format_bytes(12), "12 B")
        self.assertEqual(self.m._format_bytes(2048), "2.0 KB")
        self.assertIn(
            "50.0% (1.0 KB / 2.0 KB)",
            self.m._format_ollama_pull_progress(
                "gemma",
                {"status": "pulling", "digest": "abcdef1234567890", "completed": 1024, "total": 2048},
            ),
        )
        self.assertEqual(
            self.m._format_ollama_pull_progress("gemma", {"completed": 1024}),
            "gemma: descargando (1.0 KB)",
        )

    def test_import_without_torch_and_auto_ollama_gpu_branches(self):
        auto_env = {"OLLAMA_NUM_GPU": "", "RAG_MODEL_DEVICE": None}

        without_torch = _load_module_without_torch(env=auto_env)
        self.assertIsNone(without_torch.torch)
        self.assertEqual(without_torch.settings.RAG_MODEL_DEVICE, "cpu")
        self.assertEqual(without_torch.settings.OLLAMA_NUM_GPU, -1)
        self.assertEqual(without_torch.settings.OLLAMA_NUM_GPU_SOURCE, "auto-ollama")

        cuda_module = _load_module(cuda_available=True, env=auto_env)
        self.assertEqual(cuda_module.settings.RAG_MODEL_DEVICE, "cuda")
        self.assertEqual(cuda_module.settings.OLLAMA_NUM_GPU, -1)
        self.assertEqual(cuda_module.settings.OLLAMA_NUM_GPU_SOURCE, "auto-ollama")

        cpu_module = _load_module(cuda_available=False, env=auto_env)
        self.assertEqual(cpu_module.settings.RAG_MODEL_DEVICE, "cpu")
        self.assertEqual(cpu_module.settings.OLLAMA_NUM_GPU, -1)
        self.assertEqual(cpu_module.settings.OLLAMA_NUM_GPU_SOURCE, "auto-ollama")

    def test_embedding_model_singleton_properties_and_call_shapes(self):
        self.m.EmbeddingModelSingleton._instance = None
        model = self.m.EmbeddingModelSingleton(model_id="fake-model", device="cpu", cache_dir=Path("cache"))
        same_model = self.m.EmbeddingModelSingleton()

        self.assertIs(model, same_model)
        self.assertEqual(model.model_id, "fake-model")
        self.assertEqual(model.embedding_size, 3)
        self.assertEqual(model.max_input_length, 8)
        self.assertIsInstance(model.tokenizer, _FakeTokenizer)
        self.assertEqual(model("texto"), [1.0, 2.0, 3.0])
        self.assertEqual(model(["a", "b"]), [[0.0, 1.0, 2.0], [1.0, 2.0, 3.0]])
        self.assertIsInstance(model("texto", to_list=False), _FakeArray)

    def test_embedding_model_falls_back_to_cpu_when_cuda_runs_out_of_memory(self):
        self.m.EmbeddingModelSingleton._instance = None
        model = self.m.EmbeddingModelSingleton(model_id="fake-model", device="cuda")
        model._model.fail_cuda_oom_once = True
        self.assertEqual(model("texto"), [1.0, 2.0, 3.0])
        self.assertEqual(model._device, "cpu")
        self.assertEqual(model._model.device, "cpu")
        self.assertEqual(self.m.settings.RAG_MODEL_DEVICE, "cpu")

    def test_make_qdrant_client_retries_returns_none_and_raises_on_init_failure(self):
        _FakeQdrantClient.fail_get_collections_times = 2
        with patch.object(self.m.time, "sleep") as mock_sleep:
            client = self.m._make_qdrant_client()
        self.assertIsInstance(client, _FakeQdrantClient)
        self.assertEqual(mock_sleep.call_count, 2)

        _FakeQdrantClient.fail_get_collections_times = 99
        with patch.object(self.m.time, "sleep"):
            self.assertIsNone(self.m._make_qdrant_client())

        _FakeQdrantClient.fail_init = True
        with self.assertRaises(RuntimeError):
            self.m._make_qdrant_client()
        _FakeQdrantClient.fail_init = False

    def test_close_qdrant_closes_ignores_errors_and_clears_global(self):
        client = _FakeQdrantClient()
        self.m.qdrant = client
        self.m._close_qdrant()
        self.assertTrue(client.closed)
        self.assertIsNone(self.m.qdrant)

        bad_client = MagicMock()
        bad_client.close.side_effect = RuntimeError("close")
        self.m.qdrant = bad_client
        self.m._close_qdrant()
        self.assertIsNone(self.m.qdrant)

    def test_hash_filters_and_qdrant_helpers(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "a.pdf"
            path.write_bytes(b"abc")
            self.assertEqual(self.m.pdf_sha256(path), "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad")

        self.assertIsNone(self.m.build_qdrant_metadata_filter())
        filename_filter = self.m.build_qdrant_metadata_filter(filename="a.pdf")
        self.assertEqual(filename_filter.must[0].key, "metadata.filename")
        hash_filter = self.m.build_qdrant_metadata_filter(filename="a.pdf", sha256="hash")
        self.assertEqual(hash_filter.must[1].key, "metadata.sha256")

        self.m.qdrant.scroll_result = ([object()], None)
        self.assertTrue(self.m.qdrant_has_filename("a.pdf"))
        self.assertTrue(self.m.qdrant_has_same_hash("a.pdf", "hash"))
        self.m.qdrant.scroll_result = ([], None)
        self.assertFalse(self.m.qdrant_has_filename("a.pdf"))

        self.m.qdrant_delete_by_filename("a.pdf")
        self.assertEqual(len(self.m.qdrant.deleted), 1)

    def test_qdrant_get_payloads_empty_success_and_error_paths(self):
        self.assertEqual(self.m.qdrant_get_payloads(["", None]), {})

        point_id = uuid4()
        self.m.qdrant.retrieve_result = [SimpleNamespace(id=point_id, payload={"content": "txt"})]
        self.assertEqual(self.m.qdrant_get_payloads([str(point_id)]), {str(point_id): {"content": "txt"}})

        self.m.qdrant.retrieve = MagicMock(side_effect=ValueError("missing collection"))
        self.assertEqual(self.m.qdrant_get_payloads(["x"]), {})
        self.m.qdrant.retrieve = MagicMock(side_effect=RuntimeError("boom"))
        self.assertEqual(self.m.qdrant_get_payloads(["x"]), {})

    def test_vector_document_mapping_save_find_and_search(self):
        doc_id = uuid4()
        doc = self.m.VectorBaseDocument(id=doc_id, content="texto", embedding=[0.1], metadata={"a": 1})

        self.m.qdrant.collections[self.m.VectorBaseDocument.get_collection_name()] = object()
        point = doc.to_point()
        self.assertEqual(point.id, str(doc_id))
        self.assertEqual(point.payload["metadata"], {"a": 1})

        record = SimpleNamespace(id=doc_id, payload={"content": "texto", "metadata": {"b": 2}}, vector=[0.2])
        restored = self.m.VectorBaseDocument.from_record(record)
        self.assertEqual(restored.content, "texto")
        self.assertEqual(restored.metadata, {"b": 2})
        defaulted = self.m.VectorBaseDocument.from_record(SimpleNamespace(id=doc_id, payload=None))
        self.assertEqual(defaulted.content, "")

        doc.save()
        self.m.VectorBaseDocument.save_many([doc])
        self.assertEqual(len(self.m.qdrant.upserts), 2)

        next_id = uuid4()
        self.m.qdrant.scroll_result = ([record], str(next_id))
        docs, offset = self.m.VectorBaseDocument.bulk_find(limit=1, offset=doc_id)
        self.assertEqual(docs[0].id, doc_id)
        self.assertEqual(offset, next_id)
        self.m.qdrant.scroll_result = ([record], None)
        _, offset = self.m.VectorBaseDocument.bulk_find()
        self.assertIsNone(offset)

        self.m.qdrant.query_result = SimpleNamespace(points=[record])
        self.assertEqual(self.m.VectorBaseDocument.search([0.1])[0].metadata, {"b": 2})
        self.m.qdrant.query_result = [record]
        self.assertEqual(self.m.VectorBaseDocument.search([0.1])[0].content, "texto")

        self.m.qdrant.collections = {}
        self.m.VectorBaseDocument._ensure_collection()
        self.assertIn(self.m.VectorBaseDocument.get_collection_name(), self.m.qdrant.collections)

    def test_chunking_and_token_helpers(self):
        fake_embedding_model = SimpleNamespace(tokenizer=_FakeTokenizer(), max_input_length=4)
        self.m.embedding_model = fake_embedding_model
        text = "uno dos\ntres cuatro\nBAD\ncinco seis"
        chunks = self.m.chunk_text(text, overlap_ratio=0.5)
        self.assertTrue(chunks)
        self.assertEqual(self.m.token_len(self.m.embedding_model.tokenizer, "uno dos"), 2)
        self.assertIsNone(self.m.token_len(self.m.embedding_model.tokenizer, "BAD"))

        out = []
        self.m.get_chunk(out, [("  ", 1)])
        self.assertEqual(out, [])
        overlap, tokens = self.m.token_overlap([("a", 1), ("b c", 2), ("d", 1)], 2)
        self.assertEqual(overlap, [("d", 1)])
        self.assertEqual(tokens, 1)
        self.assertEqual(list(self.m.iter_clean_lines("\n a \n\n b")), ["a", "b"])

    def test_metadata_filters_and_retrieval_helpers(self):
        self.assertIsNone(self.m.build_metadata_filter())
        both = self.m.build_metadata_filter("EXP", "tecnico")
        self.assertEqual([condition.key for condition in both.must], ["metadata.numero_expediente", "metadata.tipo_documento"])

        record = SimpleNamespace(id=uuid4(), payload={"content": "txt", "metadata": {"filename": "doc.pdf"}}, score=0.4)
        self.m.qdrant.query_result = SimpleNamespace(points=[record])
        result = self.m.recuperacion_chunk("pregunta", k=3, numero_expediente="EXP")
        self.assertEqual(result[0].content, "txt")
        self.assertEqual(result[0].metadata["filename"], "doc.pdf")

        point = SimpleNamespace(id=uuid4(), payload={"content": "txt"}, score=0.51)
        low_score = SimpleNamespace(id=uuid4(), payload={"content": "low"}, score=0.5)
        self.m.qdrant.query_result = SimpleNamespace(points=[point, low_score])
        self.assertEqual(self.m.recuperacion_chunk_con_scores("pregunta"), [point])
        self.assertEqual(self.m.normalize_retrieval_k(1), 5)
        self.assertEqual(self.m.normalize_retrieval_k(80), 80)

        self.m.qdrant.query_points = MagicMock(return_value=SimpleNamespace(points=[point]))
        self.m.recuperacion_chunk_con_scores("pregunta", k=1)
        self.assertEqual(self.m.qdrant.query_points.call_args.kwargs["limit"], 5)

        self.m.qdrant.query_points = MagicMock(return_value=SimpleNamespace(points=[point]))
        self.m.recuperacion_chunk_con_scores("pregunta", k=80)
        self.assertEqual(self.m.qdrant.query_points.call_args.kwargs["limit"], 80)

        self.m.qdrant.query_points = MagicMock(side_effect=RuntimeError("qdrant down"))
        self.assertEqual(self.m.recuperacion_chunk_con_scores("pregunta"), [])

    def test_ask_ollama_success_cancel_and_timeout(self):
        _AsyncClient.created = []
        _AsyncClient.stream_obj = _AsyncStream([
            "",
            '{"response": "Hola ", "done": false}',
            '{"response": "mundo", "done": true}',
            '{"response": "ignorado", "done": true}',
        ])
        with patch.object(self.m.httpx, "AsyncClient", _AsyncClient):
            answer = asyncio.run(self.m.ask_ollama("prompt", model="m"))
        self.assertEqual(answer, "Hola mundo")
        self.assertEqual(_AsyncClient.created[0].stream_kwargs["json"]["model"], "m")

        with self.assertRaises(self.m.QueryCancelledError):
            asyncio.run(self.m.ask_ollama("prompt", should_cancel=lambda: True))

        calls = {"n": 0}

        def cancel_after_first_line():
            calls["n"] += 1
            return calls["n"] > 1

        _AsyncClient.stream_obj = _AsyncStream(['{"response": "x"}'])
        with patch.object(self.m.httpx, "AsyncClient", _AsyncClient):
            with self.assertRaises(self.m.QueryCancelledError):
                asyncio.run(self.m.ask_ollama("prompt", should_cancel=cancel_after_first_line))

        _AsyncClient.stream_obj = _AsyncStream(exc=self.m.httpx.TimeoutException("slow"))
        with patch.object(self.m.httpx, "AsyncClient", _AsyncClient):
            with self.assertRaises(self.m.OllamaTimeoutError) as ctx:
                asyncio.run(self.m.ask_ollama("prompt"))
        self.assertIn("sin limite", str(ctx.exception))

        self.m.settings.OLLAMA_READ_TIMEOUT_SECONDS = 5
        with patch.object(self.m.httpx, "AsyncClient", _AsyncClient):
            with self.assertRaises(self.m.OllamaTimeoutError) as ctx:
                asyncio.run(self.m.ask_ollama("prompt"))
        self.assertIn("5 s", str(ctx.exception))
        self.m.settings.OLLAMA_READ_TIMEOUT_SECONDS = None

    def test_ask_ollama_reports_chat_http_errors(self):
        _AsyncClient.created = []

        _AsyncClient.stream_obj = _FailingAsyncStream(
            self.m,
            status_code=404,
            body=b'{"error":"model not found"}',
        )
        with patch.object(self.m.httpx, "AsyncClient", _AsyncClient):
            with self.assertRaises(self.m.OllamaModelNotFoundError):
                asyncio.run(self.m.ask_ollama("prompt", model="missing"))

        _AsyncClient.stream_obj = _FailingAsyncStream(
            self.m,
            status_code=500,
            body=b"ollama down",
        )
        with patch.object(self.m.httpx, "AsyncClient", _AsyncClient):
            with self.assertRaises(RuntimeError) as ctx:
                asyncio.run(self.m.ask_ollama("prompt", model="broken"))
        self.assertIn("HTTP 500", str(ctx.exception))

        _AsyncClient.stream_obj = _FailingAsyncStream(self.m, status_code=500, body=b"")
        with patch.object(self.m.httpx, "AsyncClient", _AsyncClient):
            with self.assertRaises(self.m.httpx.HTTPStatusError):
                asyncio.run(self.m.ask_ollama("prompt", model="broken"))

    def test_ask_ollama_cancels_while_reading_chat_stream(self):
        _AsyncClient.created = []
        _AsyncClient.stream_obj = _AsyncStream(['{"response": "x"}'])
        cancel_calls = {"n": 0}

        def cancel_on_stream_line():
            cancel_calls["n"] += 1
            return cancel_calls["n"] > 1

        with patch.object(self.m.httpx, "AsyncClient", _AsyncClient), patch.object(
            self.m,
            "ensure_ollama_model_available",
            new_callable=unittest.mock.AsyncMock,
        ):
            with self.assertRaises(self.m.QueryCancelledError):
                asyncio.run(self.m.ask_ollama("prompt", model="m", should_cancel=cancel_on_stream_line))

    def test_ask_rag_llm_applies_generation_timeout(self):
        original_timeout = self.m.settings.OLLAMA_GENERATION_TIMEOUT_SECONDS

        async def slow_ask_ollama(*_args, **_kwargs):
            await asyncio.sleep(10)
            return "late"

        try:
            self.m.settings.OLLAMA_GENERATION_TIMEOUT_SECONDS = 0.01
            with patch.object(self.m, "ask_ollama", side_effect=slow_ask_ollama):
                with self.assertRaises(self.m.OllamaTimeoutError) as ctx:
                    asyncio.run(self.m.ask_rag_llm("pregunta", ["contexto"], model="m"))
            self.assertIn("tiempo máximo de generación", str(ctx.exception))
        finally:
            self.m.settings.OLLAMA_GENERATION_TIMEOUT_SECONDS = original_timeout

    def test_ensure_ollama_model_ready_opens_client_and_delegates(self):
        _AsyncClient.created = []
        with patch.object(self.m.httpx, "AsyncClient", _AsyncClient), patch.object(
            self.m,
            "ensure_ollama_model_available",
            new_callable=unittest.mock.AsyncMock,
        ) as mock_ensure:
            asyncio.run(self.m.ensure_ollama_model_ready("m"))

        self.assertEqual(_AsyncClient.created[0].kwargs["base_url"], self.m.OLLAMA_BASE_URL)
        mock_ensure.assert_awaited_once()

    def test_ensure_ollama_model_available_error_and_download_paths(self):
        class Response:
            def __init__(self, module, status_code=200, text=""):
                self.module = module
                self.status_code = status_code
                self.text = text

            def raise_for_status(self):
                request = self.module.httpx.Request("POST", "http://ollama/api/show")
                response = self.module.httpx.Response(self.status_code, request=request)
                raise self.module.httpx.HTTPStatusError("error", request=request, response=response)

        class Client:
            def __init__(self, module, show_response, stream_obj=None):
                self.module = module
                self.show_response = show_response
                self.stream_obj = stream_obj or _AsyncStream([])

            async def post(self, *_args, **_kwargs):
                return self.show_response

            def stream(self, *_args, **_kwargs):
                return self.stream_obj

        with self.assertRaises(self.m.QueryCancelledError):
            asyncio.run(
                self.m.ensure_ollama_model_available(
                    Client(self.m, Response(self.m)),
                    "m",
                    should_cancel=lambda: True,
                )
            )

        with self.assertRaises(RuntimeError) as ctx:
            asyncio.run(
                self.m.ensure_ollama_model_available(
                    Client(self.m, Response(self.m, status_code=500, text="show failed")),
                    "m",
                )
            )
        self.assertIn("show failed", str(ctx.exception))

        with self.assertRaises(self.m.OllamaModelNotFoundError) as ctx:
            asyncio.run(
                self.m.ensure_ollama_model_available(
                    Client(
                        self.m,
                        Response(self.m, status_code=404),
                        _FailingAsyncStream(self.m, status_code=500, body=b"pull failed"),
                    ),
                    "m",
                )
            )
        self.assertIn("pull failed", str(ctx.exception))

        with self.assertRaises(self.m.OllamaModelNotFoundError) as ctx:
            asyncio.run(
                self.m.ensure_ollama_model_available(
                    Client(
                        self.m,
                        Response(self.m, status_code=404),
                        _AsyncStream(['{"error": "manifest missing"}']),
                    ),
                    "m",
                )
            )
        self.assertIn("manifest missing", str(ctx.exception))

        statuses = []
        asyncio.run(
            self.m.ensure_ollama_model_available(
                Client(
                    self.m,
                    Response(self.m, status_code=404),
                    _AsyncStream([
                        "",
                        '{"status": "pulling", "digest": "abcdef123456", "completed": 1024, "total": 2048}',
                        '{"status": "success", "done": true}',
                    ]),
                ),
                "m",
                on_status=statuses.append,
            )
        )
        self.assertIn("Descargando modelo m", statuses[0])
        self.assertTrue(any("m: success" in item for item in statuses))

        cancel_calls = {"n": 0}

        def cancel_after_download_starts():
            cancel_calls["n"] += 1
            return cancel_calls["n"] > 1

        with self.assertRaises(self.m.QueryCancelledError):
            asyncio.run(
                self.m.ensure_ollama_model_available(
                    Client(self.m, Response(self.m, status_code=404), _AsyncStream(['{"status": "pulling"}'])),
                    "m",
                    should_cancel=cancel_after_download_starts,
                )
            )

    def test_ensure_ollama_model_available_timeout_paths(self):
        class Response:
            status_code = 404
            text = ""

        class Client:
            async def post(self, *_args, **_kwargs):
                return Response()

            def stream(self, *_args, **_kwargs):
                return _AsyncStream(['{"status": "pulling"}'])

        original_total = self.m.settings.OLLAMA_PULL_TIMEOUT_SECONDS
        original_idle = self.m.settings.OLLAMA_PULL_IDLE_TIMEOUT_SECONDS
        try:
            self.m.settings.OLLAMA_PULL_TIMEOUT_SECONDS = 30
            self.m.settings.OLLAMA_PULL_IDLE_TIMEOUT_SECONDS = 0
            monotonic_values = iter([0, 31])
            fake_time = SimpleNamespace(monotonic=lambda: next(monotonic_values))

            with patch.object(self.m, "time", fake_time):
                with self.assertRaises(self.m.OllamaTimeoutError) as ctx:
                    asyncio.run(self.m.ensure_ollama_model_available(Client(), "m"))
            self.assertIn("superó 30", str(ctx.exception))

            async def fake_wait_for(*_args, **_kwargs):
                raise asyncio.TimeoutError()

            self.m.settings.OLLAMA_PULL_TIMEOUT_SECONDS = 0
            self.m.settings.OLLAMA_PULL_IDLE_TIMEOUT_SECONDS = 12
            with patch.object(self.m.asyncio, "wait_for", side_effect=fake_wait_for):
                with self.assertRaises(self.m.OllamaTimeoutError) as ctx:
                    asyncio.run(self.m.ensure_ollama_model_available(Client(), "m"))
            self.assertIn("no avanzó durante 12", str(ctx.exception))
        finally:
            self.m.settings.OLLAMA_PULL_TIMEOUT_SECONDS = original_total
            self.m.settings.OLLAMA_PULL_IDLE_TIMEOUT_SECONDS = original_idle

    def test_obtener_chunk_de_query_and_mejor_chunk_paths(self):
        doc = self.m.VectorBaseDocument(
            content="chunk",
            metadata={"title": "Titulo", "filename": "doc.pdf", "segment_index": 2},
        )
        with patch.object(self.m, "recuperacion_chunk", return_value=[]):
            self.assertIsNone(self.m.obtener_chunk_de_query("pregunta"))
        with patch.object(self.m, "recuperacion_chunk", return_value=[doc]):
            result = self.m.obtener_chunk_de_query("pregunta")
        self.assertEqual(result["filename"], "doc.pdf")

        with self.assertRaises(self.m.QueryCancelledError):
            asyncio.run(self.m.obtener_mejor_chunk(" pregunta ", should_cancel=lambda: True))

        statuses = []
        with patch.object(self.m, "recuperacion_chunk_con_scores", return_value=[]), patch.object(
            self.m,
            "ensure_ollama_model_ready",
            new_callable=unittest.mock.AsyncMock,
        ):
            empty = asyncio.run(self.m.obtener_mejor_chunk(" pregunta ", on_status=statuses.append, numero_expediente="EXP"))
        self.assertEqual(empty["retrieved"], [])
        self.assertEqual(empty["applied_filters"]["numero_expediente"], "EXP")

        point = SimpleNamespace(
            id=uuid4(),
            score=0.75,
            payload={
                "content": "contenido",
                "metadata": {
                    "document_id": 7,
                    "sha256": "sha",
                    "segment_index": 4,
                    "filename": "doc.pdf",
                    "title": "Titulo",
                },
            },
        )
        async def fake_ask_ollama(_prompt, **_kwargs):
            return "respuesta"

        with patch.object(self.m, "recuperacion_chunk_con_scores", return_value=[point]), patch.object(
            self.m,
            "ensure_ollama_model_ready",
            new_callable=unittest.mock.AsyncMock,
        ), patch.object(
            self.m,
            "ask_ollama",
            side_effect=fake_ask_ollama,
        ):
            full = asyncio.run(self.m.obtener_mejor_chunk(" pregunta ", on_status=statuses.append, tipo_documento="tecnico"))
        self.assertEqual(full["answer"], "respuesta")
        self.assertEqual(full["retrieved"][0]["qdrant_point_id"], str(point.id))
        self.assertIn("Generando respuesta del modelo...", statuses)

        cancel_calls = {"n": 0}

        def cancel_in_loop():
            cancel_calls["n"] += 1
            return cancel_calls["n"] > 1

        with patch.object(self.m, "recuperacion_chunk_con_scores", return_value=[point]), patch.object(
            self.m,
            "ensure_ollama_model_ready",
            new_callable=unittest.mock.AsyncMock,
        ):
            with self.assertRaises(self.m.QueryCancelledError):
                asyncio.run(self.m.obtener_mejor_chunk("pregunta", should_cancel=cancel_in_loop))

    def test_index_pdf_error_empty_chunk_mismatch_and_success_paths(self):
        with tempfile.TemporaryDirectory() as tmp:
            pdf_path = Path(tmp) / "doc.pdf"
            pdf_path.write_bytes(b"%PDF-1.4 fake")

            with patch.object(self.m, "PdfReader", side_effect=RuntimeError("read")):
                self.assertEqual(self.m.index_pdf(pdf_path), [])

            empty_reader = SimpleNamespace(metadata={}, pages=[SimpleNamespace(extract_text=lambda: "   ")])
            with patch.object(self.m, "PdfReader", return_value=empty_reader):
                self.assertEqual(self.m.index_pdf(pdf_path), [])

            text_reader = SimpleNamespace(metadata={"/Title": "Titulo"}, pages=[SimpleNamespace(extract_text=lambda: "texto")])
            with patch.object(self.m, "PdfReader", return_value=text_reader), patch.object(
                self.m,
                "chunk_text",
                side_effect=RuntimeError("chunk"),
            ):
                self.assertEqual(self.m.index_pdf(pdf_path), [])

            with patch.object(self.m, "PdfReader", return_value=text_reader), patch.object(self.m, "chunk_text", return_value=[]):
                self.assertEqual(self.m.index_pdf(pdf_path), [])

            with patch.object(self.m, "PdfReader", return_value=text_reader), patch.object(
                self.m,
                "chunk_text",
                return_value=["a", "b"],
            ), patch.object(self.m, "embedding_model", MagicMock(return_value=[[1.0]])):
                self.assertEqual(self.m.index_pdf(pdf_path), [])

            fake_embedding = MagicMock(return_value=[[1.0], [2.0]])
            fake_embedding.model_id = "model"
            fake_embedding.embedding_size = 1
            fake_embedding.max_input_length = 8
            with patch.object(self.m, "PdfReader", return_value=text_reader), patch.object(
                self.m,
                "pdf_sha256",
                return_value="hash",
            ), patch.object(self.m, "chunk_text", return_value=["a", "b"]), patch.object(
                self.m,
                "embedding_model",
                fake_embedding,
            ), patch.object(self.m.VectorBaseDocument, "save_many") as mock_save_many:
                docs = self.m.index_pdf(pdf_path, document_id=5, numero_expediente="EXP", tipo_documento="admin")
            self.assertEqual(len(docs), 2)
            self.assertEqual(docs[0].metadata["document_id"], 5)
            self.assertEqual(docs[0].metadata["segment_index"], 0)
            mock_save_many.assert_called_once()

    def test_index_pliegos_dir_summarizes_missing_same_modified_new_and_errors(self):
        with tempfile.TemporaryDirectory() as tmp:
            missing = Path(tmp) / "missing"
            with self.assertRaises(SystemExit):
                self.m.index_pliegos_dir(missing)

            pliegos = Path(tmp) / "pliegos"
            pliegos.mkdir()
            same = pliegos / "a.pdf"
            modified = pliegos / "b.pdf"
            new = pliegos / "c.pdf"
            error = pliegos / "d.pdf"
            for path in (same, modified, new, error):
                path.write_bytes(path.name.encode())

            def same_hash(filename, _doc_hash):
                return filename == same.name

            def has_filename(filename):
                return filename == modified.name

            def fake_index(path):
                if path.name == error.name:
                    return []
                return [object(), object()]

            with patch.object(self.m.VectorBaseDocument, "_ensure_collection"), patch.object(
                self.m,
                "qdrant_has_same_hash",
                side_effect=same_hash,
            ), patch.object(self.m, "qdrant_has_filename", side_effect=has_filename), patch.object(
                self.m,
                "qdrant_delete_by_filename",
            ) as mock_delete, patch.object(self.m, "index_pdf", side_effect=fake_index):
                summary = self.m.index_pliegos_dir(pliegos)

        self.assertEqual(summary["pdfs_total"], 4)
        self.assertEqual(summary["pdfs_omitidos"], 1)
        self.assertEqual(summary["pdfs_modificados"], 1)
        self.assertEqual(summary["pdfs_nuevos"], 2)
        self.assertEqual(summary["chunks_guardados"], 4)
        self.assertEqual(summary["pdfs_error_o_sin_texto"], 1)
        mock_delete.assert_called_once_with(modified.name)


if __name__ == "__main__":
    unittest.main()
