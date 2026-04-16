import importlib
import importlib.util
import sys
import types
import unittest
from unittest.mock import AsyncMock, MagicMock


def _module_available(name):
    try:
        return importlib.util.find_spec(name) is not None
    except (ImportError, ValueError):
        return False


def _install_optional_dependency_stubs():
    if not _module_available("httpx") and "httpx" not in sys.modules:
        httpx = types.ModuleType("httpx")
        httpx.TimeoutException = TimeoutError
        httpx.HTTPError = RuntimeError
        httpx.HTTPStatusError = RuntimeError
        httpx.AsyncClient = object
        httpx.Response = object
        sys.modules["httpx"] = httpx

    if not _module_available("PIL") and "PIL" not in sys.modules:
        pil = types.ModuleType("PIL")
        image = types.ModuleType("PIL.Image")
        pil.Image = image
        sys.modules["PIL"] = pil
        sys.modules["PIL.Image"] = image

    if not _module_available("pdf2image") and "pdf2image" not in sys.modules:
        pdf2image = types.ModuleType("pdf2image")
        pdf2image.convert_from_path = MagicMock()
        pdf2image.pdfinfo_from_path = MagicMock()
        sys.modules["pdf2image"] = pdf2image


_install_optional_dependency_stubs()
conversion = importlib.import_module("app.markdown.Conversion_markdown")


class ConversionMarkdownUnitTest(unittest.TestCase):
    def test_build_chat_payload_sets_model_image_and_gpu_options(self):
        payload = conversion._build_chat_payload("contenido", "base64", num_gpu=0)

        self.assertEqual(payload["model"], conversion.MODEL_NAME)
        self.assertEqual(payload["messages"][0]["images"], ["base64"])
        self.assertFalse(payload["stream"])
        self.assertEqual(payload["options"]["num_gpu"], 0)

    def test_response_error_details_prefers_json_error_fields(self):
        response = MagicMock()
        response.json.return_value = {"detail": "detalle de error"}

        self.assertEqual(conversion._response_error_details(response), "detalle de error")

    def test_response_error_details_uses_text_when_json_is_invalid(self):
        response = MagicMock(text="error plano")
        response.json.side_effect = ValueError

        self.assertEqual(conversion._response_error_details(response), "error plano")

    def test_clean_index_dots_removes_dot_leaders_and_dot_only_lines(self):
        markdown = "1. OBJETO............. 3\n.....\nTexto normal"

        self.assertEqual(conversion.clean_index_dots(markdown), "1. OBJETO 3\nTexto normal")

    def test_normalize_headings_converts_supported_heading_patterns(self):
        markdown = "1. OBJETO DEL CONTRATO\n1.1. Alcance\n1.1.1. Detalle\nG.2.2. Codigo\n- 1. Lista"

        normalized = conversion.normalize_headings(markdown)

        self.assertIn("# 1. OBJETO DEL CONTRATO", normalized)
        self.assertIn("## 1.1. Alcance", normalized)
        self.assertIn("### 1.1.1. Detalle", normalized)
        self.assertIn("### G.2.2. Codigo", normalized)
        self.assertIn("- 1. Lista", normalized)

    def test_post_ollama_chat_async_returns_json_payload(self):
        response = MagicMock()
        response.raise_for_status.return_value = None
        response.json.return_value = {"message": {"content": "ok"}}
        client = MagicMock()
        client.post = AsyncMock(return_value=response)

        result = conversion.asyncio.run(conversion._post_ollama_chat_async(client, {"payload": True}))

        self.assertEqual(result, {"message": {"content": "ok"}})
        client.post.assert_awaited_once_with("/api/chat", json={"payload": True})
