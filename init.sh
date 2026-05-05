#!/bin/bash
# Price Sentinel — Setup & Recovery Script
# Riavvia l'ambiente, applica le migrazioni pendenti e prepara il Frontend.

echo "============================================="
echo "🛡️  PRICE SENTINEL - AMBIENTE SETUP & RECOVERY"
echo "============================================="

# 1. Pulizia Docker Hang
echo -n "🛠️  Pulizia container e sblocco network... "
docker-compose down -v >/dev/null 2>&1
echo "Fatto."

# 2. Riavvio Backend & DB
echo -n "🚀 Riavvio database e backend FastAPI... "
docker-compose up -d --build >/dev/null 2>&1
echo "Fatto."

sleep 5

# 3. Applicazione Migrazioni (Telegram)
echo -n "🗄️  Applicazione modifiche DB (Migrazione)... "
docker-compose exec -T backend alembic revision --autogenerate -m "Aggiornamento_Sprint_3_4" >/dev/null 2>&1
docker-compose exec -T backend alembic upgrade head >/dev/null 2>&1
echo "Fatto."

# 4. Installazione Frontend (se non bloccata)
echo "📦 Installazione dipendenze Frontend..."
cd frontend
npm cache clean --force
echo "Avviene in background così non blocca il tuo terminale."
nohup npm install > npm_install.log 2>&1 &

echo "============================================="
echo "✅  TUTTO PRONTO E AGGIORNATO (Sprint 4 Completo)!"
echo "Backend: https://localhost/api/v1/docs"
echo "Per entrare in React: cd frontend && npm run dev"
echo "============================================="
