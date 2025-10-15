"""
Autor: Lydia Blanco Ruiz
Versión: 1.0
Descripción: Script realizado con Playwright para automatizar la extracción de documentos de Contratación del Sector Público.
El script abre la plataforma, navega al "Perfil Contratante", localiza el buscador dentro de iframes, abre el selector de órganos y selecciona la opción 
"Junta de Gobierno de la Diputaciñon Provincial de Burgos". Después segun la consulta elige en que pestaña entrar. 

"""
# ======== Imports de playwright ========
import json
import re, time
from urllib.parse import urljoin, urlparse
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, List, Tuple, Optional
from datetime import datetime

from playwright.sync_api import expect
from playwright.sync_api import sync_playwright, Error, TimeoutError as PlaywrightTimeoutError
from playwright.sync_api import Page, sync_playwright, TimeoutError as PWTimeoutError

# ======== Constantes ========
BASE_URL = "https://contrataciondelestado.es/wps/portal/plataforma"
TIMEOUT = 30000        # 30s por acción
OUTPUT_JSON = "resultados_playwright.json"
QUERY = "licitacion" 
OBJETIVO = "Junta de Gobierno de la Diputación Provincial de Burgos"

# ======== Utilidades de espera ========
def esperarFrame(page, selector, timeout=60000)-> Tuple[Optional[object], object]:
    """
    Espera hasta encontrar un elemento visible por selector en la raíz o en un iframes.
    Mantiene el foco en el frame donde está el elemento para devolverlo.

    Argumentos:
        page: Pagina en la que se va a bs¡uscar el frame.
        selector: Selector CSS a localizar.
        timeout: Tiempo máximo de espera.

    Return:
        el frame_web_element_or_None y el locator_web_element, como dupla

    Excepción:
        PWTimeoutError: Si no se localiza a tiempo.
    """
    deadline = time.time() + timeout/1000
    while time.time() < deadline:
        for f in page.frames:
            try:
                loc = f.locator(selector).first
                if loc.is_visible():
                    return f, loc
            except Exception:
                pass
        page.wait_for_timeout(200)
    raise PWTimeoutError(f"No encontré '{selector}' visible en ningún iframe.")

# ======== Reintentos de clic para abrir ventana ========
def clickReintentos(boton, ventana, page, timeout=30_000, espera=400)-> bool:
    """
    Hace click sobre el boton con reintentos hasta que el locator `ventana_by_sel` sea visible
    o hasta alcanzar el timeout.    

     Argumentos:
        boton: WebElement del botón a pulsar.
        ventana: identificador la ventana/panel esperado.
        timeout: Tiempo máximo total de reintentos.
        espera: Pausa entre intentos.

    Return: 
        Devuelve True si se abrió.
    
    Raises:
        PWTimeoutError: Si no se abrió a tiempo.

    """
    start = time.monotonic()
    intento = 1

    while (time.monotonic() - start) * 1000 < timeout:
        page.wait_for_load_state("networkidle")
        if ventana.is_visible():
            return True
        
        print(f"Intento #{intento} de hacer click en 'Seleccionar'...")

        try:
                    
            try:
                boton.evaluate("el => el.click()")
            except Exception:
                try:
                    boton.click(force=True)
                except Exception:
                    boton.dispatch_event("click")
        except Exception:
            pass  # ignoramos y reintentamos
        
        try:
            ventana.wait_for(state="visible", timeout=1500)
            return True
        except PWTimeoutError:
            pass
        
        try:
            page.wait_for_load_state("networkidle", timeout=1200)
        except PWTimeoutError:
            pass
        
        page.wait_for_timeout(espera)
        intento+=1
        
    raise PWTimeoutError("No se abrió la ventana dentro del tiempo esperado.")

# ======== Flujos específicos de la página ========

