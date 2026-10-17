import { useEffect, useMemo, useState } from 'react';
import type { CSSProperties } from 'react';
import { fetchWithAuth } from '../api';

type Supplier = { id: number; nome_azienda: string };
type PriceRow = { id: number; sku_interno: string; descrizione: string; prezzo_pattuito: number | string; unita_misura: string; data_inizio_validita: string; data_scadenza?: string | null; category?: string | null; subcategory?: string | null };
type FormItem = { id: number; sku_interno: string; descrizione: string; prezzo_corrente: string; unita_corrente: string; prezzo_inviato?: string | null; unita_inviata?: string | null; conferma_prezzo?: boolean | null; nota_fornitore?: string | null; esito: string };
type FormRequest = { id: number; supplier_id: number; supplier_name: string; status: string; created_at: string; expires_at: string; submitted_at?: string | null; note?: string | null; items: FormItem[] };
type CreateResult = { request: FormRequest; token: string; public_path: string };

const card: CSSProperties = { border: '1px solid var(--border-glass)', borderRadius: 12, padding: 16, background: 'rgba(255,255,255,.025)' };
const field: React.CSSProperties = { width: '100%', boxSizing: 'border-box', padding: 10, color: 'white', background: 'var(--bg-secondary)', border: '1px solid var(--border-glass)', borderRadius: 8 };

