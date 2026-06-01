"""
Autora: Lydia Blanco Ruiz
Script con pruebas unitarias del módulo PliegosPlaywrightAsincrono.py, encargado de realizar el scraping de licitaciones públicas mediante Playwright. 
Las pruebas verifican la navegación por la plataforma de contratación, la localización de elementos de la interfaz, la extracción de datos de las licitaciones, 
el procesamiento de tablas y documentos, la actualización de resultados y la gestión de errores durante la automatización del navegador.
"""

import asyncio
import importlib
import importlib.util
import json
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, mock_open, patch


def _module_available(name):
    """
    Comprueba si un módulo está disponible para importación.
    """
    try:
        return importlib.util.find_spec(name) is not None
    except (ImportError, ValueError):
        return False


def _install_optional_dependency_stubs():
    """
    Instala stubs para dependencias opcionales, permitiendo que las pruebas se ejecuten incluso si Playwright no está instalado.
    """
    if _module_available("playwright"):
        return

    class TimeoutErrorStub(Exception):
        """
        Stub para Playwright TimeoutError.
        """
        

    if "playwright" not in sys.modules:
        sys.modules["playwright"] = types.ModuleType("playwright")

    if "playwright.async_api" not in sys.modules:
        sys.modules["playwright.async_api"] = types.ModuleType("playwright.async_api")

    async_api = sys.modules["playwright.async_api"]
    async_api.Frame = getattr(async_api, "Frame", object)
    async_api.Page = getattr(async_api, "Page", object)
    async_api.Locator = getattr(async_api, "Locator", object)
    async_api.TimeoutError = getattr(async_api, "TimeoutError", TimeoutErrorStub)
    async_api.async_playwright = getattr(async_api, "async_playwright", MagicMock())
    async_api.expect = getattr(async_api, "expect", MagicMock())


_install_optional_dependency_stubs()
pliegos = importlib.import_module("app.main.code.services.web_scraping.PliegosPlaywrightAsincrono")


class AsyncContext:
    """
    Context manager asíncrono de prueba para simular expect_navigation.
    """
    def __init__(self, value=None):
        """
        Inicializa el contexto con un valor opcional.
        """
        self.value = value

    async def __aenter__(self):
        """
        Entra en el contexto asíncrono, devolviendo el valor configurado.
        """
        return self.value

    async def __aexit__(self, *_args):
        """
        Sale del contexto asíncrono sin manejar excepciones.
        """
        return False


class FakeLocator:
    """
    Locator de prueba para simular elementos de la interfaz en las pruebas unitarias.
    """
    def __init__(self, *, count=1, text="", attrs=None, children=None, nth_items=None, first=None, last=None):
        """
        Inicializa el locator con propiedades configurables para simular diferentes escenarios de prueba.
        """
        self._count = count
        self._text = text
        self._attrs = attrs or {}
        self._children = children or {}
        self._nth_items = nth_items or []
        self.first = first or self
        self.last = last or self
        self.wait_for = AsyncMock()
        self.scroll_into_view_if_needed = AsyncMock()
        self.click = AsyncMock()
        self.select_option = AsyncMock()

    async def count(self):
        """
        Devuelve el número de elementos encontrados por el locator.
        """
        await asyncio.sleep(0)
        return self._count

    async def inner_text(self):
        """
        Devuelve el texto interno del elemento localizado.
        """
        await asyncio.sleep(0)
        return self._text

    async def get_attribute(self, name):
        """
        Devuelve el valor de un atributo del elemento localizado.
        """
        await asyncio.sleep(0)
        return self._attrs.get(name)

    def locator(self, selector, **kwargs):
        """
        Devuelve un nuevo locator basado en un selector y opciones de búsqueda, simulando la búsqueda de elementos hijos.
        """
        key = (selector, "has_text") if "has_text" in kwargs else selector
        return self._children.get(key, FakeLocator(count=0))

    def nth(self, index):
        """
        Devuelve el locator correspondiente al índice especificado, simulando la selección de un elemento específico dentro de un conjunto.
        """
        return self._nth_items[index]


