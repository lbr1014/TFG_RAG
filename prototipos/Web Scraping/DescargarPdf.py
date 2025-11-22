import asyncio
import json
import shutil
from pathlib import Path

from playwright.async_api import TimeoutError as PlaywrightTimeoutError
from playwright.async_api import (
    async_playwright,
)

RUTA_JSON = Path("resultados_playwright_asincrono_servidor.json")
DEST = Path("pdfs")
DEST.mkdir(parents=True, exist_ok=True)

TIMEOUT_MS = 60_000


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


async def descargar_pdf_es(context, page, expediente: str) -> bool:
    """
    Hace click en el botón #ES-signed y guarda el PDF descargado.
    Devuelve True si se descargó, False en caso contrario.
    """
    locator = page.locator("#ES-signed")
    if not await locator.count():
        return False  # no existe el botón

    # Asegura que el botón es visible
    await locator.scroll_into_view_if_needed()

    try:
        # Espera la descarga al hacer click
        async with page.expect_download() as dl_info:
            await locator.click()
        download = await dl_info.value

        # Nombre final
        filename = f"{limpiar_expediente(expediente)}.pdf"
        if not filename.lower().endswith(".pdf"):
            filename = f"{limpiar_expediente(expediente)}.pdf"

        destino = DEST / filename
        await download.save_as(destino)
        print(f"PDF ES guardado: {destino.name}")
        return True
    except Exception as e:
        print(f"No se pudo descargar el PDF ES: {e}")
        return False


async def visitar_doue(page_factory, context, url: str, expediente: str):
    try:
        page = await page_factory()
        await page.goto(url, wait_until="networkidle")
        await page.wait_for_load_state("load")

        # Descarga el PDF en español
        ok = await descargar_pdf_es(context, page, expediente)
        if not ok:
            print(f"SIN PDF ES: {expediente} -> {url}")
    except PlaywrightTimeoutError:
        print(f"FALLO (timeout): {expediente} -> {url}")
    except Exception as e:
        print(f"FALLO: {expediente} -> {url} -> {e}")
    finally:
        try:
            await page.close()
        except Exception:
            pass


async def run():
    items = json.loads(RUTA_JSON.read_text(encoding="utf-8"))

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(
            user_agent="Mozilla/5.0",
            accept_downloads=True,
        )

        async def page_factory():
            return await context.new_page()

        tareas = []

        for item in items:
            datos = item.get("datos", {}) or {}
            expediente = datos.get("Expediente")
            doue = datos.get("DOUE - Publicación")

            if (
                not expediente
                or not doue
                or str(doue).strip().lower() in {"", "vacío", "vacio"}
            ):
                continue

            url = str(doue).strip()

            await visitar_doue(page_factory, context, url, expediente)

        await asyncio.gather(*tareas)

        zip_path = shutil.make_archive(DEST.name, "zip", root_dir=DEST)
        print(f"ZIP creado: {zip_path}")

        await context.close()
        await browser.close()


if __name__ == "__main__":
    asyncio.run(run())
