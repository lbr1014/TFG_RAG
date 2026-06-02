"""
Autora: Lydia Blanco Ruiz
Script con pruebas unitarias avanzadas del módulo evaluacion_RAGAS orientadas a cubrir rutas de ejecución excepcionales, mecanismos de recuperación ante errores y 
ramas de inicialización dependientes del entorno. Las pruebas verifican la carga dinámica de dependencias opcionales, la configuración de modelos y embeddings,
la ejecución de evaluaciones mediante RAGAS, la generación de métricas de similitud coseno, la construcción de diagnósticos y la creación de artefactos de resultados.
"""

import asyncio
import json
import os
import runpy
import sys
import types
import unittest
from importlib.machinery import SourceFileLoader
from importlib.util import module_from_spec, spec_from_loader
from pathlib import Path
from types import SimpleNamespace
from unittest import mock
from uuid import uuid4


def _apply_env_overrides(env: dict[str, str] | None) -> dict[str, str | None]:
    """
    Aplica variables de entorno temporales y devuelve los valores originales para poder restaurarlo posteriormente.
    """
    old_env = {}

    if env:
        for key, value in env.items():
            old_env[key] = os.environ.get(key)
            os.environ[key] = value

    return old_env


def _restore_env(old_env: dict[str, str | None]) -> None:
    """
    Restaura las variables de entorno a su estado original utilizando los valores previamente almacenados.
    """
    for key, old_value in old_env.items():
        if old_value is None:
            os.environ.pop(key, None)
        else:
            os.environ[key] = old_value


def _inject_modules(
    extra_modules: dict[str, types.ModuleType] | None,
) -> dict[str, types.ModuleType | None]:
    """
    Inyecta módulos simulados en sys.modules, almacenando las referencias originales para posibilitar su restauración al finalizar la prueba.
    """
    old_modules = {}

    if extra_modules:
        for name, module in extra_modules.items():
            old_modules[name] = sys.modules.get(name)
            sys.modules[name] = module

    return old_modules


def _restore_modules(
    old_modules: dict[str, types.ModuleType | None],
) -> None:
    """
    Restaura el contenido original de sys.modules, eliminando o reemplazando los módulos simulados inyectados durante la prueba.
    """
    for name, old_module in old_modules.items():
        if old_module is None:
            sys.modules.pop(name, None)
        else:
            sys.modules[name] = old_module


def _create_guarded_import(block_imports: set[str] | None):
    """
    Crea un importador que bloquea módulos específicos para simular dependencias ausentes durante las pruebas.
    """
    import builtins

    real_import = builtins.__import__

    def guarded_import(name, *args, **kwargs):
        """
        Intercepta las operaciones de importación y genera una excepción ImportError para los módulos configurados como bloqueados, delegando
        el resto de importaciones al mecanismo estándar de Python.
        """
        if block_imports and name in block_imports:
            raise ImportError("blocked for test")
        return real_import(name, *args, **kwargs)

    return guarded_import


def _load_eval_module(
    *,
    env: dict[str, str] | None = None,
    extra_modules: dict[str, types.ModuleType] | None = None,
    block_imports: set[str] | None = None,
):
    """
    Carga dinámicamente evaluacion_RAGAS permitiendo modificar temporalmente variables de entorno, sustituir dependencias por implementaciones 
    simuladas y bloquear importaciones para validar distintos escenarios de inicialización.
    """
    repo_root = Path(__file__).resolve().parents[4]
    module_path = (
        repo_root
        / "app"
        / "main"
        / "code"
        / "services"
        / "evaluation"
        / "evaluacion_RAGAS.py"
    )
    module_name = f"evaluacion_RAGAS_test_{uuid4().hex}"

    old_env = _apply_env_overrides(env)
    old_modules = _inject_modules(extra_modules)

    loader = SourceFileLoader(module_name, str(module_path))
    spec = spec_from_loader(loader.name, loader)
    module = module_from_spec(spec)

    sys.modules[loader.name] = module

    try:
        with mock.patch(
            "builtins.__import__",
            side_effect=_create_guarded_import(block_imports),
        ):
            loader.exec_module(module)

        return module

    finally:
        _restore_env(old_env)
        _restore_modules(old_modules)

class _FakeSeries:
    """
    Implementa una versión simplificada de una serie de datos para simular operaciones estadísticas utilizadas durante las pruebas.
    """
    def __init__(self, values):
        """
        Inicializa la serie almacenando los valores proporcionados para su uso posterior en las operaciones estadísticas simuladas.
        """
        self._values = list(values)

    @property
    def empty(self):
        """
        Indica si la serie contiene elementos, reproduciendo el comportamiento de la propiedad equivalente en pandas.
        """
        return len(self._values) == 0

    def dropna(self):
        """
        Devuelve una nueva serie excluyendo los valores nulos presentes en la colección original.
        """
        return _FakeSeries([v for v in self._values if v is not None])

    def mean(self):
        """
        Calcula la media de los valores válidos de la serie. Si no existen elementos no nulos devuelve NaN para reproducir el comportamiento de
        las bibliotecas de análisis de datos.
        """
        vals = [v for v in self._values if v is not None]
        if not vals:
            return float("nan")
        return sum(vals) / len(vals)

    def notna(self):
        """
        Genera una serie booleana que indica qué elementos contienen valores válidos y cuáles son nulos.
        """
        return _FakeSeries([v is not None for v in self._values])

    def sum(self):
        """
        Cuenta el número de elementos evaluados como verdaderos dentro de la serie.
        """
        return sum(1 for v in self._values if v)


