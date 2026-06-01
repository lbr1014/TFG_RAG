"""
Autora: Lydia Blanco Ruiz
Script con pruebas unitarias para el modulo DescargarPliegos.py, encargado de localizar, extraer y descargar los pliegos asociados a las 
licitaciones obtenidas previamente durante el proceso de scraping. Las pruebas verifican la identificación de documentos relevantes, 
la extracción de enlaces, la descarga de archivos PDF, la generación de ficheros JSON de resultados y la correcta gestión de errores 
producidos durante las operaciones de red y almacenamiento.
"""

import importlib
import importlib.util
import json
import sys
import types
import unittest
from collections import defaultdict
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, mock_open, patch


def _module_available(name):
    """
    Verifica si un módulo opcional está disponible.
    """
    try:
        return importlib.util.find_spec(name) is not None
    except (ImportError, ValueError):
        return False


def _install_optional_dependency_stubs():
    """
    Instala stubs para dependencias opcionales si no están disponibles.
    """
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
descargar = importlib.import_module("app.main.code.services.web_scraping.DescargarPliegos")


class AsyncContext:
    """
    Mock de context manager asíncrono para simular aiofiles.open y otros contextos asíncronos.
    """
    def __init__(self, value=None):
        """
        Inicializa el context manager con un valor opcional que se devolverá en __aenter__.
        """
        self.value = value

    async def __aenter__(self):
        """
        Devuelve el valor configurado al entrar en el contexto asíncrono.
        """
        return self.value

    async def __aexit__(self, *_args):
        """
        Sale del contesto asíncrono. Devuelve Flase para indicar que no se ha manejado ninguna excepción, permitiendo que se propaguen normalmente.
        """
        return False


