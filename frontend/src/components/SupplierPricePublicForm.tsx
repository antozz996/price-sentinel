import { useEffect, useState } from 'react';
import type { CSSProperties, FormEvent } from 'react';
import { API_BASE } from '../api';

type PublicItem = { id: number; sku_interno: string; descrizione: string; prezzo_corrente?: string | null; unita_corrente?: string | null; validita_corrente_da?: string | null; validita_corrente_a?: string | null };
type FormData = { supplier_name: string; request_type: 'confirmation' | 'new_listino'; expires_at: string; note?: string | null; items: PublicItem[] };
type Answer = { prezzo: string; unita_misura: string; conferma_prezzo: boolean; non_trattato: boolean; nota: string };

export default function SupplierPricePublicForm({ token }: { token: string }) {
  const [data, setData] = useState<FormData | null>(null);
  const [answers, setAnswers] = useState<Record<number, Answer>>({});
  const [validitaDa, setValiditaDa] = useState('');
  const [validitaA, setValiditaA] = useState('');
  const [loading, setLoading] = useState(true);
  const [sending, setSending] = useState(false);
  const [error, setError] = useState('');
  const [done, setDone] = useState(false);

  useEffect(() => {
    let active = true;
    fetch(`${API_BASE}/supplier-price-forms/public/${encodeURIComponent(token)}`)
      .then(async r => { const body = await r.json().catch(() => ({})); if (!r.ok) throw new Error(body.detail || 'Link non valido o scaduto'); return body as FormData; })
      .then(form => {
        if (!active) return;
        setData(form);
        setAnswers(Object.fromEntries(form.items.map(i => [i.id, { prezzo: i.prezzo_corrente || '', unita_misura: i.unita_corrente || '', conferma_prezzo: false, non_trattato: false, nota: '' }])));
      })
      .catch(e => { if (active) setError(e.message || 'Impossibile caricare il modulo'); })
      .finally(() => { if (active) setLoading(false); });
    return () => { active = false; };
  }, [token]);

  const setAnswer = (id: number, change: Partial<Answer>) => setAnswers(prev => {
    const old = prev[id]; const next = { ...old, ...change };
    if (change.prezzo !== undefined || change.unita_misura !== undefined || change.non_trattato) next.conferma_prezzo = false;
    if (change.non_trattato) { next.prezzo = ''; next.unita_misura = ''; }
    return { ...prev, [id]: next };
  });

  const submit = async (event: FormEvent) => {
    event.preventDefault(); if (!data) return;
    setSending(true); setError('');
    try {
      const response = await fetch(`${API_BASE}/supplier-price-forms/public/${encodeURIComponent(token)}/submit`, {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          validita_inviata_da: validitaDa,
          validita_inviata_a: validitaA,
          answers: data.items.map(i => ({ item_id: i.id, prezzo: answers[i.id].non_trattato ? null : answers[i.id].prezzo, unita_misura: answers[i.id].non_trattato ? null : answers[i.id].unita_misura, conferma_prezzo: data.request_type === 'confirmation' && !answers[i.id].non_trattato && answers[i.id].conferma_prezzo, non_trattato: answers[i.id].non_trattato, nota: answers[i.id].nota || null }))
        })
      });
      const body = await response.json().catch(() => ({}));
      if (!response.ok) throw new Error(body.detail || 'Invio non riuscito');
      setDone(true);
    } catch (e) { setError(e instanceof Error ? e.message : 'Invio non riuscito'); }
    finally { setSending(false); }
  };

  const wrap: CSSProperties = { minHeight: '100vh', padding: '24px 14px', boxSizing: 'border-box', background: '#0b1220', color: 'white', fontFamily: 'system-ui,sans-serif' };
  const box: React.CSSProperties = { maxWidth: 900, margin: '0 auto', padding: 20, border: '1px solid rgba(255,255,255,.14)', borderRadius: 14, background: 'rgba(255,255,255,.04)' };
  const input: React.CSSProperties = { width: '100%', boxSizing: 'border-box', padding: 10, borderRadius: 8, border: '1px solid rgba(255,255,255,.2)', background: '#111827', color: 'white' };
  if (loading) return <main style={wrap}><div style={box}>Caricamento modulo…</div></main>;
  if (error && !data) return <main style={wrap}><div style={box}><h1>Modulo non disponibile</h1><p>{error}</p></div></main>;
  if (done) return <main style={wrap}><div style={box}><h1>Risposta inviata</h1><p>Grazie. La risposta e il periodo di validità indicato sono stati registrati e saranno verificati dall’azienda. Non hanno modificato automaticamente il listino ufficiale.</p></div></main>;
  if (!data) return null;

  return <main style={wrap}><form style={box} onSubmit={submit}>
    <h1 style={{ marginTop: 0 }}>{data.request_type === 'new_listino' ? 'Nuova offerta listino' : 'Conferma listino'} · {data.supplier_name}</h1>
    <p>{data.request_type === 'new_listino' ? 'Inserisci il prezzo e l’unità di misura offerti per ciascun prodotto. La tua offerta sarà revisionata dall’azienda e non aggiorna automaticamente il listino ufficiale.' : 'Verifica ogni prezzo. Puoi confermare il valore pattuito oppure indicare una proposta diversa. La proposta sarà sottoposta a verifica dall’azienda.'}</p>{data.note && <p><strong>Nota dell’azienda:</strong> {data.note}</p>}
    <p style={{ color: '#cbd5e1' }}>Link valido fino al {new Date(data.expires_at).toLocaleString('it-IT')}</p>
    <section style={{ ...box, padding: 16, maxWidth: 'none', margin: '14px 0' }}>
      <h2 style={{ fontSize: '1.1rem', marginTop: 0 }}>Periodo di validità del listino</h2>
      <p style={{ color: '#cbd5e1' }}>{data.request_type === 'new_listino' ? 'Indica il periodo di validità dell’offerta che stai inviando.' : 'Indica da quando a quando sono validi i prezzi che confermi o proponi in questo modulo. Il periodo sarà registrato insieme alla risposta e verificato dall’azienda.'}</p>
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit,minmax(200px,1fr))', gap: 10 }}>
        <label>Valido dal<input style={input} type="date" required value={validitaDa} onChange={e => setValiditaDa(e.target.value)} /></label>
        <label>Valido fino al<input style={input} type="date" required min={validitaDa || undefined} value={validitaA} onChange={e => setValiditaA(e.target.value)} /></label>
      </div>
    </section>
    {data.items.map(item => {
      const answer = answers[item.id]; if (!answer) return null;
      return <section key={item.id} style={{ ...box, padding: 16, margin: '14px 0', maxWidth: 'none' }}>
        <h2 style={{ fontSize: '1.1rem', marginTop: 0 }}>{item.descrizione}</h2>
        <p style={{ color: '#cbd5e1' }}>SKU {item.sku_interno}{data.request_type === 'new_listino' ? ` · Unità di riferimento: ${item.unita_corrente || 'da indicare'}` : ` · Prezzo attuale: € ${item.prezzo_corrente} / ${item.unita_corrente}`}</p>
        {data.request_type === 'confirmation' && item.validita_corrente_da && <p style={{ color: '#cbd5e1' }}>Validità: dal {new Date(item.validita_corrente_da).toLocaleDateString('it-IT')}{item.validita_corrente_a ? ' al ' + new Date(item.validita_corrente_a).toLocaleDateString('it-IT') : ''}</p>}
        <label style={{ display: 'block', margin: '12px 0' }}><input type="checkbox" checked={answer.non_trattato} onChange={e => setAnswer(item.id, { non_trattato: e.target.checked })} /> Non trattiamo questo prodotto</label>
        {answer.non_trattato ? <p style={{ color: '#cbd5e1' }}>Non è necessario inserire prezzo o unità di misura per questo prodotto.</p> : <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit,minmax(160px,1fr))', gap: 10 }}>
          <label>{data.request_type === 'new_listino' ? 'Prezzo offerto (€)' : 'Prezzo proposto (€)'}<input style={input} type="number" min="0.0001" step="0.0001" required value={answer.prezzo} onChange={e => setAnswer(item.id, { prezzo: e.target.value })} /></label>
          <label>Unità di misura<input style={input} required maxLength={50} value={answer.unita_misura} onChange={e => setAnswer(item.id, { unita_misura: e.target.value })} /></label>
        </div>}
        {data.request_type === 'confirmation' && !answer.non_trattato && <label style={{ display: 'block', marginTop: 12 }}><input type="checkbox" checked={answer.conferma_prezzo} onChange={e => setAnswer(item.id, { conferma_prezzo: e.target.checked })} /> Confermo che prezzo e unità corrispondono al pattuito</label>}
        <label style={{ display: 'block', marginTop: 10 }}>Nota<textarea style={{ ...input, marginTop: 4 }} rows={2} maxLength={1000} value={answer.nota} onChange={e => setAnswer(item.id, { nota: e.target.value })} /></label>
      </section>;
    })}
    {error && <p role="alert" style={{ color: '#fca5a5' }}>{error}</p>}
    <button className="btn btn-primary" disabled={sending} type="submit">{sending ? 'Invio…' : 'Invia risposte'}</button>
  </form></main>;
}

