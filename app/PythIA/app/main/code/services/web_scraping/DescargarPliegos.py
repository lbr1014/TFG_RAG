"""
Autora: Lydia Blanco Ruiz
Script para descargar los PDFs de pliegos a partir de las URLs extraídas por web scraping.
"""

import asyncio
import json
import logging
import os
from typing import Any, Awaitable, Iterable, List, Tuple
import aiofiles
from collections import defaultdict
from pathlib import Path

from playwright.async_api import async_playwright

RUTA_JSON = Path(os.environ.get("PLIEGOS_INPUT_JSON", "resultados_playwright_asincrono_servidor.json"))
DEST = Path(os.environ.get("DOCS_DIR") or os.environ.get("PLIEGOS_DEST", "pliegos"))
JSON_SALIDA = Path(os.environ.get("PLIEGOS_OUTPUT_JSON", "pliegos_pdfs.json"))
DEST.mkdir(parents=True, exist_ok=True)

# Playwright usa milisegundos para los timeouts
TIMEOUT_MS = 90_000
logger = logging.getLogger(__name__)


def limpiar_expediente(expediente: str) -> str:
    """
    Normaliza el nombre de archivo a partir del 'Expediente'.
    Sustituye caracteres problemáticos por '_'.
    
    Args:
        expediente: El número de expediente original que puede contener caracteres no aptos para nombres de archivo.
        
    Returns:
        Una versión limpia del expediente apta para usar en nombres de archivo.
    """
    permitido = "-_.()[] "
    limpio = "".join(
        c if c.isalnum() or c in permitido else "_" for c in expediente.strip()
    ).strip(" .")
    return limpio or "expediente"


async def descargar_pdf_es(context, url: str, expediente: str, nombre_doc: str, indice: int) -> bool:
    """
    Descarga la URL indicada usando el request del contexto de Playwright.
    Guarda el fichero con un nombre basado en el expediente y el tipo de documento.
    
    Args:
        context: Contexto de Playwright para realizar la petición.
        url: URL del PDF a descargar.
        expediente: Número de expediente para nombrar el archivo.
        nombre_doc: Nombre del documento para nombrar el archivo.
        indice: Índice para diferenciar múltiples documentos del mismo expediente y tipo.
    
    Returns:
        ``True`` si la descarga y guardado fueron exitosos, ``False`` en caso de error.
    """
    try:
        response = await context.request.get(url, timeout=TIMEOUT_MS)
    except Exception:
        logger.exception("Error de red al descargar [%s] %s #%s", expediente, nombre_doc, indice)
        return False

    if not response.ok:
        logger.error("Error HTTP %s al descargar [%s] %s #%s: %s", response.status, expediente, nombre_doc, indice, url)
        return False

    try:
        contenido = await response.body()
        ctype = (response.headers.get("content-type") or "").lower()

        # Comprobar que sea un PDF real
        es_pdf = ("application/pdf" in ctype) or contenido.startswith(b"%PDF-")

        if not es_pdf:
            logger.warning("La descarga no es PDF (%s).", ctype)
            return False
    except Exception:
        logger.exception("Error al leer el cuerpo de la respuesta [%s] %s #%s", expediente, nombre_doc, indice)
        return False

    base_exp = limpiar_expediente(expediente)
    base_doc = limpiar_expediente(nombre_doc)

    filename = f"{base_exp}__{base_doc}_{indice}.pdf"
    destino = DEST / filename

    try:
        async with aiofiles.open(destino, "wb") as f:
            await f.write(contenido)
        logger.info("Guardado: %s", destino.name)
        return True
    except Exception:
        logger.exception("Error al guardar archivo [%s] %s #%s", expediente, nombre_doc, indice)
        return False


async def extraer_urls_pliegos_desde_pagina(context, url: str, expediente: str, nombre_doc: str):
    """
    Extrae URLs de PDFs desde una página HTML de pliegos.

    Args:
        context: Contexto Playwright usado para abrir la página.
        url: URL HTML de detalle del documento.
        expediente: Número de expediente asociado.
        nombre_doc: Nombre del documento de pliegos.

    Returns:
        Lista de tuplas ``(nombre_enlace, url_pdf)``.
    """
    page = await context.new_page()
    try:
        logger.info("Abrir pagina de pliegos [%s] %s: %s", expediente, nombre_doc, url)
        await page.goto(url, wait_until="networkidle", timeout=TIMEOUT_MS)
    except Exception:
        logger.exception("Error al cargar la pagina [%s] %s", expediente, nombre_doc)
        await page.close()
        return []

    nombres_enlaces = [
        "Pliego Prescripciones Técnicas",
        "Pliego Cláusulas Administrativas",
    ]

    encontrados = []
    for nombre in nombres_enlaces:
        # Buscamos el enlace por su texto
        locator = page.get_by_role("link", name=nombre)

        try:
            count = await locator.count()
        except Exception:
            logger.exception("Error al buscar enlace '%s' en [%s]", nombre, expediente)
            continue

        if count == 0:
            logger.warning("No se encontro el enlace '%s' en [%s]", nombre, expediente)
            continue

        href = await locator.first.get_attribute("href")
        if not href:
            logger.warning("Enlace '%s' en [%s] sin href", nombre, expediente)
            continue

        encontrados.append((nombre, href))

    await page.close()
    return encontrados