class DescargarPliegosUnitTest(unittest.TestCase):
    def test_limpiar_expediente_replaces_invalid_filename_characters(self):
        """
        Verifica que los identificadores de expediente se transforman correctamente en nombres de archivo válidos.
        """
        self.assertEqual(descargar.limpiar_expediente(" EXP/123:ABC. "), "EXP_123_ABC")
        self.assertEqual(descargar.limpiar_expediente("..."), "expediente")

    def test_es_pliego_detects_pliego_names(self):
        """
        Comprueba que el sistema identifica correctamente los documentos que corresponden a pliegos.
        """
        self.assertTrue(descargar.es_pliego("Pliego de clausulas"))
        self.assertFalse(descargar.es_pliego("Anuncio de licitacion"))
        self.assertFalse(descargar.es_pliego(""))

    def test_primera_url_returns_first_pipe_separated_url(self):
        """
        Verifica la extracción de la primera URL válida de una lista de enlaces separados por barras verticales.
        """
        self.assertEqual(descargar.primera_url({"Ver documentos (urls)": "http://a|http://b"}), "http://a")
        self.assertEqual(descargar.primera_url({}), "")

    def test_iterar_paginas_yields_only_pliegos_with_urls(self):
        """
        Comprueba que únicamente se procesan los pliegos que disponen de enlaces válidos asociados.
        """
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
        """
        Verifica la generación de tareas asíncronas para procesar las páginas que contienen pliegos descargables.
        """
        with patch("app.main.code.services.web_scraping.DescargarPliegos.procesar_pagina_pliego", new=MagicMock(return_value="task")) as mock_process:
            tasks = descargar.get_paginas("context", [{"datos": {"Expediente": "EXP", "Documentos": [{"Documento": "Pliego", "Ver documentos (urls)": "url"}]}}], {})

        self.assertEqual(tasks, ["task"])
        mock_process.assert_called_once()

    def test_import_ignores_oserror_in_chmod_and_unlink_cleanup(self):
        """
        Comprueba que los errores del sistema de archivos durante tareas de limpieza no interrumpen la carga del módulo.
        """
        original_module = descargar
        try:
            with patch.object(original_module, "_project_root", return_value=Path.cwd()), patch(
                "pathlib.Path.mkdir", return_value=None
            ), patch("pathlib.Path.chmod", side_effect=OSError("chmod")), patch(
                "pathlib.Path.open", mock_open()
            ), patch("pathlib.Path.unlink", side_effect=OSError("unlink")):
                importlib.reload(original_module)
        finally:
            importlib.reload(original_module)

    def test_descargar_pdf_es_returns_false_for_non_pdf_response(self):
        """
        Verifica que se rechazan correctamente respuestas que no contienen documentos PDF válidos.
        """
        response = MagicMock(ok=True, headers={"content-type": "text/plain"})
        response.body = AsyncMock(return_value=b"html")
        context = MagicMock()
        context.request.get = AsyncMock(return_value=response)

        result = descargar.asyncio.run(descargar.descargar_pdf_es(context, "http://x", "EXP", "Pliego", 1))

        self.assertFalse(result)

    def test_descargar_pdf_es_handles_network_http_body_and_write_errors(self):
        """
        Comprueba la gestión de errores de red, respuestas HTTP inválidas y fallos durante la escritura de archivos descargados.
        """
        context = MagicMock()
        context.request.get = AsyncMock(side_effect=RuntimeError("network"))
        result = descargar.asyncio.run(descargar.descargar_pdf_es(context, "http://x", "EXP", "Pliego", 1))
        self.assertFalse(result)

        response = MagicMock(ok=False, status=500, headers={})
        context.request.get = AsyncMock(return_value=response)
        result = descargar.asyncio.run(descargar.descargar_pdf_es(context, "http://x", "EXP", "Pliego", 1))
        self.assertFalse(result)

        response = MagicMock(ok=True, headers={"content-type": "application/pdf"})
        response.body = AsyncMock(side_effect=RuntimeError("body"))
        context.request.get = AsyncMock(return_value=response)
        result = descargar.asyncio.run(descargar.descargar_pdf_es(context, "http://x", "EXP", "Pliego", 1))
        self.assertFalse(result)

        response.body = AsyncMock(return_value=b"%PDF-1.4")
        bad_handle = AsyncMock()
        bad_handle.write.side_effect = RuntimeError("write")
        with patch("app.main.code.services.web_scraping.DescargarPliegos.aiofiles.open", return_value=AsyncContext(bad_handle)):
            result = descargar.asyncio.run(descargar.descargar_pdf_es(context, "http://x", "EXP", "Pliego", 1))
        self.assertFalse(result)

    def test_descargar_pdf_es_saves_pdf_response(self):
        """
        Verifica que los documentos PDF válidos se descargan y almacenan correctamente.
        """
        response = MagicMock(ok=True, headers={"content-type": "application/pdf"})
        response.body = AsyncMock(return_value=b"%PDF-1.4")
        context = MagicMock()
        context.request.get = AsyncMock(return_value=response)
        file_handle = AsyncMock()

        with patch("app.main.code.services.web_scraping.DescargarPliegos.aiofiles.open", return_value=AsyncContext(file_handle)) as mock_open:
            result = descargar.asyncio.run(descargar.descargar_pdf_es(context, "http://x", "EXP/1", "Pliego tecnico", 2))

        self.assertTrue(result)
        self.assertEqual(mock_open.call_args.args[1], "wb")
        file_handle.write.assert_awaited_once_with(b"%PDF-1.4")

    def test_extraer_urls_pliegos_desde_pagina_handles_navigation_error(self):
        """
        Comprueba la gestión de errores producidos durante la navegación a páginas que contienen documentos.
        """
        page = MagicMock()
        page.goto = AsyncMock(side_effect=RuntimeError("goto"))
        page.close = AsyncMock()
        context = MagicMock()
        context.new_page = AsyncMock(return_value=page)

        result = descargar.asyncio.run(
            descargar.extraer_urls_pliegos_desde_pagina(context, "http://x", "EXP", "Pliego")
        )

        self.assertEqual(result, [])
        page.close.assert_awaited_once()

    def test_extraer_urls_pliegos_desde_pagina_extracts_links_and_skips_invalid_ones(self):
        """
        Verifica la extracción de enlaces válidos y el descarte de enlaces incorrectos o vacíos.
        """
        good_locator = MagicMock()
        good_locator.count = AsyncMock(return_value=1)
        good_locator.first.get_attribute = AsyncMock(return_value="http://pdf")

        no_href = MagicMock()
        no_href.count = AsyncMock(return_value=1)
        no_href.first.get_attribute = AsyncMock(return_value="")

        page = MagicMock()
        page.goto = AsyncMock()
        page.close = AsyncMock()
        page.get_by_role = MagicMock(side_effect=[good_locator, no_href])
        context = MagicMock()
        context.new_page = AsyncMock(return_value=page)

        result = descargar.asyncio.run(
            descargar.extraer_urls_pliegos_desde_pagina(context, "http://x", "EXP", "Pliego")
        )

        self.assertEqual(result, [("Pliego Prescripciones Técnicas", "http://pdf")])
        page.close.assert_awaited_once()

    def test_extraer_urls_pliegos_desde_pagina_continues_on_locator_errors_and_missing_links(self):
        """
        Comprueba que el proceso continúa correctamente cuando se producen errores al localizar elementos o faltan enlaces.
        """
        bad_locator = MagicMock()
        bad_locator.count = AsyncMock(side_effect=RuntimeError("count"))
        missing_locator = MagicMock()
        missing_locator.count = AsyncMock(return_value=0)

        page = MagicMock()
        page.goto = AsyncMock()
        page.close = AsyncMock()
        page.get_by_role = MagicMock(side_effect=[bad_locator, missing_locator])
        context = MagicMock()
        context.new_page = AsyncMock(return_value=page)

        result = descargar.asyncio.run(
            descargar.extraer_urls_pliegos_desde_pagina(context, "http://x", "EXP", "Pliego")
        )

        self.assertEqual(result, [])

    def test_procesar_pagina_pliego_extends_dictionary_only_when_urls_exist(self):
        """
        Verifica que únicamente se almacenan resultados cuando se encuentran URLs válidas asociadas a un expediente.
        """
        dic_urls = defaultdict(list)
        with patch(
            "app.main.code.services.web_scraping.DescargarPliegos.extraer_urls_pliegos_desde_pagina",
            new=AsyncMock(return_value=[("Doc", "url")]),
        ):
            descargar.asyncio.run(descargar.procesar_pagina_pliego("ctx", "url", "EXP", "Pliego", dic_urls))
        self.assertEqual(dic_urls["EXP"], [("Doc", "url")])

        with patch(
            "app.main.code.services.web_scraping.DescargarPliegos.extraer_urls_pliegos_desde_pagina",
            new=AsyncMock(return_value=[]),
        ):
            descargar.asyncio.run(descargar.procesar_pagina_pliego("ctx", "url", "EXP2", "Pliego", dic_urls))
        self.assertNotIn("EXP2", dic_urls)

    def test_write_json_uses_aiofiles_with_serialized_payload(self):
        """
        Comprueba la escritura correcta de resultados serializados en formato JSON.
        """
        file_handle = AsyncMock()
        context_manager = MagicMock()
        context_manager.__aenter__ = AsyncMock(return_value=file_handle)
        context_manager.__aexit__ = AsyncMock(return_value=None)

        with patch("app.main.code.services.web_scraping.DescargarPliegos.aiofiles.open", return_value=context_manager) as mock_open:
            descargar.asyncio.run(descargar.write_json(Path("out.json"), {"EXP": [("doc", "url")]}))

        mock_open.assert_called_once_with(Path("out.json"), "w", encoding="utf-8")
        file_handle.write.assert_awaited_once()

    def test_run_extracts_downloads_writes_and_closes_playwright_resources(self):
        """
        Verifica el flujo completo de extracción, descarga y almacenamiento de pliegos, incluyendo la liberación de recursos de Playwright.
        """
        async def add_pdf(_context, _items, dic_urls):
            await descargar.asyncio.sleep(0)
            dic_urls["EXP"].append(("Pliego tecnico", "http://pdf"))

        browser = MagicMock()
        browser.new_context = AsyncMock()
        browser.close = AsyncMock()
        context = MagicMock()
        context.close = AsyncMock()
        browser.new_context.return_value = context
        playwright = MagicMock()
        playwright.chromium.launch = AsyncMock(return_value=browser)

        with patch("app.main.code.services.web_scraping.DescargarPliegos.RUTA_JSON") as mock_input, patch(
            "app.main.code.services.web_scraping.DescargarPliegos.async_playwright", return_value=AsyncContext(playwright)
        ), patch("app.main.code.services.web_scraping.DescargarPliegos.get_paginas", side_effect=lambda ctx, items, dic: [add_pdf(ctx, items, dic)]), patch(
            "app.main.code.services.web_scraping.DescargarPliegos.descargar_pdf_es", new=MagicMock(side_effect=lambda **_kwargs: descargar.asyncio.sleep(0))
        ) as mock_download, patch(
            "app.main.code.services.web_scraping.DescargarPliegos.write_json", new=AsyncMock()
        ) as mock_write:
            mock_input.read_text.return_value = json.dumps([{"datos": {"Expediente": "EXP"}}])
            descargar.asyncio.run(descargar.run())

        mock_download.assert_called_once()
        mock_write.assert_awaited_once()
        context.close.assert_awaited_once()
        browser.close.assert_awaited_once()

    def test_main_guard_runs_async_entrypoint(self):
        """
        Comprueba que la ejecución directa del script invoca correctamente el punto de entrada asíncrono principal.
        """
        import runpy

        def close_coroutine(coro):
            coro.close()

        with patch("app.main.code.services.web_scraping.DescargarPliegos.run", new=AsyncMock()), patch("asyncio.run", side_effect=close_coroutine) as mock_asyncio_run:
            runpy.run_module("app.main.code.services.web_scraping.DescargarPliegos", run_name="__main__")

        mock_asyncio_run.assert_called_once()