def abrirSeleccionar(page,frame, timeout=15_000):
    """
    Pulsa 'Seleccionar' y espera el árbol del popup.

    Argumentos:
        page: Pagina en la que se encuentra el botón seleccionar.
        frame: Frame donde se encuentra el botón 'Seleccionar'. Puede ser None.
        timeout: Tiempo máximo de espera del popup.

    Return:
        Devuelve la dupla (frame_arbol, locator_arbol) cuando el árbol esté visible. Es decir, el frame y el localizador del arbol.
    """
    boton = frame.locator(r'#viewns_Z7_AVEQAI930GRPE02BR764FO30G0_\:listaperfiles\:idSeleccionarOCLink').first
    boton.wait_for(state="visible")
    boton.click()
    ventana = frame.locator(r'#viewns_Z7_AVEQAI930GRPE02BR764FO30G0_\:listaperfiles\:arbolPopup_tb')
    if not ventana.is_visible():
        clickReintentos(boton, ventana, page, timeout=timeout)
        ventana.wait_for(state="visible", timeout=timeout)
    print("Seleccionar")

    # Tras el clic, el árbol puede aparecer en OTRO iframe.
    frame_arbol, loc_arbol = esperarFrame(page, r'#tafelTree_maceoArbol_id_1', timeout=timeout)
    print(frame_arbol)

    return frame_arbol, loc_arbol
        

def eleccionOrgano(frame_arbol, texto_objetivo) -> None:
    """
    Selecciona en el listbox inferior (comboNombreOrgano) la option cuyo texto contiene texto_objetivo pulsa Añadir.
    
    Argumentos: 
        frame_arbol: Frame donde se renderiza el árbol y el combo del órgano.
        texto_objetivo: Cadena a buscar (insensible a mayúsculas/minúsculas).
    """
    # Localiza el <select> del recuadro inferior
    sel = frame_arbol.locator(r'[id$="\:comboNombreOrgano"]').first
    sel.wait_for(state="visible")

    # Espera a que tenga opciones cargadas
    frame_arbol.wait_for_selector(r'[id$="\:comboNombreOrgano"] option')

   # Busca la <option> por texto
    opcion = sel.locator("option", has_text=re.compile(re.escape(texto_objetivo), re.I)).first
    opcion.wait_for(state="attached")

    # Selecciona por value 
    value = opcion.get_attribute("value")
    if not value:
        raise RuntimeError(f"No se encontró value para la opción '{texto_objetivo}'")
    sel.select_option(value=value)

    # Pulsa 'Añadir'
    frame_arbol.get_by_role("button", name=re.compile(r"^Añadir$", re.I)).click()
    
def pestanaDiputacion(busqueda: str) -> str:
    """
    Devuelve la clave de pestaña a abrir según el texto de búsqueda.

    Argumentos:
        busqeuda: texto que de búsqueda segun el cual se va a seleccioanr la pestaña.
    Returns:
        nombre de pestaña a abrir

    """
    b = (busqueda or "").lower()
    print (busqueda)
    print(any(k in b for k in ("pliego", "pliegos", "doc", "documento", "documentos")))
    if any(k in b for k in ("pliego", "pliegos", "doc", "documento", "documentos")):
        return "Documentos"
    if any(k in b for k in ("licitacion", "licitación", "licitaciones", "expediente", "expedientes")):
        return "Licitaciones"
    if any(k in b for k in ("menor", "contrato menor", "contratos menores")):
        return "Contratos Menores"
    if any(k in b for k in ("encargo", "medios propios", "medio propio")):
        return "Encargos a medios propios"
    if any(k in b for k in ("consulta preliminar", "consultas preliminares", "consulta")):
        return "Consultas preliminares"
    return "perfil"  

