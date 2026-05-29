"""
Evalua el sistema RAG combinando metricas RAGAS y similitud por coseno.

Autor: Lydia Blanco Ruiz
"""

import asyncio
import json
import math
import os
import traceback
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[5]

from datasets import Dataset
from langchain_community.embeddings import HuggingFaceEmbeddings

try:
    from langchain_community.llms import Ollama as OllamaLLM
except Exception:  
    OllamaLLM = None  

try:
    from langchain_community.chat_models import (
        ChatOllama as CommunityChatOllama,
    )
except Exception:  
    CommunityChatOllama = None  

try:
    from langchain_ollama import ChatOllama as OllamaChatOllama
except Exception:  
    OllamaChatOllama = None  
from ragas import evaluate
from ragas.run_config import RunConfig

from app.main.code.services.rag.PrototipoRAG import obtener_mejor_chunk

try:
    import torch
except ImportError:
    torch = None


def load_env_file(path: str | Path) -> None:
    """Carga variables de entorno desde un archivo `.env` simple.

    Args:
        path: Ruta del archivo de configuracion.

    Returns:
        None.
    """
    env_path = Path(path)
    if not env_path.exists():
        return

    for raw_line in env_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        os.environ.setdefault(key, value)


load_env_file(Path(__file__).parent / "config.env")
load_env_file(PROJECT_ROOT / "config.env")


def obtener_mejor_chunk_sync(question: str) -> dict:
    """
    Wrapper síncrono para `obtener_mejor_chunk` (que es async en PrototipoRAG).
    """
    return asyncio.run(obtener_mejor_chunk(question))

OLLAMA_BASE_URL = os.getenv(
    "OLLAMA_BASE_URL",
    os.getenv("ARES_OLLAMA_BASE_URL", "http://127.0.0.1:11435"),
).rstrip("/")
if OLLAMA_BASE_URL and "://" not in OLLAMA_BASE_URL:
    OLLAMA_BASE_URL = f"http://{OLLAMA_BASE_URL}".rstrip("/")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "llama3.1:8b-instruct-q4_K_M")
RAGAS_JUDGE_MODEL = os.getenv("RAGAS_JUDGE_MODEL", "gemma3:4b")
OLLAMA_REQUEST_TIMEOUT = int(os.getenv("OLLAMA_REQUEST_TIMEOUT", "300"))
RAGAS_REQUEST_TIMEOUT = int(os.getenv("RAGAS_REQUEST_TIMEOUT", "1800"))
RAGAS_RAISE_EXCEPTIONS = os.getenv("RAGAS_RAISE_EXCEPTIONS", "1") == "1"
FINAL_RAGAS_WEIGHT = float(os.getenv("FINAL_RAGAS_WEIGHT", "0.7"))
FINAL_FALLBACK_WEIGHT = float(os.getenv("FINAL_FALLBACK_WEIGHT", "0.3"))
RAGAS_QUESTIONS_PATH = Path(
    os.getenv("RAGAS_QUESTIONS_PATH", "questions_auto_ARES.json")
)
RAGAS_RESULTS_PATH = Path(os.getenv("RAGAS_RESULTS_PATH", "ragas_results.json"))
RAGAS_ROW_RESULTS_PATH = Path(
    os.getenv("RAGAS_ROW_RESULTS_PATH", "ragas_results_rows.json")
)
CONFIGURACION_PATH = Path(
    os.getenv("CONFIGURACION_PATH", "configuracion.json")
)
EMBED_MODEL = os.getenv(
    "RAGAS_EMBEDDINGS_MODEL", "sentence-transformers/all-MiniLM-L6-v2"
)
RAGAS_EMBEDDINGS_DEVICE = os.getenv(
    "RAGAS_EMBEDDINGS_DEVICE",
    "cuda" if torch is not None and torch.cuda.is_available() else "cpu",
)
RAGAS_K_CONTEXTS = int(os.getenv("RAGAS_K_CONTEXTS", "3"))
RAGAS_METRICS = [
    metric.strip()
    for metric in os.getenv(
        "RAGAS_METRICS",
        "faithfulness,answer_relevancy,answer_correctness,context_precision,context_recall,context_relevancy",
    ).split(",")
    if metric.strip()
]

