# syntax=docker/dockerfile:1.7
FROM mcr.microsoft.com/playwright/python:v1.57.0-jammy

# Evita pyc y habilita logs directos
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

WORKDIR /app

# Dependencias del sistema:
# - build-essential/gcc para paquetes que compilan
# - libpq-dev para psycopg2
# - curl para healthchecks/debug
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential gcc \
    libpq-dev \
    python3-dev \
    poppler-utils \
    curl \
 && rm -rf /var/lib/apt/lists/*

RUN useradd --create-home --shell /usr/sbin/nologin appuser

# Copiamos primero requirements para aprovechar cache
COPY docker/requirements_docker.txt /app/requirements_docker.txt
RUN pip install --upgrade pip \
 && pip install -r requirements_docker.txt 

RUN --mount=type=bind,source=app/main,target=/tmp/build/app/main \
    --mount=type=bind,source=migrations,target=/tmp/build/migrations \
    --mount=type=bind,source=docker/entrypoint.sh,target=/tmp/build/docker/entrypoint.sh \
    mkdir -p /app/app /app/docker \
 && cp -a /tmp/build/app/main /app/app/main \
 && cp -a /tmp/build/migrations /app/migrations \
 && cp /tmp/build/docker/entrypoint.sh /app/docker/entrypoint.sh \
 && chmod +x /app/docker/entrypoint.sh \
 && mkdir -p /data /home/appuser/.cache/huggingface \
 && chown -R appuser:appuser /app /data /home/appuser/.cache

# Puerto Flask/Gunicorn
EXPOSE 5000

USER appuser

CMD ["/app/docker/entrypoint.sh"]

