#!/usr/bin/env bash
# ==============================================================================
# Price Sentinel — Script di Deployment Multi-Istanza per Nuovi Clienti
# ==============================================================================
# Utilizzo:
#   ./scripts/deploy_client.sh <nome_cliente> <porta_frontend> <porta_backend> <porta_db>
#
# Esempio:
#   ./scripts/deploy_client.sh cliente_alberghi 8081 8001 5433
# ==============================================================================

set -euo pipefail

CLIENT_NAME="${1:-}"
FRONTEND_PORT="${2:-}"
BACKEND_PORT="${3:-}"
DB_PORT="${4:-}"

if [[ -z "$CLIENT_NAME" || -z "$FRONTEND_PORT" || -z "$BACKEND_PORT" || -z "$DB_PORT" ]]; then
    echo "❌ Errore: parametri mancanti."
    echo "Uso: ./scripts/deploy_client.sh <nome_cliente_slug> <porta_frontend> <porta_backend> <porta_db>"
    echo "Esempio: ./scripts/deploy_client.sh playa_group 8081 8001 5433"
    exit 1
fi

BASE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
CLIENT_DIR="${BASE_DIR}/../instances/${CLIENT_NAME}"

echo "=================================================="
echo "🚀 Avvio provisioning nuova istanza per: ${CLIENT_NAME}"
echo "📁 Cartella installazione: ${CLIENT_DIR}"
echo "🌐 Porte assegnate: Web=${FRONTEND_PORT}, API=${BACKEND_PORT}, DB=${DB_PORT}"
echo "=================================================="

mkdir -p "${CLIENT_DIR}"
cp -r "${BASE_DIR}/backend" "${CLIENT_DIR}/backend"
cp -r "${BASE_DIR}/frontend" "${CLIENT_DIR}/frontend"

# Genera docker-compose dedicato
cat <<EOF > "${CLIENT_DIR}/docker-compose.yml"
version: '3.8'

services:
  db_${CLIENT_NAME}:
    image: postgres:15-alpine
    container_name: ps_db_${CLIENT_NAME}
    environment:
      POSTGRES_USER: sentinel_${CLIENT_NAME}
      POSTGRES_PASSWORD: secret_${CLIENT_NAME}_pwd
      POSTGRES_DB: sentinel_db_${CLIENT_NAME}
    volumes:
      - pgdata_${CLIENT_NAME}:/var/lib/postgresql/data
    ports:
      - "${DB_PORT}:5432"
    restart: unless-stopped

  backend_${CLIENT_NAME}:
    build:
      context: ./backend
      dockerfile: Dockerfile
    container_name: ps_backend_${CLIENT_NAME}
    environment:
      DATABASE_URL: postgresql+asyncpg://sentinel_${CLIENT_NAME}:secret_${CLIENT_NAME}_pwd@db_${CLIENT_NAME}:5432/sentinel_db_${CLIENT_NAME}
      SECRET_KEY: $(openssl rand -hex 32)
      ALGORITHM: HS256
      ACCESS_TOKEN_EXPIRE_MINUTES: 10080
    ports:
      - "${BACKEND_PORT}:8000"
    depends_on:
      - db_${CLIENT_NAME}
    restart: unless-stopped

  frontend_${CLIENT_NAME}:
    build:
      context: ./frontend
      dockerfile: Dockerfile
    container_name: ps_frontend_${CLIENT_NAME}
    environment:
      VITE_API_BASE: http://localhost:${BACKEND_PORT}/api/v1
    ports:
      - "${FRONTEND_PORT}:80"
    depends_on:
      - backend_${CLIENT_NAME}
    restart: unless-stopped

volumes:
  pgdata_${CLIENT_NAME}:
EOF

echo "✅ File docker-compose.yml generato con successo in ${CLIENT_DIR}"
echo "🚀 Per avviare l'istanza del cliente:"
echo "   cd \"${CLIENT_DIR}\" && docker compose up -d --build"
echo "=================================================="
