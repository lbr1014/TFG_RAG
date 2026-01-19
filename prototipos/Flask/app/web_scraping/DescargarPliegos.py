import asyncio
import json
import shutil
import os
from collections import defaultdict
from pathlib import Path

from playwright.async_api import async_playwright

RUTA_JSON = Path("resultados_playwright_asincrono_servidor.json")
DEST = Path(os.environ.get("PLIEGOS_DEST", "pliegos"))
JSON_SALIDA = Path("pliegos_pdfs.json")
DEST.mkdir(parents=True, exist_ok=True)

# Playwright usa milisegundos para los timeouts
TIMEOUT_MS = 90_000


def limpiar_expediente(expediente: str) -> str:
    """
    Normaliza el nombre de archivo a partir del 'Expediente'.
    Sustituye caracteres problemáticos por '_'.
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
    """
    try:
        response = await context.request.get(url, timeout=TIMEOUT_MS)
    except Exception as e:
        print(f"ERROR de red al descargar [{expediente}] {nombre_doc} #{indice}: {e}")
        return False

    if not response.ok:
        print(
            f"ERROR HTTP {response.status} al descargar [{expediente}] {nombre_doc} #{indice}: {url}"
        )
        return False

    try:
        contenido = await response.body()
    except Exception as e:
        print(
            f"ERROR al leer el cuerpo de la respuesta [{expediente}] {nombre_doc} #{indice}: {e}"
        )
        return False

    base_exp = limpiar_expediente(expediente)
    base_doc = limpiar_expediente(nombre_doc)

    filename = f"{base_exp}__{base_doc}_{indice}.pdf"
    destino = DEST / filename

    try:
        with open(destino, "wb") as f:
            f.write(contenido)
        print(f"Guardado: {destino.name}")
        return True
    except Exception as e:
        print(f"ERROR al guardar archivo [{expediente}] {nombre_doc} #{indice}: {e}")
        return False


async def extraer_urls_pliegos_desde_pagina(context, url: str, expediente: str, nombre_doc: str):
    """
    Entra en la URL HTML de 'Documento de Pliegos' y extrae las URLs
    de:
        - 'Pliego Prescripciones Técnicas'
        - 'Pliego Cláusulas Administrativas'
    devolviendo una lista de tuplas [(nombre_enlace, url_pdf), ...]
    """
    page = await context.new_page()
    try:
        print(f"Abrir página de pliegos [{expediente}] {nombre_doc}: {url}")
        await page.goto(url, wait_until="networkidle", timeout=TIMEOUT_MS)
    except Exception as e:
        print(f"ERROR al cargar la página [{expediente}] {nombre_doc}: {e}")
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
        except Exception as e:
            print(f"ERROR al buscar enlace '{nombre}' en [{expediente}]: {e}")
            continue

        if count == 0:
            print(f"No se encontró el enlace '{nombre}' en [{expediente}]")
            continue

        href = await locator.first.get_attribute("href")
        if not href:
            print(f"Enlace '{nombre}' en [{expediente}] sin href")
            continue

        encontrados.append((nombre, href))

    await page.close()
    return encontrados


async def procesar_pagina_pliego(context, url: str, expediente: str, nombre_doc: str, dic_urls: dict):
    """
    Entra en la página HTML del pliego, extrae las URLs de los PDFs que nos interesan
    y las añade al diccionario dic_urls[expediente].
    """
    urls_encontradas = await extraer_urls_pliegos_desde_pagina(context, url, expediente, nombre_doc)
    if not urls_encontradas:
        return

    dic_urls[expediente].extend(urls_encontradas)


async def run():
    items = json.loads(RUTA_JSON.read_text(encoding="utf-8"))

    pdfs_por_expediente = defaultdict(list)

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(
            user_agent="Mozilla/5.0",
        )

        tareas_paginas = []

        for item in items:
            datos = item.get("datos", {}) or {}
            expediente = datos.get("Expediente")
            if not expediente:
                continue

            documentos = datos.get("Documentos") or []
            for doc in documentos:
                nombre_doc = (doc.get("Documento") or "").strip()
                if not nombre_doc:
                    continue

                # Solo entramos en los pliegos
                if "pliego" not in nombre_doc.lower():
                    continue

                urls_str = doc.get("Ver documentos (urls)")
                if not urls_str:
                    # Ignoramos los Pliegos sin URL 
                    continue

                primera_url = urls_str.split("|")[0].strip()
                if not primera_url:
                    continue

                tareas_paginas.append(
                    procesar_pagina_pliego(
                        context=context,
                        url=primera_url,
                        expediente=expediente,
                        nombre_doc=nombre_doc,
                        dic_urls=pdfs_por_expediente,
                    )
                )

        # 1) Recogemos los URLs de los PDF en paralelo
        if tareas_paginas:
            await asyncio.gather(*tareas_paginas)

        # 2) Descargamos todos los PDFs encontrados
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
            
        datos_para_json = {k: v for k, v in pdfs_por_expediente.items()}

        with JSON_SALIDA.open("w", encoding="utf-8") as f:
            json.dump(datos_para_json, f, ensure_ascii=False, indent=2)

        print(f"Diccionario de pliegos guardado en: {JSON_SALIDA}")

        # Crear ZIP con todo lo descargado
        zip_path = shutil.make_archive(DEST.name, "zip", root_dir=DEST)
        print(f"ZIP creado: {zip_path}")

        await context.close()
        await browser.close()


if __name__ == "__main__":
    asyncio.run(run())
