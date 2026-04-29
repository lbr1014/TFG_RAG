"""
Autora: Lydia Blanco Ruiz
Script con la lógica de recuperación, generación, embeddings e indexación en Qdrant para el sistema RAG.
"""

# =========================
# Imports
# =========================
from __future__ import annotations

import logging
import os
import re
import time
import atexit
import json
import asyncio
from contextlib import contextmanager
from dataclasses import dataclass
from functools import cached_property
from pathlib import Path
from typing import Any, Generic, Iterable, Optional, Type, TypeVar, Dict
from uuid import UUID, uuid4

import httpx
from pydantic import BaseModel, Field
from pypdf import PdfReader
from pypdf.errors import PdfReadError, PdfStreamError
from qdrant_client import QdrantClient
from qdrant_client import models as qmodels
from sentence_transformers import SentenceTransformer
try:
    import torch
except ImportError:
    torch = None

from hashlib import sha256

# Logger
logger = logging.getLogger(__name__)   


class QueryCancelledError(RuntimeError):
    """
    Error que se lanza cuando el usuario cancela una consulta RAG en curso.
    """
    pass


class OllamaTimeoutError(RuntimeError):
    """
    Error que se lanza cuando una operación con Ollama supera el tiempo de espera configurado.
    """
    pass


class OllamaModelNotFoundError(RuntimeError):
    """
    Error que se lanza cuando un modelo de Ollama no se encuentra.
    """
    pass


QUERY_CANCELLED_MESSAGE = "Consulta cancelada por el usuario."


def _service_url_from_env(env_name: str, default_host: str) -> str:
    """
    Construye la URL de un servicio a partir de una variable de entorno, con soporte para esquemas y puertos.

    Args:
        env_name (str): Nombre de la variable de entorno que contiene la URL o el host del servicio.
        default_host (str): Host por defecto si la variable de entorno no está definida.

    Returns:
        str: URL completa del servicio.
    """
    value = os.getenv(env_name, default_host).strip().rstrip("/")
    if "://" not in value:
        scheme = os.getenv(f"{env_name}_SCHEME", "http").strip() or "http"
        return f"{scheme}://{value}"
    return value


OLLAMA_BASE_URL = _service_url_from_env("OLLAMA_BASE_URL", "127.0.0.1:11434")

# Qdrant (Docker / remoto)
_qdrant_url = os.getenv("QDRANT_URL", "").strip()
QDRANT_URL = _service_url_from_env("QDRANT_URL", "") if _qdrant_url else ""
QDRANT_HOST = os.getenv("QDRANT_HOST", "qdrant").strip()
QDRANT_PORT = int(os.getenv("QDRANT_PORT", "6333"))
QDRANT_API_KEY = os.getenv("QDRANT_API_KEY") or None

# =========================
# Función para medir los tiempos de ejecución
# =========================
@contextmanager
def timed_block(name: str):
    """
    Método para medir el tiempo de un bloque de código.
    Escribe el resultado en el logger.
    """
    start = time.perf_counter()
    try:
        yield
    finally:
        elapsed = time.perf_counter() - start
        logger.info("Tiempo %s: %.3f s", name, elapsed)


# =========================
# Settings: configuración del modelo de embeddings y de la base vectorial
# =========================
@dataclass
class Settings:
    """
    Parámetros de configuración básicos del sistema.

    Solo se guardan los valores necesarios para:
        Cargar el modelo de embeddings.
        Conectarse a Qdrant.
    """
    
    # Embeddings
    TEXT_EMBEDDING_MODEL_ID: str = os.getenv(
        "TEXT_EMBEDDING_MODEL_ID",
        "sentence-transformers/all-MiniLM-L6-v2",
    )
    RAG_MODEL_DEVICE: str = os.getenv(
        "RAG_MODEL_DEVICE",
        "cuda" if torch is not None and torch.cuda.is_available() else "cpu",
    )
    EMBEDDING_BATCH_SIZE: int = int(os.getenv("EMBEDDING_BATCH_SIZE", "32"))

    # Ollama
    DEFAULT_RAG_LLM_MODEL: str = os.getenv(
        "RAG_LLM_MODEL",
        os.getenv("OLLAMA_MODEL", "llama3.1:8b-instruct-q4_K_M"),
    )
    RAG_LLM_MODELS: str = os.getenv(
        "RAG_LLM_MODELS",
        f"{DEFAULT_RAG_LLM_MODEL},gemma3:4b,qwen3:4b-instruct",
    )
    _ollama_num_gpu = os.getenv("OLLAMA_NUM_GPU")
    _cuda_available = torch is not None and torch.cuda.is_available()
    if _ollama_num_gpu not in (None, ""):
        OLLAMA_NUM_GPU: int = int(_ollama_num_gpu)
        OLLAMA_NUM_GPU_SOURCE: str = "env"
    elif _cuda_available:
        OLLAMA_NUM_GPU: int = -1
        OLLAMA_NUM_GPU_SOURCE: str = "auto-cuda-full-offload"
    else:
        OLLAMA_NUM_GPU: int = 0
        OLLAMA_NUM_GPU_SOURCE: str = "auto-cpu"
    OLLAMA_CONNECT_TIMEOUT_SECONDS: float = float(
        os.getenv("OLLAMA_CONNECT_TIMEOUT_SECONDS", "10")
    )
    _ollama_read_timeout = os.getenv("OLLAMA_READ_TIMEOUT_SECONDS")
    OLLAMA_READ_TIMEOUT_SECONDS: Optional[float] = (
        float(_ollama_read_timeout)
        if _ollama_read_timeout not in (None, "")
        else None
    )
    OLLAMA_WRITE_TIMEOUT_SECONDS: float = float(
        os.getenv("OLLAMA_WRITE_TIMEOUT_SECONDS", "120")
    )
    OLLAMA_POOL_TIMEOUT_SECONDS: float = float(
        os.getenv("OLLAMA_POOL_TIMEOUT_SECONDS", "10")
    )
    OLLAMA_PULL_TIMEOUT_SECONDS: float = float(
        os.getenv("OLLAMA_PULL_TIMEOUT_SECONDS", "1800")
    )
    OLLAMA_PULL_IDLE_TIMEOUT_SECONDS: float = float(
        os.getenv("OLLAMA_PULL_IDLE_TIMEOUT_SECONDS", "300")
    )
    OLLAMA_PULL_LOG_INTERVAL_SECONDS: float = float(
        os.getenv("OLLAMA_PULL_LOG_INTERVAL_SECONDS", "20")
    )

    # Qdrant
    USE_QDRANT_CLOUD: bool = False
    QDRANT_DATABASE_HOST: str = "localhost"
    QDRANT_DATABASE_PORT: int = 6333
    QDRANT_CLOUD_URL: str = _service_url_from_env("QDRANT_CLOUD_URL", "localhost:6333")
    QDRANT_APIKEY: Optional[str] = None


settings = Settings()


def _embedding_execution_backend() -> str:
    device = settings.RAG_MODEL_DEVICE
    if device.startswith("cuda"):
        if torch is None:
            return f"{device} (torch no disponible)"
        if not torch.cuda.is_available():
            return f"{device} (CUDA no disponible)"
        gpu_name = torch.cuda.get_device_name(0)
        gpu_count = torch.cuda.device_count()
        return f"GPU {device} ({gpu_name}, total_gpus={gpu_count})"
    return f"CPU ({device})"


def _ollama_execution_backend() -> str:
    num_gpu = settings.OLLAMA_NUM_GPU
    if num_gpu == -1:
        return f"GPU (num_gpu=-1, all layers when possible, source={settings.OLLAMA_NUM_GPU_SOURCE})"
    if num_gpu > 0:
        return f"GPU (num_gpu={num_gpu} layers, source={settings.OLLAMA_NUM_GPU_SOURCE})"
    return f"CPU (num_gpu=0, source={settings.OLLAMA_NUM_GPU_SOURCE})"


