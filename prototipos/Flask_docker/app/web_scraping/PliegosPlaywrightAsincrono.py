import asyncio
import json
import re
import time
import os
from pathlib import Path
from typing import Any, List, Optional
from urllib.parse import urljoin

from playwright.async_api import Frame, Page, async_playwright, expect, Locator
from playwright.async_api import TimeoutError as PWTimeoutError

# ======== Constantes ========
BASE_URL = "https://contrataciondelestado.es/wps/portal/plataforma"
OUTPUT_JSON = "resultados_playwright_asincrono_servidor.json"
QUERY = "licitacion"
OBJETIVO = "Junta de Gobierno de la Diputación Provincial de Burgos"


def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", s).strip()


# ---------- Funciones ----------
async def encontrar_frame(page, selector: str, timeout_ms: int = 30_000) -> Frame:
    """
    Devuelve el primer Frame de la página que contenga `selector`.
    Recorre todos los frames e intenta esperar el selector con un timeout corto.
    """
    deadline = time.monotonic() + (timeout_ms / 1000.0)

    while time.monotonic() < deadline:
        for f in page.frames:
            try:
                await f.wait_for_selector(selector, timeout=800)
                return f
            except PWTimeoutError:
                continue
        await asyncio.sleep(0.25)

    raise PWTimeoutError(f"No se encontró ningún frame con el selector: {selector}")


async def eleccion_organo(frame_arbol: Frame, texto_objetivo: str) -> None:
    """
    Selecciona en el listbox inferior (comboNombreOrgano) la option cuyo texto contiene
    `texto_objetivo` y pulsa Añadir.
    """
    # Recuadro inferior, id dinámico
    sel = frame_arbol.locator(r'[id$=":comboNombreOrgano"]').first
    await sel.wait_for(state="visible")
    await sel.scroll_into_view_if_needed()

    print("SELECT ENCONTRADO")

    # Asegura que hay opciones cargadas
    await sel.locator("option").first.wait_for(state="attached")

    print("OPTIONS CARGADAS")

    # Busca la option por texto
    opcion = sel.locator(
        "option", has_text=re.compile(re.escape(texto_objetivo), re.I)
    ).first
    await opcion.wait_for(state="attached")

    print("BÚSQUEDA POR TEXTO")
    # Selecciona por value la opción
    value = await opcion.get_attribute("value")
    if value:
        await sel.select_option(value=value)
    else:
        await sel.select_option(label=texto_objetivo)
    print("SELECCiÓN POR ÍNDICES")

    # Pulsa el botón Añadir
    btn_anadir = frame_arbol.get_by_role("button", name=re.compile(r"^Añadir$", re.I))
    await btn_anadir.wait_for(state="visible")
    await btn_anadir.click()


def pestana_diputacion(busqueda: str) -> str:
    """
    Devuelve la clave de pestaña a abrir según el texto de búsqueda.

    Argumentos:
        busqeuda: texto que de búsqueda segun el cual se va a seleccioanr la pestaña.
    Returns:
        nombre de pestaña a abrir

    """
    b = (busqueda or "").lower()
    print(busqueda)
    print(any(k in b for k in ("pliego", "pliegos", "doc", "documento", "documentos")))
    if any(k in b for k in ("pliego", "pliegos", "doc", "documento", "documentos")):
        return "Documentos"
    if any(
        k in b
        for k in (
            "licitacion",
            "licitación",
            "licitaciones",
            "expediente",
            "expedientes",
        )
    ):
        return "Licitaciones"
    if any(k in b for k in ("menor", "contrato menor", "contratos menores")):
        return "Contratos Menores"
    if any(k in b for k in ("encargo", "medios propios", "medio propio")):
        return "Encargos a medios propios"
    if any(
        k in b for k in ("consulta preliminar", "consultas preliminares", "consulta")
    ):
        return "Consultas preliminares"
    return "perfil"


