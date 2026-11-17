import { useEffect, useMemo, useState } from 'react';
import type { CSSProperties, FormEvent } from 'react';
import { API_BASE } from '../api';

// Listino sempre aperto: il fornitore cambia solo i prezzi, quando vuole.
// Ribasso: vale subito. Aumento: vale dalla prossima data fissa (1 o 15 del mese).

type Pending = { tipo: string; prezzo: string | null; decorrenza: string; sospesa: boolean };
type Item = {
  listino_id: number; descrizione: string; dicitura?: string | null; marca?: string | null; formato: string;
  prezzo: string; importante: boolean; siete_i_piu_convenienti: boolean | null; in_attesa: Pending | null;
};
type Data = { fornitore: string; oggi: string; prossima_data_fissa: string; ultima_conferma: string | null; importanti: number; items: Item[] };
type Edit = { prezzo: string; non_trattato: boolean };
type Summary = { ribassi: number; aumenti: number; non_trattati: number; sospese: number; annullate: number; invariati: number };

const euro = (value: string | number) => `€ ${Number(value).toLocaleString('it-IT', { minimumFractionDigits: 2, maximumFractionDigits: 4 })}`;
const day = (iso: string) => new Date(`${iso}T12:00:00`).toLocaleDateString('it-IT', { day: 'numeric', month: 'long' });
const parsePrice = (text: string) => Number(text.replace(',', '.'));

function errorText(detail: unknown, fallback: string) {
  if (typeof detail === 'string' && detail.trim()) return detail;
  if (Array.isArray(detail)) return detail.map(d => (d && typeof d === 'object' && 'msg' in d ? String(d.msg) : '')).filter(Boolean).join(' · ') || fallback;
  return fallback;
}

