import { useEffect, useMemo, useState } from 'react';
import type { CSSProperties } from 'react';
import { fetchWithAuth } from '../api';

type Supplier = { id: number; nome_azienda: string; telefono_contatto?: string | null };
type CapabilitySupplier = { supplier_id: number; supplier_name: string; categories: Record<string, boolean> };
type Category = { nome: string; is_active: boolean };
type PriceRow = { id: number; sku_interno: string; descrizione: string; prezzo_pattuito: number | string; unita_misura: string; data_inizio_validita: string; data_scadenza?: string | null; category?: string | null; subcategory?: string | null };
type FormItem = { id: number; sku_interno: string; descrizione: string; prezzo_corrente: string; unita_corrente: string; prezzo_inviato?: string | null; unita_inviata?: string | null; conferma_prezzo?: boolean | null; nota_fornitore?: string | null; esito: string };
type FormRequest = { id: number; supplier_id: number; supplier_name: string; status: string; created_at: string; expires_at: string; submitted_at?: string | null; note?: string | null; items: FormItem[] };
type CreateResult = { request: FormRequest; token: string; public_path: string };
type CreatedLink = { supplier: Supplier; url: string; publicPath: string };
type MatrixResponse = { categories?: Category[]; suppliers?: CapabilitySupplier[] };

const card: CSSProperties = { border: '1px solid var(--border-glass)', borderRadius: 12, padding: 16, background: 'rgba(255,255,255,.025)' };
const field: CSSProperties = { width: '100%', boxSizing: 'border-box', padding: 10, color: 'white', background: 'var(--bg-secondary)', border: '1px solid var(--border-glass)', borderRadius: 8 };
const configuredPublicOrigin = ((import.meta as any).env?.VITE_PUBLIC_APP_URL || '').trim().replace(/\/$/, '');
const localBrowserOrigin = /^(https?:\/\/)?(localhost|127\.0\.0\.1)(:\d+)?$/i.test(window.location.origin);
const isLocalAddress = (value: string) => /^(https?:\/\/)?(localhost|127\.0\.0\.1)(:\d+)?$/i.test(value.trim());

function phoneForWhatsApp(value?: string | null) {
  let digits = (value || '').replace(/\D/g, '');
  if (digits.startsWith('00')) digits = digits.slice(2);
  // Supplier contacts are Italian; local 10-digit mobiles need the +39 prefix for wa.me.
  if (digits.length === 10 && digits.startsWith('3')) digits = '39' + digits;
  return digits.length >= 8 ? digits : '';
}

