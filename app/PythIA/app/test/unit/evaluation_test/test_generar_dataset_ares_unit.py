"""
Autora: Lydia Blanco Ruiz
Script con pruebas unitarias para cubrir el archivo generar_dataset_ARES, encargado de construir conjuntos de datos para la evaluación automática de sistemas RAG mediante ARES.
Las pruebas verifican la generación de datasets a partir de preguntas de referencia, la obtención de respuestas y contextos mediante el sistema RAG, la creación de archivos 
JSON y TSV para evaluación, así como la gestión de errores, preguntas inválidas y escenarios en los que ya existen resultados previamente generados.
"""

import asyncio
import importlib
import json
import sys
import types
from pathlib import Path
from unittest.mock import patch

from app.test.support import BaseAppTestCase


def _install_fake_prototipo_rag(*, results=None, raise_for=None):
    """
    Crea una versión simulada del módulo PrototipoRAG para controlar las respuestas devueltas durante las pruebas de generación de datasets.
    """
    module = types.ModuleType("app.main.code.services.rag.PrototipoRAG")

    async def obtener_mejor_chunk(question: str, *args, **kwargs):
        """
        Simula la recuperación del mejor fragmento documental para una pregunta determinada. Permite devolver resultados predefinidos o provocar errores
        controlados para validar distintos escenarios de prueba.
        """
        await asyncio.sleep(0)
        if raise_for and question in raise_for:
            raise RuntimeError("boom")
        payload = (results or {}).get(question) or {"answer": "A", "retrieved": [{"chunk": "C1"}]}
        return payload

    module.obtener_mejor_chunk = obtener_mejor_chunk
    return module


