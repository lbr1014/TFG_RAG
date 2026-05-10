"""
Autora: Lydia Blanco Ruiz
Script para configurar los ejecutores de tareas en segundo plano de la aplicación.
"""

from __future__ import annotations

import os
from concurrent.futures import ThreadPoolExecutor

executor = ThreadPoolExecutor(max_workers=int(os.getenv("RAG_MAX_WORKERS", "4")))
markdown_executor = ThreadPoolExecutor(max_workers=int(os.getenv("MARKDOWN_MAX_WORKERS", "1")))