export default function SupplierPriceForms() {
  const [suppliers, setSuppliers] = useState<Supplier[]>([]);
  const [rows, setRows] = useState<PriceRow[]>([]);
  const [supplierId, setSupplierId] = useState('');
  const [selected, setSelected] = useState<number[]>([]);
  const [listinoSection, setListinoSection] = useState('all');
  const [days, setDays] = useState(14);
  const [note, setNote] = useState('');
  const [forms, setForms] = useState<FormRequest[]>([]);
  const [created, setCreated] = useState<CreateResult | null>(null);
  const [detail, setDetail] = useState<FormRequest | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');

  const loadForms = async () => {
    try { setForms(await fetchWithAuth('/supplier-price-forms/?status_filter=all')); }
    catch (e) { setError(e instanceof Error ? e.message : 'Impossibile caricare i moduli'); }
  };
  useEffect(() => {
    loadForms();
    fetchWithAuth('/fornitori/').then((data: any) => setSuppliers(Array.isArray(data) ? data : data.items || data.records || [])).catch((e: unknown) => setError(e instanceof Error ? e.message : 'Impossibile caricare i fornitori'));
  }, []);
  useEffect(() => {
    let live = true;
    setRows([]); setSelected([]); setCreated(null); setListinoSection('all');
    if (!supplierId) return;
    (async () => {
      try {
        const result = await fetchWithAuth('/supplier-price-forms/catalog/' + encodeURIComponent(supplierId));
        const data = Array.isArray(result) ? result : (result.items || result.records || result.data || []);
        if (live) setRows(data.filter((r: PriceRow) => r && r.id));
      } catch (e) { if (live) setError(e instanceof Error ? e.message : 'Impossibile caricare il listino'); }
    })();
    return () => { live = false; };
  }, [supplierId]);

  const groupOptions = useMemo(() => {
    const categoryCounts = new Map<string, number>();
    const subcategoryCounts = new Map<string, { category: string; subcategory: string; count: number }>();
    let uncategorizedCount = 0;
    rows.forEach(row => {
      const category = row.category?.trim();
      const subcategory = row.subcategory?.trim();
      if (!category) { uncategorizedCount += 1; return; }
      categoryCounts.set(category, (categoryCounts.get(category) || 0) + 1);
      if (subcategory) {
        const key = category + '::' + subcategory;
        const current = subcategoryCounts.get(key);
        subcategoryCounts.set(key, { category, subcategory, count: (current?.count || 0) + 1 });
      }
    });
    return [
      { value: 'all', label: `Tutto il listino (${rows.length})`, category: null as string | null, subcategory: null as string | null, uncategorized: false },
      ...Array.from(categoryCounts.entries()).sort(([a], [b]) => a.localeCompare(b, 'it')).map(([category, count]) => ({
        value: 'category:' + category, label: `${category} (${count})`, category, subcategory: null, uncategorized: false
      })),
      ...Array.from(subcategoryCounts.entries()).sort(([, a], [, b]) => (a.category + a.subcategory).localeCompare(b.category + b.subcategory, 'it')).map(([key, item]) => ({
        value: 'subcategory:' + key, label: `${item.category} · ${item.subcategory} (${item.count})`, category: item.category, subcategory: item.subcategory, uncategorized: false
      })),
      ...(uncategorizedCount ? [{ value: 'uncategorized', label: `Senza categoria (${uncategorizedCount})`, category: null, subcategory: null, uncategorized: true }] : [])
    ];
  }, [rows]);
  const activeGroup = groupOptions.find(option => option.value === listinoSection) || groupOptions[0];
  const visibleRows = useMemo(() => rows.filter(row => {
    if (!activeGroup || activeGroup.value === 'all') return true;
    if (activeGroup.uncategorized) return !row.category?.trim();
    if (activeGroup.subcategory) return row.category?.trim() === activeGroup.category && row.subcategory?.trim() === activeGroup.subcategory;
    return row.category?.trim() === activeGroup.category;
  }), [rows, activeGroup]);
  const allVisibleSelected = visibleRows.length > 0 && visibleRows.every(row => selected.includes(row.id));
  const publicUrl = useMemo(() => created ? window.location.origin + created.public_path : '', [created]);
  const toggleVisibleRows = () => setSelected(current => {
    const visibleIds = visibleRows.map(row => row.id);
    if (allVisibleSelected) return current.filter(id => !visibleIds.includes(id));
    return Array.from(new Set([...current, ...visibleIds]));
  });
  const toggleRow = (id: number) => setSelected(current => current.includes(id) ? current.filter(x => x !== id) : [...current, id]);

  const createForm = async () => {
    setBusy(true); setError(''); setNotice(''); setCreated(null);
    try {
      const result = await fetchWithAuth('/supplier-price-forms/', { method: 'POST', body: JSON.stringify({
        supplier_id: Number(supplierId), listino_ids: selected, expires_in_days: days, note: note.trim() || null
      }) }) as CreateResult;
      setCreated(result); setNotice('Modulo creato. Il link è visibile solo qui: copialo e invialo tu al fornitore.');
      await loadForms();
    } catch (e) { setError(e instanceof Error ? e.message : 'Creazione non riuscita'); }
    finally { setBusy(false); }
  };
  const openDetail = async (id: number) => {
    setError('');
    try { setDetail(await fetchWithAuth('/supplier-price-forms/' + id)); }
    catch (e) { setError(e instanceof Error ? e.message : 'Impossibile caricare il dettaglio'); }
  };
  const closeForm = async (id: number) => {
    setBusy(true); setError('');
    try { await fetchWithAuth('/supplier-price-forms/' + id + '/close', { method: 'POST' }); setDetail(null); await loadForms(); }
    catch (e) { setError(e instanceof Error ? e.message : 'Chiusura non riuscita'); }
    finally { setBusy(false); }
  };
  const copyLink = async () => {
    try { await navigator.clipboard.writeText(publicUrl); setNotice('Link copiato. Invialo al fornitore tramite il canale che preferisci.'); }
    catch { setNotice('Copia non disponibile: seleziona e copia il link mostrato.'); }
  };

  return <div style={{ display: 'grid', gap: 20, maxWidth: 1200 }}>
    <section style={card}>
      <h2 style={{ marginTop: 0 }}>Crea modulo per un fornitore</h2>
      <p style={{ color: 'var(--text-secondary)' }}>Scegli il fornitore e poi la categoria/scheda del listino da inviare. Puoi selezionare tutte le righe visibili o scegliere solo alcuni prodotti. Le risposte del fornitore non cambiano il listino master.</p>
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit,minmax(220px,1fr))', gap: 12 }}>
        <label>Fornitore<select style={field} value={supplierId} onChange={e => setSupplierId(e.target.value)}><option value="">Seleziona…</option>{suppliers.map(s => <option key={s.id} value={s.id}>{s.nome_azienda}</option>)}</select></label>
        <label>Scadenza link<select style={field} value={days} onChange={e => setDays(Number(e.target.value))}>{[7,14,21,30].map(d => <option key={d} value={d}>{d} giorni</option>)}</select></label>
        <label style={{ gridColumn: '1 / -1' }}>Nota per il fornitore<textarea style={field} rows={2} maxLength={1000} value={note} onChange={e => setNote(e.target.value)} placeholder="Facoltativa" /></label>
      </div>
      {supplierId && <div style={{ marginTop: 16, display: 'grid', gap: 12 }}>
        <label>Listino / sezione da inviare
          <select style={field} value={listinoSection} onChange={e => setListinoSection(e.target.value)}>
            {groupOptions.map(option => <option key={option.value} value={option.value}>{option.label}</option>)}
          </select>
        </label>
        <div style={{ display: 'flex', justifyContent: 'space-between', gap: 8, alignItems: 'center', flexWrap: 'wrap' }}>
          <strong>Righe visibili {visibleRows.length} · selezionate {selected.length}</strong>
          <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
            {selected.length > 0 && <button className="btn" type="button" onClick={() => setSelected([])}>Azzera selezione</button>}
            <button className="btn" type="button" onClick={toggleVisibleRows} disabled={!visibleRows.length}>{allVisibleSelected ? 'Deseleziona righe visibili' : 'Seleziona tutte le righe visibili'}</button>
          </div>
        </div>
        <div style={{ maxHeight: 360, overflow: 'auto', border: '1px solid var(--border-glass)', borderRadius: 8 }}>
          {visibleRows.map(r => <label key={r.id} style={{ display: 'grid', gridTemplateColumns: '24px 1fr auto', gap: 10, padding: 10, borderBottom: '1px solid var(--border-glass)', alignItems: 'center' }}>
            <input type="checkbox" checked={selected.includes(r.id)} onChange={() => toggleRow(r.id)} />
            <span>{r.descrizione}<small style={{ display: 'block', color: 'var(--text-secondary)' }}>{r.sku_interno}{r.category ? ` · ${r.category}${r.subcategory ? ' / ' + r.subcategory : ''}` : ' · Senza categoria'}</small></span>
            <span>€ {r.prezzo_pattuito} / {r.unita_misura}</span>
          </label>)}
          {rows.length === 0 && <p style={{ padding: 12, color: 'var(--text-secondary)' }}>Nessuna riga attiva trovata per questo fornitore.</p>}
          {rows.length > 0 && visibleRows.length === 0 && <p style={{ padding: 12, color: 'var(--text-secondary)' }}>Nessuna riga in questa sezione.</p>}
        </div>
      </div>}
      <button className="btn btn-primary" style={{ marginTop: 16 }} disabled={busy || !supplierId || !selected.length} onClick={createForm}>{busy ? 'Creazione…' : 'Crea link personale'}</button>
      {created && <div style={{ ...card, marginTop: 14, borderColor: 'rgba(34,197,94,.45)' }}>
        <strong>Link pronto per {created.request.supplier_name}</strong>
        <p style={{ overflowWrap: 'anywhere' }}>{publicUrl}</p>
        <button className="btn" type="button" onClick={copyLink}>Copia link</button>
        <p style={{ color: 'var(--text-secondary)', marginBottom: 0 }}>Il link viene mostrato una sola volta. Price Sentinel non lo invia automaticamente.</p>
      </div>}
    </section>

    <section style={card}>
      <div style={{ display: 'flex', justifyContent: 'space-between', gap: 12, alignItems: 'center' }}>
        <h2 style={{ margin: 0 }}>Moduli creati</h2><button className="btn" type="button" onClick={loadForms}>Aggiorna</button>
      </div>
      {forms.length ? <div style={{ overflowX: 'auto', marginTop: 12 }}><table style={{ width: '100%', borderCollapse: 'collapse' }}><thead><tr><th align="left">Fornitore</th><th align="left">Creato</th><th align="left">Scadenza</th><th align="left">Stato</th><th></th></tr></thead><tbody>
        {forms.map(f => <tr key={f.id}><td>{f.supplier_name}</td><td>{new Date(f.created_at).toLocaleDateString('it-IT')}</td><td>{new Date(f.expires_at).toLocaleDateString('it-IT')}</td><td>{f.status}</td><td><button className="btn" onClick={() => openDetail(f.id)}>Dettaglio</button></td></tr>)}
      </tbody></table></div> : <p style={{ color: 'var(--text-secondary)' }}>Nessun modulo ancora creato.</p>}
    </section>

    {detail && <section style={card}>
      <div style={{ display: 'flex', justifyContent: 'space-between', gap: 12 }}><h2 style={{ marginTop: 0 }}>Risposte · {detail.supplier_name}</h2><button className="btn" onClick={() => setDetail(null)}>Chiudi</button></div>
      <p>Stato: <strong>{detail.status}</strong>{detail.submitted_at ? ' · inviato ' + new Date(detail.submitted_at).toLocaleString('it-IT') : ''}</p>
      <div style={{ display: 'grid', gap: 8 }}>{detail.items.map(i => <div key={i.id} style={{ ...card, padding: 12 }}>
        <strong>{i.descrizione}</strong><small style={{ display: 'block', color: 'var(--text-secondary)' }}>{i.sku_interno}</small>
        <div>Pattuito: € {i.prezzo_corrente} / {i.unita_corrente} · Risposta: {i.prezzo_inviato ? '€ ' + i.prezzo_inviato + ' / ' + i.unita_inviata : 'in attesa'}</div>
        <div>Esito: {i.esito === 'confermato' ? 'Confermato' : i.esito === 'proposta_variazione' ? 'Proposta di variazione' : 'Da compilare'}{i.nota_fornitore ? ' · Nota: ' + i.nota_fornitore : ''}</div>
      </div>)}</div>
      {['open','submitted','expired'].includes(detail.status) && <button className="btn" disabled={busy} onClick={() => closeForm(detail.id)}>Chiudi link</button>}
      <p style={{ color: 'var(--text-secondary)' }}>Per applicare un’eventuale variazione, revisiona la proposta e usa il normale flusso di approvazione/importazione.</p>
    </section>}
    {error && <div role="alert" style={{ color: '#fca5a5' }}>{error}</div>}
    {notice && <div role="status" style={{ color: '#86efac' }}>{notice}</div>}
  </div>;
}
