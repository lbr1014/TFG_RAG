# selenium
"""
Autor: Lydia Blanco Ruiz
Versión: 1.0
Descripción: Script realizado con Selenium para automatizar la extracción de documentos de Contratación del Sector Público.
El script abre la plataforma, navega al "Perfil Contratante", localiza el buscador dentro de iframes, abre el selector de órganos y selecciona la opción 
"Junta de Gobierno de la Diputaciñon Provincial de Burgos". Después segun la consulta elige en que pestaña entrar. 

"""
# ======== Imports de selenium ========
import re
import time
import json
from datetime import datetime
from typing import Any, List, Tuple, Optional

from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait, Select
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import (TimeoutException, StaleElementReferenceException)

# ======== Constantes ========
BASE_URL = "https://contrataciondelestado.es/wps/portal/plataforma"
TIMEOUT = 30            # segundos por espera
OUTPUT_JSON = "resultados_Selenium.json"
QUERY = "licitacion"
OBJETIVO = "Junta de Gobierno de la Diputación Provincial de Burgos"


# ======== Utilidades de espera ========

def espera(driver: webdriver.Chrome, timeout: int=TIMEOUT)-> None:
    """
    Bloquea hasta que el estado del documento este completo.

    Argumentos:
        driver: Instancia de WebDriver abierta sobre la página. 
        timeout: Tiempo máximo de espera en segundos.

    Excepción:
        TimeoutException: Si no se alcanza el estado completo en el tiempo indicado en timeout.
    """
    WebDriverWait(driver, timeout).until(
        lambda d: d.execute_script("return document.readyState") == "complete"
    )

def PausaMilisegundos(ms: int = 300)-> None:
    """
    Pausa corta en milisegundos para poner entre acciones. Aunque, no sustituye esperas explícitas.
    
    Argumento:
        ms: Tiempo que va a esperar. 
    """
    time.sleep(ms / 1000.0)

def visible(driver: webdriver.Chrome, by: By, sel: str, timeout: int=TIMEOUT):
    """
    Espera y devuelve el primer elemento visible que coincide con el localizador.

    Argumentos: 
        driver: Instancia de WebDriver.
        by: Estrategia de localización.
        sel: Selector correspondiente.
        timeout: Tiempo de espera en segundos.

    Returns:
        Los elementos visibles de la web 

    Excepción:
          TimeoutException: Si no aparece visible a tiempo.

    """
    return WebDriverWait(driver, timeout).until(
        EC.visibility_of_element_located((by, sel))
    )

def clickSeguro(driver: webdriver.Chrome, element) -> None:
    """
    Click robusto que intenta múltiples estrategias para minimizar fallos por overlays/interceptaciones.

    Argumentos:
        driver: Instancia de WebDriver.
        element: WebElement objetivo.
    """
    try:
        driver.execute_script("arguments[0].click()", element)
        return
    except Exception:
        pass
    try:
        element.click()
        return
    except Exception:
        pass
    try:
        driver.execute_script(
            "var ev=new MouseEvent('click',{bubbles:true,cancelable:true});arguments[0].dispatchEvent(ev);",
            element,
        )
    except Exception:
        pass

# ======== Gestión de iframes ========

def buscarVisibleEnContexto(driver: webdriver.Chrome, css_selector: str):
    """
    Busca el primer elemento de la web (WebElement) visible en el contexto actual para el selector especificado.
    
    Argumentos:
        driver: Instancia de WebDriver.
        css_selector: Selector css que se busca en el contexto actual.

    Return:
        Devuelve el elemento, en caso de que el selector no exista o no sea visible devuelve None.
    """
    try:
        el = driver.find_element(By.CSS_SELECTOR, css_selector)
        if el.is_displayed():
            return el
    except Exception:
        pass
    return None

def iterarEnIframes(driver: webdriver.Chrome):
    """
    Itera iframes/frames de PRIMER nivel del documento actual.
    """
    return driver.find_elements(By.CSS_SELECTOR, "iframe, frame")

def buscarPadres(driver: webdriver.Chrome) -> None:
    """
    Vuelve al contexto por degfecto (default_content).
    """
    driver.switch_to.default_content()