RAGAS_USE_CHAT = os.getenv("RAGAS_USE_CHAT", "0") == "1"


def safe_text(value: any) -> str:
    """
    Convierte un valor opcional en texto limpio.

    Normaliza cualquier entrada a una cadena de texto sin espacios al inicio o final.

    Args:
        value: Valor a normalizar. Puede ser None, string o cualquier tipo convertible.

    Returns:
        str: Cadena sin espacios sobrantes.
    """
    return (value or "").strip()


def is_nan(value: float | None) -> bool:
    """
    Indica si un valor numérico es NaN (Not a Number).

    Comprueba de manera segura si un valor es NaN usando math.isnan.

    Args:
        value: Valor numérico a comprobar.

    Returns:
        bool: True si el valor es NaN, False si no es NaN o hay error de conversión.
    """
    try:
        return math.isnan(value)
    except Exception:
        return False


def clamp_score(value: float) -> float:
    """
    Limita una puntuacion al rango cerrado entre 0 y 1.

    Args:
        value: Puntuacion original.

    Returns:
        float: Puntuacion normalizada y redondeada.
    """
    if value < 0.0:
        return 0.0
    if value > 1.0:
        return 1.0
    return round(float(value), 6)


def cosine_similarity(vec_a: list[float], vec_b: list[float]) -> float:
    """
    Calcula la similitud coseno entre dos vectores.

    Args:
        vec_a: Primer vector.
        vec_b: Segundo vector.

    Returns:
        float: Similitud coseno ajustada al rango esperado.
    """
    dot = sum(a * b for a, b in zip(vec_a, vec_b))
    norm_a = math.sqrt(sum(a * a for a in vec_a))
    norm_b = math.sqrt(sum(b * b for b in vec_b))
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return clamp_score(dot / (norm_a * norm_b))


def batch_embeddings(
    embeddings: HuggingFaceEmbeddings, texts: list[str]
) -> list[list[float]]:
    """
    Genera embeddings por lotes a partir de una lista de textos.

    Args:
        embeddings: Modelo de embeddings de LangChain.
        texts: Textos a vectorizar.

    Returns:
        list[list[float]]: Vectores generados para cada texto.
    """
    normalized = [safe_text(text) or " " for text in texts]
    return embeddings.embed_documents(normalized)


def mean(values: list[float]) -> float:
    """
    Calcula la media de una lista ignorando valores nulos.

    Args:
        values: Valores numericos a agregar.

    Returns:
        float: Media aritmetica de los valores validos.
    """
    valid = [v for v in values if v is not None]
    if not valid:
        return 0.0
    return sum(valid) / len(valid)


def resolve_embeddings_device() -> str:
    """
    Selecciona el dispositivo de ejecucion para embeddings.

    Args:
        None.

    Returns:
        str: Nombre del dispositivo finalmente elegido.
    """
    requested = safe_text(RAGAS_EMBEDDINGS_DEVICE).lower() or "auto"
    if requested != "auto":
        if requested.startswith("cuda"):
            if torch is None:
                return "cpu"
            if not torch.cuda.is_available():
                return "cpu"
        return requested

    try:
        if torch.cuda.is_available():
            return "cuda"
        if hasattr(torch.backends, "mps") and torch.backends.mps.is_available():
            return "mps"
    except Exception:
        pass

    return "cpu"


def get_torch_diagnostics() -> dict:
    """
    Recopila informacion diagnostica sobre la instalacion de PyTorch.

    Args:
        None.

    Returns:
        dict: Estado de disponibilidad de torch y CUDA.
    """
    diagnostics = {
        "torch_available": False,
        "torch_version": None,
        "cuda_built_version": None,
        "cuda_available": False,
        "cuda_device_count": 0,
        "cuda_devices": [],
    }

    try:
        import torch

        diagnostics["torch_available"] = True
        diagnostics["torch_version"] = getattr(torch, "__version__", None)
        diagnostics["cuda_built_version"] = getattr(torch.version, "cuda", None)
        diagnostics["cuda_available"] = torch.cuda.is_available()
        diagnostics["cuda_device_count"] = torch.cuda.device_count()
        if diagnostics["cuda_available"]:
            diagnostics["cuda_devices"] = [
                torch.cuda.get_device_name(i)
                for i in range(torch.cuda.device_count())
            ]
    except Exception as exc:
        diagnostics["error"] = str(exc) or type(exc).__name__

    return diagnostics