class _FakeDF:
    """
    Implementa una estructura simplificada similar a un DataFrame utilizada para probar el procesamiento de resultados sin depender de bibliotecas externas.
    """
    def __init__(self, mapping: dict[str, list]):
        """
        Inicializa el DataFrame simulado a partir de un diccionario que asocia nombres de columnas con sus correspondientes valores.
        """
        self._mapping = {k: list(v) for k, v in mapping.items()}
        self.columns = list(self._mapping.keys())

    def __getitem__(self, key):
        """
        Construye una representación tabular simplificada almacenando las columnas y sus valores asociados, reproduciendo la interfaz mínima
        necesaria para las pruebas.
        """
        return _FakeSeries(self._mapping[key])


class EvaluacionRAGASFullUnitTest(unittest.TestCase):
    def test_import_fallbacks_for_ragas_and_torch_and_invalid_base_url(self):
        """
        Verifica la inicialización del módulo cuando las dependencias RAGAS y Torch no están disponibles y se proporciona una URL de configuración inválida.
        """
        m = _load_eval_module(
            env={"OLLAMA_BASE_URL": "http://example.com:11434"},
            block_imports={"ragas", "ragas.run_config", "torch"},
        )
        self.assertIsNone(m.evaluate)
        self.assertIsNone(m.RunConfig)
        self.assertIsNone(m.torch)
        self.assertEqual(m.OLLAMA_BASE_URL, "")

    def test_import_success_for_ragas_evaluate_and_runconfig(self):
        """
        Comprueba la carga correcta de las dependencias de RAGAS cuando están disponibles en el entorno.
        """
        fake_ragas = types.ModuleType("ragas")
        fake_ragas.__path__ = []
        fake_run_config = types.ModuleType("ragas.run_config")

        class RunConfig:
            """
            Implementación simulada de la clase de configuración de RAGAS utilizada para validar su importación durante la inicialización del módulo.
            """

        def evaluate(*_args, **_kwargs):
            """
            Implementación simulada de la función principal de evaluación de RAGAS. Su ejecución no debe producirse durante esta prueba, ya que únicamente
            se valida el proceso de importación.
            """
            raise AssertionError("not executed in import test")

        fake_ragas.evaluate = evaluate
        fake_run_config.RunConfig = RunConfig
        m = _load_eval_module(extra_modules={"ragas": fake_ragas, "ragas.run_config": fake_run_config})
        self.assertIs(m.evaluate, evaluate)
        self.assertIs(m.RunConfig, RunConfig)

    def test_obtener_mejor_chunk_sync_wraps_async(self):
        """
        Verifica la adaptación de funciones asíncronas a interfaces síncronas utilizadas durante la evaluación
        """
        m = _load_eval_module()

        async def _fake(question):
            """
            Simula una operación asíncrona de recuperación documental devolviendo una respuesta predefinida asociada a la pregunta recibida.
            """
            await asyncio.sleep(0)
            return {"answer": f"A:{question}"}

        with mock.patch.object(m, "obtener_mejor_chunk", _fake):
            self.assertEqual(m.obtener_mejor_chunk_sync("q")["answer"], "A:q")

    def test_is_local_hostname_empty(self):
        """
        Comprueba la validación de nombres de host vacíos o inexistentes.
        """
        m = _load_eval_module()
        self.assertFalse(m._is_local_hostname(None))

    def test_is_nan_exception_branch_and_score_helpers(self):
        """
        Verifica las funciones auxiliares relacionadas con la detección de valores inválidos, normalización y cálculo de puntuaciones.
        """
        m = _load_eval_module()
        self.assertFalse(m.is_nan("nope"))
        self.assertEqual(m.clamp_score(-1.0), 0.0)
        self.assertEqual(m.clamp_score(2.0), 1.0)
        self.assertEqual(m.mean([]), 0.0)

    def test_resolve_embeddings_device_paths(self):
        """
        Comprueba la selección automática del dispositivo de ejecución para embeddings según la disponibilidad de GPU o CPU.
        """
        m = _load_eval_module()
        m.RAGAS_EMBEDDINGS_DEVICE = "auto"

        fake_torch = types.SimpleNamespace(
            cuda=types.SimpleNamespace(is_available=lambda: True),
            backends=types.SimpleNamespace(mps=types.SimpleNamespace(is_available=lambda: False)),
        )
        with mock.patch.object(m, "torch", fake_torch):
            self.assertEqual(m.resolve_embeddings_device(), "cuda")

        m.RAGAS_EMBEDDINGS_DEVICE = "cuda"
        with mock.patch.object(
            m,
            "torch",
            types.SimpleNamespace(cuda=types.SimpleNamespace(is_available=lambda: False)),
        ):
            self.assertEqual(m.resolve_embeddings_device(), "cpu")

    def test_resolve_embeddings_device_requested_and_exception(self):
        """
        Verifica el tratamiento de configuraciones explícitas de dispositivos y errores producidos durante la detección automática.
        """
        m = _load_eval_module()
        m.RAGAS_EMBEDDINGS_DEVICE = "cuda:0"
        with mock.patch.object(m, "torch", None):
            self.assertEqual(m.resolve_embeddings_device(), "cpu")

        m.RAGAS_EMBEDDINGS_DEVICE = "cpu"
        self.assertEqual(m.resolve_embeddings_device(), "cpu")

        m.RAGAS_EMBEDDINGS_DEVICE = "auto"
        
        def _raise_runtime_error():
            """
            Simula un fallo durante la ejecución lanzando una excepción RuntimeError controlada para validar los mecanismos de gestión y propagación de errores.
            """
            raise RuntimeError("x")
        
        bad_torch = types.SimpleNamespace(
            cuda=types.SimpleNamespace(is_available=_raise_runtime_error),
            backends=types.SimpleNamespace(mps=types.SimpleNamespace(is_available=lambda: True)),
        )
        
        with mock.patch.object(m, "torch", bad_torch):
            self.assertEqual(m.resolve_embeddings_device(), "cpu")

    def test_resolve_embeddings_device_mps_auto(self):
        """
        Comprueba la detección automática de dispositivos MPS en sistemas compatibles.
        """
        m = _load_eval_module()
        m.RAGAS_EMBEDDINGS_DEVICE = "auto"
        fake_torch = types.SimpleNamespace(
            cuda=types.SimpleNamespace(is_available=lambda: False),
            backends=types.SimpleNamespace(mps=types.SimpleNamespace(is_available=lambda: True)),
        )
        with mock.patch.object(m, "torch", fake_torch):
            self.assertEqual(m.resolve_embeddings_device(), "mps")

    def test_get_torch_diagnostics_lists_devices(self):
        """
        Verifica la generación de diagnósticos relacionados con dispositivos GPU disponibles.
        """
        m = _load_eval_module()
        fake_torch = types.ModuleType("torch")
        fake_torch.__version__ = "0"
        fake_torch.version = types.SimpleNamespace(cuda="0")
        fake_torch.cuda = types.SimpleNamespace(
            is_available=lambda: True,
            device_count=lambda: 2,
            get_device_name=lambda i: f"GPU{i}",
        )
        with mock.patch.dict(sys.modules, {"torch": fake_torch}):
            diag = m.get_torch_diagnostics()
        self.assertTrue(diag["torch_available"])
        self.assertEqual(diag["cuda_devices"], ["GPU0", "GPU1"])

    def test_get_torch_diagnostics_exception_is_reported(self):
        """
        Comprueba que los errores producidos durante la obtención de diagnósticos son registrados adecuadamente.
        """
        m = _load_eval_module()
        fake_torch = types.ModuleType("torch")
        fake_torch.__version__ = "0"
        fake_torch.version = types.SimpleNamespace(cuda="0")

        def _boom():
            """
            Simula un fallo durante la consulta de información del subsistema CUDA lanzando una excepción controlada.
            """
            raise RuntimeError("boom")

        fake_torch.cuda = types.SimpleNamespace(is_available=lambda: True, device_count=_boom)
        with mock.patch.dict(sys.modules, {"torch": fake_torch}):
            diag = m.get_torch_diagnostics()
        self.assertIn("error", diag)

    def test_wrap_llm_and_embeddings_choose_wrappers(self):
        """
        Verifica la selección automática de envoltorios compatibles entre LangChain y RAGAS para modelos y embeddings.
        """
        fake_ragas = types.ModuleType("ragas")
        fake_ragas.__path__ = []
        fake_llms = types.ModuleType("ragas.llms")

        class LangchainLLMWrapper:
            """
            Implementación simulada del envoltorio recomendado por RAGAS para integrar modelos de lenguaje compatibles con LangChain.
            """
            def __init__(self, llm):
                """
                Inicializa el envoltorio almacenando la referencia al modelo de lenguaje.
                """
                self.llm = llm

        class LangchainLLM:
            """
            Implementación simulada del envoltorio alternativo utilizado cuando el wrapper principal no puede ser instanciado.
            """
            def __init__(self, llm):
                """
                Inicializa el adaptador almacenando la referencia al modelo de lenguaje.
                """
                self.llm = llm

        fake_llms.LangchainLLMWrapper = LangchainLLMWrapper
        fake_llms.LangchainLLM = LangchainLLM

        fake_embeddings = types.ModuleType("ragas.embeddings")

        class LangchainEmbeddingsWrapper:
            """
            Implementación simulada del envoltorio utilizado por RAGAS para adaptar modelos de embeddings compatibles con LangChain.
            """
            def __init__(self, emb):
                """
                Inicializa el envoltorio almacenando la referencia al modelo de embeddings.
                """
                self.emb = emb

        fake_embeddings.LangchainEmbeddingsWrapper = LangchainEmbeddingsWrapper

        m = _load_eval_module()
        with mock.patch.dict(
            sys.modules,
            {"ragas": fake_ragas, "ragas.llms": fake_llms, "ragas.embeddings": fake_embeddings},
        ):
            wrapped = m.wrap_llm_for_ragas(object())
        self.assertIsInstance(wrapped, LangchainLLMWrapper)
        with mock.patch.dict(
            sys.modules,
            {"ragas": fake_ragas, "ragas.llms": fake_llms, "ragas.embeddings": fake_embeddings},
        ):
            wrapped_emb = m.wrap_embeddings_for_ragas(object())
        self.assertIsInstance(wrapped_emb, LangchainEmbeddingsWrapper)

        # Fuerza fallback a LangchainLLM cuando el wrapper falla.
        class BrokenWrapper:
            """
            Implementación simulada de un envoltorio defectuoso utilizada para comprobar los mecanismos de recuperación ante errores de adaptación.
            """
            def __init__(self, _llm):
                """
                Simula un fallo durante la creación del envoltorio lanzando una excepción controlada.
                """
                raise RuntimeError("boom")

        fake_llms2 = types.ModuleType("ragas.llms")
        fake_llms2.LangchainLLMWrapper = BrokenWrapper
        fake_llms2.LangchainLLM = LangchainLLM
        m2 = _load_eval_module()
        with mock.patch.dict(sys.modules, {"ragas": fake_ragas, "ragas.llms": fake_llms2}):
            wrapped2 = m2.wrap_llm_for_ragas("x")
        self.assertIsInstance(wrapped2, LangchainLLM)

    def test_wrap_llm_and_embeddings_return_original_on_failure(self):
        """
        Comprueba los mecanismos de recuperación utilizados cuando la creación de envoltorios compatibles falla.
        """
        m = _load_eval_module()
        original = object()
        fake_ragas = types.ModuleType("ragas")
        fake_ragas.__path__ = []
        fake_llms = types.ModuleType("ragas.llms")

        class LangchainLLM:
            """
            Implementación simulada de un adaptador de modelos de lenguaje que provoca un error durante su inicialización para probar los mecanismos de recuperación.
            """
            def __init__(self, _llm):
                """
                Simula un fallo en la creación del envoltorio lanzando una excepción controlada.
                """
                raise RuntimeError("boom")

        fake_llms.LangchainLLM = LangchainLLM
        with mock.patch.dict(sys.modules, {"ragas": fake_ragas, "ragas.llms": fake_llms}):
            self.assertIs(m.wrap_llm_for_ragas(original), original)

        fake_emb = types.ModuleType("ragas.embeddings")

        class LangchainEmbeddings:
            """
            Implementación simulada de un adaptador de embeddings que provoca un error durante su inicialización para validar el comportamiento de recuperación.
            """
            def __init__(self, _emb):
                """
                Simula un fallo en la creación del envoltorio lanzando una excepción controlada.
                """
                raise RuntimeError("boom")

        fake_emb.LangchainEmbeddings = LangchainEmbeddings
        with mock.patch.dict(sys.modules, {"ragas": fake_ragas, "ragas.embeddings": fake_emb}):
            self.assertIs(m.wrap_embeddings_for_ragas(original), original)

    def test_resolve_ragas_metrics_builds_aliases_and_optional_answer_correctness(self):
        """
        Verifica la construcción dinámica de métricas RAGAS y la activación opcional de métricas dependientes de respuestas de referencia.
        """
        fake_ragas = types.ModuleType("ragas")
        fake_ragas.__path__ = []
        fake_metrics = types.ModuleType("ragas.metrics")
        for name in [
            "faithfulness",
            "answer_relevancy",
            "context_precision",
            "context_recall",
            "context_relevancy",
            "answer_correctness",
        ]:
            setattr(fake_metrics, name, SimpleNamespace(name=name))

        m = _load_eval_module()
        with mock.patch.dict(sys.modules, {"ragas": fake_ragas, "ragas.metrics": fake_metrics}
        ), mock.patch.object(m, "selected_metric_names", return_value=m.metric_names()):
            metrics, aliases = m.resolve_ragas_metrics([{"ground_truth": "GT"}])
        self.assertTrue(metrics)
        self.assertIn("answer_correctness", aliases)

        with mock.patch.dict(sys.modules, {"ragas": fake_ragas, "ragas.metrics": fake_metrics}
        ), mock.patch.object(m, "selected_metric_names", return_value=["answer_correctness"]):
            metrics2, aliases2 = m.resolve_ragas_metrics([{"ground_truth": ""}])
        self.assertFalse(metrics2)
        self.assertFalse(aliases2)

    def test_build_ragas_rows_filters_and_limits_contexts(self):
        """
        Comprueba la generación de registros de evaluación filtrando preguntas inválidas y limitando el número de contextos utilizados.
        """
        m = _load_eval_module()
        questions = [
            {"question": "  ", "ground_truth": "GT"},
            {"question": "Q", "evidence": "EV"},
        ]
        rag_out = {
            "answer": "A",
            "retrieved": [
                {"chunk": "c1"},
                {"chunk": "c2"},
                {"chunk": ""},
                {"chunk": "c3"},
            ],
        }
        with mock.patch.object(m, "obtener_mejor_chunk_sync", return_value=rag_out):
            rows = m.build_ragas_rows(questions, k_contexts=2)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["contexts"], ["c1", "c2"])
        self.assertEqual(rows[0]["reference"], "EV")

    def test_coseno_context_recall_without_ground_truth_uses_evidence(self):
        """
        Verifica el cálculo de métricas de recuperación cuando no existe respuesta de referencia pero sí evidencia asociada.
        """
        m = _load_eval_module()

        class Emb:
            """
            Implementación simulada de un modelo de embeddings utilizada para generar vectores deterministas durante el cálculo de métricas de similitud.
            """
            def embed_documents(self, texts):
                """
                Devuelve embeddings fijos para los textos recibidos, permitiendo controlar el resultado de las comparaciones durante la prueba.
                """
                return [[1.0, 0.0] for _ in texts]

        score = m._coseno_context_recall(
            embeddings=Emb(),
            joined_context="ctx",
            ground_truth="",
            ground_truth_vec=[0.0, 1.0],
            evidence_vec=[1.0, 0.0],
        )
        self.assertEqual(score, 1.0)

    def test_ragas_empty_result_structure(self):
        """
        Comprueba la estructura generada para representar resultados vacíos de evaluación.
        """
        m = _load_eval_module()
        summary, rows, diag = m._ragas_empty_result({"m": "m_raw"})
        self.assertEqual(summary, {})
        self.assertEqual(rows, [])
        self.assertIn("issues", diag)

    def test_ragas_evaluate_with_timeout_fallback_paths(self):
        """
        Verifica los mecanismos de recuperación utilizados cuando una evaluación supera el tiempo máximo permitido.
        """
        m = _load_eval_module()
        metric_ok = SimpleNamespace(name="faithfulness")
        metric_ac = SimpleNamespace(name="answer_correctness")
        aliases = {"answer_correctness": "answer_correctness"}
        diagnostics = {"issues": []}

        with mock.patch.object(m, "_ragas_evaluate_dataset", return_value="DF"):
            res, active = m._ragas_evaluate_with_timeout_fallback(
                dataset_local=object(),
                metrics_local=[metric_ok],
                aliases_local={},
                ragas_llm_local=object(),
                ragas_embeddings_local=object(),
                run_config_local=object(),
                diagnostics_local=diagnostics,
            )
        self.assertEqual(res, "DF")
        self.assertEqual(active, {})

        def _side_effect(*_a, **_k):
            """
            Simula una evaluación que siempre excede el tiempo máximo permitido, provocando una excepción TimeoutError.
            """
            raise TimeoutError()

        with mock.patch.object(m, "_ragas_evaluate_dataset", side_effect=[TimeoutError(), "DF2"]):
            res2, active2 = m._ragas_evaluate_with_timeout_fallback(
                dataset_local=object(),
                metrics_local=[metric_ok, metric_ac],
                aliases_local=dict(aliases),
                ragas_llm_local=object(),
                ragas_embeddings_local=object(),
                run_config_local=object(),
                diagnostics_local=diagnostics,
            )
        self.assertEqual(res2, "DF2")
        self.assertNotIn("answer_correctness", active2)

        with mock.patch.object(m, "_ragas_evaluate_dataset", side_effect=_side_effect
        ), self.assertRaises(TimeoutError):
                m._ragas_evaluate_with_timeout_fallback(
                    dataset_local=object(),
                    metrics_local=[metric_ok],
                    aliases_local={},
                    ragas_llm_local=object(),
                    ragas_embeddings_local=object(),
                    run_config_local=object(),
                    diagnostics_local=diagnostics,
                )

    def test_ragas_evaluate_dataset_calls_evaluate(self):
        """
        Comprueba la invocación correcta del motor de evaluación RAGAS con la configuración especificada.
        """
        m = _load_eval_module()

        def evaluate(dataset, metrics, llm, embeddings, run_config, raise_exceptions):
            """
            Implementación simulada del motor de evaluación de RAGAS utilizada para comprobar que los parámetros son transmitidos correctamente durante la
            ejecución de la evaluación.
            """
            return {
                "dataset": dataset,
                "metrics": metrics,
                "llm": llm,
                "embeddings": embeddings,
                "run_config": run_config,
                "raise_exceptions": raise_exceptions,
            }

        with mock.patch.object(m, "evaluate", evaluate), mock.patch.object(
            m, "RAGAS_RAISE_EXCEPTIONS", False
        ):
            out = m._ragas_evaluate_dataset(
                dataset_local="D",
                active_metrics_local=["M"],
                ragas_llm_local="L",
                ragas_embeddings_local="E",
                run_config_local="C",
            )
        self.assertEqual(out["dataset"], "D")

    def test_ragas_summarize_and_normalize_rows(self):
        """
        Verifica la agregación de métricas y la normalización de resultados obtenidos tras la evaluación.
        """
        m = _load_eval_module()
        df = _FakeDF({"faithfulness_raw": [0.5, 1.0]})
        aliases = {"faithfulness": "faithfulness_raw"}
        summary = m._ragas_summarize(df, aliases)
        self.assertEqual(summary["faithfulness"], 0.75)
        rows = m._ragas_normalize_rows([{"question": "q", "faithfulness_raw": 0.25}], aliases)
        self.assertEqual(rows[0]["faithfulness"], 0.25)

    def test_ragas_build_and_add_column_diagnostics(self):
        """
        Comprueba la generación de diagnósticos asociados a las columnas de resultados producidas por RAGAS.
        """
        m = _load_eval_module()
        aliases = {"faithfulness": "faithfulness_raw"}
        diag = m._ragas_build_diagnostics(aliases)
        self.assertEqual(diag["resolved_metrics"], ["faithfulness_raw"])
        df = _FakeDF({"faithfulness_raw": [None, 1.0]})
        m._ragas_add_column_diagnostics(df, aliases, diag)
        self.assertIn("dataframe_columns", diag)

    def test_run_ragas_raises_when_dependencies_missing(self):
        """
        Verifica que la evaluación falla correctamente cuando faltan dependencias esenciales para ejecutar RAGAS.
        """
        m = _load_eval_module(block_imports={"ragas", "datasets"})
        with mock.patch.object(m, "resolve_ragas_metrics", return_value=([object()], {"m": "m"})
        ), self.assertRaises(RuntimeError):
                m.run_ragas([{"question": "q"}], embeddings=object(), llm=object())

    def test_main_chat_and_llm_branches(self):
        """
        Comprueba las distintas ramas de inicialización de modelos de lenguaje utilizadas por el punto de entrada principal del módulo.
        """
        tmp = Path(os.getenv("TEMP", "."))
        questions = tmp / f"q_{uuid4().hex}.json"
        questions.write_text(json.dumps([{"question": "q"}]), encoding="utf-8")

        fake_emb_mod = types.ModuleType("langchain_community.embeddings")

        class HuggingFaceEmbeddings:
            """
            Implementación simulada de un modelo de embeddings utilizada para proporcionar vectores deterministas durante la ejecución de la prueba.
            """
            def __init__(self, *args, **kwargs):
                """
                Inicializa el modelo de embeddings simulado.
                """

            def embed_documents(self, texts):
                """
                Genera embeddings fijos para los textos recibidos.
                """
                return [[1.0, 0.0, 0.0] for _ in texts]

        fake_emb_mod.HuggingFaceEmbeddings = HuggingFaceEmbeddings

        fake_chat_mod = types.ModuleType("langchain_community.chat_models")

        class ChatOllama:
            """
            Implementación simulada del modelo conversacional de Ollama utilizada para validar los mecanismos de compatibilidad durante la inicialización.
            """
            def __init__(self, *args, **kwargs):
                """
                Simula una incompatibilidad con el parámetro `client_kwargs`, forzando la ejecución de la ruta alternativa de inicialización.
                """
                if "client_kwargs" in kwargs:
                    raise TypeError("no client_kwargs")

        fake_chat_mod.ChatOllama = ChatOllama

        fake_llm_mod = types.ModuleType("langchain_community.llms")

        class Ollama:
            """
            Implementación simulada del modelo LLM de Ollama utilizada para probar mecanismos de recuperación ante diferencias entre versiones de la API.
            """
            def __init__(self, *args, **kwargs):
                """
                Simula una incompatibilidad con el parámetro `base_url`, provocando la ejecución de rutas alternativas de inicialización.
                """
                if "base_url" in kwargs:
                    raise TypeError("boom")

        fake_llm_mod.Ollama = Ollama

        m = _load_eval_module(
            env={
                "RAGAS_QUESTIONS_PATH": str(questions),
                "RAGAS_USE_CHAT": "1",
                "RAGAS_RESULTS_PATH": str(tmp / f"out_{uuid4().hex}.json"),
                "RAGAS_ROW_RESULTS_PATH": str(tmp / f"rows_{uuid4().hex}.json"),
                "CONFIGURACION_PATH": str(tmp / f"cfg_{uuid4().hex}.json"),
            },
            extra_modules={
                "langchain_community.embeddings": fake_emb_mod,
                "langchain_community.chat_models": fake_chat_mod,
                "langchain_community.llms": fake_llm_mod,
            },
        )
        with mock.patch.object(
            m,
            "build_ragas_rows",
            return_value=[{"question": "q", "answer": "a", "contexts": []}],
        ), mock.patch.object(m, "run_ragas", side_effect=RuntimeError("boom")):
            # No debe explotar por el builder de llm; cae en el handler de excepción de run_ragas.
            m.main()

    def test_main_raises_when_no_rows_or_missing_embeddings_or_chat_impl(self):
        """
        Verifica la gestión de errores cuando faltan datos de evaluación, embeddings o implementaciones de modelos necesarias.
        """
        m = _load_eval_module()
        with mock.patch.object(m, "load_questions", return_value=[{"question": "q"}]), mock.patch.object(
            m, "build_ragas_rows", return_value=[]
        ), self.assertRaises(SystemExit):
            m.main()

        m2 = _load_eval_module()
        with mock.patch.object(m2, "HuggingFaceEmbeddings", None), mock.patch.object(
            m2, "load_questions", return_value=[{"question": "q"}]
        ), mock.patch.object(m2, "build_ragas_rows", return_value=[{"question": "q"}]
        ), self.assertRaises(RuntimeError):
           m2.main()

        tmp = Path(os.getenv("TEMP", "."))
        qfile = tmp / f"q_{uuid4().hex}.json"
        qfile.write_text(json.dumps([{"question": "q"}]), encoding="utf-8")
        m3 = _load_eval_module(env={"RAGAS_QUESTIONS_PATH": str(qfile), "RAGAS_USE_CHAT": "1"})
        with mock.patch.object(m3, "CommunityChatOllama", None), mock.patch.object(
            m3, "OllamaChatOllama", None
        ), mock.patch.object(m3, "build_ragas_rows", return_value=[{"question": "q", "answer": "a", "contexts": []}]), mock.patch.object(
            m3, "compute_coseno_metrics", return_value=[{"question": "q", "answer": "a", "contexts": []}]
        ), mock.patch.object(m3, "HuggingFaceEmbeddings", lambda *a, **k: object()
        ), self.assertRaises(RuntimeError):
            m3.main()

    def test_main_non_chat_raises_when_llm_missing(self):
        """
        Comprueba el comportamiento del sistema cuando se solicita una evaluación sin disponer de un modelo de lenguaje válido.
        """
        m = _load_eval_module()
        with mock.patch.object(m, "RAGAS_USE_CHAT", False), mock.patch.object(m, "OllamaLLM", None), mock.patch.object(
            m, "load_questions", return_value=[{"question": "q"}]
        ), mock.patch.object(
            m, "build_ragas_rows", return_value=[{"question": "q", "answer": "a", "contexts": []}]
        ), mock.patch.object(m, "HuggingFaceEmbeddings", lambda *a, **k: object()), mock.patch.object(
            m, "compute_coseno_metrics", return_value=[{"question": "q", "answer": "a", "contexts": []}]
        ), self.assertRaises(RuntimeError):
            m.main()

    def test_main_non_chat_instantiates_llm(self):
        """
        Verifica la creación de modelos de lenguaje en los modos de evaluación que no utilizan interfaces de chat.
        """
        tmp = Path(os.getenv("TEMP", "."))
        questions = tmp / f"q_{uuid4().hex}.json"
        questions.write_text(json.dumps([{"question": "q"}]), encoding="utf-8")
        out = tmp / f"out_{uuid4().hex}.json"
        rows = tmp / f"rows_{uuid4().hex}.json"
        cfg = tmp / f"cfg_{uuid4().hex}.json"

        fake_llm_mod = types.ModuleType("langchain_community.llms")

        class Ollama:
            """
            Implementación simulada de un modelo de lenguaje Ollama utilizada para validar las distintas rutas de inicialización del módulo de evaluación.
            """
            _calls = 0

            def __init__(self, *args, **kwargs):
                """
                Simula un fallo durante el primer intento de inicialización y permite que los intentos posteriores se completen correctamente para verificar
                los mecanismos de recuperación.
                """
                type(self)._calls += 1
                if type(self)._calls == 1:
                    raise TypeError("first call fails")
                self.kwargs = kwargs

        fake_llm_mod.Ollama = Ollama

        m = _load_eval_module(
            env={
                "RAGAS_QUESTIONS_PATH": str(questions),
                "RAGAS_USE_CHAT": "0",
                "RAGAS_RESULTS_PATH": str(out),
                "RAGAS_ROW_RESULTS_PATH": str(rows),
                "CONFIGURACION_PATH": str(cfg),
            },
            extra_modules={"langchain_community.llms": fake_llm_mod},
        )
        with mock.patch.object(
            m, "build_ragas_rows", return_value=[{"question": "q", "answer": "a", "contexts": []}]
        ), mock.patch.object(
            m, "HuggingFaceEmbeddings", lambda *a, **k: object()
        ), mock.patch.object(
            m, "compute_coseno_metrics", return_value=[{"question": "q", "answer": "a", "contexts": []}]
        ), mock.patch.object(m, "run_ragas", side_effect=RuntimeError("boom")):
            m.main()

    def test_run_ragas_success_path_and_merge_metrics_source(self):
        """
        Comprueba la ejecución completa de una evaluación satisfactoria y la combinación de métricas procedentes de distintas fuentes de evaluación.
        """
        m = _load_eval_module()

        class FakeDataset:
            """
            Implementación simulada del conjunto de datos utilizado por RAGAS para ejecutar las métricas de evaluación.
            """
            @classmethod
            def from_list(cls, rows):
                """
                Simula la construcción de un dataset a partir de una colección de registros.
                """
                return ("DATASET", rows)

        class FakeRunConfig:
            """
            Implementación simulada de la configuración de ejecución utilizada por RAGAS durante la evaluación.
            """
            def __init__(self, **_kwargs):
                """
                Inicializa una configuración de ejecución simulada.
                """

        class FakeDF:
            """
            Implementación simplificada de un DataFrame utilizada para representar los resultados generados por RAGAS.
            """
            def __init__(self):
                """
                Inicializa la estructura de resultados simulada con las columnas necesarias para la prueba.
                """
                self.columns = ["faithfulness_raw"]

            def to_dict(self, orient="records"):
                """
                Devuelve los resultados de evaluación en formato de registros.
                """
                self._orient = orient
                return [{"question": "q", "faithfulness_raw": 0.5}]

            def __getitem__(self, key):
                """
                Recupera una columna simulada para permitir el cálculo de estadísticas agregadas.
                """
                return _FakeSeries([0.5])

        class FakeResult:
            """
            Representa el objeto de resultados devuelto por una evaluación RAGAS simulada.
            """
            def to_pandas(self):
                """
                Convierte los resultados simulados a una estructura compatible con DataFrame.
                """
                return FakeDF()

        with mock.patch.object(m, "Dataset", FakeDataset), mock.patch.object(
            m, "RunConfig", FakeRunConfig
        ), mock.patch.object(m, "evaluate", object()), mock.patch.object(
            m, "resolve_ragas_metrics", return_value=([SimpleNamespace(name="faithfulness")], {"faithfulness": "faithfulness_raw"})
        ), mock.patch.object(m, "_ragas_evaluate_with_timeout_fallback", return_value=(FakeResult(), {"faithfulness": "faithfulness_raw"})):
            summary, ragas_rows, diag = m.run_ragas([{"question": "q"}], embeddings=object(), llm=object())
        self.assertEqual(summary["faithfulness"], 0.5)
        self.assertEqual(ragas_rows[0]["faithfulness"], 0.5)
        self.assertIn("resolved_metrics", diag)

        _, final_rows = m.merge_metrics(
            rows=[
                {
                    "question": "q",
                    "answer": "a",
                    "contexts": [],
                    "ground_truth": "",
                    "reference": "",
                    "evidence": "",
                    "coseno_metrics": {"faithfulness": None},
                }
            ],
            ragas_rows=[{"question": "q", "faithfulness": 0.2}],
        )
        self.assertEqual(final_rows[0]["score_source"]["faithfulness"], "ragas")

    def test_run_ragas_returns_empty_when_no_metrics(self):
        """
        Verifica la generación de resultados vacíos cuando no existen métricas configuradas para la evaluación.
        """
        m = _load_eval_module()
        with mock.patch.object(m, "resolve_ragas_metrics", return_value=([], {})):
            summary, rows, diag = m.run_ragas([{"question": "q"}], embeddings=object(), llm=object())
        self.assertEqual(summary, {})
        self.assertEqual(rows, [])
        self.assertIn("issues", diag)

    def test_ragas_add_column_diagnostics_missing_and_all_null(self):
        """
        Comprueba la generación de advertencias y diagnósticos cuando determinadas métricas no aparecen o contienen únicamente valores nulos.
        """
        m = _load_eval_module()
        diag = {"non_null_counts": {}, "issues": []}
        df = _FakeDF({"other": [1]})
        m._ragas_add_column_diagnostics(df, {"m": "missing"}, diag)
        self.assertIn("no aparecio", diag["issues"][0])

        diag2 = {"non_null_counts": {}, "issues": []}
        df2 = _FakeDF({"m_raw": [None, None]})
        m._ragas_add_column_diagnostics(df2, {"m": "m_raw"}, diag2)
        self.assertTrue(any("todos sus valores" in msg for msg in diag2["issues"]))
        self.assertTrue(any("no produjo ningun valor" in msg for msg in diag2["issues"]))

    def test_main_guard_writes_artifacts_on_failure(self):
        """
        Verifica que el punto de entrada principal genera correctamente los artefactos mínimos de salida incluso cuando la ejecución termina con error.
        """
        repo_root = Path(__file__).resolve().parents[4]
        module_path = repo_root / "app" / "main" / "code" / "services" / "evaluation" / "evaluacion_RAGAS.py"
        tmp = Path(os.getenv("TEMP", "."))
        out = tmp / f"guard_out_{uuid4().hex}.json"
        rows = tmp / f"guard_rows_{uuid4().hex}.json"
        cfg = tmp / f"guard_cfg_{uuid4().hex}.json"
        missing_questions = tmp / f"missing_{uuid4().hex}.json"
        with mock.patch.dict(
            os.environ,
            {
                "RAGAS_QUESTIONS_PATH": str(missing_questions),
                "RAGAS_RESULTS_PATH": str(out),
                "RAGAS_ROW_RESULTS_PATH": str(rows),
                "CONFIGURACION_PATH": str(cfg),
            },
        ), self.assertRaises(FileNotFoundError):
            runpy.run_path(str(module_path), run_name="__main__")
        self.assertTrue(out.exists())
        self.assertTrue(rows.exists())
        self.assertTrue(cfg.exists())
