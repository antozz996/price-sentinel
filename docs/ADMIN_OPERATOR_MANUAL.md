# Price Sentinel — manuale amministratore e operatore

## Attivazione di una sede

Aprire **Onboarding**, scegliere la sede e completare la checklist. L'admin configura
le tolleranze assolute/percentuali, la soglia per anomalie importanti e i giorni oltre
i quali una riconciliazione o una nota di credito richiedono attenzione.

La checklist legge dati reali: non crea fatture, prodotti, listini o ordini demo.

## Riconciliare un ordine

1. Aprire **Riconciliazioni ordini**.
2. Verificare il mapping esplicito della venue.
3. Selezionare il sotto-ordine LiquidStock.
4. Verificare il fornitore canonico e i prodotti associati.
5. Valutare le fatture candidate e scegliere manualmente quella corretta.
6. Controllare quantità, prezzi, ricezioni e tolleranze.
7. Risolvere manualmente le righe ambigue; chiudere solo dopo il controllo.

Una fattura futura per un ordine può essere proposta, mai collegata definitivamente
senza conferma. Il nome simile non è una prova di equivalenza.

## Aprire una contestazione

1. Aprire **Contestazioni e recuperi**.
2. Filtrare sede, fornitore o stato e scegliere le anomalie compatibili.
3. Inserire l'importo richiesto; il sistema non lo inventa.
4. Salvare la bozza e controllare il riepilogo economico.
5. Generare una comunicazione, modificarla se necessario e salvarne la versione.
6. Copiare il testo o aprire il client email.
7. Confermare manualmente l'invio: l'apertura del client non equivale a consegna.

Ogni nuova versione della comunicazione conserva lo snapshot precedente.

## Risposte, riconoscimenti e note di credito

- Registrare la risposta del fornitore con data, canale e testo.
- Registrare l'importo riconosciuto solo quando esplicitamente confermato.
- Per una nota di credito indicare documento, data, fornitore e importo.
- Il tipo TD04 e il contesto della fattura sono validati.
- Allocare la nota alle anomalie interessate senza superare gli importi disponibili.
- Il recupero parziale mantiene la pratica aperta; quello completo consente lo stato
  `recovered`.

Gli allegati accettati sono limitati a tipi sicuri e 10 MB. Il PDF pratica è un
riepilogo operativo, non sostituisce il documento fiscale originale.

## Monitor operativo

Aprire **Monitor operativo**, leggere gli alert e usare **Presa visione** dopo aver
valutato il caso. Solo l'admin può avviare manualmente una scansione. L'avviso non
esegue correzioni automatiche.

## Dashboard economica

La pagina Contestazioni mostra importi richiesti, riconosciuti, recuperati e ancora
aperti, pratiche scadute e andamento temporale. Le pratiche annullate non contribuiscono
agli importi economici.

## Regole da non violare

- non cancellare o ricaricare il database reale;
- non correggere una fattura sorgente per far quadrare una contestazione;
- non dedurre venue, fornitore o prodotto solo dal nome;
- non usare l'apertura email/WhatsApp come prova di invio o ricezione;
- non modificare la giacenza LiquidStock da Price Sentinel.

## Usare il Listino Smart

La pagina contiene quattro tab:

- **Matrice**: confronta prezzi per prodotto canonico e fornitore. Il bordo blu indica
  il minimo assoluto; “CONSIGLIATO” segue invece qualità e regole. Un fornitore bloccato
  resta visibile ma non è selezionabile automaticamente.
- **Incolla prezzi**: copia una matrice da Excel/Sheets con il prodotto nella prima
  colonna e i fornitori nelle successive. Le celle vuote sono ignorate.
- **Qualità e regole**: assegna qualità 1–5, approvato/sconsigliato/bloccato e policy.
- **Storico e audit**: mostra versioni prezzo, modifiche alle regole e scostamenti.

Per un incolla massivo:

1. Incollare il blocco e scegliere data di validità e unità.
2. Premere **Analizza senza salvare**.
3. Associare solo le intestazioni o i prodotti non riconosciuti; quelli univoci sono
   risolti automaticamente.
4. Correggere tutti gli errori. Il sistema non permette il commit finché restano
   ambiguità, prezzi invalidi o doppie righe attive.
5. Controllare il riepilogo nuovi/aggiornati/invariati e confermare.

Per una singola cella, cliccare il prezzo o **inserisci**, indicare valore e unità e
generare l'anteprima. Anche questa scorciatoia applica la stessa conferma sicura.

Una motivazione è obbligatoria per `sconsigliato` e `bloccato`. Il premium percentuale
o assoluto consente di preferire qualità/fornitore indicato entro la soglia; con zero
premium vince il miglior prezzo idoneo. La modalità manuale non emette una selezione
automatica.