def metric_names() -> list[str]:
    """
    Devuelve la lista de metricas soportadas por el flujo.

    Args:
        None.

    Returns:
        list[str]: Nombres canonicos de metricas.
    """
    return [
        "faithfulness",
        "answer_relevancy",
        "answer_correctness",
        "context_precision",
        "context_recall",
        "context_relevancy",
    ]


def selected_metric_names() -> list[str]:
    """
    Filtra las metricas configuradas frente al conjunto soportado.

    Args:
        None.

    Returns:
        list[str]: Metricas activas para la ejecucion actual.
    """
    valid = set(metric_names())
    selected = [metric for metric in RAGAS_METRICS if metric in valid]
    return selected or metric_names()


def valid_score(value: float | None) -> float | None:
    """
    Normaliza una puntuación o devuelve None si no es utilizable.

    Valida que el valor sea un número válido (no NaN) y lo ajusta al rango [0, 1].

    Args:
        value: Valor de entrada numérico o None.

    Returns:
        float | None: Puntuación ajustada entre 0.0 y 1.0, o None si inválido.
    """
    if value is None or is_nan(value):
        return None
    return clamp_score(value)


def combine_scores(ragas_value: float | None, fallback_value: float | None) -> float | None:
    """
    Combina una puntuación RAGAS con una puntuación de respaldo.

    Utiliza ponderación configurada a través de FINAL_RAGAS_WEIGHT y FINAL_FALLBACK_WEIGHT
    para mezclar ambas métricas cuando ambas están disponibles.

    Args:
        ragas_value: Valor calculado por RAGAS (0-1) o None.
        fallback_value: Valor calculado por similitud coseno (0-1) o None.

    Returns:
        float | None: Puntuación final combinada ponderada, o el mejor valor disponible.
    """
    ragas_valid = valid_score(ragas_value)
    fallback_valid = valid_score(fallback_value)
    if ragas_valid is not None and fallback_valid is not None:
        total_weight = FINAL_RAGAS_WEIGHT + FINAL_FALLBACK_WEIGHT
        if total_weight <= 0:
            return ragas_valid
        combined = (
            (FINAL_RAGAS_WEIGHT * ragas_valid) + (FINAL_FALLBACK_WEIGHT * fallback_valid)
        ) / total_weight
        return clamp_score(combined)
    if ragas_valid is not None:
        return ragas_valid
    return fallback_valid


def summarize_metric_values(rows: list[dict], key: str) -> dict[str, float | None]:
    """
    Resume metricas fila a fila mediante la media de sus valores validos.

    Args:
        rows: Filas con resultados de evaluacion.
        key: Clave que contiene el bloque de metricas a resumir.

    Returns:
        dict[str, float | None]: Resumen agregado por metrica.
    """
    summary = {}
    for metric_name in selected_metric_names():
        values = [
            row.get(key, {}).get(metric_name)
            for row in rows
            if isinstance(row.get(key), dict)
            and row.get(key, {}).get(metric_name) is not None
            and not is_nan(row.get(key, {}).get(metric_name))
        ]
        summary[metric_name] = None if not values else clamp_score(mean(values))
    return summary


def build_source_counts(rows: list[dict]) -> dict[str, dict[str, int]]:
    """
    Para cada puntuacion final calculada muetra su trazabilidad por cada metrica.

    Args:
        rows: Filas finales con trazabilidad de origen.

    Returns:
        dict[str, dict[str, int]]: Conteo de fuentes por metrica.
    """
    counts = {}
    for metric_name in selected_metric_names():
        counts[metric_name] = {"weighted": 0, "ragas": 0, "coseno": 0, "missing": 0}
        for row in rows:
            source = ((row.get("score_source") or {}).get(metric_name) or "missing").lower()
            if source not in counts[metric_name]:
                source = "missing"
            counts[metric_name][source] += 1
    return counts