async def ir_pestana(page: Page, clave: str) -> None:
    """
    Hace clic en la pestaña indicada en la clave usando Playwright.

    Argumentos:
        page: Playwright Page.
        clave: la clave para ir a la pestaña.

    Excepciones:
        ValueError: Si la pestaña no está mapeada.
        PlaywrightTimeoutError: Si no se puede abrir la pestaña.
    """
    VISTA = r"#viewns_Z7_AVEQAI930GRPE02BR764FO30G0_"

    mapping = {
        "Perfil del Contratante": (
            VISTA + r"\:perfilComp\:textLinkOff"
        ),
        "Documentos": (
            VISTA + r"\:perfilComp\:linkPrepDocs"
        ),
        "Licitaciones": (
            VISTA + r"\:perfilComp\:linkPrepLic"
        ),
        "Contratos Menores": (
            VISTA
            + r"\:perfilComp\:linkPrepContratosMenores"
        ),
        "Encargos a medios propios": (
            VISTA
            + r"\:perfilComp\:linkPrepEncargosMP"
        ),
        "Consultas preliminares": (
            VISTA
            + r"\:perfilComp\:linkPrepConsultasAnuncio"
        ),
    }

    sel = mapping.get(clave)
    if not sel:
        raise ValueError(f"Pestaña no soportada: {clave}")

    try:
        locator = page.locator(sel).first
        await locator.wait_for(state="visible")
        await locator.scroll_into_view_if_needed()
        await expect(locator).to_be_enabled()
        await locator.click(trial=True)
        await locator.click()
    except PWTimeoutError as err:
        raise PWTimeoutError(f"No se pudo abrir la pestaña: {clave}") from err

    try:
        await page.wait_for_timeout(5_000)
    except Exception:
        pass
    await page.wait_for_timeout(400)


async def extraer_licitaciones(page: Page, resultados: list[dict], index: dict[str, int]) -> list[dict]:
    """
    Recorre las licitaciones de la página entrando en cada una
    Argumentos:
        page: la página actual (Licitacion) de la cual queremos extrear el JSON

    Return:
        Devuelve un diccionario con la información extraida.
    """
    print("voy a descaragr licitaciones")
    url = page.url
    tabla = page.locator(r"#tableLicitacionesPerfilContratante")
    await tabla.wait_for(state="visible")

    filas = tabla.locator("tbody tr")
    total = await filas.count()
    print(f"Filas en la página: {total}")

    boton_siguiente = page.locator(
        r"#viewns_Z7_AVEQAI930GRPE02BR764FO30G0_\:form1\:siguienteLink"
    )
    await boton_siguiente.wait_for(state="visible")
    await boton_siguiente.scroll_into_view_if_needed()
    j = 0
    pagina = 1
    resultados = []
    while True:

        total = await filas.count()
        print(f"Filas en la página {pagina} : {total}")

        for i in range(total):
            await tabla.wait_for(state="visible")
            fila = tabla.locator("tbody tr").nth(i)

            enlace = fila.locator('td.tdExpediente a:not([target="_blank"])').first
            await enlace.wait_for(state="visible")
            await enlace.scroll_into_view_if_needed()

            async with page.expect_navigation(wait_until="domcontentloaded"):
                await enlace.click(force=True)

            await page.wait_for_load_state("networkidle")

            await page.wait_for_timeout(400)

            datos = await extraer_detalles_licitacion(page)
            item = {"datos": datos}
            
            nuevo = actualizar_por_expediente(resultados, index, item)
            await guardar_licitacion_json(resultados)
            
            if nuevo:
                print(f"Guardada nueva licitación: {datos.get('Expediente')}")
            else:
                print(f"Actualizada (duplicado): {datos.get('Expediente')}")

            j += 1
            print(f"Licitación visitada #{i + 1} Total {j}")

            await page.goto(url)
            await ir_pestana(page, "Licitaciones")
            await page.wait_for_load_state("domcontentloaded")
            await tabla.wait_for(state="visible")
            await page.wait_for_load_state("networkidle")

        if not await boton_siguiente.is_visible():
            break

        await boton_siguiente.click(force=True)
        await page.wait_for_load_state("domcontentloaded")
        await tabla.wait_for(state="visible")
        await page.wait_for_load_state("networkidle")
        pagina += 1

    return resultados


