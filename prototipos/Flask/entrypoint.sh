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

echo "Running migrations..."
flask db upgrade

echo "Starting server..."
exec gunicorn -b 0.0.0.0:5000 run:app