def get_ollama_execution_device() -> str:
    return "GPU" if settings.OLLAMA_NUM_GPU != 0 else "CPU"


def resolve_rag_llm_model(model: str | None = None) -> str:
    """
    Resuelve el modelo LLM que se usara para una consulta RAG.

    Si no se le pasa ningun valor, se usa el modelo configurado.
    
    Args:
        model: nombre del modelo a usar (opcional).
        
    Returns:
        El nombre del modelo a usar, limpio de espacios.
    """
    selected_model = (model or "").strip()
    return selected_model or settings.DEFAULT_RAG_LLM_MODEL


def get_available_rag_llm_models() -> list[str]:
    """
    Devuelve la lista de modelos LLM disponibles para el selector RAG.

    La lista se configura con RAG_LLM_MODELS separando modelos por comas.
    El modelo por defecto siempre queda incluido.
    """
    configured_models = [
        item.strip()
        for item in (settings.RAG_LLM_MODELS or "").split(",")
        if item.strip()
    ]
    models = [settings.DEFAULT_RAG_LLM_MODEL, *configured_models]
    return list(dict.fromkeys(models))


def get_rag_llm_model_choices() -> list[tuple[str, str]]:
    """
    Devuelve opciones (valor, etiqueta) para formularios HTML.
    """
    return [(model, model) for model in get_available_rag_llm_models()]


def _format_bytes(value: Any) -> str:
    """ 
    Formatea un valor numérico de bytes en una cadena legible con unidades (B, KB, MB, GB, TB).

    Args:
        value (Any): Valor numérico que representa una cantidad de bytes. Si no es un número o es negativo, se devuelve "-".

    Returns:
        str: Cadena formateada con la cantidad de bytes y su unidad correspondiente, o "-" si el valor no es válido.
    """
    if not isinstance(value, (int, float)) or value < 0:
        return "-"
    units = ("B", "KB", "MB", "GB", "TB")
    amount = float(value)
    unit = units[0]
    for unit in units:
        if amount < 1024 or unit == units[-1]:
            break
        amount /= 1024
    if unit == "B":
        return f"{int(amount)} {unit}"
    return f"{amount:.1f} {unit}"


def _format_ollama_pull_progress(model_name: str, payload: dict[str, Any]) -> str:
    """
    Formatea el progreso de la descarga de un modelo en Ollama a partir de la información recibida en el payload.
    Args:
        model_name: Nombre del modelo que se está descargando.
        payload: Diccionario con la información de progreso enviada por Ollama.
    Returns:
        Cadena formateada con el estado actual de la descarga, incluyendo porcentaje y tamaño si están disponibles.
    """
    status = payload.get("status") or "descargando"
    digest = (payload.get("digest") or "").strip()
    completed = payload.get("completed")
    total = payload.get("total")

    progress = ""
    if isinstance(completed, (int, float)) and isinstance(total, (int, float)) and total > 0:
        percent = min(100.0, max(0.0, completed * 100.0 / total))
        progress = f" {percent:.1f}% ({_format_bytes(completed)} / {_format_bytes(total)})"
    elif isinstance(completed, (int, float)):
        progress = f" ({_format_bytes(completed)})"

    digest_suffix = f" {digest[:12]}" if digest else ""
    return f"{model_name}: {status}{digest_suffix}{progress}".strip()


async def ensure_ollama_model_available(
    client: httpx.AsyncClient,
    model_name: str,
    should_cancel=None,
    on_status=None,
) -> None:
    """
    Comprueba que el modelo exista en Ollama y lo descarga si falta.
    Esto permite que un usuario levante el proyecto en local y use cualquier
    modelo del desplegable sin ejecutar manualmente `ollama pull`.
    
    Args:
        client: Cliente HTTP asíncrono configurado para comunicarse con Ollama.
        model_name: Nombre del modelo a comprobar/descargar.
        should_cancel: Función opcional que indica si se ha solicitado cancelar la operación.
        on_status: Función opcional para recibir actualizaciones de estado (cadena).
    """
    if should_cancel and should_cancel():
        raise QueryCancelledError(QUERY_CANCELLED_MESSAGE)

    show_response = await client.post("/api/show", json={"model": model_name})
    if show_response.status_code == 200:
        logger.info("Modelo %s disponible en Ollama.", model_name)
        return

    if show_response.status_code != 404:
        try:
            show_response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            details = (show_response.text or "").strip()
            raise RuntimeError(
                f"Ollama devolvió HTTP {show_response.status_code} comprobando el modelo '{model_name}': {details}"
            ) from exc

    message = f"Descargando modelo {model_name}. Puede tardar varios minutos..."
    logger.info("Modelo %s no encontrado en Ollama. Descargando automáticamente...", model_name)
    if on_status:
        on_status(message)

    started_at = time.monotonic()
    last_log_at = 0.0
    last_progress = ""
    total_timeout = settings.OLLAMA_PULL_TIMEOUT_SECONDS
    idle_timeout = settings.OLLAMA_PULL_IDLE_TIMEOUT_SECONDS
    log_interval = settings.OLLAMA_PULL_LOG_INTERVAL_SECONDS

    async with client.stream(
        "POST",
        "/api/pull",
        json={"model": model_name, "stream": True},
    ) as pull_response:
        try:
            pull_response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            error_body = await pull_response.aread()
            error_detail = error_body.decode("utf-8", errors="replace").strip()
            raise OllamaModelNotFoundError(
                f"No se pudo descargar el modelo '{model_name}' desde Ollama: {error_detail}"
            ) from exc

        line_iterator = pull_response.aiter_lines()
        while True:
            if should_cancel and should_cancel():
                raise QueryCancelledError(QUERY_CANCELLED_MESSAGE)

            elapsed = time.monotonic() - started_at
            if total_timeout > 0 and elapsed >= total_timeout:
                raise OllamaTimeoutError(
                    f"La descarga del modelo '{model_name}' superó {total_timeout:g} s."
                )

            read_timeout = idle_timeout if idle_timeout > 0 else None
            if total_timeout > 0:
                remaining = max(0.1, total_timeout - elapsed)
                read_timeout = min(read_timeout, remaining) if read_timeout else remaining

            try:
                line = await asyncio.wait_for(line_iterator.__anext__(), timeout=read_timeout)
            except StopAsyncIteration:
                break
            except asyncio.TimeoutError as exc:
                raise OllamaTimeoutError(
                    f"La descarga del modelo '{model_name}' no avanzó durante {read_timeout:g} s."
                ) from exc

            if not line:
                continue
            payload = json.loads(line)
            if payload.get("error"):
                raise OllamaModelNotFoundError(
                    f"No se pudo descargar el modelo '{model_name}': {payload['error']}"
                )
            if payload.get("status"):
                progress = _format_ollama_pull_progress(model_name, payload)
                now = time.monotonic()
                is_done = bool(payload.get("done")) or payload.get("status") == "success"
                should_log = (
                    progress != last_progress
                    and (now - last_log_at >= log_interval or is_done)
                )
                if should_log:
                    logger.info("Descarga Ollama %s", progress)
                    if on_status:
                        on_status(progress)
                    last_progress = progress
                    last_log_at = now


async def ensure_ollama_model_ready(
    model_name: str,
    should_cancel=None,
    on_status=None,
) -> None:
    """
    Abre un cliente de Ollama y garantiza que el modelo indicado este listo.
     Esto incluye comprobar su disponibilidad y descargarlo si es necesario.
     
     Args:
        model_name: Nombre del modelo a garantizar.
        should_cancel: Función opcional que indica si se ha solicitado cancelar la operación.
        on_status: Función opcional para recibir actualizaciones de estado (cadena).
        
     Raises:
        QueryCancelledError: Si se ha solicitado cancelar la operación.
        OllamaModelNotFoundError: Si el modelo no se encuentra en Ollama y no se puede descargar.
        OllamaTimeoutError: Si la operación de descarga supera el tiempo de espera configurado.
    """
    timeout = httpx.Timeout(
        connect=settings.OLLAMA_CONNECT_TIMEOUT_SECONDS,
        read=settings.OLLAMA_READ_TIMEOUT_SECONDS,
        write=settings.OLLAMA_WRITE_TIMEOUT_SECONDS,
        pool=settings.OLLAMA_POOL_TIMEOUT_SECONDS,
    )
    async with httpx.AsyncClient(base_url=OLLAMA_BASE_URL, timeout=timeout) as client:
        await ensure_ollama_model_available(
            client,
            model_name,
            should_cancel=should_cancel,
            on_status=on_status,
        )


