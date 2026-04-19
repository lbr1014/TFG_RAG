#!/bin/sh
set -e

echo "Waiting for Postgres..."
if [ -z "${DATABASE_URL:-}" ]; then
  export DATABASE_URL="postgresql+psycopg2://${POSTGRES_USER}:${POSTGRES_PASSWORD}@${POSTGRES_HOST:-db}:${POSTGRES_PORT:-5432}/${POSTGRES_DB}"
fi
python - <<'PY'
import os, time, psycopg2
from sqlalchemy.engine import make_url
url = make_url(os.environ["DATABASE_URL"])
for i in range(60):
    try:
        conn = psycopg2.connect(
            dbname=url.database,
            user=url.username,
            password=url.password,
            host=url.host,
            port=url.port or 5432,
        )
        conn.close()
        print("Postgres OK")
        break
    except Exception as e:
        print(f"Postgres not ready ({i+1}/60): {e}")
        time.sleep(2)
else:
    raise SystemExit("Postgres did not become ready in time")
PY

echo "Waiting for Qdrant..."
QDRANT_URL_DEFAULT="${QDRANT_URL:-${QDRANT_SERVICE_HOST:-qdrant}:${QDRANT_INTERNAL_PORT:-6333}}"
case "$QDRANT_URL_DEFAULT" in
    *://*) ;;
    *) QDRANT_URL_DEFAULT="${QDRANT_URL_SCHEME:-http}://${QDRANT_URL_DEFAULT}" ;;
esac
for i in $(seq 1 60); do
    if curl -fsS "${QDRANT_URL_DEFAULT%/}/readyz" >/dev/null 2>&1; then
        echo "Qdrant OK"
        break
    fi
    echo "Qdrant not ready (${i}/60)"
    sleep 2
done

echo "Preparing Ollama models..."
python - <<'PY'
import json
import os
import socket
import sys
import time
import urllib.error
import urllib.request


def service_url_from_env(value: str, scheme: str = "http") -> str:
    value = (value or "").strip().rstrip("/")
    if "://" not in value:
        value = f"{scheme}://{value}"
    return value


ollama_base_url = service_url_from_env(
    os.environ.get(
        "OLLAMA_BASE_URL",
        f"{os.environ.get('OLLAMA_SERVICE_HOST', 'ollama')}:{os.environ.get('OLLAMA_INTERNAL_PORT', '11434')}",
    ),
    os.environ.get("OLLAMA_BASE_URL_SCHEME", "http"),
)

rag_models = [
    item.strip()
    for item in os.environ.get("RAG_LLM_MODELS", "").split(",")
    if item.strip()
]
default_model = os.environ.get("RAG_LLM_MODEL", "").strip()
if default_model and default_model not in rag_models:
    rag_models.insert(0, default_model)

ocr_model = os.environ.get("OCR_MODEL_NAME", "").strip()
models = list(dict.fromkeys([*rag_models, *([ocr_model] if ocr_model else [])]))
pull_timeout_seconds = float(os.environ.get("OLLAMA_PULL_TIMEOUT_SECONDS", "1800"))
pull_idle_timeout_seconds = float(os.environ.get("OLLAMA_PULL_IDLE_TIMEOUT_SECONDS", "300"))
pull_log_interval_seconds = float(os.environ.get("OLLAMA_PULL_LOG_INTERVAL_SECONDS", "20"))

if not models:
    print("No Ollama models configured.")
    raise SystemExit(0)


