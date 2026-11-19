import { useEffect, useMemo, useState } from 'react';
import type { CSSProperties, FormEvent } from 'react';
import { API_BASE } from '../api';

// Listino sempre aperto: il fornitore cambia i prezzi quando vuole, corregge il suo nome
// per un prodotto e propone prodotti nuovi. Il nostro nome (in grassetto) lo decidiamo noi.
// Ribasso: vale subito. Aumento: vale dalla prossima data fissa (1 o 15 del mese).

type Pending = { tipo: string; prezzo: string | null; decorrenza: string; sospesa: boolean };
type Item = {
  listino_id: number; descrizione: string; dicitura?: string | null; nome_in_attesa?: string | null;
  unita_in_attesa?: { unita_vendita: string; contenuto_quantita?: string | null; contenuto_unita?: string | null; prezzo: string } | null;
  marca?: string | null; formato: string; prezzo: string; importante: boolean; ordine?: number;
  siete_i_piu_convenienti: boolean | null; in_attesa: Pending | null;
};
type Proposed = { id: number; nome: string; unita_vendita: string; contenuto_quantita?: string | null; contenuto_unita?: string | null; prezzo: string };
// Prodotto della lista del settore che il fornitore non ha ancora nel nostro listino.
type Quote = {
  sku_interno: string; descrizione: string; unita_confronto?: string | null; importante: boolean; ordine: number;
  non_presente: boolean; in_attesa: { nome: string; unita_vendita: string; contenuto_quantita?: string | null; contenuto_unita?: string | null; prezzo: string } | null;
};
type Data = {
  fornitore: string; oggi: string; prossima_data_fissa: string; ultima_conferma: string | null;
  importanti: number; items: Item[]; prodotti_proposti?: Proposed[]; da_quotare?: Quote[];
};
// assente: spuntato «non lo abbiamo»; presente: tolto il segno messo in passato.
type QuoteDraft = { nome: string; unita_vendita: string; contenuto_quantita: string; contenuto_unita: string; prezzo: string; assente?: boolean; presente?: boolean };
// nome: undefined = non lo sta correggendo.
type UnitDraft = { unita_vendita: string; contenuto_quantita: string; contenuto_unita: string; prezzo: string };
// nome / unita: undefined = non li sta cambiando.
type Edit = { prezzo: string; non_trattato: boolean; nome?: string; unita?: UnitDraft };
type NewDraft = { key: string; nome: string; unita_vendita: string; contenuto_quantita: string; contenuto_unita: string; prezzo: string };
type Summary = { ribassi: number; aumenti: number; non_trattati: number; sospese: number; annullate: number; invariati: number; nomi?: number; nuovi?: number; unita?: number; quotati?: number; non_presenti?: number; di_nuovo_presenti?: number };

const UNITA: Record<string, string> = { KG: 'al kg', PZ: 'al pezzo', L: 'al litro', CT: 'a cartone', CASSA: 'a cassa' };
const CON_CONTENUTO = ['CT', 'CASSA'];

const euro = (value: string | number) => `€ ${Number(value).toLocaleString('it-IT', { minimumFractionDigits: 2, maximumFractionDigits: 4 })}`;
const day = (iso: string) => new Date(`${iso}T12:00:00`).toLocaleDateString('it-IT', { day: 'numeric', month: 'long' });
// Ultimo giorno del prezzo attuale: il giorno prima della prossima data fissa (calcolata dal server a ogni apertura).
const dayBefore = (iso: string) => {
  const d = new Date(`${iso}T12:00:00`);
  d.setDate(d.getDate() - 1);
  return d.toLocaleDateString('it-IT', { day: 'numeric', month: 'long' });
};
const parsePrice =(text: string) => Number(text.trim().replace(',', '.'));
const clean = (text?: string | null) => (text || '').replace(/\s+/g, ' ').trim();
const emptyNew = (): NewDraft => ({ key: `${Date.now()}-${Math.random()}`, nome: '', unita_vendita: '', contenuto_quantita: '', contenuto_unita: 'PZ', prezzo: '' });

const currentName = (item: Item) => item.nome_in_attesa ?? item.dicitura ?? '';
const priceChanged = (item: Item, edit?: Edit) => !!edit && (edit.non_trattato
  || (edit.prezzo.trim() !== '' && parsePrice(edit.prezzo) > 0 && parsePrice(edit.prezzo) !== Number(item.prezzo)));
const nameChanged = (item: Item, edit?: Edit) => !!edit && edit.nome !== undefined
  && clean(edit.nome).length >= 2 && clean(edit.nome).toLowerCase() !== clean(currentName(item)).toLowerCase();
const newFilled = (n: NewDraft) => !!(clean(n.nome) || n.unita_vendita || n.prezzo.trim() || n.contenuto_quantita.trim());
const unitFilled = (u?: UnitDraft) => !!u && !!(u.unita_vendita || u.prezzo.trim() || u.contenuto_quantita.trim());
const unitValid = (u?: UnitDraft) => !!u && !!UNITA[u.unita_vendita] && parsePrice(u.prezzo) > 0
  && (!CON_CONTENUTO.includes(u.unita_vendita) || parsePrice(u.contenuto_quantita) > 0);
const unitLabel = (unit: string, quantity?: string | null, contentUnit?: string | null) =>
  `${UNITA[unit] || unit}${quantity ? ` da ${Number(String(quantity).replace(',', '.')).toLocaleString('it-IT')} ${contentUnit === 'KG' ? 'kg' : 'pezzi'}` : ''}`;
