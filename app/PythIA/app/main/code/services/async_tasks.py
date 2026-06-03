"""
Autora: Lydia Blanco Ruiz
Script para configurar los ejecutores de tareas en segundo plano de la aplicación.
"""

from __future__ import annotations

import atexit
import logging
import os
import threading
from concurrent.futures import Future, ThreadPoolExecutor

_shutdown_lock = threading.Lock()
_shutdown_done = False
logger = logging.getLogger(__name__)

_futures_lock = threading.Lock()
_job_futures: dict[tuple[str, int], Future] = {}

executor = ThreadPoolExecutor(
    max_workers=int(os.getenv("RAG_MAX_WORKERS", "4")),
    thread_name_prefix="rag-worker",
)
markdown_executor = ThreadPoolExecutor(
    max_workers=int(os.getenv("MARKDOWN_MAX_WORKERS", "1")),
    thread_name_prefix="markdown-worker",
)


def shutdown_executors(*, wait: bool = False) -> None:
    """
    Cierra los ejecutores globales.

    Args:
        wait: Si es ``True``, espera a que terminen tareas en curso; por defecto no bloquea
              el apagado (cancela futuros en cola cuando es posible).
    """
    global _shutdown_done  
    with _shutdown_lock:
        if _shutdown_done:
            return
        _shutdown_done = True

    for pool in (markdown_executor, executor):
        try:
            pool.shutdown(wait=wait, cancel_futures=True)
        except TypeError:
            pool.shutdown(wait=wait)
        except (RuntimeError, OSError, ValueError) as exc:
            # Evitar que el shutdown falle en cascada pero deja rastro en logs para diagnóstico.
            logger.debug("No se pudo cerrar ThreadPoolExecutor (%s): %s", pool, exc)

    # Limpiar referencias a futuros para no retener memoria.
    with _futures_lock:
        _job_futures.clear()


def submit_tracked(
    pool: ThreadPoolExecutor,
    job_type: str,
    tracked_job_id: int,
    fn,
    *args,
    **kwargs,
) -> Future:
    """
    Envía un job al pool y guarda el Future para poder cancelarlo si aún está en cola.
    ``Future.cancel()`` solo cancela si el trabajo no ha empezado a ejecutarse.
    
    Args:
        pool: El ThreadPoolExecutor al que enviar el trabajo.
        job_type: Categoría del trabajo (p. ej. "rag", "markdown"), para organizar los futuros.
        tracked_job_id: Identificador único del trabajo a rastrear dentro de su categoría.
        fn: Función a ejecutar en el trabajo.
        *args: Argumentos posicionales para la función.
        **kwargs: Argumentos de palabra clave para la función.
        
    Returns:
        Future: El objeto Future asociado al trabajo enviado.
    """
    future = pool.submit(fn, *args, **kwargs)
    key = (job_type, int(tracked_job_id))

    with _futures_lock:
        _job_futures[key] = future

    def _cleanup(_f: Future) -> None:
        with _futures_lock:
            _job_futures.pop(key, None)

    future.add_done_callback(_cleanup)
    return future


def cancel_tracked(*, job_type: str, tracked_job_id: int) -> bool:
    """
    Intenta cancelar un job si todavía no ha empezado a ejecutarse.
    
    Args:
        job_type: Categoría del trabajo (p. ej. "rag", "markdown"), para localizar el Future correcto.
        tracked_job_id: Identificador único del trabajo a cancelar dentro de su categoría.

    Returns:
        ``True`` si el future se canceló, ``False`` si ya estaba ejecutándose o no existía.
    """
    key = (job_type, int(tracked_job_id))
    with _futures_lock:
        future = _job_futures.get(key)
    if future is None:
        return False
    cancelled = future.cancel()
    if cancelled:
        with _futures_lock:
            _job_futures.pop(key, None)
    return cancelled


def register_executor_shutdown(app=None) -> None:
    """
    Registra el cierre de los ejecutores al apagar el proceso y, si se pasa una app Flask,
    también al finalizar el ciclo de vida del servidor.
    
    Args:
        app: Instancia de Flask opcional para registrar el cierre al finalizar el servidor.
    """
    atexit.register(shutdown_executors)

    if app is None:
        return

    after_serving = getattr(app, "after_serving", None)
    if callable(after_serving):

        @app.after_serving
        def _shutdown_pools_after_serving() -> None:  
            shutdown_executors()