def wrap_llm_for_ragas(llm: any) -> any:
    """
    Adapta un LLM de LangChain al wrapper requerido por RAGAS.

    Intenta envolver el modelo usando diferentes wrappers disponibles en la instalación
    de RAGAS y LangChain para garantizar compatibilidad.

    Args:
        llm: Instancia del modelo de lenguaje de LangChain.

    Returns:
        any: Wrapper compatible con RAGAS o el objeto original si no puede envolverse.
    """
    try:
        from ragas.llms import LangchainLLMWrapper

        return LangchainLLMWrapper(llm)
    except Exception:
        pass

    try:
        from ragas.llms import LangchainLLM

        return LangchainLLM(llm)
    except Exception:
        return llm


def wrap_embeddings_for_ragas(embeddings: any) -> any:
    """
    Adapta un modelo de embeddings de LangChain para su uso en RAGAS.

    Intenta envolver el modelo de embeddings usando diferentes wrappers disponibles
    para garantizar compatibilidad con la versión de RAGAS utilizada.

    Args:
        embeddings: Instancia del modelo de embeddings de LangChain.

    Returns:
        any: Wrapper compatible con RAGAS o el objeto original si no puede envolverse.
    """
    try:
        from ragas.embeddings import LangchainEmbeddingsWrapper

        return LangchainEmbeddingsWrapper(embeddings)
    except Exception:
        pass

    try:
        from ragas.embeddings import LangchainEmbeddings

        return LangchainEmbeddings(embeddings)
    except Exception:
        return embeddings


def resolve_ragas_metrics(rows: list[dict]) -> tuple[list, dict[str, str]]:
    """
    Resuelve las metricas RAGAS disponibles segun la instalacion activa.

    Args:
        rows: Filas de evaluacion preparadas para RAGAS.

    Returns:
        tuple[list, dict[str, str]]: Lista de metricas resueltas y mapa de alias.
    """
    import ragas.metrics as ragas_metrics

    resolved = []
    aliases = {}
    selected = set(selected_metric_names())

    def add_metric(output_name: str, *candidate_names: str):
        if output_name not in selected:
            return
        for name in candidate_names:
            metric = getattr(ragas_metrics, name, None)
            if metric is not None:
                resolved.append(metric)
                aliases[output_name] = name
                return

    add_metric("faithfulness", "faithfulness")
    add_metric("answer_relevancy", "answer_relevancy", "answer_relevance")
    add_metric("context_precision", "context_precision", "llm_context_precision_with_reference")
    add_metric("context_recall", "context_recall", "context_recall_with_reference")
    add_metric(
        "context_relevancy",
        "context_relevancy",
        "context_relevance",
        "context_utilization",
    )

    if any(safe_text(row.get("ground_truth")) or safe_text(row.get("reference")) for row in rows):
        add_metric("answer_correctness", "answer_correctness")

    return resolved, aliases


def load_questions(path: str | Path) -> list[dict]:
    """
    Carga preguntas desde JSON y normaliza su estructura.

    Args:
        path: Ruta del archivo JSON de entrada.

    Returns:
        list[dict]: Preguntas normalizadas para el pipeline.
    """
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    out = []
    for item in data:
        if isinstance(item, str):
            out.append({"question": item})
        else:
            out.append(item)
    return out


def build_ragas_rows(questions: list[dict], k_contexts: int = 3) -> list[dict]:
    """
    Construye las filas de entrada necesarias para evaluar con RAGAS.

    Args:
        questions: Preguntas y referencias de evaluacion.
        k_contexts: Número maximo de contextos recuperados por pregunta.

    Returns:
        list[dict]: Filas listas para convertirse en Dataset.
    """
    rows = []
    for item in questions:
        question = safe_text(item.get("question"))
        if not question:
            continue

        rag_out = obtener_mejor_chunk_sync(question)
        answer = safe_text(rag_out.get("answer"))
        retrieved = rag_out.get("retrieved") or []
        contexts = []
        for retrieved_item in retrieved[:k_contexts]:
            chunk = safe_text(retrieved_item.get("chunk"))
            if chunk:
                contexts.append(chunk)

        ground_truth = safe_text(item.get("ground_truth"))
        evidence = safe_text(item.get("evidence"))
        reference = ground_truth or evidence

        rows.append(
            {
                "question": question,
                "user_input": question,
                "answer": answer,
                "response": answer,
                "contexts": contexts,
                "retrieved_contexts": contexts,
                "ground_truth": ground_truth,
                "reference": reference,
                "reference_contexts": [evidence] if evidence else [],
                "evidence": evidence,
            }
        )

    return rows


