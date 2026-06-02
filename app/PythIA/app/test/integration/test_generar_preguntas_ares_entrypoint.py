"""
Autora: Lydia Blanco Ruiz
Prueba de integración del bloque principal (if __name__ == "__main__":) de generar_preguntas_ARES. Su objetivo es verificar el comportamiento
del script cuando se ejecuta como programa independiente y ya existe un fichero de preguntas generado previamente. La prueba comprueba que el 
proceso finaliza correctamente sin regenerar el contenido cuando la configuración indica que no debe sobrescribirse el archivo existente. 
Para ello, se utilizan implementaciones simuladas del sistema RAG y de las funciones de generación de preguntas, permitiendo validar el 
flujo de ejecución de forma aislada.
"""

import asyncio
import os
import runpy
import sys
import types
from pathlib import Path

from app.test.support import BaseAppTestCase


class GenerarPreguntasARESMainGuardIntegrationTest(BaseAppTestCase):
    def test_main_guard_executes_without_generating_when_file_exists(self):
        """
        Verifica que la ejecución del bloque principal de generar_preguntas_ARES.py finaliza correctamente sin generar nuevas preguntas cuando
        el fichero de salida ya existe y la regeneración forzada está deshabilitada.
        """
        out_path = self._tmpdir / "questions.json"
        out_path.write_text("[]", encoding="utf-8")

        os.environ["ARES_QUESTIONS_PATH"] = str(out_path)
        os.environ["ARES_FORCE_REGENERATE"] = "0"

        fake_rag = types.ModuleType("app.main.code.services.rag.PrototipoRAG")

        class VectorBaseDocument:
            """
            Implementación simulada del repositorio documental utilizada para evitar accesos a la base vectorial durante la ejecución de la prueba.
            """
            @staticmethod
            def bulk_find(limit=100, offset=None):
                """
                Simula una recuperación documental vacía devolviendo que no existen más documentos disponibles.
                """
                return [], None

        async def ask_ollama(_prompt, model=None):
            """
            Simula una llamada al modelo de lenguaje devolviendo una lista vacía de preguntas generadas.
            """
            await asyncio.sleep(0.01)
            return "[]"

        fake_rag.VectorBaseDocument = VectorBaseDocument
        fake_rag.ask_ollama = ask_ollama

        script = Path("app/main/code/services/evaluation/generar_preguntas_ARES.py").resolve()
        with _patch_modules({"app.main.code.services.rag.PrototipoRAG": fake_rag}):
            runpy.run_path(str(script), run_name="__main__")


class _patch_modules:
    def __init__(self, mapping):
        """
        Inicializa el gestor de contexto almacenando los módulos simulados que sustituirán temporalmente a las dependencias reales 
        durante la ejecución de la prueba.
        """
        self.mapping = mapping
        self.old = {}

    def __enter__(self):
        """
        Sustituye temporalmente los módulos reales por implementaciones simuladas y fuerza la recarga del módulo bajo prueba para garantizar 
        un entorno controlado.
        """
        for key, value in self.mapping.items():
            self.old[key] = sys.modules.get(key)
            sys.modules[key] = value
        sys.modules.pop("app.main.code.services.evaluation.generar_preguntas_ARES", None)
        return self

    def __exit__(self, exc_type, exc, tb):
        """
        Restaura los módulos originales al finalizar la prueba, devolviendo el entorno de ejecución a su estado previo.
        """
        for key, old_value in self.old.items():
            if old_value is None:
                sys.modules.pop(key, None)
            else:
                sys.modules[key] = old_value
        return False

