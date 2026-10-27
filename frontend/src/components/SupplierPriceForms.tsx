import { useEffect, useMemo, useState } from 'react';
import type { CSSProperties } from 'react';
import { fetchWithAuth } from '../api';
import { prepareNormalizedSheet, writeNormalizedSheet } from './normalizedSupplierSheet';
import type { SheetOfferTarget } from './normalizedSupplierSheet';

type Supplier = { id: number; nome_azienda: string; telefono_contatto?: string | null };
type CapabilitySupplier = { supplier_id: number; supplier_name: string; categories: Record<string, boolean> };
type Category = { nome: string; is_active: boolean };
type PriceRow = { id: number; sku_interno: string; descrizione: string; prezzo_pattuito?: number | string | null; unita_misura: string; data_inizio_validita?: string | null; data_scadenza?: string | null; category?: string | null; subcategory?: string | null };
type FormItem = { id: number; sku_interno: string; descrizione: string; prezzo_corrente?: string | null; unita_corrente?: string | null; brand_corrente?: string | null; prezzo_inviato?: string | null; unita_inviata?: string | null; brand_inviata?: string | null; dicitura_inviata?: string | null; quantita_inviata?: string | null; conferma_prezzo?: boolean | null; non_trattato?: boolean; nota_fornitore?: string | null; esito: string };
type FormRequest = { id: number; supplier_id: number; supplier_name: string; request_type?: 'confirmation' | 'new_listino'; status: string; created_at: string; expires_at: string; submitted_at?: string | null; validita_inviata_da?: string | null; validita_inviata_a?: string | null; note?: string | null; items: FormItem[] };
type CreateResult = { request: FormRequest; token: string; public_path: string };
type CreatedLink = { supplier: Supplier; url: string; publicPath: string };
type MatrixResponse = { categories?: Category[]; suppliers?: CapabilitySupplier[] };

const card: CSSProperties = { border: '1px solid var(--border-glass)', borderRadius: 12, padding: 16, background: 'rgba(255,255,255,.025)' };
const field: CSSProperties = { width: '100%', boxSizing: 'border-box', padding: 10, color: 'white', background: 'var(--bg-secondary)', border: '1px solid var(--border-glass)', borderRadius: 8 };
const configuredPublicOrigin = ((import.meta as any).env?.VITE_PUBLIC_APP_URL || '').trim().replace(/\/$/, '');
const localBrowserOrigin = /^(https?:\/\/)?(localhost|127\.0\.0\.1)(:\d+)?$/i.test(window.location.origin);
const isLocalAddress = (value: string) => /^(https?:\/\/)?(localhost|127\.0\.0\.1)(:\d+)?$/i.test(value.trim());


const GOOGLE_SHEETS_CLIENT_ID = '52128477187-k0hkvu9vj0v3sbk7tf07rehhvosg0ors.apps.googleusercontent.com';
const GOOGLE_SHEETS_SCOPE = 'https://www.googleapis.com/auth/spreadsheets';
const GOOGLE_SHEETS_API = 'https://sheets.googleapis.com/v4/spreadsheets';
function loadGoogleIdentityScript(): Promise<void> {
  const google = (window as any).google;
  if (google?.accounts?.oauth2) return Promise.resolve();
  return new Promise((resolve, reject) => {
    const existing = document.querySelector<HTMLScriptElement>('script[data-google-identity-services]');
    if (existing) {
      existing.addEventListener('load', () => resolve(), { once: true });
      existing.addEventListener('error', () => reject(new Error('Impossibile caricare il login Google.')), { once: true });
      return;
    }
    const script = document.createElement('script');
    script.src = 'https://accounts.google.com/gsi/client';
    script.async = true; script.defer = true; script.dataset.googleIdentityServices = 'true';
    script.onload = () => resolve(); script.onerror = () => reject(new Error('Impossibile caricare il login Google.'));
    document.head.appendChild(script);
  });
}