async def extraer_detalles_licitacion(page: Page) -> dict:
    """
    Extrae los campos visibles de la página actual de licitaciones en formato JSON
    Argumentos:
        page: la página actual de la cual queremos extrear el JSON

    Return:
        Devuelve un diccionario con la información extraida.
    """
    datos: dict[str, str] = {}
    # Localiza la primera tabla
    head_sel = (
        r"#viewns_Z7_AVEQAI930OBRD02JPMTPG21006_\:form1 > div > div > div.row > table"
    )
    await parse_head_table(page, datos, head_sel)

    # Localiza la segunda tabla
    tabla2_sel = (
        r"#viewns_Z7_AVEQAI930OBRD02JPMTPG21006_\:form1 > div > div >"
        + r"table:nth-child(3)"
    )
    await parse_label_value_table(page, datos, tabla2_sel)

    # Localiza la tercera tabla
    tabla3_sel = (
        r"#viewns_Z7_AVEQAI930OBRD02JPMTPG21006_\:form1 > div > div >"
        + r"table:nth-child(5)"
    )
    await parse_label_value_table(page, datos, tabla3_sel)

    # Documentos
    documentos = await parse_documentos(page)
    
    if documentos:
        datos["Documentos"] = documentos
        
    print (datos)

    return datos

async def parse_head_table(page: Page, datos: dict[str, object], head_sel: str) -> None:
    head_table = page.locator(head_sel)
    if not await head_table.count():
        return
    
    await head_table.first.wait_for(state="visible")
    head_rows = head_table.locator("tbody > tr")

    # Fila 1: Órgano (url)
    r0 = head_rows.nth(0)

    # URL del Órgano de contratación (solo href)
    organo_a = r0.locator("a[href][id*=':URLOrganoContratacion']").first
    if await organo_a.count():
        href = await organo_a.get_attribute("href")
        if href and href != "#":
            datos["Órgano de contratación"] = urljoin(page.url, href)

    # ID del órgano
    id_oc_el = r0.locator("span[id*=':form1:text_IdOrganoContratacion']").first
    if await id_oc_el.count():
        datos["ID del Órgano de Contratación"] = _norm(
            await id_oc_el.inner_text()
        )

    # Ubicación orgánica
    ubig_el = r0.locator("span[id*=':form1:text_UbicacionOrganica']").first
    if await ubig_el.count():
        datos["Ubicación orgánica"] = _norm(await ubig_el.inner_text())

    # Fila 2: Expediente (texto)
    r1 = head_rows.nth(1)
    exp_el = r1.locator("span[id*=':form1:text_Expediente']").first
    if await exp_el.count():
        datos["Expediente"] = _norm(await exp_el.inner_text())

    # Fila 3: Objeto del contrato (texto)
    r2 = head_rows.nth(2)
    obj_el = r2.locator("span[id*=':form1:text_ObjetoContrato']").first
    if await obj_el.count():
        datos["Objeto del contrato"] = _norm(await obj_el.inner_text())

    # Fila 4: Enlace a la licitación (solo href)
    r3 = head_rows.nth(3)
    lic_a = r3.locator("a[href][id*=':form1:link_EnlaceLicPLACE']").first
    if await lic_a.count():
        href = await lic_a.get_attribute("href")
        if href and href != "#":
            datos["Enlace a la licitación"] = urljoin(page.url, href)

async def parse_label_value_table(page: Page, datos: dict[str, object], tabla_sel: str) -> None:
    tabla = page.locator(tabla_sel)
    if not await tabla.count():
        return
    await tabla.first.wait_for(state="visible")

    filas = tabla.locator("tbody.tabla-detalle-con-hijos > tr")
    n = await filas.count()

    for i in range(n):
        row = filas.nth(i)

        label_loc = row.locator(
            "span.cl-blue-dark.bold, span[id*=':form1:label_']"
        ).first
        label = _norm(await label_loc.inner_text()) if await label_loc.count() else None
        if not label:
            continue

        value_loc = row.locator("span[id*=':form1:text_']").first
        if await value_loc.count():
            value = await value_loc.inner_text()
        else:
            right_col = row.locator("div.col-lg-8").first
            value = await right_col.inner_text() if await right_col.count() else None

        value = _norm(value)
        datos[label] = value
        
