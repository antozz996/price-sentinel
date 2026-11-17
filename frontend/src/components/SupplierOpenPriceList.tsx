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
  const [restored, setRestored] = useState(0);
  const base = `${API_BASE}/supplier-price-links/public/${encodeURIComponent(token)}`;
  const draftKey = `ps-open-price-draft:${token}`;

  useEffect(() => {
    if (!data) return;
    try {
      const filled = Object.fromEntries(Object.entries(edits).filter(([, e]) => e.non_trattato || e.prezzo.trim()));
      if (Object.keys(filled).length) localStorage.setItem(draftKey, JSON.stringify(filled));
      else localStorage.removeItem(draftKey);
    } catch { /* salvataggio non disponibile */ }
  }, [data, edits, draftKey]);

  const clearDraft = () => { try { localStorage.removeItem(draftKey); } catch { /* niente */ } };

  useEffect(() => {
    let active = true;
    fetch(base)
      .then(async r => { const body = await r.json().catch(() => ({})); if (!r.ok) throw new Error(body.detail || 'Link non valido'); return body as Data; })
      .then(body => {
        if (!active) return;
        setData(body);
        // Riprende i prezzi scritti e non ancora inviati (solo su questo dispositivo).
        try {
          const saved = JSON.parse(localStorage.getItem(draftKey) || '{}') as Record<string, Edit>;
          const ids = new Set(body.items.map(item => item.listino_id));
          const kept = Object.fromEntries(Object.entries(saved).filter(([id, e]) =>
            ids.has(Number(id)) && e && (e.non_trattato || (typeof e.prezzo === 'string' && e.prezzo.trim()))));
          if (Object.keys(kept).length) { setEdits(kept); setRestored(Object.keys(kept).length); }
        } catch { /* nessuna bozza */ }
      })
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
      clearDraft();
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
      clearDraft();
      setDone('confermato');
    } catch (e) { setError(e instanceof Error ? e.message : 'Conferma non riuscita'); }
    finally { setSending(false); }
  };

  const wrap: CSSProperties = { minHeight: '100vh', padding: '24px 14px', boxSizing: 'border-box', background: 'var(--bg-app)', color: 'var(--text-primary)', fontFamily: 'var(--font-family)' };
  const box: CSSProperties = { maxWidth: 900, margin: '0 auto', padding: 20, border: '1px solid var(--line)', borderRadius: 'var(--radius-lg)', background: 'var(--bg-card)' };
  const input: CSSProperties = { width: '100%', boxSizing: 'border-box', padding: 10, borderRadius: 'var(--radius-sm)', border: '1px solid var(--line)', background: 'var(--bg-inset)', color: 'var(--text-primary)' };
  const panel: CSSProperties = { padding: 12, border: '1px solid var(--line)', borderRadius: 'var(--radius-md)', background: 'var(--bg-inset)' };
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
    <h1 style={{ margin: '0 0 4px' }}>Listino prezzi · {data.fornitore}</h1>
    <p style={{ margin: '0 0 16px', color: 'var(--text-secondary)' }}>
      {total} prodotti · link personale, sempre lo stesso, non scade
    </p>

    <div style={{ ...panel, marginBottom: 12 }}>
      <strong>Come si fa</strong>
      <ol style={{ margin: '6px 0 0', paddingLeft: 20, lineHeight: 1.6 }}>
        <li><strong>Prezzi tutti uguali?</strong> Premete «Confermo tutti i prezzi invariati». Avete finito.</li>
        <li><strong>Un prezzo è cambiato?</strong> Scrivetelo solo in quella riga (es. 2,35). Le righe vuote restano come sono.</li>
        <li><strong>Un prodotto non lo avete più?</strong> Spuntate «Non lo tratto più».</li>
        <li>Alla fine premete <strong>«Invia modifiche»</strong> in fondo alla pagina.</li>
      </ol>
    </div>

    <div style={{ ...note, marginBottom: 12 }}>
      <strong>Quando valgono i nuovi prezzi</strong>
      <div style={{ display: 'grid', gridTemplateColumns: 'max-content 1fr', gap: '4px 12px', marginTop: 6, lineHeight: 1.5 }}>
        <span>⬇ Ribasso</span><span>da subito</span>
        <span>⬆ Aumento</span><span>dal <strong>{fixedDay}</strong> (si cambia solo il 1° e il 15 del mese); fino ad allora vale il prezzo attuale</span>
        <span>✕ Non più trattato</span><span>il prezzo resta valido fino al {fixedDay}</span>
      </div>
    </div>

    <div style={{ ...panel, marginBottom: 12 }}>
      <strong>Potete fermarvi e riprendere dopo</strong>
      <div style={{ marginTop: 4, lineHeight: 1.5 }}>
        I prezzi che scrivete restano salvati su questo telefono o computer anche se chiudete la pagina: riaprite il link e li ritrovate.
        Diventano validi solo quando premete «Invia modifiche». Potete anche inviare una parte adesso e il resto un'altra volta.
      </div>
    </div>

    {restored > 0 && <p style={{ ...note, margin: '0 0 12px' }}>
      Avete ancora <strong>{restored} {restored === 1 ? 'prezzo scritto' : 'prezzi scritti'} e non inviati</strong> dall'ultima volta: li trovate già nelle loro righe.
      Controllateli e premete «Invia modifiche».
    </p>}

    {data.importanti > 0 && <p style={{ margin: '0 0 12px' }}>
      In cima trovate i <strong>{data.importanti} prodotti che vi acquistiamo di più</strong>: controllate prima quelli. Scorrendo trovate tutti gli altri.
    </p>}

    <details style={{ marginBottom: 16 }}>
      <summary style={{ cursor: 'pointer' }}>Altre informazioni</summary>
      <ul style={{ margin: '6px 0 0', paddingLeft: 20, lineHeight: 1.5 }}>
        <li>Ogni prezzo si riferisce all'unità indicata accanto (kg, pezzo, cartone…).</li>
        <li>Ribassi oltre il 40% e aumenti oltre il 30% vengono controllati dal nostro ufficio acquisti prima di entrare in listino.</li>
        <li>Avete sbagliato un prezzo già inviato? Rientrate dal link e correggetelo: vale l'ultimo inviato.</li>
        <li>Accanto ad alcuni prodotti vedete se oggi siete il fornitore più conveniente; i prezzi degli altri non vengono mai mostrati.</li>
        <li>Descrizione, marca e formato non si cambiano da qui: per correzioni o prodotti nuovi contattate il nostro ufficio acquisti.</li>
      </ul>
    </details>
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