# =========================
# Tokenizer / EmbeddingModelSingleton
# =========================
class EmbeddingModelSingleton:
    """
    Capa de acceso al modelo de embeddings (patrón Singleton).

    - Carga el modelo de sentence-transformers.
    - Expone:
        tokenizer: para dividir el texto en tokens y hacer el splitter.
        embedding_size: dimensión de los vectores (para configurar Qdrant).
        max_input_length: nº máximo de tokens (para controlar el tamaño de los chunks).
    - Permite llamar a la instancia como una función para obtener embeddings.
    """
    _instance: "EmbeddingModelSingleton|None" = None

    def __new__(cls, *args, **kwargs):
        """
        Garantiza que solo exista una instancia del modelo en todo el proceso.
        Si ya se ha creado una instancia, devuelve esa en lugar de crear una nueva.
        
        Args:
            *args: Argumentos posicionales para la creación de la instancia (se ignoran si la instancia ya existe).
            **kwargs: Argumentos de palabra clave para la creación de la instancia (se ignoran si la instancia ya existe).
            
        Returns:    
            La instancia única del modelo de embeddings.
        """
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(
        self,
        model_id: str = settings.TEXT_EMBEDDING_MODEL_ID,
        device: str = settings.RAG_MODEL_DEVICE,
        cache_dir: Optional[Path] = None,
    ):
        """
        Inicializa el modelo de embeddings si no se ha inicializado ya.
        Carga el modelo de SentenceTransformers y lo pone en modo evaluación.
        
        Args:
            model_id: Identificador del modelo de embeddings a cargar.
            device: Dispositivo en el que cargar el modelo (e.g., "cpu", "cuda").
            cache_dir: Directorio opcional para almacenar caché de modelos.
        """
        # Evita re-inicializar si el objeto ya estaba creado
        if hasattr(self, "_initialized"):
            return
        self._initialized = True

        self._model_id = model_id
        self._device = device
        # Carga del modelo de SentenceTransformers
        self._model = SentenceTransformer(
            model_id,
            device=device,
            cache_folder=str(cache_dir) if cache_dir else None,
        )
        # Modo evaluación
        self._model.eval()

    @staticmethod
    def _is_cuda_out_of_memory(error: Exception) -> bool:
        """
        Detecta si un error de ejecución es debido a falta de memoria en CUDA.
        
        Args:            
            error (Exception): El error a analizar.
            
        Returns:
            bool: True si el error parece ser un out of memory de CUDA, False en caso contrario.
        """
        message = str(error).lower()
        return "cuda" in message and ("out of memory" in message or "cuda out of memory" in message)

    def _clear_cuda_cache(self) -> None:
        """
        Intenta limpiar la caché de CUDA para liberar memoria después de un error de out of memory.
        """
        if torch is not None and hasattr(torch, "cuda") and hasattr(torch.cuda, "empty_cache"):
            try:
                torch.cuda.empty_cache()
            except Exception:
                logger.debug("No se pudo limpiar la cache CUDA tras fallo de embeddings.", exc_info=True)

    def _move_to_cpu(self) -> None:
        """
        Mueve el modelo a la CPU, si se detecta que el error fue por falta de memoria en CUDA, para permitir que la 
        operación de embeddings pueda completarse aunque sea más lenta.
        """
        if self._device == "cpu":
            return
        if hasattr(self._model, "to"):
            self._model.to("cpu")
        self._device = "cpu"
        settings.RAG_MODEL_DEVICE = "cpu"
        logger.warning(
            "CUDA sin memoria para embeddings; se reintentara en CPU con model_id=%s.",
            self._model_id,
        )

    @property
    def model_id(self) -> str:
        """
        Devuelve el identificador del modelo de embeddings utilizado.
        
        Returns:
            str: El identificador del modelo de embeddings.
        """
        return self._model_id

    @cached_property
    def embedding_size(self) -> int:
        """
        Dimensión de los vectores de embeddings.
        Se usa al crear las colecciones de Qdrant para indicar el tamaño del vector.
        
        Returns:
            int: La dimensión de los vectores de embeddings.
        """
        return int(self._model.get_sentence_embedding_dimension())

    @property
    def max_input_length(self) -> int:
        """
        Longitud máxima de tokens que admite el modelo.
        Sirve para construir el splitter por tokens y evitar pasarle secuencias
        más largas de lo permitido.
        
        Returns:
            int: El número máximo de tokens que el modelo puede procesar.
        """
        return int(getattr(self._model, "max_seq_length", 512))

    @property
    def tokenizer(self):
        """
        Devuelve el tokenizer asociado al modelo de embeddings.
        Este tokenizer es el que se usa para contar tokens y trocear el texto
        en chunks de tamaño controlado.
        
        Returns:
            El tokenizer del modelo de embeddings.
        """
        return self._model.tokenizer

    def __call__(self, input_text, to_list: bool = True):
        """
        Calcula los embeddings de un texto o lista de textos.
        
        Args:
            input_text: str o list[str] con el texto de entrada.
            to_list: si es True, devuelve los vectores como listas de Python,
                     lo cual facilita su uso y serialización.
                     
        Returns:
            Vector o lista de vectores de embeddings.
        
        Raises:
            RuntimeError: Si ocurre un error durante la generación de embeddings que no sea por falta de memoria en CUDA.
            QueryCancelledError: Si se detecta que el usuario ha cancelado la consulta.
        """
        try:
            emb = self._model.encode(
                input_text,
                batch_size=settings.EMBEDDING_BATCH_SIZE,
                convert_to_numpy=True,
                show_progress_bar=False,
            )
        except RuntimeError as exc:
            if not self._is_cuda_out_of_memory(exc) or self._device == "cpu":
                raise
            self._clear_cuda_cache()
            self._move_to_cpu()
            emb = self._model.encode(
                input_text,
                batch_size=settings.EMBEDDING_BATCH_SIZE,
                convert_to_numpy=True,
                show_progress_bar=False,
            )
        if to_list:
            if isinstance(input_text, list):
                #  Lista de vectores
                return [e.tolist() if hasattr(e, "tolist") else list(e) for e in emb]
            # Vector
            return emb.tolist() if hasattr(emb, "tolist") else list(emb)
        return emb


class LazyEmbeddingModel:
    """
    Carga el modelo de embeddings solo cuando alguna operación RAG lo necesita.
    Esto permite que la aplicación Flask se inicie rápidamente sin cargar modelos ni usar memoria hasta que sea necesario."""

    def __init__(self):
        """
        Inicializa la instancia sin cargar el modelo.
        """
        self._instance: EmbeddingModelSingleton | None = None

    def _get_instance(self) -> EmbeddingModelSingleton:
        """
        Obtiene la instancia del modelo de embeddings, cargándola si aún no se ha cargado.
        
        Returns:
            EmbeddingModelSingleton: La instancia del modelo de embeddings.
            
        Raises:
            RuntimeError: Si ocurre un error durante la carga del modelo de embeddings.
        """
        if self._instance is None:
            start_model = time.perf_counter()
            self._instance = EmbeddingModelSingleton()
            logger.info("Tiempo carga modelo embeddings: %.3f s", time.perf_counter() - start_model)
            logger.info(
                "Modelo de embeddings cargado en %s | model_id=%s",
                _embedding_execution_backend(),
                settings.TEXT_EMBEDDING_MODEL_ID,
            )
        return self._instance

    def __getattr__(self, name: str):
        """
        Redirige el acceso a atributos al modelo de embeddings, cargándolo si es necesario.
        
        Args:
            name: Nombre del atributo al que se quiere acceder.
            
        Returns:            
            El valor del atributo solicitado del modelo de embeddings.
        """
        return getattr(self._get_instance(), name)

    def __call__(self, input_text, to_list: bool = True):
        """ 
        Permite llamar a la instancia como una función para obtener embeddings, redirigiendo la llamada al modelo de embeddings.        

        Args:
            input_text (str | list[str]): Texto o lista de textos a los que se les quieren calcular los embeddings.
            to_list (bool, optional): Si es True, devuelve una lista de vectores. Defaults to True.

        Returns:
            Vector o lista de vectores de embeddings calculados por el modelo.
        """
        return self._get_instance()(input_text, to_list=to_list)


