import { useEffect, useState } from 'react';
import type { CSSProperties, FormEvent } from 'react';
import { API_BASE } from '../api';
import { normalizeSupplierUnit, SUPPLIER_UNIT_OPTIONS } from '../constants/units';

type PublicItem = { id: number; sku_interno: string; descrizione: string; prezzo_corrente?: string | null; unita_corrente?: string | null; quantita_corrente?: string | null; dicitura_corrente?: string | null; brand_corrente?: string | null; validita_corrente_da?: string | null; validita_corrente_a?: string | null; istruzioni?: string | null };
type FormData = { supplier_name: string; requires_supplier_details?: boolean; request_type: 'confirmation' | 'new_listino'; expires_at: string; note?: string | null; items: PublicItem[] };
type ExtraOffer = { key: string; prezzo: string; unita_misura: string; marca: string; dicitura_fornitore: string; quantita_confezione: string; nota: string };
type Answer = { prezzo: string; unita_misura: string; marca: string; dicitura_fornitore: string; quantita_confezione: string; conferma_prezzo: boolean; non_trattato: boolean; nota: string; extraOffers: ExtraOffer[] };

// "€ 3,00 per 0,25 KG" or "€ 1,00 / KG" for the agreed offer format.
const formatLabel = (quantita: string | null | undefined, unita: string) => {
  const q = Number(quantita);
  return quantita && q > 0 && q !== 1 ? ` per ${q.toLocaleString('it-IT')} ${unita}` : ` / ${unita}`;
};

// Live check of what the supplier is actually declaring, e.g. "2 KG a € 2,00 = € 1,00 al KG".
function UnitPriceHint({ prezzo, quantita, unita }: { prezzo: string; quantita: string; unita: string }) {
  const p = Number(prezzo), q = Number(quantita);
  if (!unita || !(p > 0) || !(q > 0)) return null;
  const fmt = (n: number) => n.toLocaleString('it-IT', { minimumFractionDigits: 2, maximumFractionDigits: 4 });
  return <small style={{ display: 'block', color: 'var(--text-primary)', fontWeight: 600 }}>
    {q === 1 ? `= € ${fmt(p)} per 1 ${unita}` : `${fmt(q)} ${unita} a € ${fmt(p)} = € ${fmt(p / q)} per 1 ${unita}`}
  </small>;
}

function apiErrorMessage(detail: unknown, fallback: string): string {
  if (typeof detail === 'string' && detail.trim()) return detail;
  if (Array.isArray(detail)) {
    const messages = detail
      .map(item => item && typeof item === 'object' && 'msg' in item ? String(item.msg) : '')
      .filter(Boolean);
    if (messages.length) return messages.join(' · ');
  }
  return fallback;
}

