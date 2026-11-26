// Avviso sulle pagine pubbliche dei fornitori: il sistema è nuovo, chiediamo di segnalare gli errori.
export default function NewSystemNotice() {
  return <p role="note" style={{ margin: '0 0 16px', padding: '10px 12px', borderRadius: 'var(--radius-md)', border: '1px solid var(--accent, #2563eb)', background: 'var(--bg-inset)', color: 'var(--text-primary)' }}>
    <strong>Sistema nuovo:</strong> potrebbe esserci ancora qualche errore. Se notate qualcosa che non va (un prezzo, un prodotto, un pulsante), per favore segnalatecelo rispondendo al messaggio con cui avete ricevuto questo link. Grazie!
  </p>;
}
