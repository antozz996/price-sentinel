import os
import httpx
import json
import logging
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)

# Definizione dei Tools per l'API di Groq
TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "get_kpi_economici",
            "description": "Ottiene i KPI economici attuali del sistema: Euro recuperati totali, Euro in contestazione (in reclamo), ed Euro a rischio (anomalie da verificare).",
            "parameters": {
                "type": "object",
                "properties": {},
                "required": []
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "get_top_sprechi",
            "description": "Ottiene la lista dei 5 prodotti che stanno causando la maggiore perdita finanziaria (spreco) a causa di prezzi di acquisto superiori al minimo storico.",
            "parameters": {
                "type": "object",
                "properties": {},
                "required": []
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "get_info_fornitore",
            "description": "Cerca un fornitore per nome nel database e restituisce il numero di fatture registrate e il totale degli importi (se disponibili).",
            "parameters": {
                "type": "object",
                "properties": {
                    "nome_fornitore": {
                        "type": "string",
                        "description": "Il nome del fornitore da cercare (es. 'Navas' o 'Playa')"
                    }
                },
                "required": ["nome_fornitore"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "get_prodotti_piu_acquistati_fornitore",
            "description": "Ottiene la lista dei prodotti più acquistati da un determinato fornitore, ordinati per quantità totale acquistata.",
            "parameters": {
                "type": "object",
                "properties": {
                    "nome_fornitore": {
                        "type": "string",
                        "description": "Il nome del fornitore da cercare (es. 'Navas' o 'Playa')"
                    },
                    "limit": {
                        "type": "integer",
                        "description": "Il numero massimo di prodotti da restituire (default: 50)"
                    }
                },
                "required": ["nome_fornitore"]
            }
        }
    }
]

class SentinelAI:
    def __init__(self):
        self.api_key = os.environ.get("GROQ_API_KEY", "")
        self.base_url = "https://api.groq.com/openai/v1/chat/completions"
        self.model = "llama-3.3-70b-versatile"
        
        self.system_prompt = (
            "Sei Sentinel AI, il Direttore Finanziario Virtuale (CFO) di Price Sentinel, "
            "un software B2B avanzato per il controllo di gestione nel settore Ho.Re.Ca. "
            "Hai accesso al database tramite i tuoi tool. Se l'utente ti fa una domanda sui dati "
            "(sprechi, fornitori, kpi), USA SEMPRE I TOOL a tua disposizione per trovare i numeri esatti "
            "prima di rispondere. Non inventare i numeri. "
            "Usa un tono professionale, rassicurante e molto competente. "
            "Rispondi sempre in lingua italiana, utilizzando la formattazione markdown per la leggibilità "
            "(usa tabelle, elenchi puntati e grassetti per evidenziare i dati)."
        )

    # ── Database Executions ──

    async def _execute_get_kpi_economici(self, db: AsyncSession) -> str:
        sql = """
        SELECT 
            (SELECT COALESCE(SUM(importo_recuperato), 0) FROM note_di_credito) as recuperati,
            (SELECT COALESCE(SUM(delta_totale), 0) FROM anomalie WHERE stato_validazione = 'in_reclamo') as in_contestazione,
            (SELECT COALESCE(SUM(delta_totale), 0) FROM anomalie WHERE stato_validazione IN ('da_verificare', 'contestata')) as a_rischio
        """
        res = await db.execute(text(sql))
        row = res.one()
        return json.dumps({
            "euro_recuperati": float(row.recuperati),
            "euro_in_contestazione": float(row.in_contestazione),
            "euro_a_rischio": float(row.a_rischio)
        })

    async def _execute_get_top_sprechi(self, db: AsyncSession) -> str:
        sql = """
        WITH min_prices AS (
            SELECT sku_interno, MIN(prezzo_netto_normalizzato) AS min_price
            FROM righe_fattura WHERE stato_matching = 'matched' AND sku_interno IS NOT NULL AND prezzo_netto_normalizzato > 0
            GROUP BY sku_interno
        )
        SELECT 
            r.sku_interno,
            COALESCE(MAX(lm.descrizione), MAX(r.descrizione_fornitore_raw), r.sku_interno) AS prodotto_nome,
            SUM(GREATEST(0, r.prezzo_netto_normalizzato - mp.min_price) * r.quantita) AS spreco_totale
        FROM righe_fattura r
        JOIN min_prices mp ON r.sku_interno = mp.sku_interno
        LEFT JOIN listino_master lm ON lm.sku_interno = r.sku_interno AND lm.data_scadenza IS NULL
        WHERE r.stato_matching = 'matched'
        GROUP BY r.sku_interno, mp.min_price
        HAVING SUM(GREATEST(0, r.prezzo_netto_normalizzato - mp.min_price) * r.quantita) > 0
        ORDER BY spreco_totale DESC
        LIMIT 5;
        """
        res = await db.execute(text(sql))
        results = [{"prodotto": r.prodotto_nome, "spreco": float(r.spreco_totale)} for r in res.all()]
        return json.dumps(results)

    async def _execute_get_info_fornitore(self, db: AsyncSession, nome_fornitore: str) -> str:
        sql = """
        SELECT f.id, f.nome_azienda, 
               (SELECT COUNT(*) FROM fatture WHERE fornitore_id = f.id) as num_fatture,
               (SELECT COALESCE(SUM(totale_imponibile), 0) FROM fatture WHERE fornitore_id = f.id) as fatturato_totale
        FROM fornitori f
        WHERE f.nome_azienda ILIKE :nome
        LIMIT 3
        """
        res = await db.execute(text(sql), {"nome": f"%{nome_fornitore}%"})
        results = [
            {"id": r.id, "fornitore": r.nome_azienda, "fatture": int(r.num_fatture), "fatturato_totale": float(r.fatturato_totale)} 
            for r in res.all()
        ]
        return json.dumps(results if results else {"errore": "Nessun fornitore trovato con questo nome."})

    async def _execute_get_prodotti_piu_acquistati_fornitore(self, db: AsyncSession, nome_fornitore: str, limit: int = 50) -> str:
        sql = """
        SELECT 
            COALESCE(rf.sku_interno, rf.descrizione_fornitore_raw) AS prodotto_id,
            COALESCE(MAX(lm.descrizione), MAX(rf.descrizione_fornitore_raw), MAX(rf.sku_interno)) AS prodotto_nome,
            SUM(rf.quantita) AS quantita_totale,
            COUNT(rf.id) AS numero_acquisti,
            SUM(rf.prezzo_netto_normalizzato * rf.quantita) AS spesa_totale
        FROM righe_fattura rf
        JOIN fatture f ON rf.fattura_id = f.id
        JOIN fornitori fo ON f.fornitore_id = fo.id
        LEFT JOIN listino_master lm ON lm.sku_interno = rf.sku_interno AND lm.data_scadenza IS NULL
        WHERE fo.nome_azienda ILIKE :nome
        GROUP BY COALESCE(rf.sku_interno, rf.descrizione_fornitore_raw)
        ORDER BY quantita_totale DESC
        LIMIT :limit
        """
        res = await db.execute(text(sql), {"nome": f"%{nome_fornitore}%", "limit": limit})
        results = [
            {
                "sku_interno": r.prodotto_id,
                "prodotto": r.prodotto_nome,
                "quantita_totale": float(r.quantita_totale),
                "numero_acquisti": int(r.numero_acquisti),
                "spesa_totale": float(r.spesa_totale)
            }
            for r in res.all()
        ]
        return json.dumps(results if results else {"errore": f"Nessun prodotto trovato per il fornitore '{nome_fornitore}'."})


    # ── Core Engine ──

    async def chat(self, user_message: str, chat_history: list = None, db: AsyncSession = None) -> str:
        if not self.api_key:
            return "⚠️ **Attenzione: API Key di Groq non configurata.**\nAggiungila al file .env!"

        messages = [{"role": "system", "content": self.system_prompt}]
        if chat_history:
            messages.extend(chat_history)
        messages.append({"role": "user", "content": user_message})

        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json"
        }

        async with httpx.AsyncClient(timeout=45.0) as client:
            # 1. Prima Chiamata (con Tools)
            payload = {
                "model": self.model,
                "messages": messages,
                "temperature": 0.3,
                "max_tokens": 1024,
                "tools": TOOLS,
                "tool_choice": "auto"
            }

            try:
                resp = await client.post(self.base_url, headers=headers, json=payload)
                resp.raise_for_status()
                response_data = resp.json()
                assistant_message = response_data["choices"][0]["message"]
            except Exception as e:
                logger.error(f"Errore chiamata AI: {e}")
                return "❌ Errore di comunicazione con il server AI."

            # Se l'AI decide di usare un tool
            if assistant_message.get("tool_calls"):
                messages.append(assistant_message) # Append assistant request

                # Esegue le funzioni richieste
                for tool_call in assistant_message["tool_calls"]:
                    fn_name = tool_call["function"]["name"]
                    args = json.loads(tool_call["function"]["arguments"])
                    
                    try:
                        if fn_name == "get_kpi_economici":
                            result = await self._execute_get_kpi_economici(db)
                        elif fn_name == "get_top_sprechi":
                            result = await self._execute_get_top_sprechi(db)
                        elif fn_name == "get_info_fornitore":
                            result = await self._execute_get_info_fornitore(db, args.get("nome_fornitore", ""))
                        elif fn_name == "get_prodotti_piu_acquistati_fornitore":
                            result = await self._execute_get_prodotti_piu_acquistati_fornitore(
                                db,
                                args.get("nome_fornitore", ""),
                                int(args.get("limit", 50))
                            )
                        else:
                            result = '{"error": "Funzione sconosciuta"}'
                    except Exception as ex:
                        logger.error(f"Errore esecuzione Tool SQL {fn_name}: {ex}")
                        result = f'{{"error": "Errore SQL: {str(ex)}" }}'

                    # Aggiunge il risultato dei dati al messaggio di history
                    messages.append({
                        "tool_call_id": tool_call["id"],
                        "role": "tool",
                        "name": fn_name,
                        "content": result
                    })

                # 2. Seconda Chiamata (l'AI ragiona sui dati estratti e formula la risposta)
                payload_final = {
                    "model": self.model,
                    "messages": messages,
                    "temperature": 0.4,
                    "max_tokens": 1024
                }
                resp_final = await client.post(self.base_url, headers=headers, json=payload_final)
                resp_final.raise_for_status()
                final_data = resp_final.json()
                return final_data["choices"][0]["message"]["content"]

            # Se l'AI non ha usato tool, restituisce semplicemente la risposta discorsiva
            return assistant_message["content"]

ai_engine = SentinelAI()