export default function SupplierPricePublicForm({ token }: { token: string }) {
  const [data, setData] = useState<FormData | null>(null);
  const [answers, setAnswers] = useState<Record<number, Answer>>({});
  const [validitaDa, setValiditaDa] = useState('');
  const [validitaA, setValiditaA] = useState('');
  const [anagrafica, setAnagrafica] = useState({ ragione_sociale: '', partita_iva: '', telefono_ordini: '' });
  const [loading, setLoading] = useState(true);
  const [sending, setSending] = useState(false);
  const [error, setError] = useState('');
  const [done, setDone] = useState(false);
  const [draftNotice, setDraftNotice] = useState('');
  const draftKey = `ps.supplier-price-draft.${token}`;

  useEffect(() => {
    let active = true;
    fetch(`${API_BASE}/supplier-price-forms/public/${encodeURIComponent(token)}`)
      .then(async r => { const body = await r.json().catch(() => ({})); if (!r.ok) throw new Error(body.detail || 'Link non valido o scaduto'); return body as FormData; })
      .then(form => {
        if (!active) return;
        setData(form);
        const initial = Object.fromEntries(form.items.map(i => [i.id, { prezzo: i.prezzo_corrente || '', unita_misura: normalizeSupplierUnit(i.unita_corrente), marca: i.brand_corrente || '', dicitura_fornitore: i.dicitura_corrente || '', quantita_confezione: i.quantita_corrente ? String(Number(i.quantita_corrente)) : '', conferma_prezzo: false, non_trattato: false, nota: '', extraOffers: [] }]));
        try {
          const saved = JSON.parse(localStorage.getItem(draftKey) || 'null');
          setAnswers(saved?.answers && form.items.every(i => saved.answers[i.id]) ? Object.fromEntries(form.items.map(i => [i.id, { ...initial[i.id], ...saved.answers[i.id], extraOffers: saved.answers[i.id].extraOffers || [] }])) : initial);
          if (saved?.answers) { setValiditaDa(saved.validitaDa || ''); setValiditaA(saved.validitaA || ''); setDraftNotice('Bozza recuperata da questo browser.'); }
        } catch { setAnswers(initial); }
      })
      .catch(e => { if (active) setError(e.message || 'Impossibile caricare il modulo'); })
      .finally(() => { if (active) setLoading(false); });
    return () => { active = false; };
  }, [token, draftKey]);

  const setAnswer = (id: number, change: Partial<Answer>) => setAnswers(prev => {
    const old = prev[id]; const next = { ...old, ...change };
    if (change.prezzo !== undefined || change.unita_misura !== undefined || change.marca !== undefined || change.quantita_confezione !== undefined || change.dicitura_fornitore !== undefined || change.non_trattato) next.conferma_prezzo = false;
    if (change.non_trattato) { next.prezzo = ''; next.unita_misura = ''; next.marca = ''; next.dicitura_fornitore = ''; next.quantita_confezione = ''; next.extraOffers = []; }
    return { ...prev, [id]: next };
  });

  const addExtraOffer = (id: number) => setAnswers(prev => ({ ...prev, [id]: { ...prev[id], extraOffers: [...prev[id].extraOffers, { key: crypto.randomUUID(), prezzo: '', unita_misura: prev[id].unita_misura, marca: '', dicitura_fornitore: '', quantita_confezione: '', nota: '' }] } }));
  const changeExtraOffer = (id: number, key: string, change: Partial<ExtraOffer>) => setAnswers(prev => ({ ...prev, [id]: { ...prev[id], extraOffers: prev[id].extraOffers.map(offer => offer.key === key ? { ...offer, ...change } : offer) } }));
  const removeExtraOffer = (id: number, key: string) => setAnswers(prev => ({ ...prev, [id]: { ...prev[id], extraOffers: prev[id].extraOffers.filter(offer => offer.key !== key) } }));

  const saveDraft = () => {
    localStorage.setItem(draftKey, JSON.stringify({ answers, validitaDa, validitaA }));
    setDraftNotice('Bozza salvata in questo browser. Puoi tornare usando lo stesso link.');
  };

  const submit = async (event: FormEvent) => {
    event.preventDefault(); if (!data) return;
    setSending(true); setError('');
    try {
      const response = await fetch(`${API_BASE}/supplier-price-forms/public/${encodeURIComponent(token)}/submit`, {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          validita_inviata_da: validitaDa,
          validita_inviata_a: validitaA || null,
          anagrafica: data.requires_supplier_details ? anagrafica : null,
          answers: data.items.map(i => ({ item_id: i.id, non_trattato: answers[i.id].non_trattato, offerte: answers[i.id].non_trattato ? null : [
            { prezzo: answers[i.id].prezzo, unita_misura: answers[i.id].unita_misura, marca: answers[i.id].marca, dicitura_fornitore: answers[i.id].dicitura_fornitore, quantita_confezione: answers[i.id].quantita_confezione, conferma_prezzo: data.request_type === 'confirmation' && answers[i.id].conferma_prezzo, nota: answers[i.id].nota || null },
            ...answers[i.id].extraOffers.map(offer => ({ prezzo: offer.prezzo, unita_misura: offer.unita_misura, marca: offer.marca, dicitura_fornitore: offer.dicitura_fornitore, quantita_confezione: offer.quantita_confezione, nota: offer.nota, conferma_prezzo: false })),
          ] }))
        })
      });
      const body = await response.json().catch(() => ({}));
      if (!response.ok) throw new Error(apiErrorMessage(body.detail, 'Invio non riuscito'));
      localStorage.removeItem(draftKey);
      setDone(true);
    } catch (e) { setError(e instanceof Error ? e.message : 'Invio non riuscito'); }
    finally { setSending(false); }
  };

  const wrap: CSSProperties = { minHeight: '100vh', padding: '24px 14px', boxSizing: 'border-box', background: 'var(--bg-app)', color: 'var(--text-primary)', fontFamily: 'var(--font-family)' };
  const box: React.CSSProperties = { maxWidth: 900, margin: '0 auto', padding: 20, border: '1px solid var(--line)', borderRadius: 'var(--radius-lg)', background: 'var(--bg-card)' };
  const input: React.CSSProperties = { width: '100%', boxSizing: 'border-box', padding: 10, borderRadius: 'var(--radius-sm)', border: '1px solid var(--line)', background: 'var(--bg-inset)', color: 'var(--text-primary)' };
  if (loading) return <main style={wrap}><div style={box}>Caricamento modulo…</div></main>;
  if (error && !data) return <main style={wrap}><div style={box}><h1>Modulo non disponibile</h1><p>{error}</p></div></main>;
  if (done) return <main style={wrap}><div style={box}><h1>Risposta inviata</h1><p>Grazie. La risposta e il periodo di validità indicato sono stati registrati e saranno verificati dall’azienda. Non hanno modificato automaticamente il listino ufficiale.</p></div></main>;
  if (!data) return null;

  return <main style={wrap}><form style={box} onSubmit={submit}>
    <h1 style={{ marginTop: 0 }}>{data.request_type === 'new_listino' ? 'Nuova offerta listino' : 'Conferma listino'} · {data.supplier_name}</h1>
    <p>Per ogni prodotto trattato indica quantità della confezione, unità e prezzo. Marca e vostra denominazione sono facoltative: compilale solo se diverse dalla nostra descrizione (per frutta e verdura sfusa di solito puoi lasciarle vuote). La risposta sarà revisionata dall’azienda prima di aggiornare il listino.</p>
    <p style={{ padding: 12, border: '1px solid var(--warn-border)', borderRadius: 'var(--radius-md)', background: 'var(--warn-bg)', color: 'var(--text-primary)' }}><strong>Come indicare il prezzo:</strong> il prezzo si riferisce sempre alla <strong>quantità</strong> e all’<strong>unità di misura</strong> che indichi nella stessa riga.<br />
      • <strong>Venduto a peso (sfuso)</strong>: quantità 1, unità KG, prezzo al kg. Es. melanzane a € 1,50/kg → 1 · KG · € 1,50.<br />
      • <strong>Venduto a pezzo</strong>: quantità 1, unità PZ, prezzo del singolo pezzo. Es. ananas a € 3,00 l’uno → 1 · PZ · € 3,00.<br />
      • <strong>Confezione, busta, cassetta o cartone</strong>: quantità = contenuto della confezione, prezzo dell’intera confezione. Es. sacco di patate da 2 kg a € 2,00 → 2 · KG · € 2,00; vaschetta di fragole da 250 g a € 3,00 → 0,25 · KG · € 3,00; cartone da 6 pezzi a € 12,00 → 6 · PZ · € 12,00.<br />
      Sotto ogni prezzo vedi il valore per unità calcolato: controlla che sia corretto. Se un prodotto ha un’indicazione specifica, segui quella.</p>
    {data.note && <p><strong>Nota dell’azienda:</strong> {data.note}</p>}
    <p style={{ color: 'var(--text-secondary)' }}>Link valido fino al {new Date(data.expires_at).toLocaleString('it-IT')}</p>
    {data.requires_supplier_details && <section style={{ ...box, padding: 16, maxWidth: 'none', margin: '14px 0' }}>
      <h2 style={{ fontSize: '1.1rem', marginTop: 0 }}>Dati aziendali</h2>
      <p style={{ color: 'var(--text-secondary)' }}>Servono per registrarvi come fornitori e per inviarvi gli ordini.</p>
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit,minmax(200px,1fr))', gap: 10 }}>
        <label>Ragione sociale<input style={input} required minLength={2} maxLength={255} value={anagrafica.ragione_sociale} onChange={e => setAnagrafica(a => ({ ...a, ragione_sociale: e.target.value }))} /></label>
        <label>Partita IVA<input style={input} required inputMode="numeric" pattern="(IT|it)?\s*[0-9]{11}" title="11 cifre" maxLength={20} value={anagrafica.partita_iva} onChange={e => setAnagrafica(a => ({ ...a, partita_iva: e.target.value }))} /></label>
        <label>Telefono per gli ordini<input style={input} required type="tel" maxLength={50} value={anagrafica.telefono_ordini} onChange={e => setAnagrafica(a => ({ ...a, telefono_ordini: e.target.value }))} placeholder="Es. 333 1234567" /></label>
      </div>
    </section>}
    <section style={{ ...box, padding: 16, maxWidth: 'none', margin: '14px 0' }}>
      <h2 style={{ fontSize: '1.1rem', marginTop: 0 }}>Periodo di validità del listino</h2>
      <p style={{ color: 'var(--text-secondary)' }}>Indica da quando vale la tua offerta. La data di fine è facoltativa; un prezzo approvato resta operativo fino alla successiva approvazione.</p>
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit,minmax(200px,1fr))', gap: 10 }}>
        <label>Valido dal<input style={input} type="date" required value={validitaDa} onChange={e => setValiditaDa(e.target.value)} /></label>
        <label>Valido fino al (facoltativo)<input style={input} type="date" min={validitaDa || undefined} value={validitaA} onChange={e => setValiditaA(e.target.value)} /></label>
      </div>
    </section>
    {data.items.map(item => {
      const answer = answers[item.id]; if (!answer) return null;
      return <section key={item.id} style={{ ...box, padding: 16, margin: '14px 0', maxWidth: 'none' }}>
        <h2 style={{ fontSize: '1.1rem', marginTop: 0 }}>{item.descrizione}</h2>
        <p style={{ color: 'var(--text-secondary)' }}>SKU {item.sku_interno}{data.request_type === 'new_listino' ? ` · Unità di riferimento: ${item.unita_corrente || 'da indicare'}` : ` · Prezzo attuale: € ${item.prezzo_corrente}${item.unita_corrente ? formatLabel(item.quantita_corrente, item.unita_corrente) : ' (unità da indicare)'}`}</p>
        {data.request_type === 'confirmation' && !item.unita_corrente && <p style={{ color: 'var(--warn)' }}>Il prezzo attuale non ha un’unità di misura: indica quantità e unità a cui si riferisce il tuo prezzo (KG, PZ, cartone…).</p>}
        {item.istruzioni &&<p style={{ padding: 10, border: '1px solid var(--warn-border)', borderRadius: 'var(--radius-md)', background: 'var(--warn-bg)', color: 'var(--text-primary)' }}><strong>Indicazione per questo prodotto:</strong> {item.istruzioni}</p>}
        {data.request_type === 'confirmation' && item.validita_corrente_da &&<p style={{ color: 'var(--text-secondary)' }}>Validità: dal {new Date(item.validita_corrente_da).toLocaleDateString('it-IT')}{item.validita_corrente_a ? ' al ' + new Date(item.validita_corrente_a).toLocaleDateString('it-IT') : ''}</p>}
        <label style={{ display: 'block', margin: '12px 0' }}><input type="checkbox" checked={answer.non_trattato} onChange={e => setAnswer(item.id, { non_trattato: e.target.checked })} /> Non trattiamo questo prodotto</label>
        {answer.non_trattato ? <p style={{ color: 'var(--text-secondary)' }}>Non è necessario inserire prezzo o unità di misura per questo prodotto.</p> : <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit,minmax(160px,1fr))', gap: 10 }}>
          <label>Vostra denominazione (facoltativa)<input style={input} maxLength={255} placeholder={item.descrizione} value={answer.dicitura_fornitore} onChange={e => setAnswer(item.id, { dicitura_fornitore: e.target.value })} /></label>
          <label>Marca (facoltativa)<input style={input} maxLength={100} value={answer.marca} onChange={e => setAnswer(item.id, { marca: e.target.value })} /></label>
          <label>Quantità della confezione<input style={input} type="number" min="0.001" step="0.001" required value={answer.quantita_confezione} onChange={e => setAnswer(item.id, { quantita_confezione: e.target.value })} /></label>
          <label>Unità di misura<select style={input} required value={answer.unita_misura} onChange={e => setAnswer(item.id, { unita_misura: e.target.value })}><option value="">Seleziona…</option>{SUPPLIER_UNIT_OPTIONS.map(([code, label]) => <option key={code} value={code}>{label}</option>)}</select></label>
          <label>Prezzo del prodotto/confezione (€)<input style={input} type="number" min="0.0001" step="0.0001" required value={answer.prezzo} onChange={e => setAnswer(item.id, { prezzo: e.target.value })} /><small style={{ display: 'block', color: 'var(--text-secondary)' }}>Prezzo totale della quantità indicata.</small><UnitPriceHint prezzo={answer.prezzo} quantita={answer.quantita_confezione} unita={answer.unita_misura} /></label>
        </div>}
        {!answer.non_trattato && answer.extraOffers.map((offer, index) => <div key={offer.key} style={{ marginTop: 14, padding: 12, border: '1px solid var(--line)', borderRadius: 'var(--radius-md)' }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}><strong>Altra marca o formato {index + 2}</strong><button type="button" className="btn" onClick={() => removeExtraOffer(item.id, offer.key)}>Rimuovi</button></div>
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit,minmax(160px,1fr))', gap: 10, marginTop: 10 }}>
            <label>Vostra denominazione (facoltativa)<input style={input} maxLength={255} placeholder={item.descrizione} value={offer.dicitura_fornitore} onChange={e => changeExtraOffer(item.id, offer.key, { dicitura_fornitore: e.target.value })} /></label>
            <label>Marca (facoltativa)<input style={input} maxLength={100} value={offer.marca} onChange={e => changeExtraOffer(item.id, offer.key, { marca: e.target.value })} /></label>
            <label>Quantità della confezione<input style={input} type="number" min="0.001" step="0.001" required value={offer.quantita_confezione} onChange={e => changeExtraOffer(item.id, offer.key, { quantita_confezione: e.target.value })} /></label>
            <label>Unità di misura<select style={input} required value={offer.unita_misura} onChange={e => changeExtraOffer(item.id, offer.key, { unita_misura: e.target.value })}><option value="">Seleziona…</option>{SUPPLIER_UNIT_OPTIONS.map(([code, label]) => <option key={code} value={code}>{label}</option>)}</select></label>
            <label>Prezzo del prodotto/confezione (€)<input style={input} type="number" min="0.0001" step="0.0001" required value={offer.prezzo} onChange={e => changeExtraOffer(item.id, offer.key, { prezzo: e.target.value })} /><UnitPriceHint prezzo={offer.prezzo} quantita={offer.quantita_confezione} unita={offer.unita_misura} /></label>
          </div>
          <label style={{ display: 'block', marginTop: 10 }}>Nota su questa offerta<textarea style={{ ...input, marginTop: 4 }} rows={2} maxLength={1000} value={offer.nota} onChange={e => changeExtraOffer(item.id, offer.key, { nota: e.target.value })} /></label>
        </div>)}
        {!answer.non_trattato && answer.extraOffers.length < 9 && <button type="button" className="btn" style={{ marginTop: 12 }} onClick={() => addExtraOffer(item.id)}>+ Aggiungi un’altra marca o formato</button>}
        {/* Without an agreed unit there is nothing to confirm: the answer is reviewed as a proposal. */}
        {data.request_type === 'confirmation' && !answer.non_trattato && item.unita_corrente && <label style={{ display: 'block', marginTop: 12 }}><input type="checkbox" checked={answer.conferma_prezzo} onChange={e => setAnswer(item.id, { conferma_prezzo: e.target.checked })} /> Confermo che prezzo, quantità e unità corrispondono al pattuito</label>}
        <label style={{ display: 'block', marginTop: 10 }}>Nota<textarea style={{ ...input, marginTop: 4 }} rows={2} maxLength={1000} value={answer.nota} onChange={e => setAnswer(item.id, { nota: e.target.value })} /></label>
      </section>;
    })}
    {error && <p role="alert" style={{ color: 'var(--crit)' }}>{error}</p>}
    {draftNotice && <p role="status" style={{ color: 'var(--ok)' }}>{draftNotice}</p>}
    <button className="btn" type="button" onClick={saveDraft} style={{ marginRight: 8 }}>Salva bozza in questo browser</button>
    <button className="btn btn-primary" disabled={sending} type="submit">{sending ? 'Invio…' : 'Invia risposte'}</button>
  </form></main>;
}

