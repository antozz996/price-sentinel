import logging
import os
import httpx
from pydantic_settings import BaseSettings

logger = logging.getLogger("price_sentinel.telegram")

class TelegramSettings(BaseSettings):
    telegram_bot_token: str | None = None
    
    class Config:
        env_file = ".env"
        extra = "ignore"

settings = TelegramSettings()

async def send_telegram_message(chat_id: str | None, text: str):
    """
    Invia un messaggio Telegram usando le API bot ufficiali.
    Se il TOKEN non è presente in .env, logga solo il messaggio.
    """
    if not chat_id:
        logger.debug(f"[Telegram Mock] Nessun chat_id fornito. Messaggio perso: {text}")
        return False
        
    token = settings.telegram_bot_token
    if not token or token == "mock":
        # Modalità Development / Senza Bot Serio
        logger.info(f"[Telegram Mock -> {chat_id}]: {text}")
        return True

    url = f"https://api.telegram.org/bot{token}/sendMessage"
    payload = {
        "chat_id": chat_id,
        "text": text,
        "parse_mode": "HTML"
    }

    try:
        async with httpx.AsyncClient() as client:
            response = await client.post(url, json=payload, timeout=5.0)
            if response.status_code == 200:
                logger.info(f"Notifica inviata con successo su Telegram a {chat_id}")
                return True
            else:
                logger.error(f"Errore Telegram {response.status_code}: {response.text}")
                return False
    except Exception as e:
        logger.error(f"Eccezione durante l'invio su Telegram: {e}")
        return False


async def notify_manager_anomalies(chat_id: str | None, location_name: str, count: int, fornitore_nome: str):
    """
    Notifica il manager di una location che sono arrivate nuove anomalie.
    """
    if count <= 0:
        return
        
    testo = (
        f"🚨 <b>Nuove Anomalie Rilevate</b>\n\n"
        f"📍 Sede: {location_name}\n"
        f"🏢 Fornitore: {fornitore_nome}\n"
        f"⚠️ Anomalie in attesa: <b>{count}</b>\n\n"
        f"Accedi alla Stanza di Validazione per gestirle."
    )
    await send_telegram_message(chat_id, testo)


async def notify_admin_escalation(chat_id: str | None, location_name: str, fornitore_nome: str, prodotto: str, delta: float):
    """
    Notifica l'Admin che un manager ha contestato (segnalato) un'anomalia, sollevando un'escalation.
    """
    testo = (
        f"⚠️ <b>Escalation Anomalia (Manager)</b>\n\n"
        f"📍 Sede: {location_name}\n"
        f"🏢 Fornitore: {fornitore_nome}\n"
        f"📦 Prodotto: {prodotto}\n"
        f"💸 Delta rilevato: <b>+€{delta}</b>\n\n"
        f"L'anomalia è ora in stato <b>Contestata</b> e richiede la tua attenzione per aprire un Reclamo globale."
    )
    await send_telegram_message(chat_id, testo)
