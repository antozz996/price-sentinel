# Price Sentinel — onboarding primo cliente

## Dati richiesti

- sede e utenti autorizzati;
- fornitori con contatto reale;
- catalogo prodotti e alias confermati;
- listini effettivi;
- mapping manuale della venue e dei fornitori LiquidStock;
- tolleranze economiche approvate dal cliente.

Non caricare dati fittizi nel database operativo.

## Sequenza consigliata

1. Creare/validare sede e utenti.
2. Importare fornitori, prodotti e listini.
3. Approvare gli alias prodotto.
4. Collegare manualmente venue, fornitori e prodotti LiquidStock.
5. Salvare le soglie nella pagina **Onboarding**.
6. Creare un ordine reale di prova in LiquidStock.
7. Sincronizzarlo e verificare che lo snapshot sia immutabile.
8. Importare una prima fattura reale.
9. Confermare manualmente la fattura candidata.
10. Completare una riconciliazione e, se presente una reale anomalia, provare la
    contestazione.

## Criteri di accettazione

- nessun dato visibile tra sedi non autorizzate;
- nessun matching fuzzy definitivo;
- nessuna conversione automatica delle unità;
- importi richiesti e recuperati spiegabili dall'audit;
- comunicazioni versionate e invio confermato manualmente;
- note di credito non duplicabili;
- monitor senza effetti economici automatici;
- backup e rollback validati.

## Supporto

In caso di dubbio lasciare il caso aperto e raccogliere documento, sede, fornitore,
ordine e fattura interessati. Non correggere i documenti sorgente per eliminare
l'anomalia.