# Instancia única disponible para el resto del código. La carga real es perezosa
# para que crear la aplicación Flask no descargue modelos ni contacte servicios externos.
embedding_model = LazyEmbeddingModel()


# =========================
# Conexión Qdrant
# =========================
def _make_qdrant_client() -> QdrantClient:
    """
    Crea un cliente de Qdrant apuntando al servicio de Qdrant (Docker / remoto).
    Si no hay variables de entorno, intenta una conexión por host/port.   
    
    Returns:
        QdrantClient conectado al servicio de Qdrant. 
        
    Raises:
        RuntimeError: Si no se pudo conectar a Qdrant después de varios intentos.
    """
    try:
        client = (
            QdrantClient(url=QDRANT_URL, api_key=QDRANT_API_KEY)
            if QDRANT_URL
            else QdrantClient(host=QDRANT_HOST, port=QDRANT_PORT, api_key=QDRANT_API_KEY)
        )

        for _ in range(20):
            try:
                client.get_collections()
                return client
            except Exception:
                time.sleep(0.5)

        logger.warning("Qdrant no responde tras varios intentos.")
        return None
    except Exception as e:
        logger.warning("No se pudo inicializar Qdrant remoto (%s:%s / url=%s): %s",
                       QDRANT_HOST, QDRANT_PORT, QDRANT_URL or "-", e)
        raise RuntimeError("No se pudo conectar a Qdrant")



class LazyQdrantClient:
    """
    Crea el cliente Qdrant al primer uso, no durante el import del módulo.
    Esto permite que la aplicación Flask se inicie rápidamente sin intentar conectar a Qdrant hasta que sea necesario.
    """

    def __init__(self):
        """
        Inicializa la instancia sin crear el cliente de Qdrant.
        """
        self._client: QdrantClient | None = None

    def _get_client(self) -> QdrantClient:
        """ 
        Obtiene el cliente de Qdrant, creándolo si aún no se ha creado.
        
        Returns:
            QdrantClient: El cliente de Qdrant listo para usar.
        
        Raises:
            RuntimeError: Si no se pudo conectar a Qdrant.
        """

        if self._client is None:
            self._client = _make_qdrant_client()
        if self._client is None:
            raise RuntimeError("Qdrant no está disponible")
        return self._client

    def __getattr__(self, name: str):
        """ 
        Redirige el acceso a los métodos al cliente de Qdrant, creándolo si es necesario.
        
        Args:
            name (str): Nombre del método de Qdrant al que se quiere acceder.

        Returns:
            El método solicitado del cliente de Qdrant.
        """
        return getattr(self._get_client(), name)

    def close(self) -> None:
        """ 
        Cierra la conexión del cliente de Qdrant si está abierta para liberar recursos.
        """
        if self._client is not None:
            self._client.close()
            self._client = None


# Cliente global de Qdrant. La conexión real es perezosa.
qdrant = LazyQdrantClient()

@atexit.register
def _close_qdrant():
    """ 
    Cierra la conexión de Qdrant al salir del proceso para liberar recursos.
    """
    global qdrant
    try:
        if qdrant is not None:
            qdrant.close()
    except Exception as e:
        logger.debug("Error cerrando Qdrant al salir: %s", e)
    finally:
        qdrant = None

def pdf_sha256(path: Path) -> str:
    """
    Calcula el hash SHA-256 de un archivo PDF.
    Este hash se utiliza como identificador de contenido del documento,
    permitiendo detectar si un PDF ha cambiado aunque mantenga el mismo nombre.

    Argumentos:
        path: Ruta al archivo PDF.

    Returns:
        Hash SHA-256 hexadecimal del contenido del archivo.
    """
    h = sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def _qdrant_filter_by_filename(filename: str) -> qmodels.Filter:
    """Construye un filtro de Qdrant por nombre de archivo.

    Args:
        filename: Nombre del archivo PDF.

    Returns:
        Filtro listo para usar en búsquedas o borrados.
    """
    return qmodels.Filter(
        must=[
            qmodels.FieldCondition(
                key="metadata.filename",
                match=qmodels.MatchValue(value=filename),
            )
        ]
    )


def _qdrant_filter_by_filename_and_hash(filename: str, doc_hash: str) -> qmodels.Filter:
    """
    Construye un filtro de Qdrant para comprobar si un PDF concreto ya está indexado y 
    coincide con una versión concreta del documento, es decir, si coinciden los hash.
    Este filtro se usa para decidir si un PDF puede omitirse durante el indexado incremental.

    Argumentos:
        filename: Nombre del archivo PDF.
        doc_hash: Hash SHA-256 del contenido del PDF.

    Returns:
        Filtro combinando nombre de archivo y hash.
    """
    return qmodels.Filter(
        must=[
            qmodels.FieldCondition(
                key="metadata.filename",
                match=qmodels.MatchValue(value=filename),
            ),
            qmodels.FieldCondition(
                key="metadata.sha256",
                match=qmodels.MatchValue(value=doc_hash),
            ),
        ]
    )


def qdrant_has_filename(filename: str) -> bool:
    """
    Comprueba si existen chunks indexados en Qdrant para un PDF concreto,
    independientemente de su versión. Se usa para distinguir entre un PDF nuevo y un PDF ya indexado.
    
    Argumentos:
        filename: Nombre del archivo PDF.

    Returns:
        True si existe al menos un chunk asociado al archivo.
    """
    records, _ = qdrant.scroll(
        collection_name=VectorBaseDocument.get_collection_name(),
        limit=1,
        with_payload=False,
        with_vectors=False,
        scroll_filter=_qdrant_filter_by_filename(filename),
    )
    return len(records) > 0


def qdrant_has_same_hash(filename: str, doc_hash: str) -> bool:
    """
    Comprueba si un PDF ya está indexado en Qdrant y además coincide con la versión actual 
    del archivo (mismo hash SHA-256).

    Argumentos:
        filename: Nombre del archivo PDF.
        doc_hash: Hash SHA-256 del contenido del PDF.

    Returns:
        True si el documento ya está indexado y no ha cambiado; Fase si el documento no esta inlcuido o ha cambiado.
    """
    records, _ = qdrant.scroll(
        collection_name=VectorBaseDocument.get_collection_name(),
        limit=1,
        with_payload=False,
        with_vectors=False,
        scroll_filter=_qdrant_filter_by_filename_and_hash(filename, doc_hash),
    )
    return len(records) > 0


def qdrant_delete_by_filename(filename: str) -> None:
    """
    Elimina de Qdrant todos los chunks asociados a un archivo PDF concreto.
    Esta función se utiliza cuando se detecta que un PDF ha cambiado. Primero eliminan los chunks 
    antiguos y luego indexa de nuevo el documento actualizado.

    Argumentos:
        filename: Nombre del archivo PDF a eliminar de la base vectorial.
    """
    VectorBaseDocument._ensure_collection()
    qdrant.delete(
        collection_name=VectorBaseDocument.get_collection_name(),
        points_selector=qmodels.FilterSelector(
            filter=_qdrant_filter_by_filename(filename)
        ),
    )
    
