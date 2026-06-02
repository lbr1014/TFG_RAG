"""
Autora: Lydia Blanco Ruiz
Script de pruebas de integración del pipeline de evaluación RAG (sin depender de Ollama/RAGAS reales). Su objetivo es verificar la 
construcción de los datos de evaluación, la generación de contextos recuperados, la ejecución del flujo principal de evaluación y 
la creación de los artefactos de salida. Las pruebas validan además los mecanismos de recuperación ante errores cuando la evaluación 
mediante RAGAS falla, garantizando que se generan correctamente los resultados y diagnósticos necesarios para el análisis posterior.
"""

import importlib
import json
import os
from unittest.mock import patch

from app.test.support import BaseAppTestCase


class _FakeEmbeddings:
    def __init__(self, *args, **kwargs):
        """
        Inicializa una implementación simulada del modelo de embeddings utilizada para ejecutar las pruebas sin depender de modelos reales.
        """
        self.model_name = kwargs.get("model_name", "fake")
        self.model_kwargs = kwargs.get("model_kwargs", {})

    def embed_documents(self, texts):
        """
        Genera embeddings simplificados a partir de la longitud de los textos recibidos para simular el comportamiento de un 
        modelo de embeddings real durante las pruebas.
        """
        vectors = []
        for text in texts:
            text = (text or "").strip()
            vectors.append([float(len(text)), 1.0, 0.5])
        return vectors


class EvaluacionRAGASPipelineIntegrationTest(BaseAppTestCase):
    def _import_with_env(self, **env):
        """
        Importa dinámicamente el módulo evaluacion_RAGAS aplicando variables de entorno específicas para configurar distintos escenarios de prueba.
        """
        for key, value in env.items():
            os.environ[key] = str(value)
        from app.main.code.services.evaluation import evaluacion_RAGAS

        return importlib.reload(evaluacion_RAGAS)

    def test_build_ragas_rows_uses_stubbed_rag_and_k_contexts(self):
        """
        Verifica la construcción de los registros de evaluación RAGAS utilizando respuestas simuladas del sistema RAG y comprobando que se respetan 
        los límites configurados para el número de contextos recuperados.
        """
        m = self._import_with_env()
        questions = [
            {"question": "Pregunta 1", "ground_truth": "GT", "evidence": "EV"},
            {"question": ""},
        ]

        with patch.object(m, "obtener_mejor_chunk_sync") as mock_rag:
            mock_rag.return_value = {
                "answer": "Respuesta",
                "retrieved": [{"chunk": "c1"}, {"chunk": "c2"}, {"chunk": "c3"}],
            }
            rows = m.build_ragas_rows(questions, k_contexts=2)

        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["question"], "Pregunta 1")
        self.assertEqual(rows[0]["answer"], "Respuesta")
        self.assertEqual(rows[0]["contexts"], ["c1", "c2"])
        self.assertEqual(rows[0]["reference"], "GT")
        self.assertEqual(rows[0]["reference_contexts"], ["EV"])

    def test_main_writes_outputs_and_handles_ragas_exception(self):
        """
        Comprueba la ejecución del flujo principal de evaluación cuando la evaluación RAGAS produce una excepción, verificando que se generan 
        correctamente los archivos de resultados, configuraciones y diagnósticos de error.
        """
        tmp = self._tmpdir
        questions_path = tmp / "questions.json"
        results_path = tmp / "results.json"
        row_results_path = tmp / "rows.json"
        config_path = tmp / "config.json"

        questions_path.write_text(
            json.dumps(
                [
                    {
                        "question": "Pregunta",
                        "ground_truth": "GT",
                        "evidence": "EV",
                    }
                ],
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )

        m = self._import_with_env(
            RAGAS_QUESTIONS_PATH=questions_path,
            RAGAS_RESULTS_PATH=results_path,
            RAGAS_ROW_RESULTS_PATH=row_results_path,
            CONFIGURACION_PATH=config_path,
            RAGAS_K_CONTEXTS=2,
            RAGAS_EMBEDDINGS_DEVICE="cpu",
        )

        def fake_rag_rows(_questions, k_contexts=3):
            """
            Simula la construcción de registros de evaluación RAGAS devolviendo un conjunto mínimo de datos con pregunta, respuesta,
            contexto y referencias asociadas.
            """
            return [
                {
                    "question": "Pregunta",
                    "answer": "Respuesta",
                    "ground_truth": "GT",
                    "evidence": "EV",
                    "contexts": ["c1"],
                }
            ]

        with patch.object(m, "build_ragas_rows", side_effect=fake_rag_rows), patch.object(
            m, "HuggingFaceEmbeddings", _FakeEmbeddings
        ), patch.object(m, "OllamaLLM", lambda *args, **kwargs: object()), patch.object(
            m, "run_ragas", side_effect=RuntimeError("boom-ragas")
        ):
            m.main()

        self.assertTrue(results_path.exists())
        self.assertTrue(row_results_path.exists())
        self.assertTrue(config_path.exists())

        summary = json.loads(results_path.read_text(encoding="utf-8"))
        self.assertIn("final_metrics", summary)
        self.assertIn("ragas_metrics", summary)
        self.assertIn("coseno_metrics", summary)
        self.assertIn("score_source_counts", summary)

        config = json.loads(config_path.read_text(encoding="utf-8"))
        self.assertIn("ragas_diagnostics", config)
        self.assertIn("ragas_error", config)