export default function SupplierOpenPriceList({ token }: { token: string }) {
  const [data, setData] = useState<Data | null>(null);
  const [edits, setEdits] = useState<Record<number, Edit>>({});
  const [search, setSearch] = useState('');
  const [loading, setLoading] = useState(true);
  const [sending, setSending] = useState(false);
  const [error, setError] = useState('');
  const [done, setDone] = useState<Summary | 'confermato' | null>(null);
  const base = `${API_BASE}/supplier-price-links/public/${encodeURIComponent(token)}`;

  useEffect(() => {
    let active = true;
    fetch(base)
      .then(async r => { const body = await r.json().catch(() => ({})); if (!r.ok) throw new Error(body.detail || 'Link non valido'); return body as Data; })
      .then(body => { if (active) setData(body); })
      .catch(e => { if (active) setError(e.message || 'Impossibile caricare il listino'); })
      .finally(() => { if (active) setLoading(false); });
    return () => { active = false; };
  }, [base]);

  const changed = useMemo(() => (data?.items || []).filter(item => {
    const edit = edits[item.listino_id];
    if (!edit) return false;
    if (edit.non_trattato) return true;
    const value = parsePrice(edit.prezzo);
    return edit.prezzo.trim() !== '' && value > 0 && value !== Number(item.prezzo);
  }), [data, edits]);

  const invalid = (data?.items || []).filter(item => {
    const edit = edits[item.listino_id];
    return edit && !edit.non_trattato && edit.prezzo.trim() !== '' && !(parsePrice(edit.prezzo) > 0);
  });

  const setEdit = (id: number, change: Partial<Edit>) =>
    setEdits(prev => ({ ...prev, [id]: { ...(prev[id] || { prezzo: '', non_trattato: false }), ...change } }));

  const send = async (event: FormEvent) => {
    event.preventDefault();
    if (!changed.length || invalid.length) return;
    setSending(true); setError('');
    try {
      const response = await fetch(`${base}/submit`, {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ modifiche: changed.map(item => {
          const edit = edits[item.listino_id];
          return edit.non_trattato
            ? { listino_id: item.listino_id, non_trattato: true }
            : { listino_id: item.listino_id, prezzo: String(parsePrice(edit.prezzo)) };
        }) }),
      });
      const body = await response.json().catch(() => ({}));
      if (!response.ok) throw new Error(errorText(body.detail, 'Invio non riuscito'));
      setDone(body.riepilogo as Summary);
    } catch (e) { setError(e instanceof Error ? e.message : 'Invio non riuscito'); }
    finally { setSending(false); }
  };

  const confirmAll = async () => {
    setSending(true); setError('');
    try {
      const response = await fetch(`${base}/confirm-unchanged`, { method: 'POST' });
      const body = await response.json().catch(() => ({}));
      if (!response.ok) throw new Error(errorText(body.detail, 'Conferma non riuscita'));
      setDone('confermato');
    } catch (e) { setError(e instanceof Error ? e.message : 'Conferma non riuscita'); }
    finally { setSending(false); }
  };

  const wrap: CSSProperties = { minHeight: '100vh', padding: '24px 14px', boxSizing: 'border-box', background: 'var(--bg-app)', color: 'var(--text-primary)', fontFamily: 'var(--font-family)' };
  const box: CSSProperties = { maxWidth: 900, margin: '0 auto', padding: 20, border: '1px solid var(--line)', borderRadius: 'var(--radius-lg)', background: 'var(--bg-card)' };
  const input: CSSProperties = { width: '100%', boxSizing: 'border-box', padding: 10, borderRadius: 'var(--radius-sm)', border: '1px solid var(--line)', background: 'var(--bg-inset)', color: 'var(--text-primary)' };
  const note: CSSProperties = { padding: 12, border: '1px solid var(--warn-border)', borderRadius: 'var(--radius-md)', background: 'var(--warn-bg)' };

  if (loading) return <main style={wrap}><div style={box}>Caricamento listino…</div></main>;
  if (error && !data) return <main style={wrap}><div style={box}><h1>Listino non disponibile</h1><p>{error}</p></div></main>;
  if (!data) return null;
  if (done) {
    return <main style={wrap}><div style={box}>
      <h1>Grazie</h1>
      {done === 'confermato' ? <p>Abbiamo registrato che il vostro listino è invariato.</p> : <>
        <p>Abbiamo registrato le vostre modifiche:</p>
        <ul>
          {done.ribassi > 0 && <li>{done.ribassi} ribassi: valgono da subito.</li>}
          {done.aumenti > 0 && <li>{done.aumenti} aumenti: valgono dal {day(data.prossima_data_fissa)}.</li>}
          {done.non_trattati > 0 && <li>{done.non_trattati} prodotti non più trattati: il prezzo resta valido fino al {day(data.prossima_data_fissa)}.</li>}
          {done.annullate > 0 && <li>{done.annullate} modifiche in attesa annullate (prezzo riportato a quello attuale).</li>}
          {done.sospese > 0 && <li>{done.sospese} variazioni molto forti saranno verificate dal nostro ufficio acquisti prima di diventare valide.</li>}
        </ul>
      </>}
      <p>Potete tornare su questo link quando volete per aggiornare i prezzi.</p>
    </div></main>;
  }

  const query = search.trim().toLowerCase();
  const visible = data.items.filter(item => !query || `${item.descrizione} ${item.dicitura || ''} ${item.marca || ''}`.toLowerCase().includes(query));
  const total = data.items.length;
  const others = total - data.importanti;
  const groups = [
    { title: `Da controllare per primi: i ${data.importanti} prodotti che vi acquistiamo di più`, items: visible.filter(i => i.importante) },
    { title: data.importanti ? `Tutti gli altri prodotti (${others})` : `I vostri prodotti (${total})`, items: visible.filter(i => !i.importante) },
  ].filter(group => group.items.length);
  const fixedDay = day(data.prossima_data_fissa);

  const hint = (item: Item) => {
    const edit = edits[item.listino_id];
    if (!edit) return null;
    if (edit.non_trattato) return `Il prezzo resta valido fino al ${day(data.prossima_data_fissa)}, poi il prodotto esce dal listino.`;
    const value = parsePrice(edit.prezzo), old = Number(item.prezzo);
    if (!(value > 0) || value === old) return null;
    const change = (value - old) / old;
    if (change < 0) return change < -0.4 ? 'Ribasso molto forte: lo verifichiamo prima di applicarlo.' : 'Ribasso: vale da subito.';
    return change > 0.3
      ? `Aumento oltre il 30%: lo verifichiamo prima; in ogni caso non prima del ${day(data.prossima_data_fissa)}.`
      : `Aumento: vale dal ${day(data.prossima_data_fissa)}.`;
  };

  return <main style={wrap}><form style={box} onSubmit={send}>
    <h1 style={{ marginTop: 0 }}>Listino prezzi · {data.fornitore}</h1>
    <p>
      Qui trovate <strong>tutti i {total} prodotti</strong> che vi acquistiamo, ciascuno con il prezzo che oggi abbiamo nel nostro listino.
      {data.importanti > 0 && <> In cima ci sono i {data.importanti} su cui spendiamo di più: controllate prima quelli. Scorrendo la pagina trovate tutti gli altri.</>}
    </p>
    <p>
      Questo link è <strong>sempre lo stesso e non scade</strong>: salvatelo e usatelo ogni volta che i vostri prezzi cambiano.
      Non serve mandarci listini per email o WhatsApp.
    </p>

    <h2 style={{ fontSize: '1.1rem' }}>Cosa dovete fare</h2>
    <ol style={{ paddingLeft: 20, lineHeight: 1.5 }}>
      <li>Se tutti i prezzi sono ancora giusti, premete <strong>«Confermo tutti i prezzi invariati»</strong>. Basta questo.</li>
      <li>Se un prezzo è cambiato, scrivete il nuovo prezzo <strong>solo in quella riga</strong>, nella casella «Nuovo prezzo» (per esempio 2,35). Le righe lasciate vuote restano come sono.</li>
      <li>Se un prodotto non lo trattate più, spuntate <strong>«Non lo tratto più»</strong>.</li>
      <li>Alla fine premete il pulsante in fondo alla pagina <strong>«Invia modifiche»</strong>.</li>
    </ol>

    <div style={note}>
      <strong>Quando valgono i nuovi prezzi</strong>
      <ul style={{ margin: '6px 0 0', paddingLeft: 20, lineHeight: 1.5 }}>
        <li><strong>Ribasso</strong>: vale da subito, già dalle prossime consegne.</li>
        <li><strong>Aumento</strong>: potete inserirlo quando volete, ma vale solo dalla prossima data fissa (il 1° o il 15 del mese).
          Se lo inserite oggi vale dal <strong>{fixedDay}</strong>: fino ad allora va fatturato il prezzo attuale.</li>
        <li><strong>Prodotto non più trattato</strong>: il prezzo attuale resta valido fino al {fixedDay}.</li>
        <li><strong>Variazioni molto forti</strong> (ribassi oltre il 40% o aumenti oltre il 30%) vengono controllate dal nostro ufficio acquisti prima di entrare in listino.</li>
        <li>Se avete sbagliato un prezzo, rientrate dal link e correggetelo: vale sempre l'ultimo prezzo inviato.</li>
      </ul>
    </div>
    <p><small>
      Ogni prezzo si riferisce all'unità indicata accanto (per esempio al kg, al pezzo o al cartone).
      Accanto ad alcuni prodotti vedete se oggi siete il fornitore più conveniente per noi; i prezzi degli altri fornitori non vengono mai mostrati.
      Descrizione, marca e formato non si possono cambiare da qui: se qualcosa non è corretto, o se volete proporci un prodotto nuovo, contattate il nostro ufficio acquisti.
    </small></p>
    <p style={{ display: 'flex', gap: 12, flexWrap: 'wrap', alignItems: 'center' }}>
      <button type="button" className="btn-secondary" disabled={sending} onClick={confirmAll}>Confermo tutti i prezzi invariati</button>
      {data.ultima_conferma && <small>Ultimo aggiornamento: {new Date(data.ultima_conferma).toLocaleDateString('it-IT')}</small>}
    </p>
    <input style={{ ...input, marginBottom: 16 }} placeholder="Cerca un prodotto" value={search} onChange={e => setSearch(e.target.value)} />

    {groups.map(group => <section key={group.title}>
      <h2 style={{ fontSize: '1.1rem' }}>{group.title}</h2>
      {group.items.map(item => {
        const edit = edits[item.listino_id];
        const message = hint(item);
        return <div key={item.listino_id} style={{ padding: '12px 0', borderTop: '1px solid var(--line)' }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', gap: 12, flexWrap: 'wrap' }}>
            <div style={{ flex: '1 1 260px' }}>
              <strong>{item.descrizione}</strong>
              {(item.dicitura || item.marca) && <div><small>{[item.dicitura, item.marca].filter(Boolean).join(' · ')}</small></div>}
              <div><small>Prezzo attuale: <strong>{euro(item.prezzo)}</strong> per {item.formato}</small></div>
              {item.siete_i_piu_convenienti !== null && <div><small style={{ color: item.siete_i_piu_convenienti ? 'var(--ok, green)' : 'var(--warn-text, #b45309)' }}>
                {item.siete_i_piu_convenienti ? 'Siete i più convenienti' : 'Non siete i più convenienti'}
              </small></div>}
              {item.in_attesa && <div><small>
                {item.in_attesa.tipo === 'non_trattato'
                  ? `Già segnalato come non più trattato dal ${day(item.in_attesa.decorrenza)}`
                  : `Già inserito: ${euro(item.in_attesa.prezzo || 0)} dal ${day(item.in_attesa.decorrenza)}`}
                {item.in_attesa.sospesa && ' (in verifica)'}
              </small></div>}
            </div>
            <div style={{ flex: '0 1 220px' }}>
              <input style={input} inputMode="decimal" placeholder="Nuovo prezzo" disabled={edit?.non_trattato}
                aria-label={`Nuovo prezzo per ${item.descrizione}`}
                value={edit?.prezzo || ''} onChange={e => setEdit(item.listino_id, { prezzo: e.target.value })} />
              <label style={{ display: 'flex', gap: 6, marginTop: 6 }}>
                <input type="checkbox" checked={!!edit?.non_trattato}
                  onChange={e => setEdit(item.listino_id, { non_trattato: e.target.checked, prezzo: '' })} />
                <small>Non lo tratto più</small>
              </label>
            </div>
          </div>
          {message && <small style={{ display: 'block', marginTop: 6, fontWeight: 600 }}>{message}</small>}
        </div>;
      })}
    </section>)}

    {error && <p style={{ color: 'var(--danger, #b91c1c)' }}>{error}</p>}
    {invalid.length > 0 && <p style={{ color: 'var(--danger, #b91c1c)' }}>Controlla i prezzi di: {invalid.map(i => i.descrizione).join(', ')}</p>}
    <div style={{ position: 'sticky', bottom: 0, padding: '12px 0', background: 'var(--bg-card)' }}>
      <button type="submit" className="btn-primary" disabled={sending || !changed.length || invalid.length > 0}>
        {sending ? 'Invio…' : changed.length ? `Invia ${changed.length} ${changed.length === 1 ? 'modifica' : 'modifiche'}` : 'Nessuna modifica da inviare'}
      </button>
    </div>
  </form></main>;
}