export default function SupplierPriceForms() {
  const [suppliers, setSuppliers] = useState<Supplier[]>([]);
  const [categories, setCategories] = useState<Category[]>([]);
  const [capabilitySuppliers, setCapabilitySuppliers] = useState<CapabilitySupplier[]>([]);
  const [recipientMode, setRecipientMode] = useState<'suppliers' | 'category'>('suppliers');
  const [supplierIds, setSupplierIds] = useState<number[]>([]);
  const [recipientCategory, setRecipientCategory] = useState('');
  const [rowsBySupplier, setRowsBySupplier] = useState<Record<number, PriceRow[]>>({});
  const [selectedBySupplier, setSelectedBySupplier] = useState<Record<number, number[]>>({});
  const [listinoSection, setListinoSection] = useState('all');
  const [days, setDays] = useState(14);
  const [note, setNote] = useState('');
  const [publicBaseUrl, setPublicBaseUrl] = useState(() => {
    if (configuredPublicOrigin) return configuredPublicOrigin;
    if (localBrowserOrigin) return localStorage.getItem('supplierFormsPublicBaseUrl') || '';
    return window.location.origin;
  });
  const [forms, setForms] = useState<FormRequest[]>([]);
  const [createdLinks, setCreatedLinks] = useState<CreatedLink[]>([]);
  const [detail, setDetail] = useState<FormRequest | null>(null);
  const [busy, setBusy] = useState(false);
  const [loadingCatalog, setLoadingCatalog] = useState(false);
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');

  const loadForms = async () => {
    try { setForms(await fetchWithAuth('/supplier-price-forms/?status_filter=all')); }
    catch (e) { setError(e instanceof Error ? e.message : 'Impossibile caricare i moduli'); }
  };
  useEffect(() => {
    loadForms();
    Promise.all([
      fetchWithAuth('/fornitori/'),
      fetchWithAuth('/categories/matrix'),
    ]).then(([supplierData, matrixData]: [any, MatrixResponse]) => {
      setSuppliers(Array.isArray(supplierData) ? supplierData : supplierData.items || supplierData.records || []);
      setCategories((matrixData.categories || []).filter(category => category.is_active));
      setCapabilitySuppliers(matrixData.suppliers || []);
    }).catch((e: unknown) => setError(e instanceof Error ? e.message : 'Impossibile caricare fornitori e categorie'));
  }, []);

  const eligibleSupplierIds = useMemo(() => {
    if (recipientMode !== 'category' || !recipientCategory) return [];
    return capabilitySuppliers
      .filter(s => s.categories?.[recipientCategory] === true)
      .map(s => s.supplier_id)
      .filter(id => suppliers.some(s => s.id === id));
  }, [recipientMode, recipientCategory, capabilitySuppliers, suppliers]);
  const selectedSupplierIds = recipientMode === 'category' ? eligibleSupplierIds : supplierIds;
  const selectedSuppliers = selectedSupplierIds.map(id => suppliers.find(s => s.id === id)).filter((s): s is Supplier => Boolean(s));
  const publicOrigin = publicBaseUrl.trim().replace(/\/$/, '');
  const publicUrlReady = /^https?:\/\//i.test(publicOrigin) && !isLocalAddress(publicOrigin);

  useEffect(() => {
    let live = true;
    setRowsBySupplier({});
    setSelectedBySupplier({});
    setCreatedLinks([]);
    setListinoSection(recipientMode === 'category' && recipientCategory ? 'category:' + recipientCategory : 'all');
    if (!selectedSupplierIds.length) { setLoadingCatalog(false); return; }
    setLoadingCatalog(true);
    Promise.all(selectedSupplierIds.map(async id => {
      const result = await fetchWithAuth('/supplier-price-forms/catalog/' + encodeURIComponent(String(id)));
      const data = Array.isArray(result) ? result : result.items || result.records || result.data || [];
      return [id, data.filter((r: PriceRow) => r && r.id) as PriceRow[]] as const;
    })).then(entries => {
      if (!live) return;
      setRowsBySupplier(Object.fromEntries(entries));
      if (recipientMode === 'category' && recipientCategory) {
        const initial: Record<number, number[]> = {};
        for (const [id, rows] of entries) {
          initial[id] = rows.filter(row => row.category?.trim().toLocaleLowerCase() === recipientCategory.toLocaleLowerCase()).map(row => row.id);
        }
        setSelectedBySupplier(initial);
      }
    }).catch((e: unknown) => {
      if (live) setError(e instanceof Error ? e.message : 'Impossibile caricare uno o più listini');
    }).finally(() => { if (live) setLoadingCatalog(false); });
    return () => { live = false; };
  }, [selectedSupplierIds.join(','), recipientMode, recipientCategory]);

  const allRows = selectedSupplierIds.flatMap(id => rowsBySupplier[id] || []);
  const groupOptions = useMemo(() => {
    const names = new Map<string, number>();
    const subs = new Map<string, { category: string; subcategory: string; count: number }>();
    let uncategorized = 0;
    allRows.forEach(row => {
      const c = row.category?.trim();
      const sub = row.subcategory?.trim();
      if (!c) { uncategorized += 1; return; }
      names.set(c, (names.get(c) || 0) + 1);
      if (sub) {
        const key = c + '::' + sub;
        const item = subs.get(key);
        subs.set(key, { category: c, subcategory: sub, count: (item?.count || 0) + 1 });
      }
    });
    return [
      { value: 'all', label: `Tutto il listino (${allRows.length})`, category: null as string | null, subcategory: null as string | null, uncategorized: false },
      ...Array.from(names.entries()).sort(([a], [b]) => a.localeCompare(b, 'it')).map(([category, count]) => ({ value: 'category:' + category, label: `${category} (${count})`, category, subcategory: null, uncategorized: false })),
      ...Array.from(subs.entries()).sort(([, a], [, b]) => (a.category + a.subcategory).localeCompare(b.category + b.subcategory, 'it')).map(([key, item]) => ({ value: 'subcategory:' + key, label: `${item.category} · ${item.subcategory} (${item.count})`, category: item.category, subcategory: item.subcategory, uncategorized: false })),
      ...(uncategorized ? [{ value: 'uncategorized', label: `Senza categoria (${uncategorized})`, category: null, subcategory: null, uncategorized: true }] : [])
    ];
  }, [selectedSupplierIds.join(','), rowsBySupplier]);
  const activeGroup = groupOptions.find(option => option.value === listinoSection) || groupOptions[0];
  const visibleRowsBySupplier = useMemo(() => Object.fromEntries(selectedSupplierIds.map(id => {
    const rows = rowsBySupplier[id] || [];
    return [id, rows.filter(row => {
      if (recipientMode === 'category') return row.category?.trim().toLocaleLowerCase() === recipientCategory.toLocaleLowerCase();
      if (!activeGroup || activeGroup.value === 'all') return true;
      if (activeGroup.uncategorized) return !row.category?.trim();
      if (activeGroup.subcategory) return row.category?.trim() === activeGroup.category && row.subcategory?.trim() === activeGroup.subcategory;
      return row.category?.trim() === activeGroup.category;
    })];
  })), [selectedSupplierIds.join(','), rowsBySupplier, activeGroup, recipientMode, recipientCategory]);
  const visibleRows = selectedSupplierIds.flatMap(id => visibleRowsBySupplier[id] || []);
  const selectedCount = selectedSupplierIds.reduce((sum, id) => sum + (selectedBySupplier[id]?.length || 0), 0);
  const allVisibleSelected = visibleRows.length > 0 && selectedSupplierIds.every(id =>
    (visibleRowsBySupplier[id] || []).every(row => (selectedBySupplier[id] || []).includes(row.id))
  );
  const toggleVisibleRows = () => setSelectedBySupplier(current => {
    const next = { ...current };
    for (const id of selectedSupplierIds) {
      const ids = (visibleRowsBySupplier[id] || []).map(row => row.id);
      const selected = next[id] || [];
      next[id] = ids.length && ids.every(rowId => selected.includes(rowId))
        ? selected.filter(rowId => !ids.includes(rowId))
        : Array.from(new Set([...selected, ...ids]));
    }
    return next;
  });
  const toggleRow = (supplierId: number, id: number) => setSelectedBySupplier(current => ({
    ...current, [supplierId]: (current[supplierId] || []).includes(id)
      ? current[supplierId].filter(x => x !== id) : [...(current[supplierId] || []), id]
  }));

  const createForms = async () => {
    setBusy(true); setError(''); setNotice(''); setCreatedLinks([]);
    const results: CreatedLink[] = [];
    try {
      for (const supplier of selectedSuppliers) {
        const listinoIds = selectedBySupplier[supplier.id] || [];
        if (!listinoIds.length) continue;
        const result = await fetchWithAuth('/supplier-price-forms/', { method: 'POST', body: JSON.stringify({
          supplier_id: supplier.id, listino_ids: listinoIds, expires_in_days: days, note: note.trim() || null
        }) }) as CreateResult;
        results.push({ supplier, url: publicOrigin + result.public_path, publicPath: result.public_path });
        setCreatedLinks([...results]);
      }
      if (!results.length) throw new Error('Seleziona almeno una riga per ciascun fornitore a cui vuoi inviare il modulo.');
      setNotice(results.length === selectedSuppliers.length ? `Creati ${results.length} moduli. Premi WhatsApp sul fornitore da contattare; il messaggio è precompilato e dovrai confermare l’invio in WhatsApp.` : `Creati ${results.length} moduli su ${selectedSuppliers.length}. Alcuni fornitori non avevano righe selezionate o si è verificato un errore.`);
      await loadForms();
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Creazione non riuscita');
      if (results.length) setNotice(`Sono già stati creati ${results.length} moduli; i link disponibili sono mostrati qui sotto.`);
    } finally { setBusy(false); }
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
  const copyLink = async (url: string) => {
    try { await navigator.clipboard.writeText(url); setNotice('Link copiato negli appunti.'); }
    catch { setNotice('Copia non disponibile: seleziona e copia il link mostrato.'); }
  };
  const whatsappUrl = (item: CreatedLink) => {
    const phone = phoneForWhatsApp(item.supplier.telefono_contatto);
    if (!phone || !publicUrlReady) return '';
    const message = `Buongiorno ${item.supplier.nome_azienda}, ti inviamo il modulo per la verifica del listino: ${item.url}\n\nIl link scade tra ${days} giorni.`;
    return `https://wa.me/${phone}?text=${encodeURIComponent(message)}`;
  };

  return <div style={{ display: 'grid', gap: 20, maxWidth: 1200 }}>
    <section style={card}>
      <h2 style={{ marginTop: 0 }}>Crea modulo per i fornitori</h2>
      <p style={{ color: 'var(--text-secondary)' }}>Scegli uno o più fornitori oppure una categoria per includere automaticamente tutti i fornitori associati. Puoi selezionare il listino e le righe da inviare. Le risposte non modificano il listino master: ogni invio genera un link personale.</p>
      <div style={{ display: 'flex', gap: 8, marginBottom: 14, flexWrap: 'wrap' }}>
        <button type="button" className={recipientMode === 'suppliers' ? 'btn btn-primary' : 'btn'} onClick={() => { setRecipientMode('suppliers'); setSupplierIds([]); setCreatedLinks([]); }}>Seleziona fornitori</button>
        <button type="button" className={recipientMode === 'category' ? 'btn btn-primary' : 'btn'} onClick={() => { setRecipientMode('category'); setSupplierIds([]); setRecipientCategory(''); setCreatedLinks([]); }}>Seleziona per categoria</button>
      </div>
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit,minmax(220px,1fr))', gap: 12 }}>
        {localBrowserOrigin && <label style={{ gridColumn: '1 / -1' }}>Indirizzo pubblico da inserire nei link
          <input style={field} type="url" value={publicBaseUrl} onChange={e => {
            const value = e.target.value.trim();
            setPublicBaseUrl(value);
            if (value) localStorage.setItem('supplierFormsPublicBaseUrl', value);
            else localStorage.removeItem('supplierFormsPublicBaseUrl');
          }} placeholder="https://tuo-dominio.it oppure https://tuo-tunnel.lhr.life" />
          <small style={{ display: 'block', color: 'var(--text-secondary)', marginTop: 5 }}>Incolla il dominio pubblico che il fornitore può aprire. Un indirizzo localhost non funziona sul suo telefono. Se usi un tunnel temporaneo, resterà valido solo finché il tunnel è attivo.</small>
        </label>}
        {recipientMode === 'category' ? <label>Categoria fornitori
          <select style={field} value={recipientCategory} onChange={e => setRecipientCategory(e.target.value)}>
            <option value="">Seleziona categoria…</option>
            {categories.map(category => <option key={category.nome} value={category.nome}>{category.nome}</option>)}
          </select>
        </label> : <div style={{ gridColumn: '1 / -1' }}>
          <strong>Fornitori ({supplierIds.length} selezionati)</strong>
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit,minmax(220px,1fr))', gap: 6, maxHeight: 190, overflow: 'auto', padding: 8, border: '1px solid var(--border-glass)', borderRadius: 8, marginTop: 6 }}>
            {suppliers.map(s => <label key={s.id} style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
              <input type="checkbox" checked={supplierIds.includes(s.id)} onChange={e => { setSupplierIds(current => e.target.checked ? [...current, s.id] : current.filter(id => id !== s.id)); setCreatedLinks([]); }} />
              <span>{s.nome_azienda}</span>
            </label>)}
          </div>
        </div>}
        <label>Scadenza link<select style={field} value={days} onChange={e => setDays(Number(e.target.value))}>{[7,14,21,30].map(d => <option key={d} value={d}>{d} giorni</option>)}</select></label>
        <label style={{ gridColumn: '1 / -1' }}>Nota per i fornitori<textarea style={field} rows={2} maxLength={1000} value={note} onChange={e => setNote(e.target.value)} placeholder="Facoltativa" /></label>
      </div>
      {recipientMode === 'category' && recipientCategory && <p style={{ color: 'var(--text-secondary)' }}>Fornitori associati a {recipientCategory}: <strong>{selectedSuppliers.length}</strong></p>}
      {selectedSupplierIds.length > 0 && <div style={{ marginTop: 16, display: 'grid', gap: 12 }}>
        <label>Listino / sezione da inviare
          <select style={field} value={listinoSection} onChange={e => setListinoSection(e.target.value)} disabled={recipientMode === 'category'}>
            {groupOptions.map(option => <option key={option.value} value={option.value}>{option.label}</option>)}
          </select>
        </label>
        {recipientMode === 'category' && <small style={{ color: 'var(--text-secondary)' }}>Selezione automatica di tutte le righe {recipientCategory} disponibili nei listini dei fornitori associati.</small>}
        <div style={{ display: 'flex', justifyContent: 'space-between', gap: 8, alignItems: 'center', flexWrap: 'wrap' }}>
          <strong>Fornitori {selectedSuppliers.length} · righe visibili {visibleRows.length} · selezionate {selectedCount}</strong>
          <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
            {selectedCount > 0 && recipientMode === 'suppliers' && <button className="btn" type="button" onClick={() => setSelectedBySupplier({})}>Azzera selezione</button>}
            {recipientMode === 'suppliers' && <button className="btn" type="button" onClick={toggleVisibleRows} disabled={!visibleRows.length}>{allVisibleSelected ? 'Deseleziona righe visibili' : 'Seleziona righe visibili'}</button>}
          </div>
        </div>
        {loadingCatalog ? <p>Caricamento listini dei fornitori…</p> : <div style={{ maxHeight: 360, overflow: 'auto', border: '1px solid var(--border-glass)', borderRadius: 8 }}>
          {selectedSupplierIds.map(id => {
            const supplier = suppliers.find(s => s.id === id)!;
            const supplierRows = visibleRowsBySupplier[id] || [];
            return <div key={id}>
              <div style={{ position: 'sticky', top: 0, padding: 9, background: 'var(--bg-secondary)', borderBottom: '1px solid var(--border-glass)' }}><strong>{supplier.nome_azienda}</strong> · {supplierRows.length} righe</div>
              {supplierRows.map(r => <label key={r.id} style={{ display: 'grid', gridTemplateColumns: '24px 1fr auto', gap: 10, padding: 10, borderBottom: '1px solid var(--border-glass)', alignItems: 'center' }}>
                <input type="checkbox" disabled={recipientMode === 'category'} checked={recipientMode === 'category' || (selectedBySupplier[id] || []).includes(r.id)} onChange={() => toggleRow(id, r.id)} />
                <span>{r.descrizione}<small style={{ display: 'block', color: 'var(--text-secondary)' }}>{r.sku_interno}{r.category ? ` · ${r.category}${r.subcategory ? ' / ' + r.subcategory : ''}` : ' · Senza categoria'}</small></span>
                <span>€ {r.prezzo_pattuito} / {r.unita_misura}</span>
              </label>)}
              {!supplierRows.length && <p style={{ padding: 10, color: 'var(--text-secondary)' }}>Nessuna riga disponibile per questa sezione.</p>}
            </div>;
          })}
          {!selectedSuppliers.length && <p style={{ padding: 12, color: 'var(--text-secondary)' }}>Nessun fornitore associato a questa categoria.</p>}
        </div>}
      </div>}
      <button className="btn btn-primary" style={{ marginTop: 16 }} disabled={busy || loadingCatalog || !selectedSupplierIds.length || !selectedCount || !publicUrlReady} onClick={createForms}>{busy ? 'Creazione moduli…' : `Crea ${selectedSupplierIds.length > 1 ? 'moduli' : 'link personale'}`}</button>
      {!publicUrlReady && <p style={{ color: '#fbbf24' }}>Inserisci un URL pubblico valido per creare link apribili dai fornitori.</p>}
      {createdLinks.map(item => {
        const wa = whatsappUrl(item);
        return <div key={item.supplier.id} style={{ ...card, marginTop: 14, borderColor: 'rgba(34,197,94,.45)' }}>
          <strong>Link pronto per {item.supplier.nome_azienda}</strong>
          <p style={{ overflowWrap: 'anywhere' }}>{item.url}</p>
          <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
            <button className="btn" type="button" onClick={() => copyLink(item.url)}>Copia link</button>
            {wa && <a className="btn btn-primary" href={wa} target="_blank" rel="noopener noreferrer" style={{ textDecoration: 'none', background: '#25D366', borderColor: '#25D366' }}>WhatsApp · {item.supplier.nome_azienda}</a>}
          </div>
          {!phoneForWhatsApp(item.supplier.telefono_contatto) && <p style={{ color: '#fbbf24', marginBottom: 0 }}>Numero WhatsApp mancante in anagrafica: copia il link e invialo manualmente.</p>}
          {!publicUrlReady && <p style={{ color: '#fbbf24', marginBottom: 0 }}>Il link pubblico non è configurato correttamente.</p>}
        </div>;
      })}
      {notice && <div role="status" style={{ color: '#86efac', marginTop: 10 }}>{notice}</div>}
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
  </div>;
}