def qdrant_get_payloads(point_ids: list[str]) -> dict[str, dict]:
    """ Recupera los datos de Qdrant (playloads sin metadatos) para una lista de identificadores, manejando errores y devolviendo un diccionario con los payloads encontrados.
    
    Args:
        point_ids: Lista de identificadores de puntos en Qdrant para los cuales se desean obtener los payloads.
    
    Returns:
        dict[str, dict]: Diccionario con los payloads encontrados. Las claves son los identificadores de los puntos y los valores son los payloads correspondientes. 
        Si ocurre un error durante la recuperación, se devuelve un diccionario vacío.
    """
    ids = [i for i in point_ids if i]
    if not ids:
        return {}
    try:
        res = qdrant.retrieve(
            collection_name=VectorBaseDocument.get_collection_name(),
            ids=ids,
            with_payload=True,
            with_vectors=False,
        )
    except ValueError as e:
        logger.warning("Qdrant sin colección (%s). Devolviendo payloads vacíos.", e)
        return {}
    except Exception as e:
        logger.warning("Error leyendo payloads de Qdrant: %s. Devolviendo payloads vacíos.", e)
        return {}
    
    out:  dict[str, dict] = {}
    for r in (res or []):
        out[str(r.id)] = (r.payload or {})
    return out

# =========================
# OVM mínimo (Object–Vector Mapping)
# =========================
T = TypeVar("T", bound="VectorBaseDocument")


class VectorBaseDocument(BaseModel, Generic[T]):
    """
    Entidad base con mapeo a Qdrant (payload + vector).

    Representa la forma estándar en la que cualquier "documento embebido"
    se guarda en la base de datos vectorial:

        id: identificador único (UUID).
        content: texto del chunk.
        embedding: vector de floats asociado al contenido.
        metadata: información adicional (nombre de archivo, tipo, etc.).

    Las subclases heredan estos campos y las operaciones de guardado/búsqueda.
    """

    id: UUID = Field(default_factory=uuid4)
    content: str
    # El vector se guarda fuera del payload en Qdrant
    embedding: list[float] | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)

    class Config:
        """ 
        Configuración de Pydantic para permitir tipos personalizados.
        """
        # Permite tipos que no son estándar de Pydantic
        arbitrary_types_allowed = True

    # ---- utilidades de colección
    @classmethod
    def get_collection_name(cls) -> str:
        """
        Obtiene el nombre de colección de Qdrant para esta clase.
        Cambia los espacios por '_' y elimina las mayúsculas.
        """
        name = cls.__name__
        s1 = re.sub("(.)([A-Z][a-z]+)", r"\1_\2", name)
        return re.sub("([a-z0-9])([A-Z])", r"\1_\2", s1).lower()

    # ---- creación de colección (idempotente)
    @classmethod
    def _ensure_collection(cls) -> None:
        """
        Garantiza que exista la colección asociada en Qdrant.
        Si la colección no existe, la crea usnado:
            tamaño de vector `embedding_model.embedding_size`
            métrica de similitud por coseno.
        """
        collection = cls.get_collection_name()
        dim = embedding_model.embedding_size
        try:
            qdrant.get_collection(collection)
        except Exception:
            qdrant.recreate_collection(
                collection_name=collection,
                vectors_config=qmodels.VectorParams(
                    size=dim,
                    distance=qmodels.Distance.COSINE,
                ),
            )

    # ---- mapeos
    def to_point(self) -> qmodels.PointStruct:
        """
        Convierte la instancia en un PointStruct de Qdrant.
        El payload incluye tanto el contenido como metadatos del modelo
        (id, dimensión, max_input_length) para poder auditar y reproducir
        la generación de embeddings.
        
        Returns:
            qmodels.PointStruct listo para insertar en Qdrant.
        """
        payload = {
            "content": self.content,
            "metadata": self.metadata,
            "model_id": embedding_model.model_id,
            "embedding_size": embedding_model.embedding_size,
            "max_input_length": embedding_model.max_input_length,
        }
        return qmodels.PointStruct(
            id=str(self.id),
            vector=self.embedding,
            payload=payload,
        )

    @classmethod
    def from_record(cls: Type[T], record: qmodels.ScoredPoint | qmodels.Record) -> T:
        """
        Crea una instancia de la clase a partir de un registro de Qdrant.
        """
        payload = record.payload or {}
        return cls(
            id=UUID(str(record.id)),
            content=payload.get("content", ""),
            embedding=getattr(record, "vector", None),
            metadata=payload.get("metadata", {}) or {},
        )

    # ---- escritura
    def save(self) -> None:
        """
        Guarda la instancia actual en Qdrant.
        Usa upsert, de modo que si el id ya existía lo sobrescribe.
        """
        type(self)._ensure_collection()
        point = self.to_point()
        qdrant.upsert(collection_name=type(self).get_collection_name(), points=[point])

    @classmethod
    def save_many(cls: Type[T], docs: list[T]) -> None:
        """
        Guarda una lista de documentos de golpe en Qdrant.
        Eficiente para cargar muchos chunks producidos en el pipeline.
        
        Args:
            cls: La clase de los documentos a guardar (subclase de VectorBaseDocument).
            docs: Lista de instancias a guardar. Cada una se convertirá en un punto de Qdrant usando `to_point()`.
        """
        cls._ensure_collection()
        points = [d.to_point() for d in docs]
        qdrant.upsert(collection_name=cls.get_collection_name(), points=points)

    @classmethod
    def bulk_find(
        cls: Type[T], 
        limit: int = 10, 
        offset: UUID | None = None,
    ) -> tuple[list[T], UUID | None]:
        """
        Recupera documentos de la colección usando scroll (paginación).
        
        Args:
            limit: número máximo de documentos a devolver.
            offset: id a partir del cual continuar el scroll.
            
        Returns:
            (lista_de_docs, siguiente_offset) donde siguiente_offset
            puede usarse en la siguiente llamada para seguir recorriendo.
        """
        cls._ensure_collection()
        off = str(offset) if offset else None
        records, next_off = qdrant.scroll(
            collection_name=cls.get_collection_name(),
            limit=limit,
            with_payload=True,
            with_vectors=False,
            offset=off,
        )
        docs = [cls.from_record(r) for r in records]
        return docs, (UUID(next_off, version=4) if next_off else None)

    # ---- búsqueda vectorial
    @classmethod
    def search(
        cls: Type[T],
        query_vector: list[float],
        limit: int = 10,
        **kwargs,
    ) -> list[T]:
        """
        Realiza una búsqueda vectorial en Qdrant usando el vector de consulta.
        
        Args:
            cls: La clase de los documentos a recuperar (subclase de VectorBaseDocument).
            query_vector: El vector de embedding que se usará para la búsqueda de similitud.
            limit: El número máximo de resultados a devolver.
            **kwargs: Argumentos adicionales para la consulta de Qdrant (e.g., filtros).
                
        Returns:
            Lista de instancias de la clase que representan los documentos más similares encontrados.
        """
        cls._ensure_collection()
        records = qdrant.query_points(
            collection_name=cls.get_collection_name(),
            query=query_vector,
            limit=limit,
            with_payload=True,
            with_vectors=False,
            **kwargs,
        )
        points = getattr(records, "points", records)
        return [cls.from_record(p) for p in points]
    
    
