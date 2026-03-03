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
    curl \
 && rm -rf /var/lib/apt/lists/*

# Copiamos primero requirements para aprovechar cache
COPY requirements_docker.txt /app/requirements_docker.txt
RUN pip install --upgrade pip \
 && pip install -r requirements_docker.txt 

# Copiamos el resto del proyecto
COPY . /app

# Puerto Flask/Gunicorn
EXPOSE 5000

RUN chmod +x /app/entrypoint.sh
CMD ["/app/entrypoint.sh"]