def buscarIframeVisible(driver, css_selector: str) -> Tuple[Optional[str], Optional[object]]:
    """
    Busca un selector visible en raíz y en cada iframe de primer nivel.

    Argumentos:
        driver: WebDriver.
        css_selector: Selector CSS objetivo.

    Return:
        Si encuentra el elemento devuelve le frame y el elemento, en caso de que no lo encuentre devuelve (None, None). 
        Si el elemento está en la raíz, el frame devuelto es None.
    """
    buscarPadres(driver)

    el = buscarVisibleEnContexto(driver, css_selector)
    if el:
        return None, el

    frames = iterarEnIframes(driver)
    for fr in frames:
        try:
            driver.switch_to.frame(fr)
            el = buscarVisibleEnContexto(driver, css_selector)
            if el:
                return fr, el
        except Exception:
            pass
        finally:
            driver.switch_to.default_content()

    return None, None

def esperarFrame(driver: webdriver.Chrome, selector: str, timeout_ms: int = 60_000) -> Tuple[Optional[object], object]:
    """
    Espera hasta encontrar un elemento visible por selector en la raíz o en un iframes.
    Mantiene el foco en el frame donde está el elemento para devolverlo.

    Argumentos:
        driver: WebDriver.
        selector: Selector CSS a localizar.
        timeout_ms: Tiempo máximo de espera en milisegundos.

    Return:
        el frame_web_element_or_None y el locator_web_element, como dupla

    Excepción:
        TimeoutException: Si no se localiza a tiempo.
    """
    deadline = time.time() + timeout_ms / 1000.0
    last_err = None
    while time.time() < deadline:
        try:
            frame_el, el = buscarIframeVisible(driver, selector)
            if el:
                # Nos quedamos en el frame donde está el elemento para devolverlo "usable"
                driver.switch_to.default_content()
                if frame_el is not None:
                    driver.switch_to.frame(frame_el)
                return frame_el, el
        except Exception as e:
            last_err = e
        PausaMilisegundos(200)
    raise TimeoutException(f"No encontré '{selector}' visible en ningún iframe. {last_err or ''}")

# ======== Reintentos de clic para abrir ventana ========

def clickReintentos(driver, boton, ventana_by_sel: Tuple[By, str], timeout_ms=30_000, espera_ms=400) -> bool:
    """
    Hace click sobre el boton con reintentos hasta que el locator `ventana_by_sel` sea visible
    o hasta alcanzar el timeout.

    Argumentos:
        driver: WebDriver.
        boton: WebElement del botón a pulsar.
        ventana_by_sel: Tupla (By, selector) que identifica la ventana/panel esperado.
        timeout_ms: Tiempo máximo total de reintentos.
        espera_ms: Pausa entre intentos.

    Return: 
        Devuelve True si se abrió.
    
    Raises:
        TimeoutException: Si no se abrió a tiempo.

    """
    start = time.monotonic()
    intento = 1

    while (time.monotonic() - start) * 1000 < timeout_ms:
        try:
            espera(driver, 5)
        except Exception:
            pass

        try:
            # Comprueba si la ventana es visible
            elements = driver.find_elements(*ventana_by_sel)
            if any(e.is_displayed() for e in elements):
                return True
        except Exception:
            pass

        print(f"Intento #{intento} de hacer click en 'Seleccionar'...")
        try:
            clickSeguro(driver, boton)
        except Exception:
            pass

        try:
            WebDriverWait(driver, 1.5).until(EC.visibility_of_element_located(ventana_by_sel))
            return True
        except TimeoutException:
            pass

        try:
            espera(driver, 1.2)
        except Exception:
            pass

        PausaMilisegundos(espera_ms)
        intento += 1

    raise TimeoutException("No se abrió la ventana dentro del tiempo esperado.")

# ======== Flujos específicos de la página ========

def abrirSeleccionar(driver, frame_context, timeout_ms=15_000):
    """
    Pulsa 'Seleccionar' y espera el árbol del popup.

    Argumentos:
        driver: WebDriver.
        frame_context: Frame donde se encuentra el botón 'Seleccionar'. Puede ser None.
        timeout_ms: Tiempo máximo de espera del popup.

    Return:
        Devuelve la dupla (frame_arbol, locator_arbol) cuando el árbol esté visible. Es decir, el frame y el localizador del arbol.
    
    Excepción:
        TimeoutException: Si el popup no aparece.
    """
    # Se asegura de estar en el frame correcto
    driver.switch_to.default_content()
    if frame_context is not None:
        driver.switch_to.frame(frame_context)

    sel_boton = r'#viewns_Z7_AVEQAI930GRPE02BR764FO30G0_\:listaperfiles\:idSeleccionarOCLink'
    boton = visible(driver, By.CSS_SELECTOR, sel_boton, timeout=TIMEOUT)
    clickSeguro(driver, boton)

    ventana_sel = (By.CSS_SELECTOR, r'#viewns_Z7_AVEQAI930GRPE02BR764FO30G0_\:listaperfiles\:arbolPopup_tb')
    try:
        WebDriverWait(driver, timeout_ms / 1000.0).until(EC.visibility_of_element_located(ventana_sel))
    except TimeoutException:
        clickReintentos(driver, boton, ventana_sel, timeout_ms=timeout_ms)

    print("Seleccionar")

    # El árbol puede estar en otro iframe, en ese caso lo busca
    driver.switch_to.default_content()
    frame_arbol, loc_arbol = esperarFrame(driver, r'#tafelTree_maceoArbol_id_1', timeout_ms=timeout_ms)
    print(frame_arbol)
    return frame_arbol, loc_arbol

