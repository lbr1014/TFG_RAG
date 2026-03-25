from __future__ import annotations
from concurrent.futures import ThreadPoolExecutor

executor = ThreadPoolExecutor(max_workers=2)
markdown_executor = ThreadPoolExecutor(max_workers=1)
