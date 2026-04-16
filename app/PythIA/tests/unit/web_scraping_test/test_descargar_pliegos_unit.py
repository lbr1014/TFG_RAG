import importlib
import importlib.util
import sys
import types
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch


def _module_available(name):
    try:
        return importlib.util.find_spec(name) is not None
    except (ImportError, ValueError):
        return False


def _install_optional_dependency_stubs():
    if not _module_available("aiofiles") and "aiofiles" not in sys.modules:
        aiofiles = types.ModuleType("aiofiles")
        aiofiles.open = MagicMock()
        sys.modules["aiofiles"] = aiofiles

    if _module_available("playwright"):
        return

    if "playwright" not in sys.modules:
        playwright = types.ModuleType("playwright")
        sys.modules["playwright"] = playwright

    if "playwright.async_api" not in sys.modules:
        async_api = types.ModuleType("playwright.async_api")
        sys.modules["playwright.async_api"] = async_api

    async_api = sys.modules["playwright.async_api"]
    if not hasattr(async_api, "async_playwright"):
        async_api.async_playwright = MagicMock()


_install_optional_dependency_stubs()
descargar = importlib.import_module("app.web_scraping.DescargarPliegos")


class DescargarPliegosUnitTest(unittest.TestCase):
    def test_limpiar_expediente_replaces_invalid_filename_characters(self):
        self.assertEqual(descargar.limpiar_expediente(" EXP/123:ABC. "), "EXP_123_ABC")
        self.assertEqual(descargar.limpiar_expediente("..."), "expediente")

    def test_es_pliego_detects_pliego_names(self):
        self.assertTrue(descargar.es_pliego("Pliego de clausulas"))
        self.assertFalse(descargar.es_pliego("Anuncio de licitacion"))
        self.assertFalse(descargar.es_pliego(""))

    def test_primera_url_returns_first_pipe_separated_url(self):
        self.assertEqual(descargar.primera_url({"Ver documentos (urls)": "http://a|http://b"}), "http://a")
        self.assertEqual(descargar.primera_url({}), "")

    def test_iterar_paginas_yields_only_pliegos_with_urls(self):
        items = [
            {
                "datos": {
                    "Expediente": "EXP-1",
                    "Documentos": [
                        {"Documento": "Pliego tecnico", "Ver documentos (urls)": "http://pliego|http://otro"},
                        {"Documento": "Anuncio", "Ver documentos (urls)": "http://anuncio"},
                    ],
                }
            },
            {"datos": {"Documentos": [{"Documento": "Pliego sin expediente", "Ver documentos (urls)": "http://x"}]}},
        ]

        self.assertEqual(list(descargar.iterar_paginas(items)), [("EXP-1", "Pliego tecnico", "http://pliego")])

    def test_get_paginas_builds_coroutines_for_iterated_pages(self):
        with patch("app.web_scraping.DescargarPliegos.procesar_pagina_pliego", new=MagicMock(return_value="task")) as mock_process:
            tasks = descargar.get_paginas("context", [{"datos": {"Expediente": "EXP", "Documentos": [{"Documento": "Pliego", "Ver documentos (urls)": "url"}]}}], {})

        self.assertEqual(tasks, ["task"])
        mock_process.assert_called_once()

    def test_descargar_pdf_es_returns_false_for_non_pdf_response(self):
        response = MagicMock(ok=True, headers={"content-type": "text/plain"})
        response.body = AsyncMock(return_value=b"html")
        context = MagicMock()
        context.request.get = AsyncMock(return_value=response)

        result = descargar.asyncio.run(descargar.descargar_pdf_es(context, "http://x", "EXP", "Pliego", 1))

        self.assertFalse(result)

    def test_write_json_uses_aiofiles_with_serialized_payload(self):
        file_handle = AsyncMock()
        context_manager = MagicMock()
        context_manager.__aenter__ = AsyncMock(return_value=file_handle)
        context_manager.__aexit__ = AsyncMock(return_value=None)

        with patch("app.web_scraping.DescargarPliegos.aiofiles.open", return_value=context_manager) as mock_open:
            descargar.asyncio.run(descargar.write_json(Path("out.json"), {"EXP": [("doc", "url")]}))

        mock_open.assert_called_once_with(Path("out.json"), "w", encoding="utf-8")
        file_handle.write.assert_awaited_once()