def compute_coseno_metrics(
    rows: list[dict], embeddings: HuggingFaceEmbeddings
) -> list[dict]:
    """
    Calcula metricas de respaldo basadas en similitud coseno.

    Args:
        rows: Filas base del proceso de evaluacion.
        embeddings: Modelo de embeddings para vectorizar textos.

    Returns:
        list[dict]: Filas enriquecidas con metricas de coseno.
    """
    for row in rows:
        question = safe_text(row.get("question"))
        answer = safe_text(row.get("answer"))
        ground_truth = safe_text(row.get("ground_truth"))
        evidence = safe_text(row.get("evidence"))
        contexts = [safe_text(ctx) for ctx in (row.get("contexts") or []) if safe_text(ctx)]
        reference = ground_truth or evidence or question
        joined_context = "\n\n".join(contexts)

        texts = [question, answer, ground_truth or question, evidence or reference]
        texts.extend(contexts if contexts else [""])
        vectors = batch_embeddings(embeddings, texts)

        question_vec = vectors[0]
        answer_vec = vectors[1]
        ground_truth_vec = vectors[2]
        evidence_vec = vectors[3]
        context_vecs = vectors[4:]

        answer_relevancy = cosine_similarity(question_vec, answer_vec)
        answer_correctness = (
            cosine_similarity(answer_vec, ground_truth_vec) if ground_truth else None
        )
        context_question_scores = [
            cosine_similarity(question_vec, ctx_vec) for ctx_vec in context_vecs
        ]
        context_reference_scores = [
            max(
                cosine_similarity(ground_truth_vec, ctx_vec) if ground_truth else 0.0,
                cosine_similarity(evidence_vec, ctx_vec) if evidence else 0.0,
                cosine_similarity(question_vec, ctx_vec),
            )
            for ctx_vec in context_vecs
        ]
        faithfulness = (
            max(cosine_similarity(answer_vec, ctx_vec) for ctx_vec in context_vecs)
            if context_vecs
            else 0.0
        )

        if joined_context:
            joined_context_vec = batch_embeddings(embeddings, [joined_context])[0]
            context_recall = cosine_similarity(joined_context_vec, ground_truth_vec)
            if not ground_truth:
                context_recall = cosine_similarity(joined_context_vec, evidence_vec)
        else:
            context_recall = 0.0

        row["_coseno_metrics"] = {
            "faithfulness": faithfulness,
            "answer_relevancy": answer_relevancy,
            "answer_correctness": answer_correctness,
            "context_precision": mean(context_reference_scores),
            "context_recall": context_recall,
            "context_relevancy": mean(context_question_scores),
        }

    return rows