class FakePage:
    """
    Página de prueba para simular la interfaz de Playwright en las pruebas unitarias.
    """
    def __init__(self, *, url="https://contratacion.test/base/", locators=None):
        self.url = url
        self._locators = locators or {}
        self.wait_for_timeout = AsyncMock()
        self.wait_for_load_state = AsyncMock()
        self.goto = AsyncMock()
        self.title = AsyncMock(return_value="Titulo")
        self.set_default_timeout = MagicMock()
        self.set_default_navigation_timeout = MagicMock()

    def locator(self, selector):
        """
        Devuelve un locator basado en un selector, simulando la búsqueda de elementos en la página.
        """
        return self._locators.get(selector, FakeLocator(count=0))

    def get_by_role(self, *_args, **_kwargs):
        """
        Simula la búsqueda de elementos por rol, devolviendo un locator de prueba.
        """
        return FakeLocator()

    def expect_navigation(self, **_kwargs):
        """
        Simula el contexto de espera por navegación, devolviendo un contexto de prueba que puede ser utilizado en las pruebas unitarias.
        """
        return AsyncContext()


class PliegosPlaywrightAsincronoUnitTest(unittest.TestCase):
    def test_norm_collapses_whitespace(self):
        """
        Verifica la normalización de cadenas eliminando espacios y saltos de línea innecesarios.
        """
        self.assertEqual(pliegos._norm("  uno\n dos\t tres  "), "uno dos tres")

    def test_pestana_diputacion_maps_search_terms_to_tabs(self):
        """
        Comprueba la correspondencia entre términos de búsqueda y las pestañas de navegación de la plataforma.
        """
        self.assertEqual(pliegos.pestana_diputacion("ver documentos del pliego"), "Documentos")
        self.assertEqual(pliegos.pestana_diputacion("licitacion abierta"), "Licitaciones")
        self.assertEqual(pliegos.pestana_diputacion("contrato menor"), "Contratos Menores")
        self.assertEqual(pliegos.pestana_diputacion("encargo a medio propio"), "Encargos a medios propios")
        self.assertEqual(pliegos.pestana_diputacion("consulta preliminar"), "Consultas preliminares")
        self.assertEqual(pliegos.pestana_diputacion("sin coincidencia"), "perfil")

    def test_actualizar_por_expediente_inserts_and_updates_by_expediente(self):
        """
        Verifica la inserción y actualización de resultados utilizando el número de expediente como identificador único.
        """
        resultados = []
        index = {}
        first = {"datos": {"Expediente": "EXP-1", "valor": "a"}}
        updated = {"datos": {"Expediente": "EXP-1", "valor": "b"}}

        self.assertTrue(pliegos.actualizar_por_expediente(resultados, index, first))
        self.assertFalse(pliegos.actualizar_por_expediente(resultados, index, updated))

        self.assertEqual(resultados, [updated])
        self.assertEqual(index, {"EXP-1": 0})

    def test_actualizar_por_expediente_appends_items_without_expediente(self):
        """
        Comprueba la gestión de registros que no disponen de identificador de expediente.
        """
        resultados = []

        self.assertTrue(pliegos.actualizar_por_expediente(resultados, {}, {"datos": {}}))
        self.assertEqual(resultados, [{"datos": {}}])

    def test_cargar_resultados_existentes_returns_empty_for_missing_or_invalid_file(self):
        """
        Verifica el tratamiento de archivos inexistentes o con formato JSON inválido.
        """
        with patch("app.main.code.services.web_scraping.PliegosPlaywrightAsincrono.Path.exists", return_value=False):
            self.assertEqual(pliegos.cargar_resultados_existentes(), [])

        with patch("app.main.code.services.web_scraping.PliegosPlaywrightAsincrono.Path.exists", return_value=True), patch(
            "app.main.code.services.web_scraping.PliegosPlaywrightAsincrono.Path.open", mock_open(read_data="{")
        ):
            self.assertEqual(pliegos.cargar_resultados_existentes(), [])

    def test_cargar_resultados_existentes_returns_list_json(self):
        """
        Comprueba la carga correcta de resultados almacenados previamente en formato JSON.
        """
        data = [{"datos": {"Expediente": "EXP"}}]

        with patch("app.main.code.services.web_scraping.PliegosPlaywrightAsincrono.Path.exists", return_value=True), patch(
            "app.main.code.services.web_scraping.PliegosPlaywrightAsincrono.Path.open", mock_open(read_data=json.dumps(data))
        ):
            self.assertEqual(pliegos.cargar_resultados_existentes(), data)


