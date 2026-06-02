"""
Autora: Lydia Blanco Ruiz
Script con pruebas de integración del bloque principal (if __name__ == "__main__":) de generar_dataset_ARES. Su objetivo es verificar la
ejecución completa del script cuando se lanza como programa independiente, comprobando que el proceso genera correctamente los archivos 
de salida del dataset de evaluación a partir de preguntas de entrada. Para evitar dependencias externas, se utilizan implementaciones 
simuladas del sistema RAG y de la biblioteca Pandas, permitiendo validar el flujo completo de generación de datasets de forma aislada.
"""

import asyncio
import json
import os
import runpy
import sys
import types
from pathlib import Path

from app.test.support import BaseAppTestCase


class GenerarDatasetARESMainGuardIntegrationTest(BaseAppTestCase):
    def test_main_guard_executes_and_writes_outputs(self):
        """
        Verifica la ejecución completa del bloque principal de generar_dataset_ARES.py, comprobando que se generan correctamente 
        los archivos JSON y TSV de salida a partir de un conjunto de preguntas de evaluación y utilizando implementaciones simuladas 
        de los componentes externos necesarios.
        """
        tmp = self._tmpdir
        questions_path = tmp / "questions.json"
        out_json = tmp / "out.json"
        out_tsv = tmp / "out.tsv"

        questions_path.write_text(
            json.dumps([{"question": "Q1", "ground_truth": "GT", "evidence": "EV"}], ensure_ascii=False),
            encoding="utf-8",
        )

        os.environ["ARES_QUESTIONS_PATH"] = str(questions_path)
        os.environ["ARES_DATASET_JSON_PATH"] = str(out_json)
        os.environ["ARES_DATASET_TSV_PATH"] = str(out_tsv)
        os.environ["ARES_FORCE_REGENERATE"] = "1"

        fake_rag = types.ModuleType("app.main.code.services.rag.PrototipoRAG")

        async def obtener_mejor_chunk(_question: str, *args, **kwargs):
            """
            Simula la recuperación asíncrona de información desde el sistema RAG, devolviendo una respuesta y un fragmento documental asociado.
            """
            await asyncio.sleep(0.01)
            return {"answer": "A1", "retrieved": [{"chunk": "Doc"}]}

        fake_rag.obtener_mejor_chunk = obtener_mejor_chunk

        fake_pandas = types.ModuleType("pandas")

        class _FakeSeries(list):
            """
            Implementación simplificada de una serie de datos utilizada para reproducir las operaciones mínimas requeridas durante la exportación
            del dataset.
            """
            def astype(self, _type):
                """
                Simula la conversión de tipo devolviendo la propia serie.
                """
                return self

            def apply(self, fn):
                """
                Aplica una transformación a todos los elementos de la serie.
                """
                return [fn(item) for item in self]

        class _FakeDF:
            """
            Implementación simplificada de un DataFrame utilizada para simular la construcción y exportación del dataset generado.
            """
            def __init__(self, data):
                """
                Inicializa el DataFrame simulado con los registros generados durante la construcción del dataset.
                """
                self._data = data
                self.columns = ["Query", "Document", "Answer"]

            def __len__(self):
                """
                Devuelve el número de registros almacenados en el DataFrame.
                """
                return len(self._data)

            def __getitem__(self, key):
                """
                Recupera una columna simulada para permitir las transformaciones
                realizadas antes de la exportación.
                """
                if key == "question":
                    return _FakeSeries([row["question"] for row in self._data])
                if key == "documents":
                    return _FakeSeries([row["documents"] for row in self._data])
                if key == "answer":
                    return _FakeSeries([row["answer"] for row in self._data])
                return _FakeSeries([])

            def to_csv(self, path, sep="\t", index=False):
                """
                Simula la exportación del dataset a formato TSV generando un archivo de
                salida mínimo.
                """
                Path(path).write_text("Query\tDocument\tAnswer\n", encoding="utf-8")

        def data_frame(data):
            """
            Construye una instancia del DataFrame simulado a partir de los datos
            proporcionados.
            """
            return _FakeDF(data)

        fake_pandas.DataFrame = data_frame

        script = Path("app/main/code/services/evaluation/generar_dataset_ARES.py").resolve()
        with _patch_modules(
            {
                "app.main.code.services.rag.PrototipoRAG": fake_rag,
                "pandas": fake_pandas,
            }
        ):
            runpy.run_path(str(script), run_name="__main__")

        self.assertTrue(out_json.exists())
        self.assertTrue(out_tsv.exists())


class _patch_modules:
    def __init__(self, mapping):
        """
        Inicializa el gestor de contexto almacenando los módulos simulados que sustituirán temporalmente a las dependencias reales durante la prueba.
        """
        self.mapping = mapping
        self.old = {}

    def __enter__(self):
        """
        Sustituye temporalmente los módulos reales por versiones simuladas e invalida las importaciones previas del módulo bajo prueba para 
        forzar una nueva carga.
        """
        for key, value in self.mapping.items():
            self.old[key] = sys.modules.get(key)
            sys.modules[key] = value
        sys.modules.pop("app.main.code.services.evaluation.generar_dataset_ARES", None)
        return self

    def __exit__(self, exc_type, exc, tb):
        """
        Restaura los módulos originales al finalizar la prueba, devolviendo el entorno de ejecución a su estado inicial.
        """
        for key, old_value in self.old.items():
            if old_value is None:
                sys.modules.pop(key, None)
            else:
                sys.modules[key] = old_value
        return False