async def parse_documentos(page: Page) -> Optional[list[dict[str, str]]]:
    docs_sel = "#myTablaDetalleVISUOE"
    docs_table = page.locator(docs_sel)
    if not await docs_table.count():
        return None
    
    await docs_table.first.wait_for(state="visible")

    rows = docs_table.locator("tbody.tabla-detalle > tr")
    m = await rows.count()
    
    documentos: list[dict[str, str]] = []
    
    for i in range(m):
        row = rows.nth(i)
        doc_data: dict[str, str] = {}

        # Columna 1: Publicación en plataforma
        pub_td = row.locator("td:nth-of-type(1)")
        await set_if_text(doc_data, "Publicación en plataforma", pub_td)

        # Columna 2: Documento
        doc_td = row.locator("td:nth-of-type(2)")
        await set_if_text(doc_data, "Documento", doc_td)

        # Columna 3: Ver documentos
        await documentos_extract_links(page, row.locator("td:nth-of-type(3)"), doc_data)
        
        # Columna 4: DOUE
        await parse_documentos_doue(page,row,doc_data)
                            
        if doc_data:
            documentos.append(doc_data)
    return documentos or None

async def documentos_extract_links(page: Page, links_td: Locator, doc_data: dict[str, str]) -> None:
    hrefs: list[str] = []
    if await links_td.count():
        enlaces = links_td.locator("a[href]")
        k = await enlaces.count()
        for j in range(k):
            a = enlaces.nth(j)
            href = await a.get_attribute("href")
            if href and href != "#":
                hrefs.append(urljoin(page.url, href))
    if hrefs:
        doc_data["Ver documentos (urls)"] = " | ".join(hrefs)

async def parse_documentos_doue(page: Page, row: Locator, doc_data: dict[str, str]) -> None:
    doue_td = row.locator("td:nth-of-type(4)")
    if await doue_td.count():
        # Envío
        envio_span = doue_td.locator(".flex span").first
        await set_if_text(doc_data, "DOUE - Envío", envio_span)

        # Publicación
        publi_link = doue_td.locator("a[href]").last
        if await publi_link.count():
            href_pub = await publi_link.get_attribute("href")
            if href_pub and href_pub != "#":
                doc_data["DOUE - Publicación"] = urljoin(page.url, href_pub)

            # Fecha de publicación dentro del link
            fecha_pub = _norm(await publi_link.inner_text())
            if fecha_pub:
                doc_data["DOUE - Publicación (fecha)"] = fecha_pub
        else:
            # En filas sin enlace, puede haber solo texto (o 'Vacío')
            publi_span = doue_td.locator("span.outputText").first
            await set_if_text(doc_data, "DOUE - Publicación (fecha)", publi_span)


async def set_if_text(datos: dict[str, str], key: str, value: Locator) -> None:
        
    if not await value.count():
        return
    txt = _norm(await value.first.inner_text())
    if txt:
        datos[key] = txt
    
    
async def guardar_licitacion_json(resultados: List[dict]) -> None:
    """
    Guarda las licitaciones en OUTPUT_JSON como una lista de objetos {datos, documentos} de manera incremental.

    Argumentos:
        resultados: La lista con los resultados que se van a almacenar en el json
    """

    def _write():
        path = Path(OUTPUT_JSON)
        tmp = path.with_suffix(path.suffix + ".tmp")
        with tmp.open("w", encoding="utf-8") as f:
            json.dump(resultados, f, ensure_ascii=False, indent=2)
        os.replace(tmp, path)

    await asyncio.to_thread(_write)
    