# =========================
# Chunks
# =========================
def chunk_text(text: str, overlap_ratio: float = 0.1) -> list[str]:
    """
    Trocea un texto largo en chunks controlando el número de tokens. 
    Añade un pequeño solapamiento (overlap)
    Para ello:
        Se recorre el texto línea a línea.
        Se tokeniza cada línea con el tokenizer del modelo.
        Se van concatenando líneas hasta que el número de tokens alcanza max_len.
        Cuando se supera el límite, se empieza un nuevo chunk.
    Si alguna línea produce un error de tokenización, se ignora.
    
    Args:
        text: El texto a trocear en chunks.
        overlap_ratio: Porcentaje de tokens que se solapan entre chunks consecutivos.
        
    Returns:
        Lista de strings, cada uno representando un chunk del texto original.
    """
    # Obtiene el tokenizer del modelo y calculamos un límite de tokens
    tokenizer = embedding_model.tokenizer
    # Márgen de seguridad, solo se usa el 80% de la capacidad del modelo
    max_len = int(embedding_model.max_input_length * 0.8)

    # Tokens que se solapan entre chunks
    overlap_tokens = max(1, int(max_len * overlap_ratio))

    chunks: list[str] = []
    # Guardamos las líneas y su número de tokens para hacer el solapamiento
    current: list[tuple[str, int]] = []
    current_tokens = 0

    for line in iter_clean_lines(text):
        line_tokens = token_len(tokenizer, line)
        if line_tokens is None:
            continue
                
        # Si al añadir esta línea se supera el límite, se guarda el chunk actual
        if current_tokens + line_tokens > max_len and current:
            
            # Se guarda el chunk actual
            get_chunk(chunks, current)            
            # Se empieza un nuevo chunk con el solapamiento
            current, current_tokens = token_overlap(current, overlap_tokens)
        
        # Añadimos la línea actual al chunk
        current.append((line, line_tokens))
        current_tokens += line_tokens

    # Último chunk pendiente
    if current:
        get_chunk(chunks, current)  

    return chunks

def token_len(tokenizer, text: str) -> int | None:
    """
    Devuelve el número de tokens o None si falla la tokenización.
    
    Args:
        tokenizer: El tokenizer del modelo de embeddings.
        text: El texto a tokenizar.
    
    Returns:
        El número de tokens que produce el texto al ser tokenizado, o None si ocurre un error durante la tokenización.    
    """
    try:
        return len(tokenizer.tokenize(text))
    except Exception as e:
        logger.warning("No se puede tokenizar una línea: %s", e)
        return None

def get_chunk(chunks: list[str], current: list[tuple[str, int]]) -> None:
    """
    Vuelca el chunk actual si hay contenido.
    
    Args:
        chunks: Lista donde se acumulan los chunks finales.
        current: Lista de tuplas (línea, tokens) que representa el chunk actual en construcción.
        
    """
    chunk = " ".join(s for s, _ in current).strip()
    if chunk:
        chunks.append(chunk)

def token_overlap(
    current: list[tuple[str, int]],
    overlap_tokens: int,
) -> tuple[list[tuple[str, int]], int]:
    """
    Calcula el solapamiento (líneas finales) y tokens solapados.
    
    Args:
        current: Lista de tuplas (línea, tokens) que representa el chunk actual que se acaba de cerrar.
        overlap_tokens: Número máximo de tokens que se deben solapar entre el chunk cerrado y el nuevo chunk que se va a empezar.
    
    Returns:
        (overlap, tokens_in_overlap) donde overlap es la lista de tuplas (línea, tokens) que se solapan y tokens_in_overlap es el número total de tokens que suponen esas líneas.
    """
    overlap: list[tuple[str, int]] = []
    tokens_in_overlap = 0

    for s, t in reversed(current):
        if tokens_in_overlap + t > overlap_tokens:
            break
        overlap.append((s, t))
        tokens_in_overlap += t

    overlap.reverse()
    return overlap, tokens_in_overlap

def iter_clean_lines(text: str) -> Iterable[str]:
    """
    Itera líneas limpias (strip) y no vacías.
    
    Args:
        text: El texto a iterar por líneas.
    
    Yields:
        Líneas del texto que no están vacías después de aplicar strip.
    """
    for line in text.splitlines():
        line = line.strip()
        if line:
            yield line


def build_metadata_filter(
    numero_expediente: str | None = None,
    tipo_documento: str | None = None,
) -> qmodels.Filter | None:
    """ 
    Construye un filtro de Qdrant a partir de los metadatos de número de expediente y tipo de documento, si se proporcionan. Si no se proporcionan filtros, devuelve None.
    
    Args:
        numero_expediente: Número de expediente para filtrar los documentos (opcional).
        tipo_documento: Tipo de documento para filtrar los documentos (opcional).
        
    Returns:
        Un objeto qmodels.Filter que combina las condiciones de filtrado para número de expediente y tipo de documento, o None si no se proporcionan filtros.
    """
    must: list[qmodels.FieldCondition] = []

    if numero_expediente:
        must.append(
            qmodels.FieldCondition(
                key="metadata.numero_expediente",
                match=qmodels.MatchValue(value=numero_expediente),
            )
        )

    if tipo_documento:
        must.append(
            qmodels.FieldCondition(
                key="metadata.tipo_documento",
                match=qmodels.MatchValue(value=tipo_documento),
            )
        )

    if not must:
        return None

    return qmodels.Filter(must=must)

def recuperacion_chunk(
    user_query: str,
    k: int = 10,
    numero_expediente: str | None = None,
    tipo_documento: str | None = None,
) -> list[VectorBaseDocument]:
    """
    Dada una pregunta del usuario, recupera los chunks más similares desde Qdrant.
    
    Args:
        user_query: La pregunta del usuario para la que se quieren recuperar los chunks relevantes.
        k: El número máximo de chunks a recuperar.
        numero_expediente: (Opcional) Número de expediente para filtrar los chunks por sus metadatos.
        tipo_documento: (Opcional) Tipo de documento para filtrar los chunks por sus metadatos.
        
    Returns:
        Lista de instancias de VectorBaseDocument que representan los chunks más similares encontrados en Qdrant, ordenados por similitud. 
        Cada instancia incluye el contenido del chunk, su embedding y metadatos asociados.
    """
    logger.info(
        "Recuperando chunks para consulta RAG con embeddings en %s",
        _embedding_execution_backend(),
    )
    # Embedding de la pregunta
    query_vector = embedding_model(user_query, to_list=True)

    # Búsqueda vectorial en Qdrant
    query_filter = build_metadata_filter(
        numero_expediente=numero_expediente,
        tipo_documento=tipo_documento,
    )
    docs = VectorBaseDocument.search(
        query_vector=query_vector,
        limit=k,
        query_filter=query_filter,
    )

    return docs

def recuperacion_chunk_con_scores(
    user_query: str,
    k: int = 10,
    numero_expediente: str | None = None,
    tipo_documento: str | None = None,
) -> list[qmodels.ScoredPoint]:
    """
    Recupera los k chunks más similares desde Qdrant, incluyendo score e id del punto.
    
    Args:        
        user_query: La pregunta del usuario para la que se quieren recuperar los chunks relevantes.
        k: El número máximo de chunks a recuperar.
        numero_expediente: (Opcional) Número de expediente para filtrar los chunks por sus metadatos.
        tipo_documento: (Opcional) Tipo de documento para filtrar los chunks por sus metadatos.
        
    Returns:
        Lista de objetos qmodels.ScoredPoint que representan los chunks más similares encontrados en Qdrant, ordenados por similitud. 
        Cada objeto incluye el id del punto, el score de similitud, y el payload con el contenido y metadatos del chunk.  
    """
    logger.info(
        "Recuperando chunks para consulta RAG con embeddings en %s",
        _embedding_execution_backend(),
    )
    # Embedding de la pregunta
    query_vector = embedding_model(user_query, to_list=True)
    query_filter = build_metadata_filter(
        numero_expediente=numero_expediente,
        tipo_documento=tipo_documento,
    )
    try:
        VectorBaseDocument._ensure_collection()

        # Query con scores
        res = qdrant.query_points(
            collection_name=VectorBaseDocument.get_collection_name(),
            query=query_vector,
            limit=k,
            query_filter=query_filter,
            with_payload=True,
            with_vectors=False,
        )
        return getattr(res, "points", res)
    except Exception as e:
        logger.warning("Qdrant no disponible para recuperar chunks: %s", e)
        return []


