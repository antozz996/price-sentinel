# ─────────────────────────────────────
# PRICE SENTINEL — Backend Dockerfile
# Python 3.11-slim + Uvicorn
# ─────────────────────────────────────
FROM python:3.11-slim AS base

# Previeni .pyc e buffering
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app

WORKDIR /app

# Installa dipendenze di sistema per asyncpg
RUN apt-get update && \
    apt-get install -y --no-install-recommends gcc libpq-dev && \
    rm -rf /var/lib/apt/lists/*

# Installa dipendenze Python
COPY requirements.txt .
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt

# Copia codice applicazione
COPY . .

# Porta Uvicorn
EXPOSE 8000

# Avvio con hot-reload (override in produzione)
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--reload"]