class PliegosPlaywrightAsincronoAsyncUnitTest(unittest.IsolatedAsyncioTestCase):
    async def test_encontrar_frame_returns_first_frame_with_selector(self):
        """
        Verifica la localización del primer frame que contiene un selector determinado.
        """
        failing_frame = MagicMock()
        failing_frame.wait_for_selector = AsyncMock(side_effect=pliegos.PWTimeoutError("missing"))
        matching_frame = MagicMock()
        matching_frame.wait_for_selector = AsyncMock(return_value=None)
        page = MagicMock(frames=[failing_frame, matching_frame])

        result = await pliegos.encontrar_frame(page, "#selector", timeout_ms=1_000)

        self.assertIs(result, matching_frame)
        matching_frame.wait_for_selector.assert_awaited_once_with("#selector", timeout=800)

    async def test_encontrar_frame_raises_timeout_when_no_frame_matches(self):
        """
        Comprueba la generación de una excepción cuando no se encuentra el frame buscado dentro del tiempo establecido.
        """
        frame = MagicMock()
        frame.wait_for_selector = AsyncMock(side_effect=pliegos.PWTimeoutError("missing"))
        page = MagicMock(frames=[frame])

        with patch("app.main.code.services.web_scraping.PliegosPlaywrightAsincrono.time.monotonic", side_effect=[0, 1]), \
             patch("app.main.code.services.web_scraping.PliegosPlaywrightAsincrono.asyncio.sleep", new=AsyncMock()), \
             self.assertRaises(pliegos.PWTimeoutError):
            await pliegos.encontrar_frame(page, "#selector", timeout_ms=500)

    async def test_encontrar_frame_waits_between_failed_attempts(self):
        """
        Verifica el mecanismo de reintentos utilizado para localizar frames dinámicos.
        """
        frame = MagicMock()
        frame.wait_for_selector = AsyncMock(side_effect=[pliegos.PWTimeoutError("missing"), None])
        page = MagicMock(frames=[frame])

        with patch("app.main.code.services.web_scraping.PliegosPlaywrightAsincrono.time.monotonic", side_effect=[0, 0, 1]), patch(
            "app.main.code.services.web_scraping.PliegosPlaywrightAsincrono.asyncio.sleep", new=AsyncMock()
        ) as mock_sleep:
            result = await pliegos.encontrar_frame(page, "#selector", timeout_ms=2_000)

        self.assertIs(result, frame)
        mock_sleep.assert_awaited_once_with(0.25)

    async def test_eleccion_organo_selects_by_value_and_clicks_add(self):
        """
        Comprueba la selección de órganos de contratación utilizando el valor interno de la opción correspondiente.
        """
        option = FakeLocator(attrs={"value": "org-1"})
        select = FakeLocator(
            children={
                "option": FakeLocator(),
                ("option", "has_text"): option,
            }
        )
        add_button = FakeLocator()
        frame = MagicMock()
        frame.locator.return_value.first = select
        frame.get_by_role.return_value = add_button

        await pliegos.eleccion_organo(frame, "Diputacion")

        select.select_option.assert_awaited_once_with(value="org-1")
        add_button.click.assert_awaited_once()

    async def test_eleccion_organo_falls_back_to_label_when_option_has_no_value(self):
        """
        Verifica el uso de etiquetas visibles como alternativa cuando una opción no dispone de valor interno.
        """
        option = FakeLocator(attrs={"value": None})
        select = FakeLocator(
            children={
                "option": FakeLocator(),
                ("option", "has_text"): option,
            }
        )
        frame = MagicMock()
        frame.locator.return_value.first = select
        frame.get_by_role.return_value = FakeLocator()

        await pliegos.eleccion_organo(frame, "Diputacion")

        select.select_option.assert_awaited_once_with(label="Diputacion")

    async def test_ir_pestana_clicks_mapped_tab_and_waits(self):
        """
        Comprueba la navegación entre pestañas y la espera de los elementos necesarios para continuar el scraping.
        """
        locator = FakeLocator()
        page = FakePage()
        page.locator = MagicMock(return_value=MagicMock(first=locator))

        expected = MagicMock()
        expected.to_be_enabled = AsyncMock()
        with patch("app.main.code.services.web_scraping.PliegosPlaywrightAsincrono.expect", return_value=expected):
            await pliegos.ir_pestana(page, "Documentos")

        locator.wait_for.assert_awaited_once_with(state="visible")
        locator.click.assert_any_await(trial=True)
        locator.click.assert_any_await()
        self.assertEqual(page.wait_for_timeout.await_count, 2)

    async def test_ir_pestana_rejects_unknown_tab(self):
        """
        Verifica que no se permite acceder a pestañas desconocidas o no soportadas.
        """
        with self.assertRaises(ValueError):
            await pliegos.ir_pestana(FakePage(), "No existe")

    async def test_ir_pestana_wraps_timeout_and_ignores_optional_wait_error(self):
        """
        Comprueba la gestión de tiempos de espera y errores no críticos durante la navegación.
        """
        failing_locator = FakeLocator()
        failing_locator.wait_for = AsyncMock(side_effect=pliegos.PWTimeoutError("missing"))
        page = FakePage()
        page.locator = MagicMock(return_value=MagicMock(first=failing_locator))

        with self.assertRaises(pliegos.PWTimeoutError):
            await pliegos.ir_pestana(page, "Documentos")

        locator = FakeLocator()
        page = FakePage()
        page.locator = MagicMock(return_value=MagicMock(first=locator))
        page.wait_for_timeout = AsyncMock(side_effect=[RuntimeError("optional"), None])
        expected = MagicMock()
        expected.to_be_enabled = AsyncMock()
        with patch("app.main.code.services.web_scraping.PliegosPlaywrightAsincrono.expect", return_value=expected):
            await pliegos.ir_pestana(page, "Documentos")

        self.assertEqual(page.wait_for_timeout.await_count, 2)

    async def test_set_if_text_stores_normalized_text_only_when_present(self):
        """
        Verifica el almacenamiento de textos únicamente cuando contienen información válida.
        """
        datos = {}

        await pliegos.set_if_text(datos, "Campo", FakeLocator(text="  Valor\n normalizado "))
        await pliegos.set_if_text(datos, "Vacio", FakeLocator(count=0, text="nada"))

        self.assertEqual(datos, {"Campo": "Valor normalizado"})

    async def test_documentos_extract_links_joins_absolute_urls(self):
        """
        Comprueba la extracción y normalización de enlaces absolutos de documentos asociados a una licitación.
        """
        link_1 = FakeLocator(attrs={"href": "/doc/1"})
        link_2 = FakeLocator(attrs={"href": "#"})
        link_3 = FakeLocator(attrs={"href": "https://externo.test/doc/3"})
        links = FakeLocator(count=3, nth_items=[link_1, link_2, link_3])
        links_td = FakeLocator(children={"a[href]": links})
        datos = {}

        await pliegos.documentos_extract_links(FakePage(url="https://base.test/root/"), links_td, datos)

        self.assertEqual(
            datos["Ver documentos (urls)"],
            "https://base.test/doc/1 | https://externo.test/doc/3",
        )

    async def test_parse_documentos_doue_extracts_link_and_dates(self):
        """
        Verifica la extracción de enlaces y fechas relacionadas con publicaciones en el DOUE.
        """
        envio = FakeLocator(text="  Envio 01/01 ")
        publi_link = FakeLocator(text="  Publicacion 02/01 ", attrs={"href": "/doue"})
        doue_td = FakeLocator(
            children={
                ".flex span": FakeLocator(first=envio),
                "a[href]": FakeLocator(last=publi_link),
            }
        )
        row = FakeLocator(children={"td:nth-of-type(4)": doue_td})
        datos = {}

        await pliegos.parse_documentos_doue(FakePage(url="https://base.test/x/"), row, datos)

        self.assertEqual(datos["DOUE - Envío"], "Envio 01/01")
        self.assertEqual(datos["DOUE - Publicación"], "https://base.test/doue")
        self.assertEqual(datos["DOUE - Publicación (fecha)"], "Publicacion 02/01")

    async def test_parse_documentos_doue_uses_plain_publication_text_without_link(self):
        """
        Verifica la extracción de enlaces y fechas relacionadas con publicaciones en el DOUE.
        """
        publi_span = FakeLocator(text="Sin publicacion")
        doue_td = FakeLocator(
            children={
                ".flex span": FakeLocator(first=FakeLocator(count=0)),
                "a[href]": FakeLocator(count=0, last=FakeLocator(count=0)),
                "span.outputText": FakeLocator(first=publi_span),
            }
        )
        row = FakeLocator(children={"td:nth-of-type(4)": doue_td})
        datos = {}

        await pliegos.parse_documentos_doue(FakePage(), row, datos)

        self.assertEqual(datos, {"DOUE - Publicación (fecha)": "Sin publicacion"})

    async def test_parse_label_value_table_extracts_label_and_value_pairs(self):
        """
        Verifica la extracción de pares etiqueta-valor desde tablas informativas de licitación.
        """
        row_with_text = FakeLocator(
            children={
                "span.cl-blue-dark.bold, span[id*=':form1:label_']": FakeLocator(first=FakeLocator(text="Presupuesto")),
                "span[id*=':form1:text_']": FakeLocator(first=FakeLocator(text="  1000 EUR ")),
            }
        )
        row_with_right_col = FakeLocator(
            children={
                "span.cl-blue-dark.bold, span[id*=':form1:label_']": FakeLocator(first=FakeLocator(text="Procedimiento")),
                "span[id*=':form1:text_']": FakeLocator(count=0, first=FakeLocator(count=0)),
                "div.col-lg-8": FakeLocator(first=FakeLocator(text=" Abierto ")),
            }
        )
        rows = FakeLocator(count=2, nth_items=[row_with_text, row_with_right_col])
        table = FakeLocator(children={"tbody.tabla-detalle-con-hijos > tr": rows})
        datos = {}

        await pliegos.parse_label_value_table(FakePage(locators={"#tabla": table}), datos, "#tabla")

        self.assertEqual(datos, {"Presupuesto": "1000 EUR", "Procedimiento": "Abierto"})

    async def test_table_parsers_return_or_continue_when_tables_or_labels_are_missing(self):
        """
        Comprueba que el proceso continúa correctamente cuando faltan tablas o campos esperados.
        """
        datos = {"previo": "ok"}

        await pliegos.parse_head_table(FakePage(locators={"#head": FakeLocator(count=0)}), datos, "#head")
        await pliegos.parse_label_value_table(FakePage(locators={"#tabla": FakeLocator(count=0)}), datos, "#tabla")
        docs = await pliegos.parse_documentos(FakePage(locators={"#myTablaDetalleVISUOE": FakeLocator(count=0)}))

        row_without_label = FakeLocator(
            children={
                "span.cl-blue-dark.bold, span[id*=':form1:label_']": FakeLocator(count=0, first=FakeLocator(count=0))
            }
        )
        table = FakeLocator(children={"tbody.tabla-detalle-con-hijos > tr": FakeLocator(count=1, nth_items=[row_without_label])})
        await pliegos.parse_label_value_table(FakePage(locators={"#tabla2": table}), datos, "#tabla2")

        self.assertEqual(datos, {"previo": "ok"})
        self.assertIsNone(docs)

    async def test_parse_head_table_extracts_main_fields_and_resolves_links(self):
        """
        Verifica la extracción de los principales datos identificativos de una licitación.
        """
        row_0 = FakeLocator(
            children={
                "a[href][id*=':URLOrganoContratacion']": FakeLocator(first=FakeLocator(attrs={"href": "/organo"})),
                "span[id*=':form1:text_IdOrganoContratacion']": FakeLocator(first=FakeLocator(text=" ID-OC ")),
                "span[id*=':form1:text_UbicacionOrganica']": FakeLocator(first=FakeLocator(text=" Burgos ")),
            }
        )
        row_1 = FakeLocator(children={"span[id*=':form1:text_Expediente']": FakeLocator(first=FakeLocator(text=" EXP-1 "))})
        row_2 = FakeLocator(children={"span[id*=':form1:text_ObjetoContrato']": FakeLocator(first=FakeLocator(text=" Objeto "))})
        row_3 = FakeLocator(
            children={
                "a[href][id*=':form1:link_EnlaceLicPLACE']": FakeLocator(first=FakeLocator(attrs={"href": "/licitacion"}))
            }
        )
        rows = FakeLocator(nth_items=[row_0, row_1, row_2, row_3])
        head_table = FakeLocator(children={"tbody > tr": rows})
        datos = {}

        await pliegos.parse_head_table(FakePage(url="https://base.test/root/", locators={"#head": head_table}), datos, "#head")

        self.assertEqual(datos["Órgano de contratación"], "https://base.test/organo")
        self.assertEqual(datos["ID del Órgano de Contratación"], "ID-OC")
        self.assertEqual(datos["Ubicación orgánica"], "Burgos")
        self.assertEqual(datos["Expediente"], "EXP-1")
        self.assertEqual(datos["Objeto del contrato"], "Objeto")
        self.assertEqual(datos["Enlace a la licitación"], "https://base.test/licitacion")

    async def test_parse_documentos_builds_document_rows(self):
        """
        Comprueba la generación de estructuras de datos correspondientes a los documentos asociados a una licitación.
        """
        row = FakeLocator(
            children={
                "td:nth-of-type(1)": FakeLocator(text="Publicado"),
                "td:nth-of-type(2)": FakeLocator(text="Pliego tecnico"),
                "td:nth-of-type(3)": FakeLocator(children={"a[href]": FakeLocator(count=1, nth_items=[FakeLocator(attrs={"href": "/pdf"})])}),
                "td:nth-of-type(4)": FakeLocator(count=0),
            }
        )
        docs_table = FakeLocator(children={"tbody.tabla-detalle > tr": FakeLocator(count=1, nth_items=[row])})

        documentos = await pliegos.parse_documentos(
            FakePage(url="https://base.test/root/", locators={"#myTablaDetalleVISUOE": docs_table})
        )

        self.assertEqual(
            documentos,
            [
                {
                    "Publicación en plataforma": "Publicado",
                    "Documento": "Pliego tecnico",
                    "Ver documentos (urls)": "https://base.test/pdf",
                }
            ],
        )

    async def test_extraer_detalles_licitacion_combines_table_and_document_parsers(self):
        """
        Verifica la integración de los distintos analizadores encargados de extraer los detalles completos de una licitación.
        """
        
        with patch("app.main.code.services.web_scraping.PliegosPlaywrightAsincrono.parse_head_table", new=AsyncMock()) as mock_head, patch(
            "app.main.code.services.web_scraping.PliegosPlaywrightAsincrono.parse_label_value_table", new=AsyncMock()
        ) as mock_label, patch(
            "app.main.code.services.web_scraping.PliegosPlaywrightAsincrono.parse_documentos",
            new=AsyncMock(return_value=[{"Documento": "Pliego"}]),
        ):

            async def fill_head(_page, datos, _selector):
                await asyncio.sleep(0)
                datos["Expediente"] = "EXP-1"

            async def fill_label(_page, datos, selector):
                await asyncio.sleep(0)
                datos[selector] = "ok"

            mock_head.side_effect = fill_head
            mock_label.side_effect = fill_label

            datos = await pliegos.extraer_detalles_licitacion(FakePage())

        self.assertEqual(datos["Expediente"], "EXP-1")
        self.assertEqual(datos["Documentos"], [{"Documento": "Pliego"}])
        self.assertEqual(mock_label.await_count, 2)

    async def test_extraer_licitaciones_visits_rows_updates_and_stops_without_next_page(self):
        """
        Comprueba la extracción secuencial de licitaciones y la finalización correcta cuando no existen más páginas.
        """
        enlace = FakeLocator()
        row = FakeLocator(children={'td.tdExpediente a:not([target="_blank"])': FakeLocator(first=enlace)})
        rows = FakeLocator(count=1, nth_items=[row])
        tabla = FakeLocator(children={"tbody tr": rows})
        boton_siguiente = FakeLocator()
        boton_siguiente.is_visible = AsyncMock(return_value=False)
        page = FakePage(
            url="https://contratacion.test/lista",
            locators={
                r"#tableLicitacionesPerfilContratante": tabla,
                r"#viewns_Z7_AVEQAI930GRPE02BR764FO30G0_\:form1\:siguienteLink": boton_siguiente,
            },
        )

        with patch(
            "app.main.code.services.web_scraping.PliegosPlaywrightAsincrono.extraer_detalles_licitacion",
            new=AsyncMock(return_value={"Expediente": "EXP-1"}),
        ), patch(
            "app.main.code.services.web_scraping.PliegosPlaywrightAsincrono.guardar_licitacion_json", new=AsyncMock()
        ) as mock_save, patch(
            "app.main.code.services.web_scraping.PliegosPlaywrightAsincrono.ir_pestana", new=AsyncMock()
        ) as mock_tab:
            resultados = await pliegos.extraer_licitaciones(page, [], {})

        self.assertEqual(resultados, [{"datos": {"Expediente": "EXP-1"}}])
        enlace.click.assert_awaited_once_with(force=True)
        mock_save.assert_awaited_once()
        mock_tab.assert_awaited_once_with(page, "Licitaciones")

    async def test_extraer_licitaciones_updates_duplicate_expediente(self):
        """
        Verifica la actualización de registros ya existentes cuando se encuentra nuevamente el mismo expediente.
        """
        enlace = FakeLocator()
        row = FakeLocator(children={'td.tdExpediente a:not([target="_blank"])': FakeLocator(first=enlace)})
        rows = FakeLocator(count=1, nth_items=[row])
        tabla = FakeLocator(children={"tbody tr": rows})
        boton_siguiente = FakeLocator()
        boton_siguiente.is_visible = AsyncMock(return_value=False)
        page = FakePage(
            locators={
                r"#tableLicitacionesPerfilContratante": tabla,
                r"#viewns_Z7_AVEQAI930GRPE02BR764FO30G0_\:form1\:siguienteLink": boton_siguiente,
            }
        )
        resultados = [{"datos": {"Expediente": "EXP-1", "valor": "old"}}]
        index = {"EXP-1": 0}

        with patch(
            "app.main.code.services.web_scraping.PliegosPlaywrightAsincrono.extraer_detalles_licitacion",
            new=AsyncMock(return_value={"Expediente": "EXP-1", "valor": "new"}),
        ), patch("app.main.code.services.web_scraping.PliegosPlaywrightAsincrono.guardar_licitacion_json", new=AsyncMock()), patch(
            "app.main.code.services.web_scraping.PliegosPlaywrightAsincrono.ir_pestana", new=AsyncMock()
        ):
            result = await pliegos.extraer_licitaciones(page, resultados, index)

        self.assertEqual(result, [{"datos": {"Expediente": "EXP-1", "valor": "new"}}])

    async def test_extraer_licitaciones_clicks_next_page_when_visible(self):
        """
        Comprueba la navegación automática entre páginas de resultados cuando existen páginas adicionales.
        """
        rows = FakeLocator(count=0, nth_items=[])
        tabla = FakeLocator(children={"tbody tr": rows})
        boton_siguiente = FakeLocator()
        boton_siguiente.is_visible = AsyncMock(side_effect=[True, False])
        page = FakePage(
            locators={
                r"#tableLicitacionesPerfilContratante": tabla,
                r"#viewns_Z7_AVEQAI930GRPE02BR764FO30G0_\:form1\:siguienteLink": boton_siguiente,
            }
        )

        await pliegos.extraer_licitaciones(page, [], {})

        boton_siguiente.click.assert_awaited_once_with(force=True)

    async def test_guardar_licitacion_json_writes_temp_file_and_replaces_atomically(self):
        """
        Verifica el almacenamiento seguro de resultados mediante escritura temporal y reemplazo atómico del archivo final.
        """
        with tempfile.TemporaryDirectory() as tmpdir:
            output = Path(tmpdir) / "licitaciones.json"
            with patch("app.main.code.services.web_scraping.PliegosPlaywrightAsincrono.OUTPUT_JSON", str(output)):
                await pliegos.guardar_licitacion_json([{"datos": {"Expediente": "EXP-1"}}])

            self.assertEqual(json.loads(output.read_text(encoding="utf-8")), [{"datos": {"Expediente": "EXP-1"}}])
            self.assertFalse(output.with_suffix(".json.tmp").exists())

    async def test_run_uses_playwright_flow_saves_and_closes_resources(self):
        """
        Comprueba la ejecución completa del proceso de scraping, incluyendo almacenamiento de resultados y liberación de recursos.
        """
        page = FakePage()
        context = MagicMock()
        context.tracing.start = AsyncMock()
        context.tracing.stop = AsyncMock()
        context.new_page = AsyncMock(return_value=page)
        context.close = AsyncMock()
        browser = MagicMock()
        browser.new_context = AsyncMock(return_value=context)
        browser.close = AsyncMock()
        playwright = MagicMock()
        playwright.chromium.launch = AsyncMock(return_value=browser)
        frame = MagicMock()
        frame.locator.return_value = FakeLocator()

        with patch("app.main.code.services.web_scraping.PliegosPlaywrightAsincrono.cargar_resultados_existentes", return_value=[{"datos": {"Expediente": "OLD"}}]), patch(
            "app.main.code.services.web_scraping.PliegosPlaywrightAsincrono.async_playwright", return_value=AsyncContext(playwright)
        ), patch("app.main.code.services.web_scraping.PliegosPlaywrightAsincrono.encontrar_frame", new=AsyncMock(return_value=frame)), patch(
            "app.main.code.services.web_scraping.PliegosPlaywrightAsincrono.eleccion_organo", new=AsyncMock()
        ), patch("app.main.code.services.web_scraping.PliegosPlaywrightAsincrono.ir_pestana", new=AsyncMock()), patch(
            "app.main.code.services.web_scraping.PliegosPlaywrightAsincrono.extraer_licitaciones",
            new=AsyncMock(return_value=[{"datos": {"Expediente": "OLD"}}, {"datos": {"Expediente": "NEW"}}]),
        ), patch("app.main.code.services.web_scraping.PliegosPlaywrightAsincrono.guardar_licitacion_json", new=AsyncMock()) as mock_save:
            await pliegos.run()

        mock_save.assert_awaited_once()
        context.tracing.stop.assert_awaited_once()
        context.close.assert_awaited_once()
        browser.close.assert_awaited_once()

    async def test_run_handles_timeout_and_still_saves_and_closes(self):
        """
        Verifica la gestión de errores por tiempo de espera garantizando el guardado de resultados y la liberación de recursos.
        """
        context = MagicMock()
        context.tracing.start = AsyncMock()
        context.tracing.stop = AsyncMock()
        context.new_page = AsyncMock(return_value=FakePage())
        context.close = AsyncMock()
        browser = MagicMock()
        browser.new_context = AsyncMock(return_value=context)
        browser.close = AsyncMock()
        playwright = MagicMock()
        playwright.chromium.launch = AsyncMock(return_value=browser)

        with patch("app.main.code.services.web_scraping.PliegosPlaywrightAsincrono.cargar_resultados_existentes", return_value=[]), patch(
            "app.main.code.services.web_scraping.PliegosPlaywrightAsincrono.async_playwright", return_value=AsyncContext(playwright)
        ), patch(
            "app.main.code.services.web_scraping.PliegosPlaywrightAsincrono.encontrar_frame",
            new=AsyncMock(side_effect=pliegos.PWTimeoutError("timeout")),
        ), patch("app.main.code.services.web_scraping.PliegosPlaywrightAsincrono.guardar_licitacion_json", new=AsyncMock()) as mock_save:
            await pliegos.run()

        mock_save.assert_awaited_once_with([])
        context.close.assert_awaited_once()
        browser.close.assert_awaited_once()

    async def test_run_ignores_navigation_timeouts_before_searching_frame(self):
        """
        Comprueba que determinados errores de navegación no impiden continuar con el proceso de extracción.
        """
        perfil_link = FakeLocator()
        perfil_link.click = AsyncMock(side_effect=pliegos.PWTimeoutError("perfil"))
        seleccionar_link = FakeLocator()
        seleccionar_link.click = AsyncMock(side_effect=pliegos.PWTimeoutError("seleccionar"))
        page = FakePage()
        page.get_by_role = MagicMock(side_effect=[perfil_link, seleccionar_link])
        context = MagicMock()
        context.tracing.start = AsyncMock()
        context.tracing.stop = AsyncMock()
        context.new_page = AsyncMock(return_value=page)
        context.close = AsyncMock()
        browser = MagicMock()
        browser.new_context = AsyncMock(return_value=context)
        browser.close = AsyncMock()
        playwright = MagicMock()
        playwright.chromium.launch = AsyncMock(return_value=browser)
        with patch("app.main.code.services.web_scraping.PliegosPlaywrightAsincrono.cargar_resultados_existentes", return_value=[]), patch(
            "app.main.code.services.web_scraping.PliegosPlaywrightAsincrono.async_playwright", return_value=AsyncContext(playwright)
        ), patch(
            "app.main.code.services.web_scraping.PliegosPlaywrightAsincrono.encontrar_frame",
            new=AsyncMock(side_effect=pliegos.PWTimeoutError("stop")),
        ), patch("app.main.code.services.web_scraping.PliegosPlaywrightAsincrono.guardar_licitacion_json", new=AsyncMock()):
            await pliegos.run()

        perfil_link.click.assert_awaited_once()
        seleccionar_link.click.assert_awaited_once()

    async def test_main_guard_runs_async_entrypoint(self):
        """
        Verifica que la ejecución directa del script lanza correctamente el proceso asíncrono principal.
        """
        import runpy
        await asyncio.sleep(0)

        def close_coroutine(coro):
            coro.close()

        with patch("asyncio.run", side_effect=close_coroutine) as mock_asyncio_run:
            runpy.run_module("app.main.code.services.web_scraping.PliegosPlaywrightAsincrono", run_name="__main__")

        mock_asyncio_run.assert_called_once()