def irPestana(page: Page, clave: str, timeout: float = 10_000) -> None:
    """
    Hace clic en la pestaña indicada en la clave usando Playwright.

    Argumentos:
        page: Playwright Page.
        clave: la clave para ir a la pestaña.
        timeout: timeout en ms para localizar/clickar.

    Excepciones:
        ValueError: Si la pestaña no está mapeada.
        PlaywrightTimeoutError: Si no se puede abrir la pestaña.
    """

    mapping = {
        "Perfil del Contratante": r'#viewns_Z7_AVEQAI930GRPE02BR764FO30G0_\:perfilComp\:textLinkOff',
        "Documentos": r'#viewns_Z7_AVEQAI930GRPE02BR764FO30G0_\:perfilComp\:linkPrepDocs',
        "Licitaciones": r'#viewns_Z7_AVEQAI930GRPE02BR764FO30G0_\:perfilComp\:linkPrepLic',
        "Contratos Menores": r'#viewns_Z7_AVEQAI930GRPE02BR764FO30G0_\:perfilComp\:linkPrepContratosMenores',
        "Encargos a medios propios": r'#viewns_Z7_AVEQAI930GRPE02BR764FO30G0_\:perfilComp\:linkPrepEncargosMP',
        "Consultas preliminares": r'#viewns_Z7_AVEQAI930GRPE02BR764FO30G0_\:perfilComp\:linkPrepConsultasAnuncio',
    }

    sel = mapping.get(clave)
    if not sel:
        raise ValueError(f"Pestaña no soportada: {clave}")

    try:
        locator = page.locator(sel).first
        locator.wait_for(state="visible", timeout=timeout)
        locator.scroll_into_view_if_needed(timeout=timeout)
        expect(locator).to_be_enabled(timeout=timeout)  
        locator.click(timeout=timeout, trial=True)
        locator.click(timeout=timeout)
    except PlaywrightTimeoutError:
        raise PlaywrightTimeoutError(f"No se pudo abrir la pestaña: {clave}")

    try:
        page.wait_for_timeout(5_000)
    except Exception:
        pass
    page.wait_for_timeout(400)



def extraerLicitaciones(page) -> list[dict]:
    """
    Recorre las licitaciones de la página entrando en cada una
    Argumentos:
        page: la página actual (Licitacion) de la cual queremos extrear el JSON

    Return: 
        Devuelve un diccionario con la información extraida.
    """
    print("voy a descaragr licitaciones")
    url=page.url
    tabla = page.locator(r'#tableLicitacionesPerfilContratante')
    tabla.wait_for(state="visible", timeout=30_000)

    filas = tabla.locator("tbody tr")
    total=filas.count()
    print(f"Filas en la página: {total}")

    botonSiguiente=page.locator(r'#viewns_Z7_AVEQAI930GRPE02BR764FO30G0_\:form1\:siguienteLink')
    botonSiguiente.wait_for(state="visible", timeout=30_000)
    botonSiguiente.scroll_into_view_if_needed()
    j=0
    pagina=1
    resultados=[]
    while True:
        
        total=filas.count()
        print(f"Filas en la página {pagina} : {total}")

        for i in range(total):
            tabla.wait_for(state="visible", timeout=30_000)
            fila = tabla.locator("tbody tr").nth(i)

            enlace = fila.locator('td.tdExpediente a:not([target="_blank"])').first
            enlace.wait_for(state="visible", timeout=30_000)
            enlace.scroll_into_view_if_needed()

            with page.expect_navigation(wait_until="domcontentloaded"):
                enlace.click(force=True)

            page.wait_for_load_state("networkidle")

            page.wait_for_timeout(400)

            datos, documentos = extraerDetallesLicitacion(page)
            resultados.append({"datos": datos, "documentos": documentos})

            j+=1
            print(f"Licitación visitada #{i+1} Total {j}")

            page.goto(url)
            irPestana(page, "Licitaciones")
            page.wait_for_load_state("domcontentloaded")
            tabla.wait_for(state="visible", timeout=30_000)
            page.wait_for_load_state("networkidle")

        if not botonSiguiente.is_visible():
            break

        botonSiguiente.click(force=True)
        page.wait_for_load_state("domcontentloaded")
        tabla.wait_for(state="visible", timeout=30_000)
        page.wait_for_load_state("networkidle")
        pagina+=1

    return resultados