async def procesar_pagina_pliego(context, url: str, expediente: str, nombre_doc: str, dic_urls: dict):
    """
    Procesa una página de pliegos y acumula sus URLs de PDF.

    Args:
        context: Contexto Playwright usado para abrir la página.
        url: URL HTML de detalle del documento.
        expediente: Número de expediente asociado.
        nombre_doc: Nombre del documento de pliegos.
        dic_urls: Diccionario acumulador por expediente.
    """
    urls_encontradas = await extraer_urls_pliegos_desde_pagina(context, url, expediente, nombre_doc)
    if not urls_encontradas:
        return

    dic_urls[expediente].extend(urls_encontradas)


async def run():
    """
    Ejecuta el flujo completo de extracción y descarga de pliegos de licitaciones.

    Lee las licitaciones desde el JSON de entrada, extrae las URLs de los pliegos
    desde las páginas HTML, descarga todos los PDFs encontrados y guarda un
    resumen en JSON con las URLs procesadas.

    El proceso incluye:
    - Carga de datos desde resultados_playwright_asincrono_servidor.json
    - Extracción paralela de URLs de PDFs desde páginas de pliegos
    - Descarga concurrente de todos los PDFs encontrados
    - Guardado de metadatos en pliegos_pdfs.json

    Returns:
        None: Los PDFs se guardan en el directorio DEST y los metadatos en JSON_SALIDA.
    """
    items = json.loads(RUTA_JSON.read_text(encoding="utf-8"))

    pdfs_por_expediente = defaultdict(list)

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(
            user_agent="Mozilla/5.0",
        )

        try:
            tareas_paginas = get_paginas(context, items, pdfs_por_expediente)

            # Recogemos los URLs de los PDF en paralelo
            if tareas_paginas:
                await asyncio.gather(*tareas_paginas)

            # Descargamos todos los PDFs encontrados
            tareas_descarga = []
            for expediente, lista_pdfs in pdfs_por_expediente.items():
                for idx, (nombre_pdf, url_pdf) in enumerate(lista_pdfs, start=1):
                    tareas_descarga.append(
                        descargar_pdf_es(
                            context=context,
                            url=url_pdf,
                            expediente=expediente,
                            nombre_doc=nombre_pdf,
                            indice=idx,
                        )
                    )

            if tareas_descarga:
                await asyncio.gather(*tareas_descarga)
                
            datos_para_json =  dict(pdfs_por_expediente.items())

            await write_json(JSON_SALIDA, datos_para_json)

            logger.info("Diccionario de pliegos guardado en: %s", JSON_SALIDA)

            # Crear ZIP con todo lo descargado si se necesita exportacion local.
            
        finally:
            await context.close()
            await browser.close()
            
def get_paginas(context, items: list[dict], dic_urls) -> List[Awaitable[Any]]:
    """
    Construye las tareas asíncronas de extracción de páginas de pliegos.

    Args:
        context: Contexto Playwright compartido.
        items: Licitaciones leídas desde el JSON de entrada.
        dic_urls: Diccionario acumulador de URLs.

    Returns:
        Lista de tareas asíncronas.
    """
    return [
        procesar_pagina_pliego(
            context=context,
            url=url,
            expediente=expediente,
            nombre_doc=nombre_doc,
            dic_urls=dic_urls,
        )
        for expediente, nombre_doc, url in iterar_paginas(items)
    ]

def iterar_paginas(items: list[dict]) -> Iterable[Tuple[str, str, str]]:
    """
    Itera por las páginas de pliegos incluidas en el JSON.

    Args:
        items: Licitaciones leídas desde el JSON de entrada.

    Yields:
        Tuplas con expediente, nombre del documento y primera URL.
    """
    for item in items:
        datos = item.get("datos", {}) or {}
        expediente = datos.get("Expediente")
        if not expediente:
            continue

        documentos = datos.get("Documentos") or []
        for doc in documentos:
            nombre_doc = (doc.get("Documento") or "").strip()
            if not es_pliego(nombre_doc):
                continue

            url = primera_url(doc)
            if url:
                yield expediente, nombre_doc, url
                
def es_pliego (nombre_doc: str) -> bool:
    """
    Indica si un nombre de documento corresponde a un pliego.

    Args:
        nombre_doc: Nombre del documento.

    Returns:
        ``True`` si el nombre contiene la palabra ``pliego``.
    """
    if not nombre_doc:
        return False
    return "pliego" in nombre_doc.lower()
            
def primera_url(doc: dict) -> str:
    """
    Obtiene la primera URL de un campo de URLs separadas por barras.

    Args:
        doc: Diccionario de metadatos de un documento.

    Returns:
        Primera URL encontrada o cadena vacía.
    """
    urls_str = doc.get("Ver documentos (urls)")
    if not urls_str:
        return ""
    return (urls_str.split("|")[0] or "").strip()

async def write_json(path, data: dict) -> None:
    """
    Escribe un diccionario en JSON con codificación UTF-8.

    Args:
        path: Ruta de salida.
        data: Datos que se quieren serializar.
    """
    payload = json.dumps(data, ensure_ascii=False, indent=2)
    async with aiofiles.open(path, "w", encoding="utf-8") as f:
        await f.write(payload)

if __name__ == "__main__":
    asyncio.run(run())
