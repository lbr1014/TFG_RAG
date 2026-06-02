"""
Autora: Lydia Blanco Ruiz
Script con pruebas unitarias adicionales para evaluacion_RAGAS, enfocadas en cubrir retas menos frecuentes de la evaluación. Relacionadas con el cálculo de similitudes, 
la generación de embeddings y la evaluación automática mediante RAGAS. 
Las pruebas verifican el tratamiento de vectores degenerados, la normalización de entradas vacías, la selección del dispositivo de ejecución para embeddings y los mecanismos de 
recuperación utilizados cuando determinadas métricas de RAGAS provocan errores o tiempos de espera.
"""

import importlib
from types import SimpleNamespace
from unittest.mock import patch

from app.test.support import BaseAppTestCase


class EvaluacionRAGASMoreUnitTest(BaseAppTestCase):
    def _module(self):
        """
        Carga dinámicamente el módulo evaluacion_RAGAS, forzando su recarga para garantizar que cada prueba se ejecuta sobre una instancia limpia del sistema de evaluación.
        """
        from app.main.code.services.evaluation import evaluacion_RAGAS

        return importlib.reload(evaluacion_RAGAS)

    def test_cosine_similarity_handles_zero_norm(self):
        """
        Verifica que el cálculo de similitud coseno gestiona correctamente vectores con norma nula evitando errores matemáticos y devolviendo una similitud válida.
        """
        m = self._module()
        self.assertEqual(m.cosine_similarity([0.0, 0.0], [1.0, 2.0]), 0.0)
        self.assertEqual(m.cosine_similarity([1.0, 2.0], [0.0, 0.0]), 0.0)

    def test_batch_embeddings_normalizes_empty_texts(self):
        """
        Comprueba que los textos vacíos o nulos se normalizan adecuadamente antes de generar embeddings, garantizando la estabilidad del proceso de vectorización.
        """
        m = self._module()

        class FakeEmb:
            """
            Implementación simulada de un generador de embeddings utilizada para inspeccionar los textos recibidos por el proceso de vectorización.
            """
            def embed_documents(self, texts):
                """
                Simula la generación de embeddings almacenando previamente los textos procesados para su posterior validación durante la prueba.
                """
                self.texts = texts
                return [[1.0, 0.0, 0.0] for _ in texts]

        emb = FakeEmb()
        m.batch_embeddings(emb, ["", None, "hola"])
        self.assertEqual(emb.texts[0], " ")
        self.assertEqual(emb.texts[1], " ")
        self.assertEqual(emb.texts[2], "hola")

    def test_resolve_embeddings_device_respects_requested_cuda_without_torch(self):
        """
        Verifica la selección del dispositivo de ejecución para embeddings cuando se solicita CUDA pero la biblioteca necesaria para acceder a GPU no está disponible.
        """
        m = self._module()
        with patch.object(m, "RAGAS_EMBEDDINGS_DEVICE", "cuda"), patch.object(m, "torch", None):
            self.assertEqual(m.resolve_embeddings_device(), "cpu")

    def test_ragas_timeout_fallback_removes_answer_correctness_metric(self):
        """
        Comprueba el mecanismo de recuperación utilizado cuando una evaluación RAGAS supera el tiempo límite permitido, eliminando métricas problemáticas y
        reintentando la evaluación con una configuración reducida
        """
        m = self._module()

        metric_ok = SimpleNamespace(name="faithfulness")
        metric_drop = SimpleNamespace(name="answer_correctness")
        metrics = [metric_ok, metric_drop]
        aliases = {"answer_correctness": "answer_correctness"}
        diagnostics = {"issues": []}

        with patch.object(m, "_ragas_evaluate_dataset", side_effect=[TimeoutError(), "RESULT"]):
            result, active_aliases = m._ragas_evaluate_with_timeout_fallback(
                dataset_local=object(),
                metrics_local=metrics,
                aliases_local=aliases,
                ragas_llm_local=object(),
                ragas_embeddings_local=object(),
                run_config_local=object(),
                diagnostics_local=diagnostics,
            )

        self.assertEqual(result, "RESULT")
        self.assertNotIn("answer_correctness", active_aliases)
        self.assertTrue(any("Timeout en RAGAS" in issue for issue in diagnostics["issues"]))

