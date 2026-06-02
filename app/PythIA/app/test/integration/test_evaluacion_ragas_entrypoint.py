"""
Autora: Lydia Blanco Ruiz
Script de pruebas de integración del punto de entrada principal (if __name__ == "__main__":) de evaluacion_RAGAS. Su objetivo es verificar el
omportamiento del sistema cuando la ejecución de la evaluación falla antes de completarse. En particular, comprueba que, incluso en 
presencia de errores durante la inicialización del proceso, se generan correctamente los artefactos mínimos de salida necesarios para
registrar el fallo y facilitar su posterior diagnóstico.
"""

import json
import os
import runpy
from pathlib import Path

from app.test.support import BaseAppTestCase


class EvaluacionRAGASMainGuardIntegrationTest(BaseAppTestCase):
    def test_main_guard_writes_artifacts_on_failure(self):
        """
        Verifica que la ejecución del bloque principal de evaluacion_RAGAS.py genera los ficheros de resultados, filas evaluadas 
        y configuración incluso cuando se produce un fallo durante la ejecución. Además, comprueba que el error queda registrado en 
        los resultados generados para facilitar su análisis posterior.
        """
        tmp = self._tmpdir
        results = tmp / "results.json"
        rows = tmp / "rows.json"
        config = tmp / "config.json"

        # Fuerza un fallo temprano dentro de main() (no existe el fichero de preguntas).
        os.environ["RAGAS_QUESTIONS_PATH"] = str(tmp / "missing_questions.json")
        os.environ["RAGAS_RESULTS_PATH"] = str(results)
        os.environ["RAGAS_ROW_RESULTS_PATH"] = str(rows)
        os.environ["CONFIGURACION_PATH"] = str(config)

        script = Path("app/main/code/services/evaluation/evaluacion_RAGAS.py").resolve()

        with self.assertRaises(FileNotFoundError):
            runpy.run_path(str(script), run_name="__main__")

        self.assertTrue(results.exists())
        self.assertTrue(rows.exists())
        self.assertTrue(config.exists())

        payload = json.loads(results.read_text(encoding="utf-8"))
        self.assertIn("ragas_error", payload)