def run_ragas(
    rows: list[dict],
    embeddings: HuggingFaceEmbeddings,
    llm: Any,
) -> tuple[dict, list[dict], dict]:
    """
    Ejecuta la evaluación RAGAS y recopila diagnósticos del proceso.

    Realiza evaluación de preguntas-respuestas usando múltiples métricas RAGAS.
    Si ocurre timeout, reintenta sin la métrica answer_correctness.

    Args:
        rows: Filas de evaluación listas para RAGAS con campos normalizados.
        embeddings: Modelo de embeddings compatible con LangChain.
        llm: Modelo juez usado por RAGAS para evaluación.

    Returns:
        tuple[dict, list[dict], dict]: Tupla con resumen de métricas agregadas,
            filas detalladas normalizadas con resultados, y diagnosticos técnicos.

    Raises:
        TimeoutError: Si todas las métricas fallan por timeout.
    """
    metrics, aliases = resolve_ragas_metrics(rows)
    if not metrics:
        return {}, [], {
            "resolved_metrics": [],
            "aliases": aliases,
            "dataframe_columns": [],
            "non_null_counts": {},
            "issues": ["No se resolvió ninguna métrica RAGAS con la versión instalada."],
        }

    dataset = Dataset.from_list(rows)
    run_config = RunConfig(
        timeout=RAGAS_REQUEST_TIMEOUT,
        max_workers=1,
        max_retries=2,
    )

    ragas_llm = wrap_llm_for_ragas(llm)
    ragas_embeddings = wrap_embeddings_for_ragas(embeddings)
    diagnostics = {
        "resolved_metrics": [aliases[key] for key in aliases],
        "aliases": aliases,
        "dataframe_columns": [],
        "non_null_counts": {},
        "issues": [],
        "judge_model": RAGAS_JUDGE_MODEL,
        "raise_exceptions": RAGAS_RAISE_EXCEPTIONS,
        "timeout_seconds": RAGAS_REQUEST_TIMEOUT,
    }

    active_metrics = metrics
    active_aliases = dict(aliases)
    try:
        result = evaluate(
            dataset,
            metrics=active_metrics,
            llm=ragas_llm,
            embeddings=ragas_embeddings,
            run_config=run_config,
            raise_exceptions=RAGAS_RAISE_EXCEPTIONS,
        )
    except TimeoutError:
        reduced = [
            metric
            for metric in metrics
            if active_aliases.get("answer_correctness") != getattr(metric, "name", None)
            and getattr(metric, "name", None) != active_aliases.get("answer_correctness")
        ]
        if len(reduced) == len(metrics):
            raise
        diagnostics["issues"].append(
            "Timeout en RAGAS con todas las metricas. Reintentando sin answer_correctness."
        )
        active_metrics = reduced
        active_aliases.pop("answer_correctness", None)
        result = evaluate(
            dataset,
            metrics=active_metrics,
            llm=ragas_llm,
            embeddings=ragas_embeddings,
            run_config=run_config,
            raise_exceptions=RAGAS_RAISE_EXCEPTIONS,
        )

    df = result.to_pandas()
    raw_row_records = df.to_dict(orient="records")
    row_records = []
    summary = {}

    for output_name, source_name in active_aliases.items():
        if source_name in df.columns:
            series = df[source_name]
            summary[output_name] = (
                None if series.dropna().empty else round(float(series.dropna().mean()), 6)
            )

    for record in raw_row_records:
        normalized = dict(record)
        for output_name, source_name in active_aliases.items():
            if source_name in record:
                normalized[output_name] = record[source_name]
        row_records.append(normalized)

    diagnostics["resolved_metrics"] = [active_aliases[key] for key in active_aliases]
    diagnostics["aliases"] = active_aliases
    diagnostics["dataframe_columns"] = list(df.columns)
    for output_name, source_name in active_aliases.items():
        if source_name not in df.columns:
            diagnostics["non_null_counts"][output_name] = 0
            diagnostics["issues"].append(
                f"La columna '{source_name}' no aparecio en la salida de RAGAS."
            )
            continue
        non_null = int(df[source_name].notna().sum())
        diagnostics["non_null_counts"][output_name] = non_null
        if non_null == 0:
            diagnostics["issues"].append(
                f"La columna '{source_name}' existe pero todos sus valores son nulos/NaN."
            )

    if active_aliases and all(
        diagnostics["non_null_counts"].get(name, 0) == 0 for name in active_aliases
    ):
        diagnostics["issues"].append(
            "RAGAS no produjo ningun valor util. La causa mas probable es incompatibilidad "
            "entre la version de RAGAS y los wrappers LangChain/Ollama, timeout del modelo juez "
            "o fallos de parsing del modelo."
        )

    return summary, row_records, diagnostics


