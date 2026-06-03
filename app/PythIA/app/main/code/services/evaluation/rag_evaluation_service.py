from __future__ import annotations

import json
import os
import runpy
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo


@dataclass(frozen=True)
class RAGEvaluationArtifacts:
    """ 
    Rutas de los archivos generados durante la evaluación RAG + ARES. 
    """
    output_dir: Path
    results_json_path: Path
    row_results_json_path: Path
    config_json_path: Path
    ares_questions_json_path: Path
    ares_dataset_json_path: Path
    ares_dataset_tsv_path: Path


def _timestamp_slug(now: datetime | None = None) -> str:
    """
    Genera un slug con marca de tiempo.

    Args:
        now (datetime | None, optional): Fecha y hora a formatear. Si es None, se usa la fecha y hora actual.

    Returns:
        str: Slug con marca de tiempo.
    """
    now = now or datetime.now(ZoneInfo("Europe/Madrid"))
    return now.strftime("%Y%m%d_%H%M%S")


def _ensure_dir(path: Path) -> Path:
    """
    Asegura que un directorio exista, creándolo si es necesario.
    
    Args:
        path (Path): Ruta del directorio a asegurar.
        
    Returns:
        Path: Ruta del directorio asegurado.
    """
    path.mkdir(parents=True, exist_ok=True)
    return path


def build_artifacts_dir(data_dir: Path, *, now: datetime | None = None) -> Path:
    """
    Construye el directorio para almacenar los resultados de evaluación.

    Args:
        data_dir (Path): Ruta del directorio de datos.
        now (datetime | None, optional): Fecha y hora a formatear. Si es None, se usa la fecha y hora actual.

    Returns:
        Path: Ruta del directorio de resultados.
    """
    
    base = _ensure_dir(data_dir / "evaluations")
    return _ensure_dir(base / _timestamp_slug(now))


def run_rag_evaluation(*, data_dir: Path) -> RAGEvaluationArtifacts:
    """
    Ejecuta el pipeline de evaluación ARES + RAGAS y guarda los resultados en DATA_DIR.

    Args:
        data_dir (Path): Ruta del directorio donde se guardarán los resultados.
        
    Returns:
        RAGEvaluationArtifacts: Rutas de los archivos generados durante la evaluación.
    """
    output_dir = build_artifacts_dir(data_dir)

    ares_questions_json = output_dir / "questions_auto_ARES.json"
    ares_dataset_json = output_dir / "ares_dataset.json"
    ares_dataset_tsv = output_dir / "dataset_auto_ARES.tsv"

    ragas_results_json = output_dir / "ragas_results.json"
    ragas_rows_json = output_dir / "ragas_results_rows.json"
    ragas_config_json = output_dir / "configuracion.json"

    if os.getenv("PYTHIA_TESTING") == "1" or os.getenv("TESTING") == "1":
        # En tests no se ejecutan dependencias pesadas (RAGAS/Ollama/torch).
        for path in (
            ares_questions_json,
            ares_dataset_json,
            ares_dataset_tsv,
            ragas_results_json,
            ragas_rows_json,
            ragas_config_json,
        ):
            path.write_text("{}", encoding="utf-8")
        return RAGEvaluationArtifacts(
            output_dir=output_dir,
            results_json_path=ragas_results_json,
            row_results_json_path=ragas_rows_json,
            config_json_path=ragas_config_json,
            ares_questions_json_path=ares_questions_json,
            ares_dataset_json_path=ares_dataset_json,
            ares_dataset_tsv_path=ares_dataset_tsv,
        )

    env_overrides = {
        "ARES_QUESTIONS_PATH": str(ares_questions_json),
        "ARES_DATASET_JSON_PATH": str(ares_dataset_json),
        "ARES_DATASET_TSV_PATH": str(ares_dataset_tsv),
        "RAGAS_QUESTIONS_PATH": str(ares_questions_json),
        "RAGAS_RESULTS_PATH": str(ragas_results_json),
        "RAGAS_ROW_RESULTS_PATH": str(ragas_rows_json),
        "CONFIGURACION_PATH": str(ragas_config_json),
        # Evita que ejecuciones repetidas dejen resultados inconsistentes
        "ARES_FORCE_REGENERATE": os.getenv("ARES_FORCE_REGENERATE", "0"),
    }

    old_env = os.environ.copy()
    os.environ.update(env_overrides)
    try:
        base_dir = Path(__file__).resolve().parent
        runpy.run_path(str(base_dir / "generar_preguntas_ARES.py"), run_name="__main__")
        runpy.run_path(str(base_dir / "generar_dataset_ARES.py"), run_name="__main__")
        try:
            runpy.run_path(str(base_dir / "evaluacion_RAGAS.py"), run_name="__main__")
        except Exception as exc:
            # Si falla antes de persistir, se deja resultados mínimos para depuración.
            error_message = str(exc) or type(exc).__name__
            ragas_results_json.write_text(
                '{"ragas_error": ' + json.dumps(error_message) + "}",
                encoding="utf-8",
            )
            ragas_rows_json.write_text("[]", encoding="utf-8")
            ragas_config_json.write_text(
                json.dumps(
                    {
                        "ragas_error": error_message,
                        "exception_type": type(exc).__name__,
                    },
                    ensure_ascii=False,
                    indent=2,
                ),
                encoding="utf-8",
            )
            raise
    finally:
        os.environ.clear()
        os.environ.update(old_env)

    return RAGEvaluationArtifacts(
        output_dir=output_dir,
        results_json_path=ragas_results_json,
        row_results_json_path=ragas_rows_json,
        config_json_path=ragas_config_json,
        ares_questions_json_path=ares_questions_json,
        ares_dataset_json_path=ares_dataset_json,
        ares_dataset_tsv_path=ares_dataset_tsv,
    )