class GenerarDatasetARESUnitTest(BaseAppTestCase):
    """
    Conjunto de pruebas unitarias destinadas a validar el proceso de generación de datasets para ARES, verificando la construcción de los ficheros de salida, 
    la gestión de errores y el tratamiento de distintos escenarios de entrada.
    """
    def _import_module(self, fake_rag):
        """
        Importa dinámicamente el módulo de generación de datasets utilizando implementaciones simuladas de las dependencias externas necesarias para las pruebas.
        """
        fake_pandas = types.ModuleType("pandas")

        class _FakeDF:
            """
            Implementación simplificada de un DataFrame utilizada para simular las operaciones mínimas requeridas durante la generación del dataset.
            """
            def __init__(self, data):
                """
                Inicializa el DataFrame simulado a partir de una colección de registros.
                """
                self._data = data
                self._series = {
                    "question": _FakeSeries([row.get("question") for row in data]),
                    "documents": _FakeSeries([row.get("documents") for row in data]),
                    "answer": _FakeSeries([row.get("answer") for row in data]),
                }
                self.columns = list(self._series.keys())

            def __len__(self):
                """
                Devuelve el número de registros almacenados en el DataFrame.
                """
                return len(self._data)

            def __getitem__(self, key):
                """
                Recupera una serie simulada asociada a la columna solicitada.
                """
                return self._series.get(key, _FakeSeries([]))

        class _FakeSeries(list):
            """
            Implementación simplificada de una serie de datos compatible con las operaciones utilizadas durante las pruebas.
            """
            def astype(self, _type):
                """
                Simula la conversión de tipo devolviendo la propia serie.
                """
                return self

            def apply(self, fn):
                """
                Aplica una función a todos los elementos de la serie y devuelve los resultados transformados.
                """
                return [_FakeSeriesItem(fn(item)) for item in self]

        class _FakeSeriesItem(str):
            """
            Representa un elemento individual de una serie simulada.
            """

        def _data_frame(data):
            """
            Construye una instancia de DataFrame simulada a partir de los datos proporcionados.
            """
            if isinstance(data, list):
                return _FakeDF(data)
            return _FakeDF([])

        fake_pandas.DataFrame = _data_frame

        def _to_csv(self, path, sep="\t", index=False):
            """
            Simula la exportación de un DataFrame a formato TSV generando un archivo de salida mínimo para las pruebas.
            """
            Path(path).write_text("Query\tDocument\tAnswer\n", encoding="utf-8")

        _FakeDF.to_csv = _to_csv

        with patch.dict(
            sys.modules,
            {"app.main.code.services.rag.PrototipoRAG": fake_rag, "pandas": fake_pandas},
        ):
            sys.modules.pop("app.main.code.services.evaluation.generar_dataset_ARES", None)
            return importlib.import_module("app.main.code.services.evaluation.generar_dataset_ARES")

    def _module(self):
        """
        Crea una instancia del módulo de generación de datasets utilizando una implementación simulada del sistema RAG.
        """
        fake = _install_fake_prototipo_rag()
        return self._import_module(fake)

    def test_main_skips_when_outputs_exist_and_no_force(self):
        """
        Verifica que el proceso de generación no se ejecuta cuando los archivos de salida ya existen y no se ha solicitado su regeneración forzada.
        """
        m = self._module()
        out_json = self._tmpdir / "out.json"
        out_tsv = self._tmpdir / "out.tsv"
        questions_path = self._tmpdir / "questions.json"
        out_json.write_text("[]", encoding="utf-8")
        out_tsv.write_text("", encoding="utf-8")
        questions_path.write_text("[]", encoding="utf-8")

        with patch.object(m, "OUT_JSON", out_json), patch.object(m, "OUT_TSV", out_tsv), patch.object(
            m, "QUESTIONS_PATH", questions_path
        ), patch.object(m, "FORCE_REGENERATE", False):
            m.main()

    def test_main_builds_dataset_and_writes_json_and_tsv(self):
        """
        Comprueba la construcción correcta del dataset de evaluación y la generación de los archivos JSON y TSV utilizados por ARES.
        """
        results = {"Q1": {"answer": "A1", "retrieved": [{"chunk": "Doc 1"}, {"chunk": "Doc 2"}]}}
        fake = _install_fake_prototipo_rag(results=results)
        m = self._import_module(fake)
        out_json = self._tmpdir / "out.json"
        out_tsv = self._tmpdir / "out.tsv"
        questions_path = self._tmpdir / "questions.json"
        questions_path.write_text(
            json.dumps([{"question": "Q1", "ground_truth": "GT", "evidence": "EV"}, {"question": ""}], ensure_ascii=False),
            encoding="utf-8",
        )

        with patch.object(m, "OUT_JSON", out_json), patch.object(m, "OUT_TSV", out_tsv), patch.object(
            m, "QUESTIONS_PATH", questions_path
        ), patch.object(m, "FORCE_REGENERATE", True), patch.dict(sys.modules, {"app.main.code.services.rag.PrototipoRAG": fake}):
            m.main()

        data = json.loads(out_json.read_text(encoding="utf-8"))
        self.assertEqual(len(data), 1)
        self.assertEqual(data[0]["question"], "Q1")
        self.assertEqual(data[0]["answer"], "A1")
        self.assertTrue(out_tsv.exists())

    def test_main_raises_system_exit_when_dataset_empty(self):
        """
        Verifica que el proceso finaliza con error cuando no se generan ejemplos válidos para construir el dataset de evaluación.
        """
        fake = _install_fake_prototipo_rag(results={})
        m = self._import_module(fake)
        out_json = self._tmpdir / "out.json"
        out_tsv = self._tmpdir / "out.tsv"
        questions_path = self._tmpdir / "questions.json"
        questions_path.write_text(json.dumps([{"question": ""}]), encoding="utf-8")

        with patch.object(m, "OUT_JSON", out_json), patch.object(m, "OUT_TSV", out_tsv), patch.object(
            m, "QUESTIONS_PATH", questions_path
        ), patch.object(m, "FORCE_REGENERATE", True
        ), self.assertRaises(SystemExit), patch.dict(sys.modules, {"app.main.code.services.rag.PrototipoRAG": fake}):
            m.main()

    def test_main_skips_failed_questions(self):
        """
        Comprueba que las preguntas que producen errores durante la generación de respuestas son descartadas y no se incorporan al dataset final.
        """
        fake = _install_fake_prototipo_rag(raise_for={"Q-bad"})
        m = self._import_module(fake)
        out_json = self._tmpdir / "out.json"
        out_tsv = self._tmpdir / "out.tsv"
        questions_path = self._tmpdir / "questions.json"
        questions_path.write_text(json.dumps([{"question": "Q-bad"}]), encoding="utf-8")

        with patch.object(m, "OUT_JSON", out_json), patch.object(m, "OUT_TSV", out_tsv), patch.object(
            m, "QUESTIONS_PATH", questions_path
        ), patch.object(m, "FORCE_REGENERATE", True), self.assertRaises(SystemExit
        ), patch.dict(sys.modules, {"app.main.code.services.rag.PrototipoRAG": fake}):
            m.main()
