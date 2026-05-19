import os
import httpx
import json
import logging

logger = logging.getLogger(__name__)

class SentinelAI:
    def __init__(self):
        # We look for the GROQ_API_KEY in the environment
        self.api_key = os.environ.get("GROQ_API_KEY", "")
        self.base_url = "https://api.groq.com/openai/v1/chat/completions"
        self.model = "llama3-70b-8192" # Fast, extremely smart model
        
        self.system_prompt = (
            "Sei Sentinel AI, il Direttore Finanziario Virtuale (CFO) di Price Sentinel, "
            "un software B2B avanzato per il controllo di gestione nel settore Ho.Re.Ca. "
            "Il tuo obiettivo è assistere l'utente nell'analisi dei dati, rispondere a domande "
            "sulle fatture, individuare sprechi e rincari nascosti, e offrire consulenza aziendale. "
            "Usa un tono professionale, rassicurante, estremamente competente ma conciso. "
            "Rispondi sempre in lingua italiana, utilizzando formattazione markdown per la leggibilità."
        )

    async def chat(self, user_message: str, chat_history: list = None) -> str:
        """
        Invia il messaggio all'API di Groq e restituisce la risposta.
        """
        if not self.api_key:
            return (
                "⚠️ **Attenzione: API Key di Groq non configurata.**\n\n"
                "Per attivare il mio cervello, aggiungi `GROQ_API_KEY=tua_chiave` "
                "alle variabili d'ambiente del server. Puoi ottenere una chiave gratuita su "
                "[console.groq.com](https://console.groq.com/)."
            )

        messages = [{"role": "system", "content": self.system_prompt}]
        
        if chat_history:
            messages.extend(chat_history)
            
        messages.append({"role": "user", "content": user_message})

        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json"
        }

        payload = {
            "model": self.model,
            "messages": messages,
            "temperature": 0.5,
            "max_tokens": 1024
        }

        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.post(self.base_url, headers=headers, json=payload)
                response.raise_for_status()
                data = response.json()
                return data["choices"][0]["message"]["content"]
        except httpx.HTTPStatusError as e:
            logger.error(f"Errore HTTP da Groq: {e.response.text}")
            return f"❌ Si è verificato un errore di connessione con Groq: {e.response.status_code}"
        except Exception as e:
            logger.error(f"Errore interno AI Engine: {e}")
            return f"❌ Errore interno del sistema AI: {str(e)}"

# Singleton instance
ai_engine = SentinelAI()