def cargar_resultados_existentes() -> list[dict]:
    """
    Lee OUTPUT_JSON si existe y devuelve una lista.
    Si no existe o está corrupto, devuelve [] (para no romper la ejecución).
    """
    path = Path(OUTPUT_JSON)
    if not path.exists():
        return []
    try:
        with path.open("r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, list) else []
    except Exception:
        # Si el archivo quedó a medio escribir o corrupto, no tiramos la ejecución
        return []

def actualizar_por_expediente(
    resultados: list[dict],
    index: dict[str, int],
    item: dict
) -> bool:
    """
    Inserta o actualiza un item en 'resultados' usando 'Expediente' como clave única.
    Devuelve True si se insertó nuevo, False si era duplicado (y se actualizó).
    """
    datos = item.get("datos") or {}
    expediente = (datos.get("Expediente") or "").strip()

    if not expediente:
        resultados.append(item)
        return True

    if expediente in index:
        resultados[index[expediente]] = item 
        return False

    index[expediente] = len(resultados)
    resultados.append(item)
    return True

# ========== MAIN ============
async def run() -> None:
    resultado = cargar_resultados_existentes()
    
    # Construye índice por Expediente a partir de lo ya guardado
    index: dict[str, int] = {}
    for i, it in enumerate(resultado):
        exp = ((it.get("datos") or {}).get("Expediente") or "").strip()
        if exp:
            index[exp] = i
    
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(
            locale="es-ES",
            timezone_id="Europe/Madrid",
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0.0.0 Safari/537.36"
            ),
            viewport={"width": 1366, "height": 900},
        )

        await context.tracing.start(screenshots=True, snapshots=True, sources=True)
        page = await context.new_page()
        page.set_default_timeout(90_000)
        page.set_default_navigation_timeout(90_000)

        try:
            await page.goto(BASE_URL, wait_until="networkidle", timeout=90_000)
            print("Título:", await page.title())

            # Abre la pestaña "Perfil Contratante"
            try:
                async with page.expect_navigation():
                    await page.get_by_role(
                        "link", name="Perfil Contratante", exact=True
                    ).click()
            except PWTimeoutError:
                pass
            await page.wait_for_load_state("networkidle")

            # Pulsa "Seleccionar"
            try:
                async with page.expect_navigation():
                    await page.get_by_role(
                        "link", name="Seleccionar", exact=True
                    ).click()
            except PWTimeoutError:
                pass
            await page.wait_for_load_state("networkidle")

            # --- Buscar el frame del diálogo por el <select> del recuadro inferior ---
            selector_select = r'[id$=":comboNombreOrgano"]'
            frame_arbol = await encontrar_frame(page, selector_select)

            # Pulsa "Sector Público" dentro de ese frame (usar Locator, no el string)
            selector_nodo = r"#tafelTree_maceoArbol_id_1"
            nodo_sector_publico = frame_arbol.locator(selector_nodo)
            await nodo_sector_publico.wait_for(state="attached")
            await nodo_sector_publico.scroll_into_view_if_needed()
            await nodo_sector_publico.click()

            # Buscar la Junta de gobierno de la diputación de Burgos en el listado
            await eleccion_organo(frame_arbol, OBJETIVO)
            await page.wait_for_load_state("networkidle")

            # Botón buscar
            btn_buscar = page.locator(
                r"#viewns_Z7_AVEQAI930GRPE02BR764FO30G0_\:listaperfiles\:botonbuscar"
            )
            await btn_buscar.wait_for(state="visible")
            await btn_buscar.scroll_into_view_if_needed()
            await btn_buscar.click(force=True)
            await page.wait_for_load_state("networkidle")

            # Link de la junta
            lnk_junta = page.locator(
                r"#viewns_Z7_AVEQAI930GRPE02BR764FO30G0_\:listaperfiles\:enlaceExpedienteBP_0_textoEnlace"
            )
            await lnk_junta.wait_for(state="visible")
            await lnk_junta.scroll_into_view_if_needed()
            await lnk_junta.click(force=True)
            await page.wait_for_load_state("networkidle")

            # Va a la pestaña correcta segun la query
            destino = pestana_diputacion(QUERY)
            print(f"Iré a la pestaña: {destino}")
            await ir_pestana(page, destino)

            # Extrae las licitaciones y las guarda
            if destino == "Licitaciones":
                resultado = await extraer_licitaciones(page,  resultado, index)

        except PWTimeoutError as e:
            print("Timeout al cargar o encontrar elementos: ", e)
            raise
        finally:
            await guardar_licitacion_json(resultado)
            await context.tracing.stop()
            await context.close()
            await browser.close()


if __name__ == "__main__":
    asyncio.run(run())