# =========================
# Ollama
# =========================
async def ask_ollama(
    prompt: str,
    model: str | None = None,
    should_cancel=None,
) -> str:
    """
    Envía un prompt a Ollama usando /api/chat y devuelve el texto de respuesta.
    
    Args:
        prompt: El mensaje de entrada que se le quiere enviar a Ollama.
        model: El modelo de Ollama a usar. Si es None, se usará el modelo por defecto configurado en settings.
        should_cancel: Función opcional que devuelve True si se ha solicitado cancelar la consulta.
    
    Returns:
        La respuesta generada por Ollama como un string.
        
    Raises:
        QueryCancelledError: Si se detecta que el usuario ha cancelado la consulta.
        OllamaModelNotFoundError: Si el modelo especificado no está disponible en Ollama.
        OllamaTimeoutError: Si la consulta a Ollama supera el tiempo de espera configurado.
        RuntimeError: Si Ollama devuelve un error HTTP o si ocurre un error durante la comunicación con Ollama.    
    """
    if should_cancel and should_cancel():
        raise QueryCancelledError(QUERY_CANCELLED_MESSAGE)

    model_name = resolve_rag_llm_model(model)
    chunks: list[str] = []

    request_payload = {
        "model": model_name,
        "messages": [
            {
                "role": "system",
                "content": "Responde en español de forma breve y precisa.",
            },
            {
                "role": "user",
                "content": prompt,
            },
        ],
        "stream": True,
        "options": {
            "num_gpu": settings.OLLAMA_NUM_GPU,
        },
    }

    logger.info(
        "Consulta a Ollama | model=%s | backend=%s | base_url=%s",
        model_name,
        _ollama_execution_backend(),
        OLLAMA_BASE_URL,
    )

    timeout = httpx.Timeout(
        connect=settings.OLLAMA_CONNECT_TIMEOUT_SECONDS,
        read=settings.OLLAMA_READ_TIMEOUT_SECONDS,
        write=settings.OLLAMA_WRITE_TIMEOUT_SECONDS,
        pool=settings.OLLAMA_POOL_TIMEOUT_SECONDS,
    )
    try:
        async with httpx.AsyncClient(base_url=OLLAMA_BASE_URL, timeout=timeout) as client:
            await ensure_ollama_model_available(client, model_name, should_cancel=should_cancel)
            async with client.stream(
                "POST",
                "/api/chat",
                json=request_payload,
            ) as resp:
                try:
                    resp.raise_for_status()
                except httpx.HTTPStatusError as exc:
                    error_body = await resp.aread()
                    error_detail = error_body.decode("utf-8", errors="replace").strip()
                    if error_detail:
                        if resp.status_code == 404 and "not found" in error_detail.lower():
                            raise OllamaModelNotFoundError(
                                f"El modelo '{model_name}' no está descargado en Ollama."
                            ) from exc
                        raise RuntimeError(
                            f"Ollama devolvió HTTP {resp.status_code} para el modelo '{model_name}': {error_detail}"
                        ) from exc
                    raise

                async for line in resp.aiter_lines():
                    if should_cancel and should_cancel():
                        raise QueryCancelledError(QUERY_CANCELLED_MESSAGE)
                    if not line:
                        continue

                    payload = json.loads(line)
                    message = payload.get("message") or {}
                    piece = message.get("content") or payload.get("response")
                    if piece:
                        chunks.append(piece)

                    if payload.get("done"):
                        break
    except httpx.TimeoutException as exc:
        timeout_label = (
            f"{settings.OLLAMA_READ_TIMEOUT_SECONDS:g} s"
            if settings.OLLAMA_READ_TIMEOUT_SECONDS is not None
            else "sin limite"
        )
        raise OllamaTimeoutError(
            f"Ollama ha superado el tiempo de espera de lectura ({timeout_label})."
        ) from exc
    return "".join(chunks)


def obtener_chunk_de_query(
    user_query: str,
    numero_expediente: str | None = None,
    tipo_documento: str | None = None,
) -> dict | None:
    """
    Toma una pregunta de usuario, recupera el chunk más relevante de Qdrant.
    
    Args:       
        user_query: La pregunta del usuario para la que se quiere obtener el chunk más relevante.
        numero_expediente: (Opcional) Número de expediente para filtrar los chunks por sus metadatos.
        tipo_documento: (Opcional) Tipo de documento para filtrar los chunks por sus metadatos.
        
    Returns:
        Un diccionario con los detalles del chunk más relevante encontrado, incluyendo título del documento, nombre del archivo, índice de segmento y el texto del chunk.
        Si no se encuentra ningún chunk relevante, devuelve None.
    """
    docs = recuperacion_chunk(
        user_query,
        k=1,
        numero_expediente=numero_expediente,
        tipo_documento=tipo_documento,
    )
    if not docs:
        return None

    doc = docs[0]
    metadata = doc.metadata or {}

    return {
        "title": metadata.get("title", ""),
        "filename": metadata.get("filename", ""),
        "segment_index": metadata.get("segment_index", -1),
        "chunk": doc.content,
    }
    
    
async def obtener_mejor_chunk(
    user_query: str,
    model: str | None = None,
    should_cancel=None,
    on_status=None,
    numero_expediente: str | None = None,
    tipo_documento: str | None = None,
    ) -> dict:
    """
    Dada una pregunta del usuario, recupera los chunks más relevantes de Qdrant y usa Ollama para generar una respuesta basada en esos chunks.
    
    Args:
        user_query: La pregunta del usuario para la que se quieren recuperar los chunks relevantes y generar una respuesta.
        model: El modelo de Ollama a usar para generar la respuesta. Si es None, se usará el modelo por defecto configurado en settings.
        should_cancel: Función opcional que devuelve True si se ha solicitado cancelar la consulta. 
                    Si se detecta que el usuario ha cancelado la consulta, se lanzará una QueryCancelledError.
        on_status: Función opcional para recibir actualizaciones de estado durante el proceso. Se llamará con mensajes descriptivos de cada etapa 
                    (preparando modelo, recuperando fragmentos, generando respuesta, etc.).
        numero_expediente: (Opcional) Número de expediente para filtrar los chunks por sus metadatos durante la recuperación.
        tipo_documento: (Opcional) Tipo de documento para filtrar los chunks por sus metadatos durante la recuperación.
    
    Returns:
        Un diccionario con la respuesta generada por Ollama, detalles del chunk más relevante (título del documento, nombre del archivo, índice de segmento, texto del chunk), 
        la lista de chunks recuperados con sus scores y metadatos, el modelo usado, y los filtros aplicados. Si no se encuentra ningún chunk relevante, 
        la respuesta indicará que no se encontraron fragmentos relevantes en la base de datos. 
    """
    user_query = (user_query or "").strip()
    model_name = resolve_rag_llm_model(model)
    if should_cancel and should_cancel():
        raise QueryCancelledError(QUERY_CANCELLED_MESSAGE)

    if on_status:
        on_status(f"Preparando modelo {model_name}...")
    await ensure_ollama_model_ready(
        model_name,
        should_cancel=should_cancel,
        on_status=on_status,
    )

    if on_status:
        on_status("Recuperando fragmentos relevantes...")

    points = recuperacion_chunk_con_scores(
        user_query,
        k=10,
        numero_expediente=numero_expediente,
        tipo_documento=tipo_documento,
    )
    if not points:
        return {
            "answer": "No he encontrado ningún fragmento relevante en la base de datos.",
            "title": "",
            "filename": "",
            "segment_index": -1,
            "chunk": "",
            "retrieved": [],
            "model": model_name,
            "execution_device": get_ollama_execution_device(),
            "applied_filters": {
                "numero_expediente": numero_expediente,
                "tipo_documento": tipo_documento,
            },
        }
    
    # Normaliza a lista de dicts
    retrieved: list[dict] = []
    context_blocks: list[str] = []
    
    for idx, p in enumerate(points, start=1):
        if should_cancel and should_cancel():
            raise QueryCancelledError(QUERY_CANCELLED_MESSAGE)

        payload = p.payload or {}
        meta = (payload.get("metadata") or {})
        content = payload.get("content", "") or ""

        item = {
            "ranking": idx,
            "similitud": float(getattr(p, "score", 0.0)),
            "qdrant_point_id": str(getattr(p, "id", "")),
            "document_id": meta.get("document_id"),
            "doc_sha256": meta.get("sha256"),
            "segment_index": meta.get("segment_index", -1),
            "filename": meta.get("filename", ""),
            "title": meta.get("title", ""),
            "metadata": dict(meta),
            "chunk": content,
        }
        retrieved.append(item)
        context_blocks.append(
            f"""[CHUNK #{idx} | score={item['similitud']:.6f} | file={item['filename']} | seg={item['segment_index']}]
            \"\"\"{content}\"\"\""""
        )
        
    best = retrieved[0]
        
    # Prompt para que Ollama conteste usando los 10 chunk en ranking
    prompt = f"""
    Usa EXCLUSIVAMENTE los fragmentos proporcionados (CHUNK #1 a CHUNK #10) para responder.
    Si la respuesta no puede deducirse de esos fragmentos, di explícitamente que no hay información suficiente.

    Pregunta del usuario:
    {user_query}
    
    Fragmentos (ordenados por relevancia):
    {chr(10).join(context_blocks)}

    Responde de forma breve y precisa en español.
    """

    if on_status:
        on_status("Generando respuesta del modelo...")

    answer = await ask_ollama(prompt, model=model_name, should_cancel=should_cancel)

    return {
        "answer": answer,
        "model": model_name,
        "title": best.get("title", ""),
        "filename": best.get("filename", ""),
        "segment_index": best.get("segment_index", -1),
        "chunk": best.get("chunk", ""),
        "retrieved": retrieved,
        "execution_device": get_ollama_execution_device(),
        "applied_filters": {
            "numero_expediente": numero_expediente,
            "tipo_documento": tipo_documento,
        },
    }