def eleccionOrgano(driver, frame_arbol, texto_objetivo: str) -> None:
    """
    Selecciona en el listbox inferior (comboNombreOrgano) la option cuyo texto contiene texto_objetivo pulsa Añadir.
    
    Argumentos: 
        driver: WebDriver.
        frame_arbol: Frame donde se renderiza el árbol y el combo del órgano.
        texto_objetivo: Cadena a buscar (insensible a mayúsculas/minúsculas).

    Excepción:
        RuntimeError: Si no hay ninguna opción cuyo texto contenga `texto_objetivo`.

    """
    driver.switch_to.default_content()
    if frame_arbol is not None:
        driver.switch_to.frame(frame_arbol)

    sel_combo = r'[id$="\:comboNombreOrgano"]'
    combo = visible(driver, By.CSS_SELECTOR, sel_combo)
    # Espera a que tenga options
    WebDriverWait(driver, TIMEOUT).until(
        lambda d: len(combo.find_elements(By.CSS_SELECTOR, "option")) > 0
    )

    options = combo.find_elements(By.CSS_SELECTOR, "option")
    objetivo_re = re.compile(re.escape(texto_objetivo), re.I)
    match_val = None
    for opt in options:
        try:
            if objetivo_re.search(opt.text or ""):
                match_val = opt.get_attribute("value")
                break
        except StaleElementReferenceException:
            pass

    if not match_val:
        raise RuntimeError(f"No se encontró opción que contenga: {texto_objetivo!r}")

    Select(combo).select_by_value(match_val)

    # Botón 'Añadir'
    btn_anadir = WebDriverWait(driver, 15).until(
        EC.element_to_be_clickable(
            (By.CSS_SELECTOR, r'#viewns_Z7_AVEQAI930GRPE02BR764FO30G0_\:listaperfiles\:botonAnadirMostrarPopUpArbolEO')
        )
    )
    clickSeguro(driver, btn_anadir)


def pestanaDiputacion(busqueda: str) -> str:
    """
    Devuelve la clave de pestaña a abrir según el texto de búsqueda.

    Argumentos:
        busqeuda: texto que de búsqueda segun el cual se va a seleccioanr la pestaña.
    Returns:
        nombre de pestaña a abrir

    """
    b = (busqueda or "").lower()
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
    return "Perfil del Contratante"

def irPestana(driver, clave: str):
    """
    Hace clic en la pestaña indicada en la clave.

    Argumentos:
        driver: WebDriver.
        clave: la clave para ir a la pestaña.

    Excepciones:
        ValueError: Si la pestaña no está mapeada.
        TimeoutException: Si no se puede abrir la pestaña.

    """
    driver.switch_to.default_content()

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
        btn = visible(driver, By.CSS_SELECTOR, sel, timeout=TIMEOUT)
        driver.execute_script("arguments[0].scrollIntoView({block:'center'});", btn)
        clickSeguro(driver, btn)
    except TimeoutException:
        raise TimeoutException(f"No se pudo abrir la pestaña: {clave}")

    try:
        espera(driver, 5)
    except Exception:
        pass
    PausaMilisegundos(400)