async function requestGoogleSheetsWriteToken(): Promise<string> {
  await loadGoogleIdentityScript();
  return new Promise((resolve, reject) => {
    const google = (window as any).google;
    const client = google.accounts.oauth2.initTokenClient({
      client_id: GOOGLE_SHEETS_CLIENT_ID, scope: GOOGLE_SHEETS_SCOPE,
      callback: (response: any) => {
        if (response?.error || !response?.access_token) reject(new Error(response?.error_description || response?.error || 'Consenso Google non completato.'));
        else resolve(response.access_token as string);
      },
      error_callback: (error: any) => reject(new Error(error?.message || 'Popup Google non disponibile.')),
    });
    client.requestAccessToken();
  });
}

async function googleSheetRequest(url: string, token: string, init?: RequestInit): Promise<any> {
  const response = await fetch(url, { ...init, headers: { Authorization: 'Bearer ' + token, ...(init?.headers || {}) } });
  const body = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(body?.error?.message || 'Google Sheets ha restituito HTTP ' + response.status);
  return body;
}

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
  const [requestType, setRequestType] = useState<'confirmation' | 'new_listino'>('confirmation');
  const [productCategory, setProductCategory] = useState('');
  const [supplierIds, setSupplierIds] = useState<number[]>([]);
  const [recipientCategory, setRecipientCategory] = useState('');
  const [rowsBySupplier, setRowsBySupplier] = useState<Record<number, PriceRow[]>>({});
  const [selectedBySupplier, setSelectedBySupplier] = useState<Record<number, number[]>>({});
  const [listinoSection, setListinoSection] = useState('all');
  const [days, setDays] = useState(14);
  const [note, setNote] = useState('');
  const [publicBaseUrl, setPublicBaseUrl] = useState(() => {
    if (configuredPublicOrigin) return configuredPublicOrigin;
    if (localBrowserOrigin) return localStorage.getItem('supplierFormsPublicBaseUrl') || window.location.origin;
    return window.location.origin;
  });
  const [forms, setForms] = useState<FormRequest[]>([]);
  const [createdLinks, setCreatedLinks] = useState<CreatedLink[]>([]);
  const [detail, setDetail] = useState<FormRequest | null>(null);
  const [busy, setBusy] = useState(false);
  const [loadingCatalog, setLoadingCatalog] = useState(false);
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');
  const [sheetUrl, setSheetUrl] = useState(() => localStorage.getItem('ps.normalized-sheet.url') || '');
  const [sheetTargets, setSheetTargets] = useState<SheetOfferTarget[] | null>(null);
  const [sheetBusy, setSheetBusy] = useState(false);
  const [sheetAccessToken, setSheetAccessToken] = useState('');
  const [sheetError, setSheetError] = useState('');
  const [sheetNotice, setSheetNotice] = useState('');

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
  const publicUrlReady = /^https?:\/\//i.test(publicOrigin) && (!isLocalAddress(publicOrigin) || localBrowserOrigin);

  useEffect(() => {
    let live = true;
    setRowsBySupplier({});
    setSelectedBySupplier({});
    setCreatedLinks([]);
    setListinoSection(recipientMode === 'category' && recipientCategory ? 'category:' + recipientCategory : 'all');
    if (!selectedSupplierIds.length) { setLoadingCatalog(false); return; }
    if (requestType === 'new_listino') {
      const category = recipientMode === 'category' ? recipientCategory : productCategory;
      if (!category) { setLoadingCatalog(false); return; }
      setLoadingCatalog(true);
      fetchWithAuth('/supplier-price-forms/catalog-products?category=' + encodeURIComponent(category))
        .then((result: any) => {
          if (!live) return;
          const products = (Array.isArray(result) ? result : result.items || result.records || []).filter((p: any) => p && p.id);
          const rows: PriceRow[] = products.map((p: any) => ({
            id: p.id, sku_interno: p.sku_interno, descrizione: p.descrizione,
            unita_misura: p.unita_misura, category: p.category, subcategory: p.subcategory,
          }));
          setRowsBySupplier(Object.fromEntries(selectedSupplierIds.map(id => [id, rows])));
          setSelectedBySupplier(Object.fromEntries(selectedSupplierIds.map(id => [id, rows.map(row => row.id)])));
        })
        .catch((e: unknown) => { if (live) setError(e instanceof Error ? e.message : 'Impossibile caricare il catalogo prodotti'); })
        .finally(() => { if (live) setLoadingCatalog(false); });
      return () => { live = false; };
    }
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
  }, [selectedSupplierIds.join(','), recipientMode, recipientCategory, requestType, productCategory]);

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
          supplier_id: supplier.id,
          request_type: requestType,
          ...(requestType === 'new_listino'
            ? { category: recipientMode === 'category' ? recipientCategory : productCategory, product_ids: listinoIds }
            : { listino_ids: listinoIds }),
          expires_in_days: days, note: note.trim() || null
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
    setError(''); setSheetTargets(null); setSheetError(''); setSheetNotice(''); setSheetAccessToken('');
    try { setDetail(await fetchWithAuth('/supplier-price-forms/' + id)); }
    catch (e) { setError(e instanceof Error ? e.message : 'Impossibile caricare il dettaglio'); }
  };

  const prepareSheetOffer = async () => {
    if (!detail || detail.status !== 'submitted') return;
    setSheetBusy(true); setSheetError(''); setSheetNotice(''); setSheetTargets(null);
    try {
      const match = sheetUrl.trim().match(/docs\.google\.com\/spreadsheets\/d\/([A-Za-z0-9_-]+)/);
      if (!match) throw new Error('Inserisci il link del nuovo Google Sheet.');
      const token = await requestGoogleSheetsWriteToken();
      setSheetAccessToken(token);
      const root = GOOGLE_SHEETS_API + '/' + encodeURIComponent(match[1]);
      const targets = await prepareNormalizedSheet(root, token, detail, googleSheetRequest);
      setSheetTargets(targets);
      setSheetNotice('Anteprima pronta per ID prodotto e fornitore. Nessuna riga è stata modificata.');
    } catch (e) { setSheetError(e instanceof Error ? e.message : 'Anteprima Sheet non riuscita.'); }
    finally { setSheetBusy(false); }
  };

  const writeSheetOffer = async () => {
    if (!detail || !sheetTargets?.some(target => target.status === 'ready') || sheetTargets.some(target => target.status === 'blocked') || sheetBusy) return;
    const ready = sheetTargets.filter(target => target.status === 'ready');
    const summary = ready.map(target => (target.cell || target.tab) + ': ' + (target.current || '(vuoto)') + ' → ' + target.offered + ' ' + target.unit).join('\n');
    if (!window.confirm('Confermi le offerte selezionate nel nuovo Sheet?\n\n' + summary)) return;
    setSheetBusy(true); setSheetError(''); setSheetNotice('');
    try {
      const match = sheetUrl.trim().match(/docs\.google\.com\/spreadsheets\/d\/([A-Za-z0-9_-]+)/);
      if (!match) throw new Error('Link Google Sheet non valido.');
      const token = sheetAccessToken || await requestGoogleSheetsWriteToken();
      const root = GOOGLE_SHEETS_API + '/' + encodeURIComponent(match[1]);
      await writeNormalizedSheet(root, token, detail, ready, googleSheetRequest);
      setSheetTargets(sheetTargets.map(target => target.status === 'ready' ? { ...target, status: 'written', reason: 'Offerta scritta nello Sheet.' } : target));
      setSheetNotice('Offerte registrate nel nuovo Sheet. Per aggiornare il listino operativo V2, apri Santo Graal e conferma la relativa anteprima di importazione.');
    } catch (e) { setSheetError(e instanceof Error ? e.message : 'Scrittura nello Sheet non riuscita.'); }
    finally { setSheetBusy(false); }
  };


  const closeForm = async (id: number) => {
    setBusy(true); setError('');
    try { await fetchWithAuth('/supplier-price-forms/' + id + '/close', { method: 'POST' }); setDetail(null); await loadForms(); }
    catch (e) { setError(e instanceof Error ? e.message : 'Chiusura non riuscita'); }
    finally { setBusy(false); }
  };
  const deleteForm = async (form: FormRequest) => {
    const confirmed = window.confirm(
      `Eliminare definitivamente il modulo per ${form.supplier_name}? Il link verrà revocato e le risposte del fornitore cancellate. Il listino ufficiale non verrà modificato.`
    );
    if (!confirmed) return;
    setBusy(true); setError(''); setNotice('');
    try {
      await fetchWithAuth('/supplier-price-forms/' + form.id, { method: 'DELETE' });
      if (detail?.id === form.id) setDetail(null);
      setNotice(`Modulo per ${form.supplier_name} eliminato. Il listino ufficiale non è stato modificato.`);
      await loadForms();
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Eliminazione non riuscita');
    } finally { setBusy(false); }
  };

  const copyLink = async (url: string) => {
    try { await navigator.clipboard.writeText(url); setNotice('Link copiato negli appunti.'); }
    catch { setNotice('Copia non disponibile: seleziona e copia il link mostrato.'); }
  };
  const whatsappUrl = (item: CreatedLink) => {
    const phone = phoneForWhatsApp(item.supplier.telefono_contatto);
    if (!phone || !publicUrlReady || isLocalAddress(publicOrigin)) return '';
    const message = `Buongiorno ${item.supplier.nome_azienda}, ti inviamo il modulo per la verifica del listino: ${item.url}\n\nIl link scade tra ${days} giorni.`;
    return `https://wa.me/${phone}?text=${encodeURIComponent(message)}`;
  };

  return <div style={{ display: 'grid', gap: 20, maxWidth: 1200 }}>
    <section style={card}>
      <h2 style={{ marginTop: 0 }}>Crea modulo per i fornitori</h2>
      <p style={{ color: 'var(--text-secondary)' }}>Scegli i destinatari e il catalogo prodotti. Le risposte dei fornitori restano proposte da revisionare e non modificano automaticamente il listino ufficiale.</p>
      <div style={{ display: 'flex', gap: 8, marginBottom: 14, flexWrap: 'wrap' }}>
        <button type="button" className={requestType === 'confirmation' ? 'btn btn-primary' : 'btn'} onClick={() => { setRequestType('confirmation'); setCreatedLinks([]); }}>Conferma prezzi esistenti</button>
        <button type="button" className={requestType === 'new_listino' ? 'btn btn-primary' : 'btn'} onClick={() => { setRequestType('new_listino'); setCreatedLinks([]); }}>Richiedi nuovo listino</button>
      </div>
      <div style={{ display: 'flex', gap: 8, marginBottom: 14, flexWrap: 'wrap' }}>
        <button type="button" className={recipientMode === 'suppliers' ? 'btn btn-primary' : 'btn'} onClick={() => { setRecipientMode('suppliers'); setSupplierIds([]); setCreatedLinks([]); }}>Seleziona fornitori</button>
        <button type="button" className={recipientMode === 'category' ? 'btn btn-primary' : 'btn'} onClick={() => { setRecipientMode('category'); setSupplierIds([]); setRecipientCategory(''); setCreatedLinks([]); }}>Seleziona per categoria</button>
      </div>
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit,minmax(220px,1fr))', gap: 12 }}>
        {localBrowserOrigin && <label style={{ gridColumn: '1 / -1' }}>Indirizzo base da inserire nei link
          <input style={field} type="url" value={publicBaseUrl} onChange={e => {
            const value = e.target.value.trim();
            setPublicBaseUrl(value);
            if (value) localStorage.setItem('supplierFormsPublicBaseUrl', value);
            else localStorage.removeItem('supplierFormsPublicBaseUrl');
          }} placeholder="http://localhost:28084 oppure https://tuo-tunnel.lhr.life" />
          <small style={{ display: 'block', color: 'var(--text-secondary)', marginTop: 5 }}>Per provare il modulo sul tuo computer puoi usare localhost. Il fornitore non potrà aprire un link localhost: prima di inviarlo, inserisci il dominio pubblico o il tunnel attivo.</small>
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
        {requestType === 'new_listino' ? <>
          {recipientMode === 'category'
            ? <p style={{ color: 'var(--text-secondary)', margin: 0 }}>Catalogo prodotti della categoria {recipientCategory}, da quotare da zero.</p>
            : <label>Categoria prodotti da richiedere
                <select style={field} value={productCategory} onChange={e => setProductCategory(e.target.value)}>
                  <option value="">Seleziona categoria…</option>
                  {categories.map(category => <option key={category.nome} value={category.nome}>{category.nome}</option>)}
                </select>
              </label>}
          <small style={{ color: 'var(--text-secondary)' }}>Vengono inclusi i prodotti attivi del catalogo generale per la categoria scelta. Il fornitore inserirà prezzi e unità; nessun prezzo di altri fornitori viene copiato.</small>
        </> : <>
          <label>Listino / sezione da inviare
            <select style={field} value={listinoSection} onChange={e => setListinoSection(e.target.value)} disabled={recipientMode === 'category'}>
              {groupOptions.map(option => <option key={option.value} value={option.value}>{option.label}</option>)}
            </select>
          </label>
          {recipientMode === 'category' && <small style={{ color: 'var(--text-secondary)' }}>Selezione automatica di tutte le righe {recipientCategory} disponibili nei listini dei fornitori associati.</small>}
        </>}
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
                <span>{requestType === 'new_listino' ? `Da quotare / ${r.unita_misura}` : `€ ${r.prezzo_pattuito} / ${r.unita_misura}`}</span>
              </label>)}
              {!supplierRows.length && <p style={{ padding: 10, color: 'var(--text-secondary)' }}>Nessuna riga disponibile per questa sezione.</p>}
            </div>;
          })}
          {!selectedSuppliers.length && <p style={{ padding: 12, color: 'var(--text-secondary)' }}>Nessun fornitore associato a questa categoria.</p>}
        </div>}
      </div>}
      <button className="btn btn-primary" style={{ marginTop: 16 }} disabled={busy || loadingCatalog || !selectedSupplierIds.length || !selectedCount || !publicUrlReady || (requestType === 'new_listino' && recipientMode === 'suppliers' && !productCategory)} onClick={createForms}>{busy ? 'Creazione moduli…' : requestType === 'new_listino' ? `Richiedi ${selectedSupplierIds.length > 1 ? 'nuovi listini' : 'nuovo listino'}` : `Crea ${selectedSupplierIds.length > 1 ? 'moduli' : 'link personale'}`}</button>
      {!publicUrlReady && <p style={{ color: '#fbbf24' }}>Inserisci un indirizzo valido: localhost per test locali oppure un dominio/tunnel pubblico per i fornitori.</p>}
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
          {isLocalAddress(publicOrigin) && <p style={{ color: '#fbbf24', marginBottom: 0 }}>Link di test locale: si apre solo su questo computer. Imposta un tunnel o dominio pubblico prima di inviarlo al fornitore.</p>}
        </div>;
      })}
      {notice && <div role="status" style={{ color: '#86efac', marginTop: 10 }}>{notice}</div>}
    </section>

    <section style={card}>
      <div style={{ display: 'flex', justifyContent: 'space-between', gap: 12, alignItems: 'center' }}>
        <h2 style={{ margin: 0 }}>Moduli creati</h2><button className="btn" type="button" onClick={loadForms}>Aggiorna</button>
      </div>
      {forms.length ? <div style={{ overflowX: 'auto', marginTop: 12 }}><table style={{ width: '100%', borderCollapse: 'collapse' }}><thead><tr><th align="left">Fornitore</th><th align="left">Tipo</th><th align="left">Creato</th><th align="left">Scadenza</th><th align="left">Stato</th><th></th></tr></thead><tbody>
        {forms.map(f => <tr key={f.id}><td>{f.supplier_name}</td><td>{f.request_type === 'new_listino' ? 'Nuova offerta' : 'Conferma prezzi'}</td><td>{new Date(f.created_at).toLocaleDateString('it-IT')}</td><td>{new Date(f.expires_at).toLocaleDateString('it-IT')}</td><td>{f.status}</td><td style={{ whiteSpace: 'nowrap' }}><button className="btn" type="button" onClick={() => openDetail(f.id)}>Dettaglio</button> <button className="btn" type="button" disabled={busy} onClick={() => deleteForm(f)} aria-label={`Elimina modulo per ${f.supplier_name}`} title="Elimina modulo">Elimina</button></td></tr>)}
      </tbody></table></div> : <p style={{ color: 'var(--text-secondary)' }}>Nessun modulo ancora creato.</p>}
    </section>

    {detail && <section style={card}>
      <div style={{ display: 'flex', justifyContent: 'space-between', gap: 12 }}><h2 style={{ marginTop: 0 }}>{detail.request_type === 'new_listino' ? 'Nuova offerta da revisionare' : 'Risposte'} · {detail.supplier_name}</h2><button className="btn" onClick={() => setDetail(null)}>Chiudi</button></div>
      <p>Stato: <strong>{detail.status}</strong>{detail.submitted_at ? ' · inviato ' + new Date(detail.submitted_at).toLocaleString('it-IT') : ''}</p>
      <p>Validità indicata dal fornitore: <strong>{detail.validita_inviata_da ? `dal ${new Date(detail.validita_inviata_da + 'T00:00:00').toLocaleDateString('it-IT')}${detail.validita_inviata_a ? ` al ${new Date(detail.validita_inviata_a + 'T00:00:00').toLocaleDateString('it-IT')}` : ' fino a nuova approvazione'}` : 'non ancora indicata'}</strong></p>
      {detail.status === 'submitted' && <div style={{ ...card, marginBottom: 12 }}>
        <h3 style={{ marginTop: 0 }}>Revisiona l’offerta nel nuovo Sheet</h3>
        <p style={{ color: 'var(--text-secondary)' }}>Le righe vengono abbinate per ID prodotto e ID fornitore. Controlla l’anteprima prima di scrivere; poi importa i prezzi approvati nel listino operativo V2.</p>
        <label>Link del nuovo Google Sheet<input style={field} type="url" value={sheetUrl} onChange={e => { setSheetUrl(e.target.value); localStorage.setItem('ps.normalized-sheet.url', e.target.value); setSheetTargets(null); setSheetNotice(''); setSheetAccessToken(''); }} placeholder="https://docs.google.com/spreadsheets/d/…" /></label>
        <div style={{ display: 'flex', gap: 8, marginTop: 10, flexWrap: 'wrap' }}>
          <button type="button" className="btn" disabled={sheetBusy || !sheetUrl.trim()} onClick={() => void prepareSheetOffer()}>{sheetBusy ? 'Lettura e controllo…' : 'Prepara anteprima Sheet'}</button>
          {sheetTargets?.some(target => target.status === 'ready') && <button type="button" className="btn btn-primary" disabled={sheetBusy || sheetTargets.some(target => target.status === 'blocked')} onClick={() => void writeSheetOffer()}>{sheetBusy ? 'Scrittura…' : 'Conferma scrittura nello Sheet'}</button>}
        </div>
        {sheetError && <p role="alert" style={{ color: '#fca5a5' }}>{sheetError}</p>}
        {sheetTargets?.some(target => target.status === 'blocked') && <p role="alert" style={{ color: '#fbbf24' }}>Ci sono righe bloccate. Risolvi gli ID o le associazioni indicate e prepara di nuovo l’anteprima prima di scrivere.</p>}
        {sheetNotice && <p role="status" style={{ color: '#86efac' }}>{sheetNotice}</p>}
        {sheetTargets && <div style={{ overflowX: 'auto', marginTop: 10 }}><table style={{ width: '100%', borderCollapse: 'collapse' }}><thead><tr><th align="left">Prodotto</th><th align="left">Riga</th><th align="left">Dicitura / marca</th><th align="left">Confezione</th><th align="left">Prezzo confezione</th><th align="left">Data / note</th><th align="left">Esito</th></tr></thead><tbody>
          {sheetTargets.map(target => <tr key={target.item_id}><td>{target.product}<small style={{ display: 'block', color: 'var(--text-secondary)' }}>{target.sku}</small></td><td>{target.cell || '—'}</td><td>{target.nextRow ? <>{target.snapshot?.[5] || 'vuoto'} / {target.snapshot?.[6] || 'vuoto'} → <strong>{target.nextRow[5]} / {target.nextRow[6]}</strong></> : '—'}</td><td>{target.nextRow ? <>{target.snapshot?.[7] || 'vuoto'} {target.snapshot?.[8] || ''} → <strong>{target.nextRow[7]} {target.nextRow[8]}</strong></> : '—'}</td><td>{target.current || 'vuoto'} → {target.offered || '—'}</td><td>{target.nextRow ? <>{target.snapshot?.[10] || 'vuoto'} → <strong>{target.nextRow[10]}</strong><small style={{ display: 'block' }}>{target.nextRow[11]}</small></> : '—'}</td><td>{target.status === 'ready' ? 'Pronto alla conferma' : target.status === 'already' ? 'Già presente' : target.status === 'written' ? 'Scritto' : target.status === 'not_trattato' ? 'Non trattato · escluso' : 'Bloccato · ' + target.reason}</td></tr>)}
        </tbody></table></div>}
      </div>}
      <div style={{ display: 'grid', gap: 8 }}>{detail.items.map(i => <div key={i.id} style={{ ...card, padding: 12 }}>
        <strong>{i.descrizione}</strong><small style={{ display: 'block', color: 'var(--text-secondary)' }}>{i.sku_interno}</small>
        <div>{detail.request_type === 'new_listino' ? 'Nessun prezzo precedente · Offerta: ' : 'Pattuito: € ' + i.prezzo_corrente + ' / ' + (i.unita_corrente || 'unità da completare') + ' · Risposta: '}{i.non_trattato ? 'Non trattato dal fornitore' : i.prezzo_inviato ? '€ ' + i.prezzo_inviato + ' / ' + (i.unita_inviata || 'unità da completare') : 'in attesa'}</div>
        <div>Dicitura del fornitore: {i.dicitura_inviata || 'da compilare'} · Marca: {i.brand_inviata || 'da compilare'} · Confezione: {i.quantita_inviata || 'da compilare'} {i.unita_inviata || ''}</div>
        <div>Esito: {i.esito === 'non_trattato' ? 'Non trattato' : i.esito === 'confermato' ? 'Confermato' : i.esito === 'nuova_offerta' ? 'Nuova offerta da revisionare' : i.esito === 'proposta_variazione' ? 'Proposta di variazione' : 'Da compilare'}{i.nota_fornitore ? ' · Nota: ' + i.nota_fornitore : ''}</div>
      </div>)}</div>
      {['open','submitted','expired'].includes(detail.status) && <button className="btn" disabled={busy} onClick={() => closeForm(detail.id)}>Chiudi link</button>}
      <p style={{ color: 'var(--text-secondary)' }}>Per applicare un’eventuale variazione, revisiona la proposta e usa il normale flusso di approvazione/importazione.</p>
    </section>}
    {error && <div role="alert" style={{ color: '#fca5a5' }}>{error}</div>}
  </div>;
}