def extraerDetallesLicitacion(page: Page) -> tuple[dict, list[dict]]:
    """
    Extrae los campos visibles de la página actual de licitaciones en formato JSON
    Argumentos:
        page: la página actual de la cual queremos extrear el JSON

    Return: 
        Devuelve un diccionario con la información extraida.
    """
    datos=[]

    detalles = page.locator('fieldset[id^="DetalleLicitacion"]').first
    detalles.wait_for(state="visible", timeout=30_000)

    #información de la tabla DetalleLicitacionVIS_UOE
    tabla = page.evaluate(
        """() => {
          const root = document.querySelector('#DetalleLicitacionVIS_UOE');
          if (!root) return {};

          const out = {};
          // cada fila es un <ul>; dentro hay 2 <li>: [etiqueta, valor]
          const filas = Array.from(root.querySelectorAll('ul'));
          for (const ul of filas) {
            const celdas = Array.from(ul.querySelectorAll('li'));
            if (celdas.length < 2) continue;

            const etiqueta = (celdas[0].textContent || '').trim();
            if (!etiqueta) continue;

            // valor = concatenación del texto de spans y enlaces dentro del segundo li
            const valor = (celdas[1].textContent || '').replace(/\\s+/g, ' ').trim();
            if (valor) out[etiqueta] = valor;
          }
          return out;
        }"""
    )
    datos={}
    tablaNormalizada={}
    #Normalizar los datos obtenidos
    for k,v in tabla.items():
        #Quita los espacios dejando solo uno y quita los dos puntos
        k = re.sub(r"\s+", " ",k).strip()
        k = re.sub(r":\s*$", "", k)

        v = re.sub(r"\s+", " ",v).strip()

        tablaNormalizada[k]=v

    datos.update(tablaNormalizada)

    #información de la tabla InformacionLicitacionVIS_UOE
    informacion=page.evaluate(
        """() => {
          const root = document.querySelector('#InformacionLicitacionVIS_UOE');
          if (!root) return {};

          const out = {};
          // cada fila es un <ul>; dentro hay 2 <li>: [etiqueta, valor]
          const filas = Array.from(root.querySelectorAll('ul'));
          for (const ul of filas) {
            const celdas = Array.from(ul.querySelectorAll('li'));
            if (celdas.length < 2) continue;

            const etiqueta = (celdas[0].textContent || '').trim();
            if (!etiqueta) continue;

            // valor = concatenación del texto de spans y enlaces dentro del segundo li
            const valor = (celdas[1].textContent || '').replace(/\\s+/g, ' ').trim();
            if (valor) out[etiqueta] = valor;
          }
          return out;
        }"""
    )

    informacionNormalizada={}
    for k, v in informacion.items():
        k = re.sub(r"\s+", " ", k).strip()
        k = re.sub(r":\s*$", "", k)
        v = re.sub(r"\s+", " ", v).strip()
        informacionNormalizada[k] = v

    datos.update(informacionNormalizada)

    print(f"\nDatos normalizados: {datos}")

    #informaciónde la tabla #myTablaDetalleVISUOE
    documentos = page.evaluate(
        """() => {
          const table = document.querySelector('#myTablaDetalleVISUOE');
          if (!table) return [];

          const out = [];
          const filas = Array.from(table.querySelectorAll('#myTablaDetalleVISUOE > tbody tr'))

          for (const tr of filas) {
            const tds = tr.querySelectorAll('td');

            // 0: Publicación en plataforma
            const publicacion = (tds[0].textContent || '').replace(/\\s+/g, ' ').trim();

            // 1: Documento (nombre)
            const documento = (tds[1].textContent || '').replace(/\\s+/g, ' ').trim();

            // 2: Ver documentos -> nos quedamos SOLO con el enlace cuyo texto sea "Html"
            let html = null;
            const links = Array.from(tds[2].querySelectorAll('a'));
            const htmlLink = links.find(a => /\\bhtml\\b/i.test(a.textContent || ''));
            if (htmlLink) {
              // Devolver URL absoluta
              html = new URL(htmlLink.getAttribute('href') || '', window.location.href).href;
            }

            out.push({ publicacion, documento, html });
          }
          return out;
        }"""
    )
    print (f"\n Documentos: {documentos}")    

    otrosDocumentos = page.evaluate(
        r"""() => {
        const cont = document.querySelector('#datosDocumentosGenerales');
        if (!cont) return [];

        const table = cont.querySelector('[id="viewns_Z7_AVEQAI930OBRD02JPMTPG21006_:form1:TableEx1_Aux"]');
        if (!table) return [];

        const out = [];
        const seen = new Set();
        const rows = Array.from(table.querySelectorAll('tbody tr'));

        for (const tr of rows) {
            const tds = tr.querySelectorAll('td');

            const publicacion = (tds[0].textContent || '').trim();
            const documento   = (tds[1].textContent || '').trim();

            const verLink = Array.from(tds[2].querySelectorAll('a'))
            .find(a => /\bver\b/i.test((a.textContent || '').trim()));
            if (!verLink) continue;

            const html = new URL(verLink.getAttribute('href') || '', window.location.href).href;

            const key = `${publicacion}||${documento}`;
            if (seen.has(key)) continue;
            seen.add(key);

            out.push({ publicacion, documento, html });
        }

        return out;
        }"""
    )

    print (f"\n Otros Documentos: {otrosDocumentos}")    

    documentos.extend(otrosDocumentos)

    print(f"\nDOCUMENTOS FINAL: {documentos}")

    return datos, documentos