const newValid = (n: { nome: string; unita_vendita: string; prezzo: string; contenuto_quantita: string }) =>
  clean(n.nome).length >= 2 && !!UNITA[n.unita_vendita] && parsePrice(n.prezzo) > 0
  && (!CON_CONTENUTO.includes(n.unita_vendita) || parsePrice(n.contenuto_quantita) > 0);
const quoteFilled = (q?: QuoteDraft) => !!q && !q.assente && !!(clean(q.nome) || q.unita_vendita || q.prezzo.trim() || q.contenuto_quantita.trim());
const emptyQuote = (): QuoteDraft => ({ nome: '', unita_vendita: '', contenuto_quantita: '', contenuto_unita: 'PZ', prezzo: '' });
const missingFields = (n: { nome: string; unita_vendita: string; prezzo: string; contenuto_quantita: string }) => [
  clean(n.nome).length < 2 && 'il vostro nome in fattura', !UNITA[n.unita_vendita] && 'come lo vendete',
  CON_CONTENUTO.includes(n.unita_vendita) && !(parsePrice(n.contenuto_quantita) > 0) && 'quanti dentro',
  !(parsePrice(n.prezzo) > 0) && 'prezzo',
].filter(Boolean).join(', ');

function errorText(detail: unknown, fallback: string) {
  if (typeof detail === 'string' && detail.trim()) return detail;
  if (Array.isArray(detail)) return detail.map(d => (d && typeof d === 'object' && 'msg' in d ? String(d.msg) : '')).filter(Boolean).join(' · ') || fallback;
  return fallback;
}