def merge_metrics(
    rows: list[dict], ragas_rows: list[dict], ragas_summary: dict
) -> tuple[dict, list[dict]]:
    """
    Fusiona métricas RAGAS con métricas de coseno en una salida final.

    Combina resultados de ambas metodologías de evaluación (RAGAS y similitud coseno)
    usando pesos configurados, e incluye trazabilidad del origen de cada puntuación.

    Args:
        rows: Filas base con métricas de coseno calculadas.
        ragas_rows: Filas devueltas por RAGAS con métricas calculadas.
        ragas_summary: Resumen agregado de métricas RAGAS.

    Returns:
        tuple[dict, list[dict]]: Resumen final por métrica, y detalle por pregunta
            con trazabilidad de origen (weighted, ragas, coseno) para cada puntuación.
    """
    final_rows = []
    ragas_rows_by_question = {
        safe_text(item.get("question") or item.get("user_input")): item
        for item in (ragas_rows or [])
    }

    for row in rows:
        out = {
            "question": row["question"],
            "contexts": row["contexts"],
            "answer": row["answer"],
            "ground_truth": row.get("ground_truth", ""),
            "evidence": row.get("evidence", ""),
        }

        ragas_row = ragas_rows_by_question.get(row["question"], {})
        coseno = row.get("_coseno_metrics", {})
        out["ragas_metrics"] = {}
        out["coseno_metrics"] = {}
        out["final_metrics"] = {}
        for metric_name in selected_metric_names():
            ragas_value = valid_score(ragas_row.get(metric_name))
            fallback_value = valid_score(coseno.get(metric_name))
            final_value = combine_scores(ragas_value, fallback_value)
            out["ragas_metrics"][metric_name] = ragas_value
            out["coseno_metrics"][metric_name] = fallback_value
            out["final_metrics"][metric_name] = final_value

        out["score_source"] = {
            metric_name: (
                "weighted"
                if out["ragas_metrics"].get(metric_name) is not None
                and out["coseno_metrics"].get(metric_name) is not None
                else (
                    "ragas"
                    if out["ragas_metrics"].get(metric_name) is not None
                    else "coseno"
                )
            )
            for metric_name in selected_metric_names()
        }
        final_rows.append(out)

    final_summary = {}
    for metric_name in selected_metric_names():
        values = [
            row.get("final_metrics", {}).get(metric_name)
            for row in final_rows
            if row.get("final_metrics", {}).get(metric_name) is not None
            and not is_nan(row.get("final_metrics", {}).get(metric_name))
        ]
        final_summary[metric_name] = None if not values else clamp_score(mean(values))

    return final_summary, final_rows