def guardarLicitacionJSON(resultados: List[Any]) -> None:
    """
    Guarda las licitaciones en OUTPUT_JSON como una lista de objetos { "datos": {…}, "documentos": [ … ] }

    Argumentos: 
        resultados: La lista con los resultados que se van a almacenar en el json
    """
    with open(OUTPUT_JSON, "w", encoding="utf-8") as f:
        json.dump(resultados, f, ensure_ascii=False, indent=2)

# ==== Main ====

def main():

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False)
        context = browser.new_context(
            locale="es-ES",
            timezone_id="Europe/Madrid",
            user_agent=("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                        "AppleWebKit/537.36 (KHTML, like Gecko) "
                        "Chrome/124.0.0.0 Safari/537.36"),
            viewport={"width": 1366, "height": 900},
        )
        page = context.new_page()
        page.set_default_timeout(15_000)
        page.set_default_navigation_timeout(30_000)

        try:
            page.goto(BASE_URL, wait_until="domcontentloaded", timeout=45_000)
            
            print("Título:", page.title())
            # Abre la pestaña "Perfil Contratante"
            page.get_by_role("link", name=re.compile(r"^Perfil Contratante$", re.I)).click()
            # Espera a que termine de cargar
            page.wait_for_load_state("networkidle")
            frame, _ = esperarFrame(page, r'#contenidoBuscador > fieldset:nth-child(1) > ul:nth-child(1) > li:nth-child(2)', timeout=60_000)
            print(frame)
            
            frame_arbol, nodo = abrirSeleccionar(page, frame, timeout=30_000)            
            print("Panel de selección abierto")

            page.wait_for_load_state("networkidle")

            nodo.scroll_into_view_if_needed()
            nodo.wait_for(state="visible")
            nodo.click(force=True)
            print("Sector Público pulsado")


            #Buscar la Junta de gobierno de la diputación de Burgos en el listado
            eleccionOrgano(frame_arbol, OBJETIVO)
            print("Junta")

            page.wait_for_load_state("networkidle")
            # Botón Buscar
            btn_buscar = page.locator(r'#viewns_Z7_AVEQAI930GRPE02BR764FO30G0_\:listaperfiles\:botonbuscar')
            btn_buscar.wait_for(state="visible", timeout=30_000)
            btn_buscar.scroll_into_view_if_needed()
            btn_buscar.click(force=True)
            print("Buscar")

            page.wait_for_load_state("networkidle")
            # Enlace resultado
            lnk_junta = page.locator(r'#viewns_Z7_AVEQAI930GRPE02BR764FO30G0_\:listaperfiles\:enlaceExpedienteBP_0_textoEnlace')
            lnk_junta.wait_for(state="visible", timeout=30_000)
            lnk_junta.scroll_into_view_if_needed()
            lnk_junta.click(force=True)
            print("Enlace junta")

            
            page.wait_for_load_state("networkidle")
            destino = pestanaDiputacion(QUERY) 
            print(f"Iré a la pestaña: {destino}")
            irPestana(page, destino)
            print("Pestaña abierta")
            
            resultado=[]
            if destino == "Licitaciones":
                resultado=extraerLicitaciones(page)

            guardarLicitacionJSON(resultado)

            print("HA ACABADO")



        except PWTimeoutError:
            print("Timeout al cargar o encontrar elementos.")
        finally:

            browser.close()

if __name__ == "__main__":
    main()