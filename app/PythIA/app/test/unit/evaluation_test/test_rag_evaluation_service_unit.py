"""
Autora: Lydia Blanco Ruiz
Script con pruebas unitarias para rag_evaluation_service, encargado de orquestar el proceso completo de evaluación del sistema RAG. Las pruebas verifican la generación de 
directorios y artefactos de evaluación, la ejecución secuencial de los scripts de generación de preguntas, creación de datasets y evaluación mediante RAGAS, así como la
gestión de variables de entorno y la recuperación ante errores durante la evaluación.
"""

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

from app.test.support import BaseAppTestCase


class RAGEvaluationServiceUnitTest(BaseAppTestCase):
    def test_timestamp_slug_is_deterministic(self):
        """
        Verifica que los identificadores temporales utilizados para nombrar directorios y resultados de evaluación se generan de forma determinista a partir de una fecha concreta.
        """
        from app.main.code.services.evaluation import rag_evaluation_service as svc

        now = datetime(2026, 5, 30, 12, 0, 1, tzinfo=timezone.utc)
        self.assertEqual(svc._timestamp_slug(now), "20260530_120001")

    def test_run_rag_evaluation_in_testing_mode_writes_minimal_artifacts(self):
        """
        Comprueba que el servicio de evaluación genera correctamente todos los artefactos mínimos requeridos cuando se ejecuta en modo de pruebas.
        """
        from app.main.code.services.evaluation import rag_evaluation_service as svc

        data_dir = self._tmpdir / "data"
        with patch.dict(os.environ, {"PYTHIA_TESTING": "1"}, clear=False):
            artifacts = svc.run_rag_evaluation(data_dir=data_dir)

        self.assertTrue(artifacts.output_dir.exists())
        for path in (
            artifacts.ares_questions_json_path,
            artifacts.ares_dataset_json_path,
            artifacts.ares_dataset_tsv_path,
            artifacts.results_json_path,
            artifacts.row_results_json_path,
            artifacts.config_json_path,
        ):
            self.assertTrue(path.exists())

    def test_run_rag_evaluation_calls_scripts_and_restores_env(self):
        """
        Verifica la ejecución secuencial de los distintos scripts que forman el pipeline de evaluación y la restauración correcta de las variables de entorno utilizadas durante el proceso.
        """
        from app.main.code.services.evaluation import rag_evaluation_service as svc

        data_dir = self._tmpdir / "data"
        os.environ.pop("PYTHIA_TESTING", None)
        old = os.environ.get("RAGAS_RESULTS_PATH")

        calls = []

        def fake_run_path(path, run_name="__main__"):
            calls.append(Path(path).name)

        with patch("app.main.code.services.evaluation.rag_evaluation_service.runpy.run_path", side_effect=fake_run_path):
            artifacts = svc.run_rag_evaluation(data_dir=data_dir)

        self.assertEqual(calls[:2], ["generar_preguntas_ARES.py", "generar_dataset_ARES.py"])
        self.assertIn("evaluacion_RAGAS.py", calls)
        self.assertTrue(artifacts.output_dir.exists())
        self.assertEqual(os.environ.get("RAGAS_RESULTS_PATH"), old)

    def test_run_rag_evaluation_writes_fallback_when_ragas_fails(self):
        """
        Comprueba que, cuando la fase de evaluación mediante RAGAS produce un error, el sistema genera igualmente los ficheros de resultados mínimos y 
        almacena la información del fallo para facilitar su diagnóstico.
        """
        from app.main.code.services.evaluation import rag_evaluation_service as svc

        data_dir = self._tmpdir / "data"

        def fake_run_path(path, run_name="__main__"):
            if str(path).endswith("evaluacion_RAGAS.py"):
                raise RuntimeError("boom-ragas")

        with patch("app.main.code.services.evaluation.rag_evaluation_service.runpy.run_path", side_effect=fake_run_path), self.assertRaises(RuntimeError):
            svc.run_rag_evaluation(data_dir=data_dir)

        eval_root = data_dir / "evaluations"
        dirs = sorted([p for p in eval_root.iterdir() if p.is_dir()])
        self.assertTrue(dirs)
        output_dir = dirs[-1]

        results_path = output_dir / "ragas_results.json"
        rows_path = output_dir / "ragas_results_rows.json"
        config_path = output_dir / "configuracion.json"

        self.assertTrue(results_path.exists())
        self.assertTrue(rows_path.exists())
        self.assertTrue(config_path.exists())
        payload = json.loads(results_path.read_text(encoding="utf-8"))
        self.assertIn("ragas_error", payload)