def main():
    """
    Orquesta la evaluación completa del sistema RAG.

    Carga preguntas de prueba, ejecuta el pipeline RAG, calcula métricas RAGAS y de coseno,
    y persiste todos los resultados y diagnósticos en archivos JSON.

    Args:
        None.

    Returns:
        None.

    Raises:
        SystemExit: Si no se pueden construir filas para la evaluación.
    """
    questions = load_questions(RAGAS_QUESTIONS_PATH)
    rows = build_ragas_rows(questions, k_contexts=RAGAS_K_CONTEXTS)
    if not rows:
        raise SystemExit(
            f"No se pudieron construir filas para la evaluacion a partir de {RAGAS_QUESTIONS_PATH}."
        )

    embeddings_device = resolve_embeddings_device()
    embeddings = HuggingFaceEmbeddings(
        model_name=EMBED_MODEL,
        model_kwargs={"device": embeddings_device},
    )
    rows = compute_coseno_metrics(rows, embeddings)
    llm = None
    if RAGAS_USE_CHAT:
        chat_cls = CommunityChatOllama or OllamaChatOllama
        if chat_cls is None:
            raise RuntimeError(
                "No hay implementación ChatOllama disponible (langchain-community/langchain-ollama)."
            )
        try:
            llm = chat_cls(
                model=RAGAS_JUDGE_MODEL,
                base_url=OLLAMA_BASE_URL,
                client_kwargs={"timeout": RAGAS_REQUEST_TIMEOUT},
            )
        except TypeError:
            llm = chat_cls(model=RAGAS_JUDGE_MODEL, base_url=OLLAMA_BASE_URL)
    else:
        if OllamaLLM is None:
            raise RuntimeError("No se pudo importar langchain_community.llms.Ollama.")
        # Usa /api/generate (más compatible que /api/chat en instalaciones antiguas).
        try:
            llm = OllamaLLM(model=RAGAS_JUDGE_MODEL, base_url=OLLAMA_BASE_URL)
        except TypeError:
            llm = OllamaLLM(model=RAGAS_JUDGE_MODEL, base_url=OLLAMA_BASE_URL)

    ragas_diagnostics = {}
    try:
        ragas_summary, ragas_rows, ragas_diagnostics = run_ragas(rows, embeddings, llm)
    except Exception as exc:
        error_message = str(exc) or type(exc).__name__
        ragas_summary = {"ragas_error": error_message}
        ragas_rows = []
        ragas_diagnostics = {
            "resolved_metrics": [],
            "aliases": {},
            "dataframe_columns": [],
            "non_null_counts": {},
            "judge_model": RAGAS_JUDGE_MODEL,
            "raise_exceptions": RAGAS_RAISE_EXCEPTIONS,
            "timeout_seconds": RAGAS_REQUEST_TIMEOUT,
            "issues": [f"Excepcion al ejecutar RAGAS: {error_message}"],
            "exception_type": type(exc).__name__,
            "exception_message": error_message,
            "traceback": traceback.format_exc(),
        }
        print("RAGAS evaluation failed with an exception:")
        print(ragas_diagnostics["traceback"])

    final_summary, row_records = merge_metrics(rows, ragas_rows, ragas_summary)
    coseno_summary = summarize_metric_values(row_records, "coseno_metrics")
    ragas_only_summary = summarize_metric_values(row_records, "ragas_metrics")
    source_counts = build_source_counts(row_records)

    summary = {
        "final_metrics": final_summary,
        "ragas_metrics": ragas_only_summary,
        "coseno_metrics": coseno_summary,
        "score_source_counts": source_counts,
    }
    configuracion = {
        "ragas_diagnostics": ragas_diagnostics,
        "generation_model": OLLAMA_MODEL,
        "ragas_judge_model": RAGAS_JUDGE_MODEL,
        "ragas_embeddings_model": EMBED_MODEL,
        "ragas_embeddings_device": embeddings_device,
        "torch_diagnostics": get_torch_diagnostics(),
        "configured_metrics": selected_metric_names(),
        "ragas_k_contexts": RAGAS_K_CONTEXTS,
        "final_metric_weights": {
            "ragas": FINAL_RAGAS_WEIGHT,
            "coseno": FINAL_FALLBACK_WEIGHT,
        },
    }
    if "ragas_error" in ragas_summary:
        configuracion["ragas_error"] = ragas_summary["ragas_error"]

    print(json.dumps(summary, ensure_ascii=False, indent=2))

    with open(RAGAS_RESULTS_PATH, "w", encoding="utf-8") as fh:
        json.dump(summary, fh, ensure_ascii=False, indent=2, default=str)

    with open(RAGAS_ROW_RESULTS_PATH, "w", encoding="utf-8") as fh:
        json.dump(row_records, fh, ensure_ascii=False, indent=2, default=str)

    with open(CONFIGURACION_PATH, "w", encoding="utf-8") as fh:
        json.dump(configuracion, fh, ensure_ascii=False, indent=2, default=str)


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        # Si el script falla antes de persistir artefactos, al menos generamos
        # ficheros de salida para que el pipeline no deje el directorio a medias.
        error_message = str(exc) or type(exc).__name__
        payload = {
            "final_metrics": {},
            "ragas_metrics": {},
            "coseno_metrics": {},
            "score_source_counts": {},
            "ragas_error": error_message,
        }
        try:
            RAGAS_RESULTS_PATH.parent.mkdir(parents=True, exist_ok=True)
            RAGAS_ROW_RESULTS_PATH.parent.mkdir(parents=True, exist_ok=True)
            CONFIGURACION_PATH.parent.mkdir(parents=True, exist_ok=True)
            with open(RAGAS_RESULTS_PATH, "w", encoding="utf-8") as fh:
                json.dump(payload, fh, ensure_ascii=False, indent=2, default=str)
            with open(RAGAS_ROW_RESULTS_PATH, "w", encoding="utf-8") as fh:
                json.dump([], fh, ensure_ascii=False, indent=2, default=str)
            with open(CONFIGURACION_PATH, "w", encoding="utf-8") as fh:
                json.dump(
                    {
                        "ragas_error": error_message,
                        "exception_type": type(exc).__name__,
                        "exception_message": error_message,
                        "traceback": traceback.format_exc(),
                    },
                    fh,
                    ensure_ascii=False,
                    indent=2,
                    default=str,
                )
        finally:
            raise
