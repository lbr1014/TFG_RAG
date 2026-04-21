import importlib
import importlib.util
import os
from pathlib import Path
import sys
import tempfile
import types
import unittest
from unittest.mock import AsyncMock, MagicMock
from unittest.mock import patch


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


def _fake_torch(cuda_available):
    fake_torch = types.ModuleType("torch")
    fake_torch.cuda = MagicMock()
    fake_torch.cuda.is_available.return_value = cuda_available
    return fake_torch


def _import_conversion_with_torch(cuda_available):
    original_torch = sys.modules.get("torch")
    sys.modules["torch"] = _fake_torch(cuda_available)
    sys.modules.pop("app.markdown.Conversion_markdown", None)
    try:
        with patch.dict(os.environ, {"OLLAMA_NUM_GPU": ""}):
            return importlib.import_module("app.markdown.Conversion_markdown")
    finally:
        sys.modules.pop("app.markdown.Conversion_markdown", None)
        if original_torch is None:
            sys.modules.pop("torch", None)
        else:
            sys.modules["torch"] = original_torch
        sys.modules["app.markdown.Conversion_markdown"] = conversion


class ConversionMarkdownUnitTest(unittest.TestCase):
    def setUp(self):
        sys.modules["app.markdown.Conversion_markdown"] = conversion
        import app.markdown

        app.markdown.Conversion_markdown = conversion

    def test_import_paths_cover_torch_missing_env_gpu_and_main_guard(self):
        real_import = __import__

        def import_without_torch(name, *args, **kwargs):
            if name == "torch":
                raise ImportError("torch missing")
            return real_import(name, *args, **kwargs)

        sys.modules.pop("app.markdown.Conversion_markdown", None)
        with patch("builtins.__import__", side_effect=import_without_torch):
            imported = importlib.import_module("app.markdown.Conversion_markdown")
        self.assertIsNone(imported.torch)

        sys.modules.pop("app.markdown.Conversion_markdown", None)
        with patch.dict(os.environ, {"OLLAMA_NUM_GPU": "2"}):
            imported = importlib.import_module("app.markdown.Conversion_markdown")
        self.assertEqual(imported.DEFAULT_NUM_GPU, 2)
        self.assertEqual(imported.OLLAMA_NUM_GPU_SOURCE, "env")

        sys.modules["app.markdown.Conversion_markdown"] = conversion

        import runpy

        with patch.object(sys, "argv", ["Conversion_markdown.py"]):
            with self.assertRaises(SystemExit):
                runpy.run_module("app.markdown.Conversion_markdown", run_name="__main__")

    def test_import_auto_gpu_configuration_uses_cpu_when_cuda_is_unavailable(self):
        imported = _import_conversion_with_torch(cuda_available=False)

        self.assertEqual(imported.DEFAULT_NUM_GPU, 0)
        self.assertEqual(imported.OLLAMA_NUM_GPU_SOURCE, "auto-cpu")

    def test_import_auto_gpu_configuration_uses_full_offload_when_cuda_is_available(self):
        imported = _import_conversion_with_torch(cuda_available=True)

        self.assertEqual(imported.DEFAULT_NUM_GPU, -1)
        self.assertEqual(imported.OLLAMA_NUM_GPU_SOURCE, "auto-cuda-full-offload")

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

        empty = MagicMock(text="")
        empty.json.side_effect = ValueError
        self.assertEqual(conversion._response_error_details(empty), "sin cuerpo de respuesta")

        list_response = MagicMock()
        list_response.json.return_value = ["x"]
        self.assertEqual(conversion._response_error_details(list_response), "['x']")

    def test_ocr_backend_and_page_failure_markdown(self):
        original_gpu = conversion.DEFAULT_NUM_GPU
        original_source = conversion.OLLAMA_NUM_GPU_SOURCE
        original_torch = conversion.torch
        try:
            conversion.DEFAULT_NUM_GPU = -1
            conversion.OLLAMA_NUM_GPU_SOURCE = "test"
            conversion.torch = None
            self.assertIn("GPU solicitada", conversion._ocr_execution_backend())

            fake_cuda = MagicMock()
            fake_cuda.is_available.return_value = True
            fake_cuda.get_device_name.return_value = "GPU Fake"
            fake_cuda.device_count.return_value = 2
            conversion.torch = MagicMock(cuda=fake_cuda)
            self.assertIn("GPU Fake", conversion._ocr_execution_backend())

            conversion.DEFAULT_NUM_GPU = 3
            self.assertIn("GPU parcial", conversion._ocr_execution_backend())

            conversion.DEFAULT_NUM_GPU = 0
            self.assertIn("CPU", conversion._ocr_execution_backend())
        finally:
            conversion.DEFAULT_NUM_GPU = original_gpu
            conversion.OLLAMA_NUM_GPU_SOURCE = original_source
            conversion.torch = original_torch

        markdown = conversion._page_failure_markdown(1, 3, RuntimeError("linea 1\nlinea 2"))
        self.assertIn("linea 1 linea 2", markdown)

    def test_service_url_from_env_handles_scheme_and_existing_url(self):
        with patch.dict(os.environ, {"OCR_URL": "host:123", "OCR_URL_SCHEME": "https"}):
            self.assertEqual(conversion._service_url_from_env("OCR_URL", "fallback"), "https://host:123")
        with patch.dict(os.environ, {"OCR_URL": "http://ready/"}):
            self.assertEqual(conversion._service_url_from_env("OCR_URL", "fallback"), "http://ready")

    def test_clean_index_dots_removes_dot_leaders_and_dot_only_lines(self):
        markdown = "1. OBJETO............. 3\n.....\nTexto normal"

        self.assertEqual(conversion.clean_index_dots(markdown), "1. OBJETO 3\nTexto normal")

    def test_heading_helpers_cover_invalid_and_skip_paths(self):
        self.assertTrue(conversion._should_skip_line("", ""))
        self.assertTrue(conversion._should_skip_line("# Title", "# Title"))
        self.assertTrue(conversion._should_skip_line(" line", "line"))
        self.assertFalse(conversion._should_skip_line("line", "line"))
        self.assertFalse(conversion._is_mostly_upper("1234"))
        self.assertFalse(conversion._is_mostly_upper("Titulo normal"))

        self.assertIsNone(conversion._split_numeric_heading("1 Title", 1))
        self.assertIsNone(conversion._split_numeric_heading("1.", 1))
        self.assertIsNone(conversion._split_numeric_heading("1.1. Title", 1))
        self.assertIsNone(conversion._split_numeric_heading("123. Title", 1))
        self.assertEqual(conversion._split_numeric_heading("1. Title", 1), ("1", "Title"))

        self.assertIsNone(conversion._split_letter_code_heading("G. Texto"))
        self.assertIsNone(conversion._split_letter_code_heading("g.1. Texto"))
        self.assertIsNone(conversion._split_letter_code_heading("G-1. Texto"))
        self.assertIsNone(conversion._split_letter_code_heading("G.a. Texto"))
        self.assertEqual(conversion._split_letter_code_heading("G.2. Texto"), ("G.2.", "Texto"))

        self.assertIsNone(conversion._process_single_level_heading("1. titulo minuscula"))
        self.assertIsNone(conversion._process_level2_heading("1. Texto"))
        self.assertIsNone(conversion._process_level3_heading("1.1. Texto"))
        self.assertIsNone(conversion._process_letter_code_heading("Texto"))

    def test_normalize_headings_converts_supported_heading_patterns(self):
        markdown = "\n# Ya\n1. OBJETO DEL CONTRATO\n1.1. Alcance\n1.1.1. Detalle\nG.2.2. Codigo\n- 1. Lista\nTexto normal"

        normalized = conversion.normalize_headings(markdown)

        self.assertIn("# 1. OBJETO DEL CONTRATO", normalized)
        self.assertIn("## 1.1. Alcance", normalized)
        self.assertIn("### 1.1.1. Detalle", normalized)
        self.assertIn("### G.2.2. Codigo", normalized)
        self.assertIn("- 1. Lista", normalized)
        self.assertIn("Texto normal", normalized)

    def test_post_ollama_chat_async_returns_json_payload(self):
        response = MagicMock()
        response.raise_for_status.return_value = None
        response.json.return_value = {"message": {"content": "ok"}}
        client = MagicMock()
        client.post = AsyncMock(return_value=response)

        result = conversion.asyncio.run(conversion._post_ollama_chat_async(client, {"payload": True}))

        self.assertEqual(result, {"message": {"content": "ok"}})
        client.post.assert_awaited_once_with("/api/chat", json={"payload": True})

    def test_post_ollama_chat_async_wraps_timeout_http_status_and_json_errors(self):
        client = MagicMock()
        client.post = AsyncMock(side_effect=conversion.httpx.TimeoutException("slow"))
        with self.assertRaises(conversion.OllamaOCRException):
            conversion.asyncio.run(conversion._post_ollama_chat_async(client, {}))

        client.post = AsyncMock(side_effect=conversion.httpx.HTTPError("down"))
        with self.assertRaises(conversion.OllamaOCRException):
            conversion.asyncio.run(conversion._post_ollama_chat_async(client, {}))

        response = MagicMock(status_code=500)
        response.json.return_value = {"error": "boom"}
        response.raise_for_status.side_effect = conversion.httpx.HTTPStatusError(
            "bad",
            request=MagicMock(),
            response=response,
        )
        client.post = AsyncMock(return_value=response)
        with self.assertRaises(conversion.OllamaOCRException) as ctx:
            conversion.asyncio.run(conversion._post_ollama_chat_async(client, {}))
        self.assertIn("HTTP 500", str(ctx.exception))

        response = MagicMock()
        response.raise_for_status.return_value = None
        response.json.side_effect = ValueError
        client.post = AsyncMock(return_value=response)
        with self.assertRaises(conversion.OllamaOCRException):
            conversion.asyncio.run(conversion._post_ollama_chat_async(client, {}))

    def test_pdf_info_page_render_and_resize_helpers(self):
        pdf_path = Path("doc.pdf")
        with patch("app.markdown.Conversion_markdown.pdfinfo_from_path", return_value={"Pages": "2"}):
            self.assertEqual(conversion.get_pdf_page_count(pdf_path), 2)
        with patch("app.markdown.Conversion_markdown.pdfinfo_from_path", return_value={"Pages": "0"}):
            with self.assertRaises(RuntimeError):
                conversion.get_pdf_page_count(pdf_path)

        output_dir = Path(tempfile.mkdtemp())
        image = MagicMock()
        with patch("app.markdown.Conversion_markdown.convert_from_path", return_value=[image]) as mock_convert:
            img_path = conversion.pdf_page_to_image(pdf_path, 3, output_dir, dpi=150)
        self.assertEqual(img_path, output_dir / "doc_page_3.png")
        image.save.assert_called_once_with(img_path, "PNG")
        self.assertEqual(mock_convert.call_args.kwargs["first_page"], 3)

        with patch("app.markdown.Conversion_markdown.convert_from_path", return_value=[]):
            with self.assertRaises(RuntimeError):
                conversion.pdf_page_to_image(pdf_path, 1, output_dir)

    def test_resize_image_for_ocr_returns_original_or_resized_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            image_path = Path(tmp) / "page.png"
            image_path.write_bytes(b"fake")
            small = MagicMock()
            small.__enter__.return_value = small
            small.__exit__.return_value = False
            small.size = (100, 80)
            with patch("app.markdown.Conversion_markdown.Image.open", return_value=small):
                self.assertEqual(conversion.resize_image_for_ocr(image_path, 200), image_path)

            large = MagicMock()
            large.__enter__.return_value = large
            large.__exit__.return_value = False
            large.size = (2000, 1000)
            resized = MagicMock()
            large.resize.return_value = resized
            with patch("app.markdown.Conversion_markdown.Image.open", return_value=large):
                resized_path = conversion.resize_image_for_ocr(image_path, 1000)
            self.assertEqual(resized_path.name, "page_max1000.png")
            large.resize.assert_called_once()
            resized.save.assert_called_once_with(resized_path, "PNG", optimize=True)

    def test_ocr_page_success_retries_fallback_and_final_failure(self):
        with tempfile.TemporaryDirectory() as tmp:
            image_path = Path(tmp) / "page.png"
            image_path.write_bytes(b"image")
            resized_path = Path(tmp) / "page_small.png"
            resized_path.write_bytes(b"small")
            original_sides = conversion.OCR_RETRY_MAX_IMAGE_SIDES
            original_gpu = conversion.DEFAULT_NUM_GPU
            try:
                conversion.OCR_RETRY_MAX_IMAGE_SIDES = [1000]
                conversion.DEFAULT_NUM_GPU = -1
                with patch("app.markdown.Conversion_markdown.resize_image_for_ocr", return_value=resized_path), patch(
                    "app.markdown.Conversion_markdown._post_ollama_chat_async",
                    AsyncMock(return_value={"message": {"content": "markdown"}}),
                ) as mock_post:
                    result = conversion.asyncio.run(conversion.ocr_page_with_nanonets_async(MagicMock(), image_path, 1, 2))
                self.assertEqual(result, "markdown")
                self.assertFalse(resized_path.exists())
                self.assertEqual(mock_post.call_args.args[1]["options"]["num_gpu"], -1)

                resized_path.write_bytes(b"small")
                with patch("app.markdown.Conversion_markdown.resize_image_for_ocr", return_value=image_path), patch(
                    "app.markdown.Conversion_markdown._post_ollama_chat_async",
                    AsyncMock(side_effect=[KeyError("message"), {"message": {"content": "cpu ok"}}]),
                ) as mock_post:
                    result = conversion.asyncio.run(conversion.ocr_page_with_nanonets_async(MagicMock(), image_path, 1, 2))
                self.assertEqual(result, "cpu ok")
                self.assertEqual(mock_post.call_count, 2)

                with patch("app.markdown.Conversion_markdown.resize_image_for_ocr", return_value=resized_path), patch(
                    "app.markdown.Conversion_markdown._post_ollama_chat_async",
                    AsyncMock(side_effect=conversion.OllamaOCRException("nope")),
                ), patch.object(Path, "unlink", side_effect=OSError):
                    with self.assertRaises(conversion.OllamaOCRException):
                        conversion.asyncio.run(conversion.ocr_page_with_nanonets_async(MagicMock(), image_path, 1, 2))
            finally:
                conversion.OCR_RETRY_MAX_IMAGE_SIDES = original_sides
                conversion.DEFAULT_NUM_GPU = original_gpu

    def test_process_pdf_async_success_placeholder_raise_and_unlink_error(self):
        class AsyncClientContext:
            def __init__(self, **_kwargs):
                pass

            async def __aenter__(self):
                return self

            async def __aexit__(self, *_args):
                return False

        pdf_path = Path("doc.pdf")
        callbacks = []
        image_path = Path(tempfile.mkdtemp()) / "page.png"
        image_path.write_text("img")
        with patch("app.markdown.Conversion_markdown.get_pdf_page_count", return_value=1), patch(
            "app.markdown.Conversion_markdown.pdf_page_to_image",
            return_value=image_path,
        ), patch(
            "app.markdown.Conversion_markdown.ocr_page_with_nanonets_async",
            AsyncMock(return_value="1. TITULO............. 3"),
        ), patch("app.markdown.Conversion_markdown.httpx.AsyncClient", AsyncClientContext):
            result = conversion.asyncio.run(conversion.process_pdf_async(pdf_path, on_page_start=lambda *args: callbacks.append(args)))
        self.assertIn("# 1. TITULO 3", result)
        self.assertEqual(callbacks, [(1, 1)])

        image_path.write_text("img")
        original_mode = conversion.OCR_PAGE_FAILURE_MODE
        try:
            conversion.OCR_PAGE_FAILURE_MODE = "placeholder"
            with patch("app.markdown.Conversion_markdown.get_pdf_page_count", return_value=1), patch(
                "app.markdown.Conversion_markdown.pdf_page_to_image",
                return_value=image_path,
            ), patch(
                "app.markdown.Conversion_markdown.ocr_page_with_nanonets_async",
                AsyncMock(side_effect=conversion.OllamaOCRException("fallo")),
            ), patch("app.markdown.Conversion_markdown.httpx.AsyncClient", AsyncClientContext), patch.object(
                Path,
                "unlink",
                side_effect=OSError,
            ):
                result = conversion.asyncio.run(conversion.process_pdf_async(pdf_path))
            self.assertIn("OCR no disponible", result)

            conversion.OCR_PAGE_FAILURE_MODE = "raise"
            with patch("app.markdown.Conversion_markdown.get_pdf_page_count", return_value=1), patch(
                "app.markdown.Conversion_markdown.pdf_page_to_image",
                return_value=image_path,
            ), patch(
                "app.markdown.Conversion_markdown.ocr_page_with_nanonets_async",
                AsyncMock(side_effect=conversion.OllamaOCRException("fallo")),
            ), patch("app.markdown.Conversion_markdown.httpx.AsyncClient", AsyncClientContext):
                with self.assertRaises(conversion.OllamaOCRException):
                    conversion.asyncio.run(conversion.process_pdf_async(pdf_path))
        finally:
            conversion.OCR_PAGE_FAILURE_MODE = original_mode

    def test_process_pdf_save_markdown_and_main_paths(self):
        pdf_path = Path("doc.pdf")
        with patch("app.markdown.Conversion_markdown.process_pdf_async", AsyncMock(return_value="md")):
            self.assertEqual(conversion.process_pdf(pdf_path), "md")

        with tempfile.TemporaryDirectory() as tmp:
            output_dir = Path(tmp) / "out"
            with patch("app.markdown.Conversion_markdown.process_pdf", return_value="# Markdown") as mock_process:
                out_path = conversion.save_markdown_to_file(pdf_path, output_dir)
            self.assertEqual(out_path.read_text(encoding="utf-8"), "# Markdown")
            mock_process.assert_called_once()

            in_dir = Path(tmp) / "in"
            in_dir.mkdir()
            with patch.object(sys, "argv", ["cmd", str(in_dir), str(output_dir)]):
                with self.assertRaises(SystemExit):
                    conversion.main()

            (in_dir / "a.pdf").write_text("pdf")
            (in_dir / "b.pdf").write_text("pdf")
            with patch.object(sys, "argv", ["cmd", str(in_dir), str(output_dir)]), patch(
                "app.markdown.Conversion_markdown.save_markdown_to_file",
            ) as mock_save:
                conversion.main()
            self.assertEqual(mock_save.call_count, 2)

        with patch.object(sys, "argv", ["cmd"]):
            with self.assertRaises(SystemExit):
                conversion.main()