def extraerLicitaciones(driver) -> list[dict]:
    """
    Recorre las licitaciones de la página entrando en cada una
    Argumentos:
        driver: la página actual (Licitacion) de la cual queremos extrear el JSON

    Return: 
        Devuelve un diccionario con la información extraida.
    """
    url=driver.current_url

    print("voy a descaragr licitaciones")
    tabla = WebDriverWait(driver, TIMEOUT).until(
        EC.visibility_of_element_located((By.CSS_SELECTOR, r'#tableLicitacionesPerfilContratante'))
    )   
    

    j=0
    pagina=1
    resultados=[]
    while True:
        
        filas = tabla.find_elements(By.CSS_SELECTOR, "tbody tr")
        total=len(filas)
        print(f"Filas en la página {pagina} : {total}")

        for i in range(total):
            tabla = WebDriverWait(driver, TIMEOUT).until(
                EC.visibility_of_element_located((By.CSS_SELECTOR, r'#tableLicitacionesPerfilContratante'))
            )   

            fila = driver.find_element(By.CSS_SELECTOR, f"#tableLicitacionesPerfilContratante > tbody > tr:nth-child({i+1})")

            enlace = WebDriverWait(fila, TIMEOUT).until(
                EC.visibility_of_element_located(
                    (By.CSS_SELECTOR, 'td.tdExpediente a:not([target="_blank"])')
                )
            )

            try:
                driver.execute_script("arguments[0].scrollIntoView({block:'center'});", enlace)
            except Exception:
                pass
            
            clickSeguro(driver, enlace)

            # Esperar a que cargue la página de detalle
            WebDriverWait(driver, TIMEOUT).until(
                EC.visibility_of_element_located((By.CSS_SELECTOR, 'fieldset[id^="DetalleLicitacion"]'))
            )

            datos, documentos = extraerDetallesLicitacion(driver)
            resultados.append({"datos": datos, "documentos": documentos})

            j+=1
            print(f"Licitación visitada #{i+1}. Total {j}")

            driver.get(url)
            espera(driver, 30)
            irPestana(driver, "Licitaciones")
            tabla = WebDriverWait(driver, TIMEOUT).until(
                EC.visibility_of_element_located((By.CSS_SELECTOR, r'#tableLicitacionesPerfilContratante'))
            )
            espera(driver, 30)


        try:
            botonSiguiente = WebDriverWait(driver, 3).until(
                EC.visibility_of_element_located(
                    (By.CSS_SELECTOR, r'#viewns_Z7_AVEQAI930GRPE02BR764FO30G0_\:form1\:siguienteLink')
                )
            )
        except TimeoutException:
            break 
        

        clickSeguro(driver, botonSiguiente)
        espera(driver, 30)
        
        tabla = WebDriverWait(driver, TIMEOUT).until(
            EC.visibility_of_element_located((By.CSS_SELECTOR, r'#tableLicitacionesPerfilContratante'))
        )
        pagina+=1

    return resultados