def index_pdf(
    pdf_path: Path,
    document_id: int | None = None,
    numero_expediente: str | None = None,
    tipo_documento: str | None = None,
) -> list[VectorBaseDocument]:
    """
    Esta función indexa un PDF para ello lee el texto, lo trocea en chunks, calcula embeddings y guarda los puntos en Qdrant.
    
    Args:
        pdf_path: Ruta al archivo PDF que se va a indexar.
        document_id: (Opcional) Identificador numérico del documento, que se incluirá en los metadatos de cada chunk. Útil para trazabilidad y auditoría.
        numero_expediente: (Opcional) Número de expediente asociado al documento, que se incluirá en los metadatos de cada chunk. Permite filtrar por expediente en las consultas.
        tipo_documento: (Opcional) Tipo de documento que se incluirá en los metadatos de cada chunk. Permite filtrar por tipo de documento en las consultas.
    
    Returns:    
        Lista de instancias de VectorBaseDocument que representan los chunks indexados del PDF. Cada instancia incluye el contenido del chunk, su embedding y metadatos asociados 
        (nombre de archivo, título, hash, número de expediente, tipo de documento, etc.).
        Si ocurre un error durante el proceso de indexación (lectura del PDF, chunking, generación de embeddings, guardado en Qdrant), 
        se devuelve una lista vacía y se registran los errores correspondientes.
    """
    with timed_block(f"total {pdf_path.name}"):
        logger.info("Procesando %s ...", pdf_path.name)

        # 1) Lectura del PDF
        try:
            with timed_block(f"leer pdf {pdf_path.name}"):
                reader = PdfReader(str(pdf_path))
                info = reader.metadata or {}
                title = info.get("/Title") or pdf_path.stem
                doc_hash = pdf_sha256(pdf_path)
                parts: list[str] = []
                for page in reader.pages:
                    parts.append((page.extract_text() or ""))
                full_text = "\n".join(parts)
        except (PdfReadError, PdfStreamError, Exception) as e:
            logger.error("Error leyendo %s: %s", pdf_path.name, e)
            return []

        if not full_text.strip():
            logger.warning("%s: sin texto extraído.", pdf_path.name)
            return []

        # 2) Chunking
        try:
            with timed_block(f"chunking {pdf_path.name}"):
                chunks = chunk_text(full_text)
        except Exception as e:
            logger.error("Error haciendo chunks en %s: %s", pdf_path.name, e)
            return []

        if not chunks:
            logger.warning("%s: sin chunks válidos", pdf_path.name)
            return []

        # 3) Embeddings
        with timed_block(f"embeddings {pdf_path.name}"):
            vectors = embedding_model(chunks, to_list=True)
            
        # Seguridad si no coinciden longitudes
        if len(vectors) != len(chunks):
            logger.error(
                "%s: nº chunks (%d) != nº embeddings (%d)",
                pdf_path.name, len(chunks), len(vectors)
            )
            return []

        # 4) Guardado en Qdrant
        with timed_block(f"guardar qdrant {pdf_path.name}"):
            docs: list[VectorBaseDocument] = []
            base_meta = {
                "filename": pdf_path.name,
                "title": title,
                "sha256": doc_hash,
                "numero_expediente": numero_expediente,
                "tipo_documento": tipo_documento,
            }
            if document_id is not None:
                base_meta["document_id"] = int(document_id)
                
            for idx, (chunk, vec) in enumerate(zip(chunks, vectors)):
                meta = dict(base_meta)
                meta["segment_index"] = idx
                docs.append(
                    VectorBaseDocument(
                        content=chunk,
                        embedding=vec,
                        metadata=meta,
                    )
                )
            VectorBaseDocument.save_many(docs)
            logger.info("Guardados %d chunks en Qdrant", len(docs))
        return docs


def index_pliegos_dir(pliegos_dir: Path) -> dict:
    """
    Recorre todos los PDFs de un directorio y los indexa de forma incremental.
    Si el PDF no existe en Qdrant lo indexa, si existe y el hash coincide no lo indexa y si existe y el hash no coincide borra sus chunks y lo reindexa
    
    Args:
        pliegos_dir: Ruta al directorio que contiene los archivos PDF a indexar.
        
    Returns:
        Un diccionario con un resumen del proceso de indexación, incluyendo el número total de PDFs procesados, cuántos fueron nuevos, cuántos fueron modificados (reindexados), 
        cuántos fueron omitidos por no tener cambios, cuántos tuvieron errores o no tenían texto, y el número total de chunks guardados en Qdrant.
    """
    if not pliegos_dir.exists():
        logger.error("No se encuentra la carpeta %s", pliegos_dir)
        raise SystemExit(1)

    # Asegura colección antes de empezar
    VectorBaseDocument._ensure_collection()

    summary = {
        "pdfs_total": 0,
        "pdfs_nuevos": 0,
        "pdfs_modificados": 0,
        "pdfs_omitidos": 0,
        "pdfs_error_o_sin_texto": 0,
        "chunks_guardados": 0,
    }

    pdfs = sorted(pliegos_dir.glob("*.pdf"))
    summary["pdfs_total"] = len(pdfs)

    for pdf_path in pdfs:
        filename = pdf_path.name
        doc_hash = pdf_sha256(pdf_path)

        # Si está y coincide hash no lo añade
        if qdrant_has_same_hash(filename, doc_hash):
            summary["pdfs_omitidos"] += 1
            continue

        # Si está pero hash distinto, borrar los chunks antiguos y genera los nuevos
        if qdrant_has_filename(filename):
            logger.info("%s ha cambiado => reindexando", filename)
            qdrant_delete_by_filename(filename)
            summary["pdfs_modificados"] += 1
        else:
            summary["pdfs_nuevos"] += 1

        # Si no esta lo añade
        docs = index_pdf(pdf_path)
        n_chunks = len(docs)
        if n_chunks > 0:
            summary["chunks_guardados"] += n_chunks
        else:
            summary["pdfs_error_o_sin_texto"] += 1

    return summary



if __name__ == "__main__":
    """
    Construye la base de datos vectorial a partir de los PDFs de ./pliegos y sus embeddings.
    """
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    )

    base_dir = Path(__file__).parent
    pliegos_dir = base_dir / "pliegos"

    summary = index_pliegos_dir(pliegos_dir)
    logger.info("Resumen indexado: %s", summary)