def post_json(path: str, payload: dict, timeout=None):
    data = json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(
        f"{ollama_base_url}{path}",
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    return urllib.request.urlopen(request, timeout=timeout)


def format_bytes(value):
    if not isinstance(value, (int, float)) or value < 0:
        return "-"
    units = ("B", "KB", "MB", "GB", "TB")
    amount = float(value)
    for unit in units:
        if amount < 1024 or unit == units[-1]:
            break
        amount /= 1024
    if unit == "B":
        return f"{int(amount)} {unit}"
    return f"{amount:.1f} {unit}"


def format_pull_progress(model: str, payload: dict) -> str:
    status = payload.get("status") or "pulling"
    digest = (payload.get("digest") or "").strip()
    completed = payload.get("completed")
    total = payload.get("total")
    progress = ""
    if isinstance(completed, (int, float)) and isinstance(total, (int, float)) and total > 0:
        percent = min(100.0, max(0.0, completed * 100.0 / total))
        progress = f" {percent:.1f}% ({format_bytes(completed)} / {format_bytes(total)})"
    elif isinstance(completed, (int, float)):
        progress = f" ({format_bytes(completed)})"
    digest_suffix = f" {digest[:12]}" if digest else ""
    return f"{model}: {status}{digest_suffix}{progress}".strip()


for attempt in range(60):
    try:
        urllib.request.urlopen(f"{ollama_base_url}/api/tags", timeout=5).close()
        print("Ollama OK")
        break
    except Exception as exc:
        print(f"Ollama not ready ({attempt + 1}/60): {exc}")
        time.sleep(2)
else:
    raise SystemExit("Ollama did not become ready in time")

for model in models:
    try:
        post_json("/api/show", {"model": model}).close()
        print(f"Ollama model already available: {model}")
        continue
    except urllib.error.HTTPError as exc:
        if exc.code != 404:
            detail = exc.read().decode("utf-8", errors="replace")
            print(f"WARNING: Error checking Ollama model {model}: HTTP {exc.code} {detail}")
            continue

    print(f"Downloading Ollama model: {model}")
    try:
        request_timeout = pull_idle_timeout_seconds if pull_idle_timeout_seconds > 0 else None
        with post_json("/api/pull", {"model": model, "stream": True}, timeout=request_timeout) as response:
            started_at = time.monotonic()
            last_progress = ""
            last_log_at = 0.0
            last_line_at = started_at
            while True:
                now = time.monotonic()
                elapsed = now - started_at
                idle_elapsed = now - last_line_at
                if pull_timeout_seconds > 0 and elapsed >= pull_timeout_seconds:
                    print(f"WARNING: Timeout downloading Ollama model {model} after {pull_timeout_seconds:g} seconds")
                    break
                if pull_idle_timeout_seconds > 0 and idle_elapsed >= pull_idle_timeout_seconds:
                    print(f"WARNING: Download of Ollama model {model} did not advance for {pull_idle_timeout_seconds:g} seconds")
                    break

                try:
                    raw_line = response.readline()
                except socket.timeout:
                    print(f"WARNING: Download of Ollama model {model} did not advance for {pull_idle_timeout_seconds:g} seconds")
                    break
                if not raw_line:
                    break
                last_line_at = time.monotonic()
                line = raw_line.decode("utf-8", errors="replace").strip()
                if not line:
                    continue
                try:
                    payload = json.loads(line)
                except json.JSONDecodeError:
                    print(line)
                    continue
                if payload.get("error"):
                    print(f"WARNING: Error downloading Ollama model {model}: {payload['error']}")
                    break
                status = payload.get("status")
                if status:
                    progress = format_pull_progress(model, payload)
                    now = time.monotonic()
                    is_done = bool(payload.get("done")) or status == "success"
                    if progress != last_progress and (now - last_log_at >= pull_log_interval_seconds or is_done):
                        print(progress)
                        last_progress = progress
                        last_log_at = now
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        print(f"WARNING: Error downloading Ollama model {model}: HTTP {exc.code} {detail}")
        continue

print("Ollama models ready.")
PY

echo "Running migrations..."
flask db upgrade

echo "Starting server..."
exec gunicorn -b "0.0.0.0:${WEB_INTERNAL_PORT:-5000}" -w 2 -k gthread --threads 4 --timeout 120 "run:app"
