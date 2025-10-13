import asyncio
import csv
import json
import random
import sys
import re, time
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import List, Optional

from playwright.sync_api import expect
from playwright.sync_api import sync_playwright, TimeoutError as PWTimeoutError

BASE_URL = "https://contrataciondelestado.es/wps/portal/plataforma"
DELAY_MS = (350, 900)  # min/max para pausas semi-aleatorias
API_DELAY = 0.35
TIMEOUT = 30000        # 30s por acción
OUTPUT_CSV = "resultados_playwright.csv"
OUTPUT_JSON = "resultados_playwright.json"
query = "licitacion" 


def esperarFrame(page, selector, timeout=60000):
    """Devuelve (frame, locator) del primer selector visible encontrado en cualquier iframe."""
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

def clickReintentos(boton, ventana, page, timeout=30_000, espera=400):
    """
    Hace click sobre `boton` con reintentos hasta que aparezca la ventana del árbol visible
    o hasta que se alcance el timeout.Devuelve True si se abrió.
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
    """Pulsa 'Seleccionar' y devuelve (frame_arbol, locator_arbol) cuando el árbol esté visible."""
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
        

def eleccionOrgano(frame_arbol, texto_objetivo):
    """
    Selecciona en el listbox inferior (comboNombreOrgano) la opción cuyo texto
    contiene `texto_objetivo` (case-insensitive) y pulsa 'Añadir'.
    """
    # 1) Localiza el <select> del recuadro inferior
    sel = frame_arbol.locator(r'[id$="\:comboNombreOrgano"]').first
    sel.wait_for(state="visible")

    # 2) Espera a que tenga opciones cargadas
    frame_arbol.wait_for_selector(r'[id$="\:comboNombreOrgano"] option')

   # 3) Busca la <option> por texto
    opcion = sel.locator("option", has_text=re.compile(re.escape(texto_objetivo), re.I)).first
    opcion.wait_for(state="attached")

    # 4) Selecciona por value 
    value = opcion.get_attribute("value")
    if not value:
        raise RuntimeError(f"No se encontró value para la opción '{texto_objetivo}'")
    sel.select_option(value=value)

    # 5) Pulsa 'Añadir'
    frame_arbol.get_by_role("button", name=re.compile(r"^Añadir$", re.I)).click()
    
def pestanaDiputacion(busqueda: str) -> str:
    """Devuelve la clave de pestaña a abrir según el texto de búsqueda."""
    b = (busqueda or "").lower()
    print (busqueda)
    print(any(k in b for k in ("pliego", "pliegos", "doc", "documento", "documentos")))
    if any(k in b for k in ("pliego", "pliegos", "doc", "documento", "documentos")):
        return "documentos"
    if any(k in b for k in ("licitacion", "licitación", "licitaciones", "expediente", "expedientes")):
        return "licitaciones"
    if any(k in b for k in ("menor", "contrato menor", "contratos menores")):
        return "contratos_menores"
    if any(k in b for k in ("encargo", "medios propios", "medio propio")):
        return "encargos"
    if any(k in b for k in ("consulta preliminar", "consultas preliminares", "consulta")):
        return "consultas"
    return "perfil"  

def irPestana(page, clave: str, timeout=20_000):
    """Hace clic en la pestaña indicada."""
    
    if clave==r"Perfil del Contratante":
        boton = page.locator(r'#viewns_Z7_AVEQAI930GRPE02BR764FO30G0_\:perfilComp\:textLinkOff')
        boton.click(force=True)
    if clave==r"Documentos":
        boton = page.locator(r'#viewns_Z7_AVEQAI930GRPE02BR764FO30G0_\:perfilComp\:linkPrepDocs')
        boton.click(force=True)
    if clave==r"Licitaciones":
        boton = page.locator(r'#viewns_Z7_AVEQAI930GRPE02BR764FO30G0_\:perfilComp\:linkPrepLic')
        boton.click(force=True)
    if clave==r"Contratos Menores":
        boton = page.locator(r'#viewns_Z7_AVEQAI930GRPE02BR764FO30G0_\:perfilComp\:linkPrepContratosMenores')
        boton.click(force=True)
    if clave==r"Encargos a medios propios":
        boton = page.locator(r'#viewns_Z7_AVEQAI930GRPE02BR764FO30G0_\:perfilComp\:linkPrepEncargosMP')
        boton.click(force=True)
    if clave==r"Consultas preliminares":
        boton = page.locator(r'#viewns_Z7_AVEQAI930GRPE02BR764FO30G0_\:perfilComp\:linkPrepConsultasAnuncio')
        boton.click(force=True)

    page.wait_for_load_state("networkidle")
    page.wait_for_timeout(400)


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
            objetivo = "Junta de Gobierno de la Diputación Provincial de Burgos"
            eleccionOrgano(frame_arbol, objetivo)
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
            destino = pestanaDiputacion(query) 
            print(f"Iré a la pestaña: {destino}")
            irPestana(page, destino)
            print("Pestaña abierta")



            

        except PWTimeoutError:
            print("Timeout al cargar o encontrar elementos.")
        finally:

            browser.close()

if __name__ == "__main__":
    main()