export default function SupplierOpenPriceList({ token }: { token: string }) {
  const [data, setData] = useState<Data | null>(null);
  const [edits, setEdits] = useState<Record<number, Edit>>({});
  const [nuovi, setNuovi] = useState<NewDraft[]>([]);
  const [quotes, setQuotes] = useState<Record<string, QuoteDraft>>({});
  const [search, setSearch] = useState('');
  const [loading, setLoading] = useState(true);
  const [sending, setSending] = useState(false);
  const [error, setError] = useState('');
  const [done, setDone] = useState<Summary | 'confermato' | null>(null);
  const [restored, setRestored] = useState(0);
  const base = `${API_BASE}/supplier-price-links/public/${encodeURIComponent(token)}`;
  const draftKey = `ps-open-price-draft:${token}`;

  // Quello che è scritto e non ancora inviato resta salvato su questo dispositivo.
  useEffect(() => {
    if (!data) return;
    try {
      const filled = Object.fromEntries(Object.entries(edits).filter(([, e]) => e.non_trattato || e.prezzo.trim() || e.nome !== undefined || e.unita !== undefined));
      const filledNew = nuovi.filter(newFilled);
      const filledQuotes = Object.fromEntries(Object.entries(quotes).filter(([, q]) => q.assente || q.presente || quoteFilled(q)));
      if (Object.keys(filled).length || filledNew.length || Object.keys(filledQuotes).length) {
        localStorage.setItem(draftKey, JSON.stringify({ edits: filled, nuovi: filledNew, quotes: filledQuotes }));
      } else localStorage.removeItem(draftKey);
    } catch { /* salvataggio non disponibile */ }
  }, [data, edits, nuovi, quotes, draftKey]);

  const clearDraft = () => { try { localStorage.removeItem(draftKey); } catch { /* niente */ } };

  useEffect(() => {
    let active = true;
    fetch(base)
      .then(async r => { const body = await r.json().catch(() => ({})); if (!r.ok) throw new Error(body.detail || 'Link non valido'); return body as Data; })
      .then(body => {
        if (!active) return;
        setData(body);
        try {
          const raw = JSON.parse(localStorage.getItem(draftKey) || '{}');
          const saved: Record<string, Edit> = raw && typeof raw === 'object' && 'edits' in raw ? raw.edits || {} : raw || {};
          const savedNew: NewDraft[] = Array.isArray(raw?.nuovi) ? raw.nuovi.filter((n: NewDraft) => n && typeof n.nome === 'string') : [];
          const ids = new Set(body.items.map(item => item.listino_id));
          const kept = Object.fromEntries(Object.entries(saved).filter(([id, e]) => ids.has(Number(id)) && e
            && (e.non_trattato || (typeof e.prezzo === 'string' && e.prezzo.trim()) || typeof e.nome === 'string' || (e.unita && typeof e.unita === 'object')))
            .map(([id, e]) => [id, { prezzo: typeof e.prezzo === 'string' ? e.prezzo : '', non_trattato: !!e.non_trattato, nome: e.nome, unita: e.unita }]));
          const skus = new Set((body.da_quotare || []).map(q => q.sku_interno));
          const savedQuotes: Record<string, QuoteDraft> = raw?.quotes && typeof raw.quotes === 'object'
            ? Object.fromEntries(Object.entries(raw.quotes as Record<string, QuoteDraft>).filter(([sku, q]) => skus.has(sku) && q && typeof q.nome === 'string'))
            : {};
          if (Object.keys(kept).length) setEdits(kept);
          if (savedNew.length) setNuovi(savedNew);
          if (Object.keys(savedQuotes).length) setQuotes(savedQuotes);
          setRestored(Object.keys(kept).length + savedNew.length + Object.keys(savedQuotes).length);
        } catch { /* nessuna bozza */ }
      })
      .catch(e => { if (active) setError(e.message || 'Impossibile caricare il listino'); })
      .finally(() => { if (active) setLoading(false); });
    return () => { active = false; };
  }, [base]);

  const changed = useMemo(() => (data?.items || []).filter(item =>
    priceChanged(item, edits[item.listino_id]) || nameChanged(item, edits[item.listino_id])
    || unitValid(edits[item.listino_id]?.unita)), [data, edits]);
  const incompleteUnits = (data?.items || []).filter(item => {
    const unit = edits[item.listino_id]?.unita;
    return unitFilled(unit) && !unitValid(unit);
  });
  const invalid = (data?.items || []).filter(item => {
    const edit = edits[item.listino_id];
    return edit && !edit.non_trattato && edit.prezzo.trim() !== '' && !(parsePrice(edit.prezzo) > 0);
  });
  const readyNew = nuovi.filter(newValid);
  const incompleteNew = nuovi.filter(n => newFilled(n) && !newValid(n));
  const quoteList = data?.da_quotare || [];
  const readyQuotes = quoteList.filter(q => { const d = quotes[q.sku_interno]; return !!d && !d.assente && newValid(d); });
  const incompleteQuotes = quoteList.filter(q => { const d = quotes[q.sku_interno]; return quoteFilled(d) && !newValid(d!); });
  const newAbsent = quoteList.filter(q => quotes[q.sku_interno]?.assente && !q.non_presente);
  // «Non lo abbiamo» si toglie solo scrivendo il prezzo.
  const backPresent = readyQuotes.filter(q => q.non_presente);
  const toSend = changed.length + readyNew.length + readyQuotes.length + newAbsent.length;
  // Tra i più acquistati: quelli che non hanno ancora né un prezzo né «non lo abbiamo».
  const topUnanswered = quoteList.filter(q => q.importante && !q.non_presente && !q.in_attesa
    && !quotes[q.sku_interno]?.assente && !readyQuotes.includes(q));
  const setQuote = (sku: string, change: Partial<QuoteDraft>) =>
    setQuotes(prev => ({ ...prev, [sku]: { ...(prev[sku] || emptyQuote()), ...change } }));

  const setEdit = (id: number, change: Partial<Edit>) =>
    setEdits(prev => ({ ...prev, [id]: { ...(prev[id] || { prezzo: '', non_trattato: false }), ...change } }));
  const setNew = (key: string, change: Partial<NewDraft>) => setNuovi(prev => prev.map(n => (n.key === key ? { ...n, ...change } : n)));

  const send = async (event: FormEvent) => {
    event.preventDefault();
    if (!toSend || invalid.length || incompleteNew.length || incompleteUnits.length || incompleteQuotes.length) return;
    setSending(true); setError('');
    try {
      const modifiche = changed.map(item => {
        const edit = edits[item.listino_id];
        const row: Record<string, unknown> = { listino_id: item.listino_id };
        if (priceChanged(item, edit)) {
          if (edit.non_trattato) row.non_trattato = true;
          else row.prezzo = String(parsePrice(edit.prezzo));
        }
        if (nameChanged(item, edit)) row.nome_fornitore = clean(edit.nome);
        if (unitValid(edit.unita) && edit.unita) {
          const u = edit.unita;
          delete row.prezzo; delete row.non_trattato;
          row.unita = { unita_vendita: u.unita_vendita, prezzo: String(parsePrice(u.prezzo)),
            ...(CON_CONTENUTO.includes(u.unita_vendita) ? { contenuto_quantita: String(parsePrice(u.contenuto_quantita)), contenuto_unita: u.contenuto_unita } : {}) };
        }
        return row;
      });
      const nuoviPayload = readyNew.map(n => ({
        nome: clean(n.nome), unita_vendita: n.unita_vendita, prezzo: String(parsePrice(n.prezzo)),
        ...(CON_CONTENUTO.includes(n.unita_vendita) ? { contenuto_quantita: String(parsePrice(n.contenuto_quantita)), contenuto_unita: n.contenuto_unita } : {}),
      }));
      const response = await fetch(`${base}/submit`, {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          modifiche, nuovi: nuoviPayload,
          quotazioni: readyQuotes.map(q => {
            const d = quotes[q.sku_interno];
            return { sku_interno: q.sku_interno, nome: clean(d.nome), unita_vendita: d.unita_vendita, prezzo: String(parsePrice(d.prezzo)),
              ...(CON_CONTENUTO.includes(d.unita_vendita) ? { contenuto_quantita: String(parsePrice(d.contenuto_quantita)), contenuto_unita: d.contenuto_unita } : {}) };
          }),
          assenti: newAbsent.map(q => q.sku_interno),
          presenti: backPresent.map(q => q.sku_interno),
        }),
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
      if (!toSend) clearDraft();
      setDone('confermato');
    } catch (e) { setError(e instanceof Error ? e.message : 'Conferma non riuscita'); }
    finally { setSending(false); }
  };

  const wrap: CSSProperties = { minHeight: '100vh', padding: '24px 14px', boxSizing: 'border-box', background: 'var(--bg-app)', color: 'var(--text-primary)', fontFamily: 'var(--font-family)' };
  const box: CSSProperties = { maxWidth: 900, margin: '0 auto', padding: 20, border: '1px solid var(--line)', borderRadius: 'var(--radius-lg)', background: 'var(--bg-card)' };
  const input: CSSProperties = { width: '100%', boxSizing: 'border-box', padding: 10, borderRadius: 'var(--radius-sm)', border: '1px solid var(--line)', background: 'var(--bg-inset)', color: 'var(--text-primary)' };
  const panel: CSSProperties = { padding: 12, border: '1px solid var(--line)', borderRadius: 'var(--radius-md)', background: 'var(--bg-inset)' };
  const note: CSSProperties = { padding: 12, border: '1px solid var(--warn-border)', borderRadius: 'var(--radius-md)', background: 'var(--warn-bg)' };
  const linkButton: CSSProperties = { background: 'none', border: 'none', padding: 0, marginLeft: 6, color: 'var(--accent, #2563eb)', textDecoration: 'underline', cursor: 'pointer', font: 'inherit' };

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
          {done.non_trattati > 0 && <li>{done.non_trattati} prodotti non più trattati: il prezzo resta valido fino al {dayBefore(data.prossima_data_fissa)} compreso.</li>}
          {done.annullate > 0 && <li>{done.annullate} modifiche in attesa annullate (prezzo riportato a quello attuale).</li>}
          {done.sospese > 0 && <li>{done.sospese} variazioni molto forti saranno verificate dal nostro ufficio acquisti prima di diventare valide.</li>}
          {!!done.nomi && <li>{done.nomi} {done.nomi === 1 ? 'nome corretto' : 'nomi corretti'}: li controlla il nostro ufficio acquisti.</li>}
          {!!done.unita && <li>{done.unita} {done.unita === 1 ? 'cambio di unità' : 'cambi di unità'}: li controlla il nostro ufficio acquisti; fino al via libera resta il prezzo attuale.</li>}
          {!!done.quotati && <li>{done.quotati} {done.quotati === 1 ? 'prezzo per un prodotto della nostra lista' : 'prezzi per prodotti della nostra lista'}: li controlla il nostro ufficio acquisti prima di metterli in listino.</li>}
          {!!done.non_presenti && <li>{done.non_presenti} {done.non_presenti === 1 ? 'prodotto segnato' : 'prodotti segnati'} «non lo abbiamo». Se in futuro li avrete, tornate sul link e scrivete il prezzo.</li>}
          {!!done.di_nuovo_presenti && <li>{done.di_nuovo_presenti} {done.di_nuovo_presenti === 1 ? 'prodotto tolto' : 'prodotti tolti'} da «non lo abbiamo».</li>}
          {!!done.nuovi && <li>{done.nuovi} {done.nuovi === 1 ? 'prodotto nuovo proposto' : 'prodotti nuovi proposti'}: li controlla il nostro ufficio acquisti prima di metterli in listino.</li>}
        </ul>
      </>}
      <p>Potete tornare su questo link quando volete per aggiornare i prezzi.</p>
    </div></main>;
  }

  const query = search.trim().toLowerCase();
  type Entry = { key: string; importante: boolean; ordine: number; item?: Item; quote?: Quote };
  const entries: Entry[] = [
    ...data.items.map(item => ({ key: `l${item.listino_id}`, importante: item.importante, ordine: item.ordine ?? 0, item })),
    ...quoteList.map(quote => ({ key: `q${quote.sku_interno}`, importante: quote.importante, ordine: quote.ordine, quote })),
  ].sort((a, b) => a.ordine - b.ordine);
  const visible = entries.filter(e => !query || (e.item
    ? `${e.item.descrizione} ${e.item.dicitura || ''} ${e.item.nome_in_attesa || ''} ${e.item.marca || ''}`
    : `${e.quote!.descrizione} ${quotes[e.quote!.sku_interno]?.nome || ''}`).toLowerCase().includes(query));
  const total = entries.length;
  const topCount = entries.filter(e => e.importante).length;
  const groups = [
    { top: true, title: `★ I ${topCount} prodotti che acquistiamo di più`, subtitle: 'Fermatevi su questi: per ognuno confermate o scrivete il prezzo, oppure spuntate «Non lo abbiamo». Sono la base del nostro confronto.', items: visible.filter(e => e.importante) },
    { top: false, title: topCount ? `Tutti gli altri prodotti (${total - topCount})` : `Tutti i prodotti (${total})`, subtitle: topCount ? 'Li acquistiamo meno spesso: completateli quando avete tempo.' : 'Controllate i prezzi e cambiate solo quelli diversi.', items: visible.filter(e => !e.importante) },
  ].filter(group => group.items.length);
  const fixedDay = day(data.prossima_data_fissa);
  const lastDay = dayBefore(data.prossima_data_fissa);
  const proposed = data.prodotti_proposti || [];

  const hint = (item: Item) => {
    const edit = edits[item.listino_id];
    if (!edit) return null;
    if (edit.non_trattato) return `Il prezzo resta valido fino al ${lastDay} compreso; dal ${fixedDay} il prodotto esce dal listino.`;
    const value = parsePrice(edit.prezzo), old = Number(item.prezzo);
    if (!(value > 0) || value === old) return null;
    const change = (value - old) / old;
    if (change < 0) return change < -0.4 ? 'Ribasso molto forte: lo verifichiamo prima di applicarlo.' : 'Ribasso: vale da subito.';
    return change > 0.3
      ? `Aumento oltre il 30%: lo verifichiamo prima; in ogni caso non prima del ${fixedDay}.`
      : `Aumento: vale dal ${fixedDay}.`;
  };

  const renderQuote = (quote: Quote) => {
    const d = quotes[quote.sku_interno];
    const absent = d?.assente || (quote.non_presente && !d?.presente);
    const needsContent = !!d && CON_CONTENUTO.includes(d.unita_vendita);
    return <div key={`q${quote.sku_interno}`} style={{ padding: '12px 0', borderTop: '1px solid var(--line)' }}>
      <strong>{quote.descrizione}</strong>
      <div><small style={{ color: 'var(--warn-text, #b45309)' }}>Non è ancora nel vostro listino con noi{quote.unita_confronto ? ` · lo confrontiamo ${UNITA[quote.unita_confronto.toUpperCase()] || `per ${quote.unita_confronto}`}` : ''}</small></div>
      {quote.in_attesa && !d && <div><small>
        Già inviato: <em>{quote.in_attesa.nome}</em> · {euro(quote.in_attesa.prezzo)} {unitLabel(quote.in_attesa.unita_vendita, quote.in_attesa.contenuto_quantita, quote.in_attesa.contenuto_unita)} (in verifica)
        <button type="button" style={linkButton} onClick={() => setQuote(quote.sku_interno, {
          nome: quote.in_attesa!.nome, unita_vendita: quote.in_attesa!.unita_vendita, prezzo: quote.in_attesa!.prezzo,
          contenuto_quantita: quote.in_attesa!.contenuto_quantita || '', contenuto_unita: quote.in_attesa!.contenuto_unita || 'PZ' })}>Modifica</button>
      </small></div>}
      {absent ? <div style={{ display: 'flex', gap: 8, alignItems: 'center', flexWrap: 'wrap', marginTop: 6 }}>
        <small><strong>Segnato: non lo abbiamo</strong>{quote.non_presente && !d?.assente ? ' (resta così finché non lo togliete)' : ''}</small>
        <button type="button" className="btn-secondary" onClick={() => setQuote(quote.sku_interno, { assente: false, presente: true })}>Ora lo abbiamo: scrivo il prezzo</button>
      </div> : (d || !quote.in_attesa) && <div style={{ display: 'grid', gap: 6, marginTop: 6 }}>
        <input style={input} placeholder="Come lo chiamate voi in fattura" maxLength={255} aria-label={`Il vostro nome in fattura per ${quote.descrizione}`}
          value={d?.nome || ''} onChange={e => setQuote(quote.sku_interno, { nome: e.target.value })} />
        <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap' }}>
          <select style={{ ...input, flex: '1 1 140px', width: 'auto' }} value={d?.unita_vendita || ''} onChange={e => setQuote(quote.sku_interno, { unita_vendita: e.target.value })}>
            <option value="">Come lo vendete?</option>
            {Object.entries(UNITA).map(([value, label]) => <option key={value} value={value}>{label}</option>)}
          </select>
          {needsContent && <>
            <input style={{ ...input, flex: '1 1 100px', width: 'auto' }} inputMode="decimal" placeholder="Quanti dentro?"
              value={d?.contenuto_quantita || ''} onChange={e => setQuote(quote.sku_interno, { contenuto_quantita: e.target.value })} />
            <select style={{ ...input, flex: '0 1 90px', width: 'auto' }} value={d?.contenuto_unita || 'PZ'} onChange={e => setQuote(quote.sku_interno, { contenuto_unita: e.target.value })}>
              <option value="PZ">pezzi</option>
              <option value="KG">kg</option>
            </select>
          </>}
          <input style={{ ...input, flex: '1 1 130px', width: 'auto' }} inputMode="decimal"
            placeholder={d?.unita_vendita ? `Prezzo ${UNITA[d.unita_vendita]}` : 'Prezzo'} aria-label={`Prezzo per ${quote.descrizione}`}
            value={d?.prezzo || ''} onChange={e => setQuote(quote.sku_interno, { prezzo: e.target.value })} />
        </div>
        <label style={{ display: 'flex', gap: 6 }}>
          <input type="checkbox" checked={false}
            onChange={() => setQuote(quote.sku_interno, { ...emptyQuote(), assente: true, presente: false })} />
          <small>Non lo abbiamo</small>
        </label>
        {quoteFilled(d) && !newValid(d!) && <small style={{ color: 'var(--danger, #b91c1c)' }}>Mancano: {missingFields(d!)}</small>}
        {d?.presente && quote.non_presente && <small>Senza prezzo resta segnato «non lo abbiamo».
          <button type="button" style={linkButton} onClick={() => setQuote(quote.sku_interno, { ...emptyQuote(), presente: false })}>Lascia «non lo abbiamo»</button></small>}
      </div>}
    </div>;
  };

  return <main style={wrap}><form style={box} onSubmit={send}>
    <h1 style={{ margin: '0 0 4px' }}>Listino prezzi · {data.fornitore}</h1>
    <p style={{ margin: '0 0 16px', color: 'var(--text-secondary)' }}>
      {total} prodotti{quoteList.length ? `, di cui ${quoteList.length} non ancora nel vostro listino` : ''} · link personale, sempre lo stesso, non scade
    </p>

    <div style={{ ...panel, marginBottom: 12 }}>
      <strong>Come si fa</strong>
      <ol style={{ margin: '6px 0 0', paddingLeft: 20, lineHeight: 1.6 }}>
        <li><strong>Partite dai prodotti in cima, nel riquadro ★</strong>: sono quelli che acquistiamo di più e su cui vi confrontiamo per primi.</li>
        <li><strong>Prodotto già nel vostro listino?</strong> Se il prezzo è uguale non fate nulla; se è cambiato scrivetelo in quella riga (es. 2,35).</li>
        <li><strong>Prodotto «non ancora nel vostro listino»?</strong> Se lo avete scrivete come lo chiamate in fattura, come lo vendete e il prezzo. Se non lo avete spuntate «Non lo abbiamo»: resta segnato, e se un giorno lo avrete premete «Ora lo abbiamo» e scrivete il prezzo.</li>
        <li><strong>Un prodotto non lo avete più?</strong> Spuntate «Non lo tratto più».</li>
        <li><strong>Il nome con cui lo scrivete in fattura è diverso?</strong> Premete «Correggi» accanto a «Come lo chiamate voi in fattura»: ci serve per riconoscere le vostre fatture.</li>
        <li><strong>Ci vendete un prodotto che qui non c'è?</strong> In fondo alla pagina premete «Aggiungi un prodotto».</li>
        <li>Alla fine premete <strong>«Invia modifiche»</strong> in fondo alla pagina.</li>
      </ol>
    </div>

    <div style={{ ...note, marginBottom: 12 }}>
      <strong>Quando valgono i nuovi prezzi</strong>
      <div style={{ display: 'grid', gridTemplateColumns: 'max-content 1fr', gap: '4px 12px', marginTop: 6, lineHeight: 1.5 }}>
        <span>⬇ Ribasso</span><span>da subito</span>
        <span>⬆ Aumento</span><span>dal <strong>{fixedDay}</strong> (si cambia solo il 1° e il 15 del mese); fino ad allora vale il prezzo attuale</span>
        <span>✕ Non più trattato</span><span>il prezzo resta valido fino al {lastDay} compreso, poi il prodotto esce dal listino</span>
      </div>
    </div>

    <div style={{ ...panel, marginBottom: 12 }}>
      <strong>Come indicare l'unità di misura</strong>
      <ul style={{ margin: '6px 0 0', paddingLeft: 20, lineHeight: 1.6 }}>
        <li>Usate <strong>la stessa unità che scrivete in fattura</strong>: se fatturate a kg, il prezzo è al kg.</li>
        <li>Se vendete <strong>a cassa o a cartone</strong>, indicate cosa c'è dentro: così confrontiamo il prezzo al kg o al pezzo.</li>
        <li>L'unità indicata per un prodotto è sbagliata? Premete <strong>«Cambia unità»</strong> sotto il prezzo e scrivete il prezzo nella nuova unità.</li>
      </ul>
      <div style={{ display: 'grid', gridTemplateColumns: 'max-content 1fr', gap: '2px 12px', marginTop: 8, lineHeight: 1.5 }}>
        <span>Zucchine</span><span>al kg · 1,80</span>
        <span>Meloni</span><span>al pezzo · 2,50 &nbsp;oppure&nbsp; a cassa da 6 pezzi · 15,00</span>
        <span>Fragole</span><span>a cartone da 8 pezzi (vaschette) · 16,00</span>
        <span>Patate</span><span>sacco da 10 kg: scegliete «a cassa», 10 kg · 9,00</span>
      </div>
      <small style={{ display: 'block', marginTop: 6 }}>Se l'unità in fattura è diversa da quella del listino non riusciamo a controllare i prezzi e dovremo contattarvi.</small>
    </div>

    <div style={{ ...panel, marginBottom: 12 }}>
      <strong>Potete fermarvi e riprendere dopo</strong>
      <div style={{ marginTop: 4, lineHeight: 1.5 }}>
        Quello che scrivete resta salvato su questo telefono o computer anche se chiudete la pagina: riaprite il link e lo ritrovate.
        Diventa valido solo quando premete «Invia modifiche». Potete anche inviare una parte adesso e il resto un'altra volta.
      </div>
    </div>

    {restored > 0 && <p style={{ ...note, margin: '0 0 12px' }}>
      Avete ancora <strong>{restored} {restored === 1 ? 'modifica scritta e non inviata' : 'modifiche scritte e non inviate'}</strong> dall'ultima volta: le trovate già al loro posto.
      Controllatele e premete «Invia modifiche».
    </p>}

    {topCount > 0 && <p style={{ margin: '0 0 12px' }}>
      In cima trovate i <strong>{topCount} prodotti che acquistiamo di più</strong>: è la stessa lista per tutti i fornitori del vostro settore. Completate prima quelli, poi scorrendo trovate tutti gli altri.
      {topUnanswered.length > 0 && <> Tra questi, <strong>{topUnanswered.length}</strong> {topUnanswered.length === 1 ? 'aspetta' : 'aspettano'} ancora un prezzo o «Non lo abbiamo».</>}
    </p>}

    <details style={{ marginBottom: 16 }}>
      <summary style={{ cursor: 'pointer' }}>Altre informazioni</summary>
      <ul style={{ margin: '6px 0 0', paddingLeft: 20, lineHeight: 1.5 }}>
        <li>Ogni prezzo si riferisce all'unità indicata accanto (kg, pezzo, cartone…).</li>
        <li>Ribassi oltre il 40% e aumenti oltre il 30% vengono controllati dal nostro ufficio acquisti prima di entrare in listino.</li>
        <li>Avete sbagliato un prezzo già inviato? Rientrate dal link e correggetelo: vale l'ultimo inviato.</li>
        <li>Accanto ad alcuni prodotti vedete se oggi siete il fornitore più conveniente; i prezzi degli altri non vengono mai mostrati.</li>
        <li>Il nome in grassetto è il nostro e lo scegliamo noi. Voi potete correggere il vostro nome del prodotto: lo controlla il nostro ufficio acquisti.</li>
      </ul>
    </details>

    <p style={{ display: 'flex', gap: 12, flexWrap: 'wrap', alignItems: 'center' }}>
      <button type="button" className="btn-secondary" disabled={sending} onClick={confirmAll}>Confermo tutti i prezzi invariati</button>
      {data.ultima_conferma && <small>Ultimo aggiornamento: {new Date(data.ultima_conferma).toLocaleDateString('it-IT')}</small>}
    </p>
    <input style={{ ...input, marginBottom: 16 }} placeholder="Cerca un prodotto" value={search} onChange={e => setSearch(e.target.value)} />

    {groups.map(group => <section key={group.title} style={{
      margin: '0 0 20px', padding: '0 12px 4px', borderRadius: 'var(--radius-md)',
      border: group.top ? '2px solid var(--accent, #2563eb)' : '1px solid var(--line)',
      background: group.top ? 'var(--accent-bg, rgba(37, 99, 235, 0.06))' : 'transparent',
    }}>
      <h2 style={{ fontSize: '1.1rem', margin: 0, padding: '12px 0 4px' }}>{group.title}</h2>
      <small style={{ display: 'block', paddingBottom: 8 }}>{group.subtitle}</small>
      {group.items.map(entry => {
        if (entry.quote) return renderQuote(entry.quote);
        const item = entry.item!;
        const edit = edits[item.listino_id];
        const message = hint(item);
        const editingName = edit?.nome !== undefined;
        return <div key={item.listino_id} style={{ padding: '12px 0', borderTop: '1px solid var(--line)' }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', gap: 12, flexWrap: 'wrap' }}>
            <div style={{ flex: '1 1 260px' }}>
              <strong>{item.descrizione}</strong>
              <div><small>
                Come lo chiamate voi in fattura: <em>{currentName(item) || 'non indicato'}</em>
                {item.nome_in_attesa && ' (in verifica)'}
                {item.marca && ` · ${item.marca}`}
                {!editingName && <button type="button" style={linkButton} onClick={() => setEdit(item.listino_id, { nome: currentName(item) })}>Correggi</button>}
              </small></div>
              {editingName && <div style={{ display: 'flex', gap: 6, marginTop: 6 }}>
                <input style={input} placeholder="Il vostro nome per questo prodotto" maxLength={255}
                  aria-label={`Il vostro nome per ${item.descrizione}`}
                  value={edit?.nome || ''} onChange={e => setEdit(item.listino_id, { nome: e.target.value })} />
                <button type="button" className="btn-secondary" onClick={() => setEdit(item.listino_id, { nome: undefined })}>Annulla</button>
              </div>}
              <div><small>Prezzo attuale: <strong>{euro(item.prezzo)}</strong> per {item.formato}
                {!edit?.unita && <button type="button" style={linkButton}
                  onClick={() => setEdit(item.listino_id, { unita: { unita_vendita: '', contenuto_quantita: '', contenuto_unita: 'PZ', prezzo: '' }, prezzo: '', non_trattato: false })}>Cambia unità</button>}
              </small></div>
              {item.unita_in_attesa && !edit?.unita && <div><small>
                Nuova unità già inviata: {euro(item.unita_in_attesa.prezzo)} {unitLabel(item.unita_in_attesa.unita_vendita, item.unita_in_attesa.contenuto_quantita, item.unita_in_attesa.contenuto_unita)} (in verifica)
              </small></div>}
              {edit?.unita && (() => {
                const u = edit.unita;
                const needsContent = CON_CONTENUTO.includes(u.unita_vendita);
                const setUnit = (change: Partial<UnitDraft>) => setEdit(item.listino_id, { unita: { ...u, ...change } });
                return <div style={{ ...panel, marginTop: 6, display: 'grid', gap: 6 }}>
                  <small><strong>Nuova unità</strong> · fino al via libera del nostro ufficio resta il prezzo attuale</small>
                  <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap' }}>
                    <select style={{ ...input, flex: '1 1 140px', width: 'auto' }} value={u.unita_vendita} onChange={e => setUnit({ unita_vendita: e.target.value })}>
                      <option value="">Come lo vendete?</option>
                      {Object.entries(UNITA).map(([value, label]) => <option key={value} value={value}>{label}</option>)}
                    </select>
                    {needsContent && <>
                      <input style={{ ...input, flex: '1 1 100px', width: 'auto' }} inputMode="decimal" placeholder="Quanti dentro?"
                        value={u.contenuto_quantita} onChange={e => setUnit({ contenuto_quantita: e.target.value })} />
                      <select style={{ ...input, flex: '0 1 90px', width: 'auto' }} value={u.contenuto_unita} onChange={e => setUnit({ contenuto_unita: e.target.value })}>
                        <option value="PZ">pezzi</option>
                        <option value="KG">kg</option>
                      </select>
                    </>}
                    <input style={{ ...input, flex: '1 1 130px', width: 'auto' }} inputMode="decimal"
                      placeholder={u.unita_vendita ? `Prezzo ${UNITA[u.unita_vendita]}` : 'Prezzo'}
                      value={u.prezzo} onChange={e => setUnit({ prezzo: e.target.value })} />
                    <button type="button" className="btn-secondary" onClick={() => setEdit(item.listino_id, { unita: undefined })}>Annulla</button>
                  </div>
                  {unitFilled(u) && !unitValid(u) && <small style={{ color: 'var(--danger, #b91c1c)' }}>
                    Mancano: {[!UNITA[u.unita_vendita] && 'come lo vendete', needsContent && !(parsePrice(u.contenuto_quantita) > 0) && 'quanti dentro', !(parsePrice(u.prezzo) > 0) && 'prezzo'].filter(Boolean).join(', ')}
                  </small>}
                </div>;
              })()}
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
              <input style={input} inputMode="decimal" placeholder={edit?.unita ? 'Prezzo nella nuova unità, a sinistra' : 'Nuovo prezzo'} disabled={edit?.non_trattato || !!edit?.unita}
                aria-label={`Nuovo prezzo per ${item.descrizione}`}
                value={edit?.prezzo || ''} onChange={e => setEdit(item.listino_id, { prezzo: e.target.value })} />
              <label style={{ display: 'flex', gap: 6, marginTop: 6 }}>
                <input type="checkbox" checked={!!edit?.non_trattato} disabled={!!edit?.unita}
                  onChange={e => setEdit(item.listino_id, { non_trattato: e.target.checked, prezzo: '' })} />
                <small>Non lo tratto più</small>
              </label>
            </div>
          </div>
          {message && <small style={{ display: 'block', marginTop: 6, fontWeight: 600 }}>{message}</small>}
          {nameChanged(item, edit) && <small style={{ display: 'block', marginTop: 4 }}>Il nuovo nome lo controlla il nostro ufficio acquisti.</small>}
        </div>;
      })}
    </section>)}

    <section style={{ ...panel, marginTop: 16 }}>
      <h2 style={{ fontSize: '1.1rem', marginTop: 0 }}>Prodotti che ci vendete e qui non ci sono</h2>
      <small>Bastano nome, come lo vendete e prezzo. Il nome nel nostro listino lo sceglie il nostro ufficio acquisti.</small>
      {proposed.length > 0 && <div style={{ marginTop: 8 }}>
        <small><strong>Già proposti, in verifica:</strong></small>
        <ul style={{ margin: '4px 0 0', paddingLeft: 20 }}>
          {proposed.map(p => <li key={p.id}><small>
            {p.nome} · {euro(p.prezzo)} {UNITA[p.unita_vendita] || ''}
            {p.contenuto_quantita && ` (${Number(p.contenuto_quantita).toLocaleString('it-IT')} ${p.contenuto_unita === 'KG' ? 'kg' : 'pezzi'})`}
          </small></li>)}
        </ul>
      </div>}
      {nuovi.map(n => {
        const needsContent = CON_CONTENUTO.includes(n.unita_vendita);
        const incomplete = newFilled(n) && !newValid(n);
        return <div key={n.key} style={{ display: 'grid', gap: 8, padding: '12px 0', borderTop: '1px solid var(--line)', marginTop: 8 }}>
          <input style={input} placeholder="Nome del prodotto, come lo scrivete in fattura" maxLength={255}
            value={n.nome} onChange={e => setNew(n.key, { nome: e.target.value })} />
          <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
            <select style={{ ...input, flex: '1 1 160px', width: 'auto' }} value={n.unita_vendita} onChange={e => setNew(n.key, { unita_vendita: e.target.value })}>
              <option value="">Come lo vendete?</option>
              {Object.entries(UNITA).map(([value, label]) => <option key={value} value={value}>{label}</option>)}
            </select>
            {needsContent && <>
              <input style={{ ...input, flex: '1 1 110px', width: 'auto' }} inputMode="decimal" placeholder="Quanti dentro?"
                value={n.contenuto_quantita} onChange={e => setNew(n.key, { contenuto_quantita: e.target.value })} />
              <select style={{ ...input, flex: '0 1 100px', width: 'auto' }} value={n.contenuto_unita} onChange={e => setNew(n.key, { contenuto_unita: e.target.value })}>
                <option value="PZ">pezzi</option>
                <option value="KG">kg</option>
              </select>
            </>}
            <input style={{ ...input, flex: '1 1 140px', width: 'auto' }} inputMode="decimal"
              placeholder={n.unita_vendita ? `Prezzo ${UNITA[n.unita_vendita]}` : 'Prezzo'}
              value={n.prezzo} onChange={e => setNew(n.key, { prezzo: e.target.value })} />
            <button type="button" className="btn-secondary" onClick={() => setNuovi(prev => prev.filter(x => x.key !== n.key))}>Togli</button>
          </div>
          {incomplete && <small style={{ color: 'var(--danger, #b91c1c)' }}>
            Mancano: {[clean(n.nome).length < 2 && 'nome', !UNITA[n.unita_vendita] && 'come lo vendete', needsContent && !(parsePrice(n.contenuto_quantita) > 0) && 'quanti dentro', !(parsePrice(n.prezzo) > 0) && 'prezzo'].filter(Boolean).join(', ')}
          </small>}
        </div>;
      })}
      <button type="button" className="btn-secondary" style={{ marginTop: 10 }} onClick={() => setNuovi(prev => [...prev, emptyNew()])}>+ Aggiungi un prodotto</button>
    </section>

    {error && <p style={{ color: 'var(--danger, #b91c1c)' }}>{error}</p>}
    {invalid.length > 0 && <p style={{ color: 'var(--danger, #b91c1c)' }}>Controlla i prezzi di: {invalid.map(i => i.descrizione).join(', ')}</p>}
    <div style={{ position: 'sticky', bottom: 0, padding: '12px 0', background: 'var(--bg-card)' }}>
      <button type="submit" className="btn-primary" disabled={sending || !toSend || invalid.length > 0 || incompleteNew.length > 0 || incompleteUnits.length > 0 || incompleteQuotes.length > 0}>
        {sending ? 'Invio…' : toSend ? `Invia ${toSend} ${toSend === 1 ? 'modifica' : 'modifiche'}` : 'Nessuna modifica da inviare'}
      </button>
      {incompleteNew.length > 0 && <small style={{ marginLeft: 8 }}>Completate o togliete i prodotti nuovi incompleti.</small>}
      {incompleteQuotes.length > 0 && <small style={{ marginLeft: 8 }}>Completate i prodotti iniziati: {incompleteQuotes.map(q => q.descrizione).join(', ')}.</small>}
      {incompleteUnits.length > 0 && <small style={{ marginLeft: 8 }}>Completate o annullate il cambio di unità di: {incompleteUnits.map(i => i.descrizione).join(', ')}.</small>}
    </div>
  </form></main>;
}
