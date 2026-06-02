"""
Autora: Lydia Blanco Ruiz
Script con pruebas unitarias complementarias del módulo PrototipoRAG, centradas en mecanismos de recuperación ante errores,
validación de embeddings, gestión del cliente Qdrant y tratamiento de escenarios excepcionales durante la recuperación de información. 
Las pruebas verifican el comportamiento del sistema ante errores de memoria GPU, dependencias opcionales ausentes, 
filtros de búsqueda complejos y respuestas con baja similitud. Su objetivo es reforzar la robustez del motor RAG garantizando
un funcionamiento estable incluso en situaciones poco frecuentes o anómalas.
"""

import builtins
import sys
import unittest
from importlib.machinery import SourceFileLoader
from importlib.util import module_from_spec, spec_from_loader
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch
from uuid import uuid4


def _import_real_prototipo():
    """
    Carga dinámicamente una instancia independiente del módulo PrototipoRAG para realizar pruebas aisladas sobre su implementación real.
    """
    repo_root = Path(__file__).resolve().parents[4]
    module_path = repo_root / "app" / "main" / "code" / "services" / "rag" / "PrototipoRAG.py"
    module_name = f"PrototipoRAG_real_more_{uuid4().hex}"
    loader = SourceFileLoader(module_name, str(module_path))
    spec = spec_from_loader(loader.name, loader)
    module = module_from_spec(spec)
    sys.modules[loader.name] = module
    loader.exec_module(module)
    return module


class PrototipoRAGMoreCoverageUnitTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        """
        Inicializa una única instancia del módulo prototipo_rag para ser reutilizada por todas las pruebas de la clase, evitando cargas repetidas y reduciendo el tiempo de 
        ejecución de los tests.
        """
        cls.m = _import_real_prototipo()

    def test_embedding_singleton_properties_and_cuda_oom_fallback(self):
        """
        Verifica las propiedades del modelo de embeddings y el mecanismo de recuperación automática ante errores de memoria GPU, 
        incluyendo la migración de la ejecución a CPU.
        """
        m = self.m

        class FakeModel:
            """
            Implementación simulada de un modelo de embeddings utilizada para probar el mecanismo de recuperación ante errores de memoria CUDA.
            La primera llamada a encode lanza una excepción de falta de memoria en GPU, mientras que las llmadas posteriores devuelven un embedding válido, 
            permitiendo verificar el cambio automático de ejecución a CPU.
            """
            def __init__(self):
                """
                Inicializa un modelo simulado con valores fijos para la longitud máxima secuencia, tokenizer y contador de llamadas.
                """
                self.max_seq_length = 123
                self.tokenizer = object()
                self._device = None
                self.calls = 0

            def to(self, device):
                """
                Simula el traslado del modelo al dispositivo especificado.
                """
                self._device = device

            def get_sentence_embedding_dimension(self):
                """
                Devuelve una dimensión de embedding fija utilizada durante la prueba.
                """
                return 7

            def encode(self, _text, **_kwargs):
                """
                Simula la generación de embeddings. La primera invocación provoca un error de memoria CUDA y las siguientes devuelven un embedding válido,
                permitiendo comprobar la lógica de recuperación ante fallos.
                """
                self.calls += 1
                if self.calls == 1:
                    raise RuntimeError("CUDA out of memory")
                return [0.1, 0.2, 0.3]

        singleton = m.EmbeddingModelSingleton.__new__(m.EmbeddingModelSingleton)
        singleton._initialized = True
        singleton._model_id = "fake"
        singleton._device = "cuda"
        singleton._model = FakeModel()

        with patch.object(singleton, "_is_cuda_out_of_memory", return_value=True), patch.object(
            singleton, "_clear_cuda_cache"
        ) as mock_clear:
            emb = singleton("hola", to_list=True)

        self.assertEqual(singleton._device, "cpu")
        self.assertEqual(singleton.embedding_size, 7)
        self.assertEqual(singleton.max_input_length, 123)
        self.assertIs(singleton.tokenizer, singleton._model.tokenizer)
        self.assertEqual(emb, [0.1, 0.2, 0.3])
        mock_clear.assert_called()

        lazy = m.LazyEmbeddingModel()
        with patch.object(lazy, "_instance", singleton):
            self.assertEqual(lazy("hola", to_list=True), [0.1, 0.2, 0.3])

    def test_close_qdrant_closes_client(self):
        """
        Comprueba el cierre correcto del cliente Qdrant y la liberación de los recursos asociados.
        """
        m = self.m
        # _close_qdrant deja el global a None, se trabaja sobre una instancia temporal.
        tmp_qdrant = m.LazyQdrantClient()
        client = SimpleNamespace(close=MagicMock())
        tmp_qdrant._client = client
        with patch.object(m, "qdrant", tmp_qdrant):
            m._close_qdrant()
        client.close.assert_called_once()
        self.assertIsNone(tmp_qdrant._client)

    def test_qdrant_exists_by_metadata_scroll_paths(self):
        """
        Verifica la detección de documentos almacenados en Qdrant mediante búsquedas basadas en metadatos.
        """
        m = self.m
        tmp_qdrant = m.LazyQdrantClient()
        tmp_qdrant._client = SimpleNamespace(scroll=MagicMock(return_value=([object()], None)))
        with patch.object(m, "qdrant", tmp_qdrant), patch.object(
            m, "build_qdrant_metadata_filter", return_value=object()
        ), patch.object(m.VectorBaseDocument, "get_collection_name", return_value="c"):
            self.assertTrue(m.qdrant_exists_by_metadata(filename="a.pdf"))

        tmp_qdrant2 = m.LazyQdrantClient()
        tmp_qdrant2._client = SimpleNamespace(scroll=MagicMock(return_value=([], None)))
        with patch.object(m, "qdrant", tmp_qdrant2), patch.object(
            m, "build_qdrant_metadata_filter", return_value=object()
        ), patch.object(m.VectorBaseDocument, "get_collection_name", return_value="c"):
            self.assertFalse(m.qdrant_exists_by_metadata(filename="a.pdf"))

    def test_normalize_tipo_documento_handles_unicodedata_import_error(self):
        """
        Comprueba la normalización de tipos documentales cuando la biblioteca encargada del tratamiento Unicode no está disponible.
        """
        m = self.m
        real_import = builtins.__import__

        def guard(name, *args, **kwargs):
            """
            Simula un fallo en la importación del módulo unicodedata lanzando una excepción ImportError. Para el resto de módulos delega el proceso de
            importación al mecanismo estándar de Python.
            """
            if name == "unicodedata":
                raise ImportError("blocked")
            return real_import(name, *args, **kwargs)

        with patch("builtins.__import__", side_effect=guard):
            self.assertEqual(m._normalize_tipo_documento("  Técnico  "), "técnico")
            self.assertEqual(m._normalize_tipo_documento("Administración"), "administrativo")

    def test_log_qdrant_query_filter_unserializable_dump(self):
        """
        Verifica el registro de filtros de búsqueda utilizados en Qdrant cuando estos contienen estructuras difíciles de serializar.
        """
        m = self.m

        class BadFilter:
            def model_dump(self):
                raise TypeError("boom")

        with patch.object(m.logger, "info") as mock_info:
            m._log_qdrant_query_filter(BadFilter(), numero_expediente="EXP", tipo_documento="tecnico")
        mock_info.assert_called_once()

    def test_filter_points_by_similarity_fallback_when_all_below_threshold(self):
        """
        Comprueba el mecanismo de recuperación utilizado cuando todos los resultados recuperados presentan una similitud inferior al umbral establecido.
        """
        m = self.m
        points = [SimpleNamespace(score=0.1), SimpleNamespace(score=0.2)]
        with patch.object(m.logger, "info") as mock_info:
            out = m._filter_points_by_similarity(points, min_similarity=0.9, k=1)
        self.assertEqual(out, points)
        mock_info.assert_called_once()

    def test_qdrant_query_points_with_tipo_fallback(self):
        """
        Verifica la estrategia de recuperación alternativa que elimina el filtro de tipo documental cuando una búsqueda inicial no devuelve resultados relevantes.
        """
        m = self.m
        first = SimpleNamespace(points=[])
        second = SimpleNamespace(points=[SimpleNamespace(id="1", score=0.5, payload={"content": "c", "metadata": {}})])
        tmp_qdrant = m.LazyQdrantClient()
        tmp_qdrant._client = SimpleNamespace(query_points=MagicMock(side_effect=[first, second]))
        with patch.object(m, "qdrant", tmp_qdrant), patch.object(m.VectorBaseDocument, "_ensure_collection"):
            out = m._qdrant_query_points_with_optional_tipo_fallback(
                query_vector=[0.0],
                k=3,
                query_filter=object(),
                numero_expediente="EXP",
                tipo_documento="tecnico",
            )
        self.assertEqual(len(out), 1)
