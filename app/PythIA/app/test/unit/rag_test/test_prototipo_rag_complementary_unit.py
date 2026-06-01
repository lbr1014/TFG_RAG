"""
Autora: Lydia Blanco Ruiz
Script con pruebas unitarias para el modulo PrototipoRAG, centrada en cubrir rutas de ejecución poco frecuentes relacionadas con la 
importación de dependencias opcionales, la serialización de datos y la indexación documental.
Las pruebas verifican el comportamiento del sistema cuando determinadas librerías no están disponibles, la gestión de datos no serializables, 
la detección del dispositivo de ejecución de Ollama y distintos casos límite durante la indexación de documentos PDF.
"""

import builtins
import sys
import types
import unittest
from importlib.machinery import SourceFileLoader
from importlib.util import module_from_spec, spec_from_loader
from pathlib import Path
from unittest.mock import patch
from uuid import uuid4


def _load_prototipo_with_import_block(block_name: str):
    """
    Carga dinámicamente el módulo PrototipoRAG simulando la ausencia de una dependencia concreta para verificar los mecanismos de respaldo
    implementados durante la importación.
    """
    real_import = builtins.__import__

    def guarded_import(name, *args, **kwargs):
        """
        Guarda el import para evitar que se importe torch durante la importación del módulo.
        """
        if name == block_name:
            raise ImportError("blocked for test")
        return real_import(name, *args, **kwargs)

    repo_root = Path(__file__).resolve().parents[4]
    module_path = repo_root / "app" / "main" / "code" / "services" / "rag" / "PrototipoRAG.py"
    module_name = f"PrototipoRAG_real_block_{uuid4().hex}"
    loader = SourceFileLoader(module_name, str(module_path))
    spec = spec_from_loader(loader.name, loader)
    module = module_from_spec(spec)
    sys.modules[loader.name] = module
    old_sentence = None
    if block_name == "torch":
        # Evita que sentence_transformers/transformers intenten torch durante el import del módulo.
        old_sentence = sys.modules.get("sentence_transformers")
        fake_sentence = types.ModuleType("sentence_transformers")

        class SentenceTransformer:
            def __init__(self, *args, **kwargs):
                """
                Inicializa el SentenceTransformer salso con una longitud de secuencia por defecto.
                """
                self.max_seq_length = 512

            def encode(self, *args, **kwargs):
                """
                Devuelve un embedding para las entradas poroporcionadas.
                """
                return [0.0, 0.0, 0.0]

        fake_sentence.SentenceTransformer = SentenceTransformer
        sys.modules["sentence_transformers"] = fake_sentence

    try:
        with patch("builtins.__import__", side_effect=guarded_import):
            loader.exec_module(module)
    finally:
        if block_name == "torch":
            if old_sentence is None:
                sys.modules.pop("sentence_transformers", None)
            else:
                sys.modules["sentence_transformers"] = old_sentence
    return module


class PrototipoRAGAdditionalCoverageUnitTest(unittest.TestCase):
    def test_import_without_torch_hits_importerror_branch(self):
        """
        Verifica que el módulo se inicializa correctamente cuando la biblioteca torch no está disponible y se 
        ejecuta la rama de recuperación correspondiente.
        """
        m = _load_prototipo_with_import_block("torch")
        self.assertIsNone(m.torch)

    def test_infer_device_from_ollama_ps_payload_handles_bad_size_vram(self):
        """
        Comprueba la detección del dispositivo de ejecución cuando la información de memoria de vídeo proporcionada por Ollama
        es inválida o no puede interpretarse correctamente.
        """
        m = _load_prototipo_with_import_block("torch")
        payload = {"models": [{"name": "m", "size_vram": "bad"}]}
        device = m._infer_device_from_ollama_ps_payload(payload, target_model="m")
        self.assertEqual(device, "CPU")

    def test_infer_device_from_ollama_ps_payload_skips_non_matching_model(self):
        """
        Verifica que únicamente se analiza la información correspondiente al modelo solicitado, ignorando el resto de modelos presentes en la 
        respuesta de Ollama.
        """
        m = _load_prototipo_with_import_block("torch")
        payload = {"models": [{"name": "other", "size_vram": 123}]}
        self.assertIsNone(m._infer_device_from_ollama_ps_payload(payload, target_model="m"))

    def test_to_jsonable_handles_item_errors(self):
        """
        Comprueba la conversión segura de estructuras de datos a formatos serializables gestionando correctamente errores producidos durante la 
        obtención de valores internos.
        """
        m = _load_prototipo_with_import_block("torch")

        class WithItem:
            def item(self):
                """
                Lanza un error al intentar recuperar el valor del elemento.           
                """
                raise ValueError("boom")

        self.assertIsNone(m._to_jsonable(float("inf")))
        converted = m._to_jsonable({"a": WithItem()})
        self.assertIn("a", converted)
        self.assertIsInstance(converted["a"], str)

    def test_index_pdf_handles_empty_text_and_mismatch_vectors(self):
        """
        Verifica que la indexación de documentos PDF gestiona correctamente casos en los que no existe texto recuperable o cuando el número de
        embeddings generados no coincide con el número de fragmentos obtenidos.
        """
        m = _load_prototipo_with_import_block("torch")

        class FakeReader:
            def __init__(self):
                """
                Inicializa FakeReader con los metadatos y las páginas vacios.
                """
                self.metadata = {}
                self.pages = [types.SimpleNamespace(extract_text=lambda: "")]

        pdf = Path("fake.pdf")

        with patch.object(m, "PdfReader", return_value=FakeReader()), patch.object(m, "pdf_sha256", return_value="h"):
            self.assertEqual(m.index_pdf(pdf), [])

        class FakeReader2:
            def __init__(self):
                """
                Inicializa FakeReader2 con texto de página válido.
                """
                self.metadata = {}
                self.pages = [types.SimpleNamespace(extract_text=lambda: "texto")]

        with patch.object(m, "PdfReader", return_value=FakeReader2()), patch.object(m, "pdf_sha256", return_value="h"), patch.object(
            m, "chunk_text", return_value=["c1", "c2"]
        ), patch.object(m, "embedding_model", return_value=[[0.0]]):
            self.assertEqual(m.index_pdf(pdf), [])