def extraerDetallesLicitacion(driver) ->  tuple[dict, list[dict]]:
    """
    Extrae los campos visibles de la página actual de licitaciones en formato JSON
    Argumentos:
        driver: la página actual de la cual queremos extrear el JSON

    Return: 
        Devuelve un diccionario con la información extraida.
    """
    datos=[]

    # Asegurar que el detalle está visible
    WebDriverWait(driver, TIMEOUT).until(
        EC.visibility_of_element_located((By.CSS_SELECTOR, 'fieldset[id^="DetalleLicitacion"]'))
    )

    #información de la tabla DetalleLicitacionVIS_UOE
    tabla_js = r"""
        return (function () {
          const root = document.querySelector('#DetalleLicitacionVIS_UOE');
          if (!root) return {};
          const out = {};
          const filas = Array.from(root.querySelectorAll('ul'));
          for (const ul of filas) {
            const celdas = Array.from(ul.querySelectorAll('li'));
            if (celdas.length < 2) continue;
            const etiqueta = (celdas[0].textContent || '').trim();
            if (!etiqueta) continue;
            const valor = (celdas[1].textContent || '').replace(/\s+/g, ' ').trim();
            if (valor) out[etiqueta] = valor;
          }
          return out;
        })();
    """
    tabla = driver.execute_script(tabla_js) or {}

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
    info_js = r"""
        return (function () {
          const root = document.querySelector('#InformacionLicitacionVIS_UOE');
          if (!root) return {};
          const out = {};
          const filas = Array.from(root.querySelectorAll('ul'));
          for (const ul of filas) {
            const celdas = Array.from(ul.querySelectorAll('li'));
            if (celdas.length < 2) continue;
            const etiqueta = (celdas[0].textContent || '').trim();
            if (!etiqueta) continue;
            const valor = (celdas[1].textContent || '').replace(/\s+/g, ' ').trim();
            if (valor) out[etiqueta] = valor;
          }
          return out;
        })();
    """
    informacion = driver.execute_script(info_js) or {}

    informacionNormalizada={}
    for k, v in informacion.items():
        k = re.sub(r"\s+", " ", k).strip()
        k = re.sub(r":\s*$", "", k)
        v = re.sub(r"\s+", " ", v).strip()
        informacionNormalizada[k] = v

    datos.update(informacionNormalizada)

    print(f"\nDatos normalizados: {datos}")

    #informaciónde la tabla #myTablaDetalleVISUOE
    docs_js = r"""
        return (function () {
          const table = document.querySelector('#myTablaDetalleVISUOE');
          if (!table) return [];
          const out = [];
          const filas = Array.from(table.querySelectorAll('#myTablaDetalleVISUOE > tbody tr'));
          for (const tr of filas) {
            const tds = tr.querySelectorAll('td');
            const publicacion = (tds[0].textContent || '').replace(/\s+/g, ' ').trim();
            const documento   = (tds[1].textContent || '').replace(/\s+/g, ' ').trim();
            let html = null;
            const links = Array.from(tds[2].querySelectorAll('a'));
            const htmlLink = links.find(a => /\bhtml\b/i.test(a.textContent || ''));
            if (htmlLink) {
              html = new URL(htmlLink.getAttribute('href') || '', window.location.href).href;
            }
            out.push({ publicacion, documento, html });
          }
          return out;
        })();
    """
    documentos = driver.execute_script(docs_js) or []
    print (f"\n Documentos: {documentos}")  

    #informaciónde la tabla #datosDocumentosGenerales
    otros_js = r"""
        return (function () {
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
        })();
    """
    otrosDocumentos = driver.execute_script(otros_js) or []
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
    # Configuración de Chrome
    opts = webdriver.ChromeOptions()
    opts.add_argument("--start-maximized")
    opts.add_argument("--lang=es-ES")
    opts.add_argument(
        "user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    )
    
    driver = webdriver.Chrome(options=opts)
    driver.set_page_load_timeout(45)
    driver.implicitly_wait(0)  

    try:
        driver.execute_cdp_cmd("Emulation.setTimezoneOverride", {"timezoneId": "Europe/Madrid"})
    except Exception:
        pass

    try:
        driver.get(BASE_URL)
        espera(driver, 30)
        print("Título:", driver.title)

        # Click en "Perfil Contratante" 
        link_pc = WebDriverWait(driver, TIMEOUT).until(
            EC.element_to_be_clickable((By.XPATH, "//a[normalize-space(.)='Perfil Contratante']"))
        )
        clickSeguro(driver, link_pc)

        espera(driver, 15)

        # Encontrar el frame con el buscador
        frame, _ = esperarFrame(
            driver,
            r"#contenidoBuscador > fieldset:nth-child(1) > ul:nth-child(1) > li:nth-child(2)",
            timeout_ms=60_000,
        )
        print(frame)

        frame_arbol, nodo = abrirSeleccionar(driver, frame, timeout_ms=30_000)
        print("Panel de selección abierto")

        # Pulsar nodo "Sector Público" en el árbol
        try:
            driver.execute_script("arguments[0].scrollIntoView({block:'center'});", nodo)
        except Exception:
            pass
        PausaMilisegundos(150)
        clickSeguro(driver, nodo)
        print("Sector Público pulsado")

        #Buscar la Junta de gobierno de la diputación de Burgos en el listado
        eleccionOrgano(driver, frame_arbol, OBJETIVO)
        print("Junta")

        driver.switch_to.default_content()
        # Botón Buscar
        btn_buscar_sel = r'#viewns_Z7_AVEQAI930GRPE02BR764FO30G0_\:listaperfiles\:botonbuscar'
        btn_buscar = visible(driver, By.CSS_SELECTOR, btn_buscar_sel, timeout=TIMEOUT)
        try:
            driver.execute_script("arguments[0].scrollIntoView({block:'center'});", btn_buscar)
        except Exception:
            pass
        clickSeguro(driver, btn_buscar)
        print("Buscar")
        espera(driver, 15)

        # Enlace resultado
        lnk_sel = r'#viewns_Z7_AVEQAI930GRPE02BR764FO30G0_\:listaperfiles\:enlaceExpedienteBP_0_textoEnlace'
        lnk_junta = visible(driver, By.CSS_SELECTOR, lnk_sel, timeout=TIMEOUT)
        try:
            driver.execute_script("arguments[0].scrollIntoView({block:'center'});", lnk_junta)
        except Exception:
            pass
        clickSeguro(driver, lnk_junta)
        print("Enlace junta")

        espera(driver, 15)
        destino = pestanaDiputacion(QUERY)
        print(f"Iré a la pestaña: {destino}")
        irPestana(driver, destino)
        print("Pestaña abierta")

        resultado=[]
        if destino == "Licitaciones":
            resultado=extraerLicitaciones(driver)

        guardarLicitacionJSON(resultado)
        print("HA ACABADO")

 
    except TimeoutException:
        print("Timeout al cargar o encontrar elementos.")
    finally:
        driver.quit()

if __name__ == "__main__":
    main()
