import { useEffect, useMemo, useState } from 'react';
import type { CSSProperties } from 'react';
import { API_BASE, fetchWithAuth, getHeaders, refreshAuthSession } from '../api';

type Supplier = { id: number; nome_azienda: string; telefono_contatto?: string | null };
type CapabilitySupplier = { supplier_id: number; supplier_name: string; categories: Record<string, boolean> };
type Category = { nome: string; is_active: boolean };
type PriceRow = { id: number; sku_interno: string; descrizione: string; prezzo_pattuito?: number | string | null; unita_misura: string; data_inizio_validita?: string | null; data_scadenza?: string | null; category?: string | null; subcategory?: string | null };
type SubmittedOffer = { id_offerta: string; prezzo: string; unita_misura: string; marca: string; dicitura_fornitore: string; quantita_confezione: string; nota?: string | null; conferma_prezzo: boolean };
type FormItem = { id: number; sku_interno: string; descrizione: string; prezzo_corrente?: string | null; unita_corrente?: string | null; quantita_corrente?: string | null; brand_corrente?: string | null; prezzo_inviato?: string | null; unita_inviata?: string | null; brand_inviata?: string | null; dicitura_inviata?: string | null; quantita_inviata?: string | null; offerte_inviate?: SubmittedOffer[]; conferma_prezzo?: boolean | null; non_trattato?: boolean; nota_fornitore?: string | null; esito: string; best_price?: string | null; best_price_unit?: string | null; recipient_is_best?: boolean | null };
type SupplierDetails = { ragione_sociale: string; partita_iva: string; telefono_ordini: string };
type FormRequest = { id: number; supplier_id: number; supplier_name: string; requires_supplier_details?: boolean; anagrafica_inviata?: SupplierDetails | null; request_type?: 'confirmation' | 'new_listino'; show_best_price?: boolean; status: string; created_at: string; expires_at: string; submitted_at?: string | null; validita_inviata_da?: string | null; validita_inviata_a?: string | null; note?: string | null; items: FormItem[] };
type CreateResult = { request: FormRequest; token: string; public_path: string };

const FORM_STATUS_LABELS: Record<string, string> = {
  open: 'Aperto',
  submitted: 'Da revisionare',
  approved: 'Approvato',
  rejected: 'Rifiutato',
  expired: 'Scaduto',
  closed: 'Chiuso',
};
const formStatusLabel = (status: string) => FORM_STATUS_LABELS[status] ?? status;
const BASE_UNIT_LABELS: Record<string, string> = { kg: 'kg', liter: 'litro', piece: 'pezzo', box: 'confezione', bottle: 'bottiglia' };
const bestPriceText = (price: string, unit?: string | null) =>
  `€ ${Number(price).toLocaleString('it-IT', { minimumFractionDigits: 2, maximumFractionDigits: 4 })}/${BASE_UNIT_LABELS[unit || ''] || unit || ''}`;
type CreatedLink = { supplier: Supplier; url: string; publicPath: string };
type MatrixResponse = { categories?: Category[]; suppliers?: CapabilitySupplier[] };

const card: CSSProperties = { border: '1px solid var(--line)', borderRadius: 'var(--radius-lg)', padding: 16, background: 'var(--bg-card)' };
const field: CSSProperties = { width: '100%', boxSizing: 'border-box', padding: 10, color: 'var(--text-primary)', background: 'var(--bg-inset)', border: '1px solid var(--line)', borderRadius: 'var(--radius-sm)' };
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
  const [requestType, setRequestType] = useState<'confirmation' | 'new_listino'>('confirmation');
  const [productCategory, setProductCategory] = useState('');
  const [supplierIds, setSupplierIds] = useState<number[]>([]);
  const [recipientCategory, setRecipientCategory] = useState('');
  const [rowsBySupplier, setRowsBySupplier] = useState<Record<number, PriceRow[]>>({});
  const [selectedBySupplier, setSelectedBySupplier] = useState<Record<number, number[]>>({});
  const [listinoSection, setListinoSection] = useState('all');
  const [days, setDays] = useState(14);
  const [note, setNote] = useState('');
  const [showBestPrice, setShowBestPrice] = useState(false);  // opt-in per form, never on by default
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
  const [listNotice, setListNotice] = useState('');  // feedback for actions on created forms (link, PDF)
  const [newSupplierOpen, setNewSupplierOpen] = useState(false);
  const [newSupplierName, setNewSupplierName] = useState('');
  const [newSupplierCategories, setNewSupplierCategories] = useState<string[]>([]);

  // A supplier not yet in the registry: created with a provisional name, it sends
  // company name, VAT number and order phone in the form; they apply on approval.
  const createSupplier = async () => {
    setBusy(true); setError(''); setNotice('');
    try {
      const created: Supplier = await fetchWithAuth('/supplier-price-forms/new-supplier', {
        method: 'POST',
        body: JSON.stringify({ nome: newSupplierName.trim(), categories: newSupplierCategories }),
      });
      setSuppliers(current => [...current, created].sort((a, b) => a.nome_azienda.localeCompare(b.nome_azienda)));
      setSupplierIds(current => [...current, created.id]);
      setNotice(`Fornitore "${created.nome_azienda}" creato e selezionato. Nel modulo indicherà ragione sociale, partita IVA e telefono per gli ordini.`);
      setNewSupplierOpen(false); setNewSupplierName(''); setNewSupplierCategories([]);
    } catch (e) { setError(e instanceof Error ? e.message : 'Creazione fornitore non riuscita'); }
    finally { setBusy(false); }
  };

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
  }, [selectedSupplierIds, recipientMode, recipientCategory, requestType, productCategory]);

  const allRows = useMemo(
    () => selectedSupplierIds.flatMap(id => rowsBySupplier[id] || []),
    [selectedSupplierIds, rowsBySupplier]
  );
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
  }, [allRows]);
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
  })), [selectedSupplierIds, rowsBySupplier, activeGroup, recipientMode, recipientCategory]);
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
          expires_in_days: days, note: note.trim() || null, show_best_price: showBestPrice
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
  // PDF of the compiled price list, named "<fornitore> - <data di compilazione>.pdf" by the server.
  const fetchFormPdf = async (form: FormRequest): Promise<{ blob: Blob; name: string }> => {
    const url = `${API_BASE}/supplier-price-forms/${form.id}/pdf`;
    let response = await fetch(url, { headers: getHeaders() });
    if (response.status === 401 && await refreshAuthSession(true)) response = await fetch(url, { headers: getHeaders() });
    if (!response.ok) {
      const body = await response.json().catch(() => null);
      throw new Error(body?.detail || 'PDF non disponibile');
    }
    const disposition = response.headers.get('Content-Disposition') || '';
    const utf8Name = /filename\*=UTF-8''([^;]+)/i.exec(disposition)?.[1];
    const name = utf8Name ? decodeURIComponent(utf8Name) : (/filename="([^"]+)"/.exec(disposition)?.[1] || `${form.supplier_name}.pdf`);
    return { blob: await response.blob(), name };
  };
  const saveBlob = (blob: Blob, name: string) => {
    const link = document.createElement('a');
    link.href = URL.createObjectURL(blob); link.download = name; link.click();
    setTimeout(() => URL.revokeObjectURL(link.href), 10000);
  };
  const downloadPdf = async (form: FormRequest) => {
    setError(''); setNotice(''); setListNotice('');
    try {
      const { blob, name } = await fetchFormPdf(form);
      saveBlob(blob, name);
      setListNotice(`PDF scaricato: ${name}`);
    } catch (e) { setError(e instanceof Error ? e.message : 'PDF non disponibile'); }
  };
  // On phones the share sheet attaches the PDF directly (WhatsApp included);
  // on desktop it is downloaded and the supplier chat is opened.
  const sharePdf = async (form: FormRequest) => {
    setError(''); setNotice(''); setListNotice('');
    try {
      const { blob, name } = await fetchFormPdf(form);
      const file = new File([blob], name, { type: 'application/pdf' });
      const validity = form.validita_inviata_da
        ? ` valido dal ${new Date(form.validita_inviata_da + 'T00:00:00').toLocaleDateString('it-IT')}${form.validita_inviata_a ? ' al ' + new Date(form.validita_inviata_a + 'T00:00:00').toLocaleDateString('it-IT') : ''}`
        : '';
      const text = `Listino ${form.supplier_name}${validity}${form.status === 'approved' ? '' : ' (in revisione)'}.`;
      if (navigator.canShare?.({ files: [file] })) {
        try { await navigator.share({ files: [file], title: name, text }); return; }
        catch (shareError) { if ((shareError as DOMException)?.name === 'AbortError') return; }
      }
      saveBlob(blob, name);
      const phone = phoneForWhatsApp(suppliers.find(s => s.id === form.supplier_id)?.telefono_contatto);
      window.open(`https://wa.me/${phone}?text=${encodeURIComponent(text + ' In allegato il PDF.')}`, '_blank', 'noopener,noreferrer');
      setListNotice(`PDF scaricato (${name}). Nella chat WhatsApp che si è aperta allegalo con la graffetta.`
        + (phone ? '' : ' Numero del fornitore non presente: scegli tu il contatto.'));
    } catch (e) { setError(e instanceof Error ? e.message : 'PDF non disponibile'); }
  };

  const approveForm = async (id: number) => {
    if (!window.confirm('Integrare tutte le offerte di questa risposta nel listino operativo V2? I prezzi precedenti resteranno nello storico.')) return;
    setBusy(true); setError(''); setNotice('');
    try {
      const result = await fetchWithAuth('/supplier-price-forms/' + id + '/approve', { method: 'POST' });
      setNotice(`Risposta approvata: ${result.result?.created || 0} nuove varianti e ${result.result?.updated || 0} prezzi aggiornati nel listino V2.`);
      setDetail(await fetchWithAuth('/supplier-price-forms/' + id));
      await loadForms();
    } catch (e) { setError(e instanceof Error ? e.message : 'Approvazione non riuscita'); }
    finally { setBusy(false); }
  };
  const rejectForm = async (id: number) => {
    if (!window.confirm('Rifiutare questa risposta? Nessun prezzo verrà modificato.')) return;
    setBusy(true); setError(''); setNotice('');
    try {
      await fetchWithAuth('/supplier-price-forms/' + id + '/reject', { method: 'POST' });
      setNotice('Risposta rifiutata. Il listino ufficiale non è stato modificato.');
      setDetail(await fetchWithAuth('/supplier-price-forms/' + id));
      await loadForms();
    } catch (e) { setError(e instanceof Error ? e.message : 'Rifiuto non riuscito'); }
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
  // Share again the link of a queued form (open, not yet compiled): full URL copied and supplier chat opened.
  const isQueued = (form: FormRequest) => form.status === 'open' && new Date(form.expires_at).getTime() > Date.now();
  const shareFormLink = async (form: FormRequest) => {
    setError(''); setNotice(''); setListNotice('');
    if (!publicUrlReady) { setError('Indirizzo pubblico dell’app non valido: impostalo nella sezione di creazione dei moduli.'); return; }
    try {
      const call = (newLink: boolean) => fetchWithAuth(`/supplier-price-forms/${form.id}/share-link`, {
        method: 'POST', body: JSON.stringify({ new_link: newLink }),
      });
      let result = await call(false);
      if (result.needs_new_link) {
        const ok = window.confirm(`Il modulo per ${form.supplier_name} è stato creato prima che i link venissero salvati, quindi quello originale non è recuperabile.\n\nGenero un nuovo link? Il link precedente smetterà di funzionare: se l’avevi già inviato, il fornitore dovrà usare quello nuovo.`);
        if (!ok) return;
        result = await call(true);
      }
      const url = publicOrigin + result.public_path;
      const daysLeft = Math.max(1, Math.ceil((new Date(result.expires_at).getTime() - Date.now()) / 86400000));
      const phone = phoneForWhatsApp(suppliers.find(s => s.id === form.supplier_id)?.telefono_contatto);
      try { await navigator.clipboard.writeText(url); } catch { /* the link is also shown in the notice */ }
      if (!isLocalAddress(publicOrigin)) {
        const message = `Buongiorno ${form.supplier_name}, ti inviamo il modulo per la verifica del listino: ${url}\n\nIl link scade tra ${daysLeft} giorni.`;
        window.open(`https://wa.me/${phone}?text=${encodeURIComponent(message)}`, '_blank', 'noopener,noreferrer');
      }
      setListNotice(`${result.new_link ? 'Nuovo link generato e copiato' : 'Link copiato'} per ${form.supplier_name}: ${url}`
        + (isLocalAddress(publicOrigin) ? ' (indirizzo locale: non inviarlo al fornitore)' : phone ? '' : ' · numero WhatsApp non in anagrafica: scegli tu il contatto nella chat aperta'));
    } catch (e) { setError(e instanceof Error ? e.message : 'Condivisione del link non riuscita'); }
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
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit,minmax(220px,1fr))', gap: 6, maxHeight: 190, overflow: 'auto', padding: 8, border: '1px solid var(--line)', borderRadius: 'var(--radius-md)', marginTop: 6 }}>
            {suppliers.map(s => <label key={s.id} style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
              <input type="checkbox" checked={supplierIds.includes(s.id)} onChange={e => { setSupplierIds(current => e.target.checked ? [...current, s.id] : current.filter(id => id !== s.id)); setCreatedLinks([]); }} />
              <span>{s.nome_azienda}</span>
            </label>)}
          </div>
          {!newSupplierOpen ? <button type="button" className="btn" style={{ marginTop: 8 }} onClick={() => setNewSupplierOpen(true)}>+ Nuovo fornitore</button> : <div style={{ ...card, marginTop: 8, display: 'grid', gap: 10 }}>
            <strong>Nuovo fornitore</strong>
            <label>Nome provvisorio<input style={field} maxLength={255} value={newSupplierName} onChange={e => setNewSupplierName(e.target.value)} placeholder="Es. Caseificio da contattare" /></label>
            <div>Categorie trattate
              <div style={{ display: 'flex', gap: 14, flexWrap: 'wrap', marginTop: 4 }}>
                {['Food', 'Beverage', 'Materiali'].map(category => <label key={category} style={{ display: 'flex', gap: 6, alignItems: 'center' }}>
                  <input type="checkbox" checked={newSupplierCategories.includes(category)} onChange={e => setNewSupplierCategories(current => e.target.checked ? [...current, category] : current.filter(c => c !== category))} />{category}
                </label>)}
              </div>
            </div>
            <small style={{ color: 'var(--text-secondary)' }}>Ragione sociale, partita IVA e telefono per gli ordini li inserirà il fornitore nel modulo. Diventano definitivi quando approvi la sua risposta.</small>
            <div style={{ display: 'flex', gap: 8 }}>
              <button type="button" className="btn btn-primary" disabled={busy || newSupplierName.trim().length < 2 || !newSupplierCategories.length} onClick={() => void createSupplier()}>Crea fornitore</button>
              <button type="button" className="btn" onClick={() => setNewSupplierOpen(false)}>Annulla</button>
            </div>
          </div>}
        </div>}
        <label>Scadenza link<select style={field} value={days} onChange={e => setDays(Number(e.target.value))}>{[7,14,21,30].map(d => <option key={d} value={d}>{d} giorni</option>)}</select></label>
        <label style={{ gridColumn: '1 / -1' }}>Nota per i fornitori<textarea style={field} rows={2} maxLength={1000} value={note} onChange={e => setNote(e.target.value)} placeholder="Facoltativa" /></label>
        <label style={{ gridColumn: '1 / -1', display: 'flex', gap: 8, alignItems: 'flex-start' }}>
          <input type="checkbox" checked={showBestPrice} onChange={e => setShowBestPrice(e.target.checked)} style={{ marginTop: 3 }} />
          <span><strong>Mostra ai fornitori il miglior prezzo ricevuto</strong>
            <small style={{ display: 'block', color: 'var(--text-secondary)' }}>Accanto a ogni prodotto il fornitore vede il prezzo più basso degli altri fornitori, senza nomi, solo se confrontabile per unità (€/kg, €/pezzo…). Non compare se il fornitore ha già un prezzo uguale o più basso; se è il migliore vede “Siete il prezzo migliore”.</small></span>
        </label>
      </div>
      {recipientMode === 'category' && recipientCategory && <p style={{ color: 'var(--text-secondary)' }}>Fornitori associati a {recipientCategory}: <strong>{selectedSuppliers.length}</strong></p>}
      {selectedSupplierIds.length > 0 && <div style={{ marginTop: 16, display: 'grid', gap: 12 }}>
        {requestType === 'new_listino' ? <>
          {recipientMode === 'category'
            ? <p style={{ color: 'var(--text-secondary)', margin: 0 }}>Catalogo prodotti della categoria {recipientCategory}, uguale per tutti i fornitori: i prezzi già a listino di ciascuno sono precompilati, gli altri prodotti sono da quotare.</p>
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
        {loadingCatalog ? <p>Caricamento listini dei fornitori…</p> : <div style={{ maxHeight: 360, overflow: 'auto', border: '1px solid var(--line)', borderRadius: 'var(--radius-md)' }}>
          {selectedSupplierIds.map(id => {
            const supplier = suppliers.find(s => s.id === id)!;
            const supplierRows = visibleRowsBySupplier[id] || [];
            return <div key={id}>
              <div style={{ position: 'sticky', top: 0, padding: 9, background: 'var(--bg-inset)', borderBottom: '1px solid var(--line)' }}><strong>{supplier.nome_azienda}</strong> · {supplierRows.length} righe</div>
              {supplierRows.map(r => <label key={r.id} style={{ display: 'grid', gridTemplateColumns: '24px 1fr auto', gap: 10, padding: 10, borderBottom: '1px solid var(--line)', alignItems: 'center' }}>
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
      {!publicUrlReady && <p style={{ color: 'var(--warn)' }}>Inserisci un indirizzo valido: localhost per test locali oppure un dominio/tunnel pubblico per i fornitori.</p>}
      {createdLinks.map(item => {
        const wa = whatsappUrl(item);
        return <div key={item.supplier.id} style={{ ...card, marginTop: 14, borderColor: 'var(--ok-border)' }}>
          <strong>Link pronto per {item.supplier.nome_azienda}</strong>
          <p style={{ overflowWrap: 'anywhere' }}>{item.url}</p>
          <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
            <button className="btn" type="button" onClick={() => copyLink(item.url)}>Copia link</button>
            {wa && <a className="btn btn-primary" href={wa} target="_blank" rel="noopener noreferrer" style={{ textDecoration: 'none', background: '#25D366', borderColor: '#25D366' }}>WhatsApp · {item.supplier.nome_azienda}</a>}
          </div>
          {!phoneForWhatsApp(item.supplier.telefono_contatto) && <p style={{ color: 'var(--warn)', marginBottom: 0 }}>Numero WhatsApp mancante in anagrafica: copia il link e invialo manualmente.</p>}
          {isLocalAddress(publicOrigin) && <p style={{ color: 'var(--warn)', marginBottom: 0 }}>Link di test locale: si apre solo su questo computer. Imposta un tunnel o dominio pubblico prima di inviarlo al fornitore.</p>}
        </div>;
      })}
      {notice && <div role="status" style={{ color: 'var(--ok)', marginTop: 10 }}>{notice}</div>}
    </section>

    <section style={card}>
      <div style={{ display: 'flex', justifyContent: 'space-between', gap: 12, alignItems: 'center' }}>
        <h2 style={{ margin: 0 }}>Moduli creati</h2><button className="btn" type="button" onClick={loadForms}>Aggiorna</button>
      </div>
      {listNotice && <div role="status" style={{ color: 'var(--ok)', marginTop: 10, overflowWrap: 'anywhere' }}>{listNotice}</div>}
      {error && <div role="alert" style={{ color: 'var(--crit)', marginTop: 10 }}>{error}</div>}
      {forms.length ? <div style={{ overflowX: 'auto', marginTop: 12 }}><table className="ds-table" style={{ width: '100%', borderCollapse: 'collapse' }}><thead><tr><th align="left">Fornitore</th><th align="left">Tipo</th><th align="left">Creato</th><th align="left">Scadenza</th><th align="left">Stato</th><th></th></tr></thead><tbody>
        {forms.map(f => <tr key={f.id}><td>{f.supplier_name}</td><td>{f.request_type === 'new_listino' ? 'Nuova offerta' : 'Conferma prezzi'}</td><td>{new Date(f.created_at).toLocaleDateString('it-IT')}</td><td>{new Date(f.expires_at).toLocaleDateString('it-IT')}</td><td>{formStatusLabel(f.status)}</td><td style={{ whiteSpace: 'nowrap' }}><button className="btn" type="button" onClick={() => openDetail(f.id)}>Dettaglio</button> {isQueued(f) && <><button className="btn" type="button" style={{ background: '#25D366', borderColor: '#25D366', color: '#fff' }} onClick={() => void shareFormLink(f)} title="Copia il link e apri la chat WhatsApp del fornitore">Condividi link</button> </>}{['submitted', 'approved'].includes(f.status) && <><button className="btn" type="button" onClick={() => void downloadPdf(f)} title="Scarica il PDF con i prezzi">PDF</button> </>}<button className="btn" type="button" disabled={busy || f.status === 'approved'} onClick={() => deleteForm(f)} aria-label={`Elimina modulo per ${f.supplier_name}`} title="Elimina modulo">Elimina</button></td></tr>)}
      </tbody></table></div> : <p style={{ color: 'var(--text-secondary)' }}>Nessun modulo ancora creato.</p>}
    </section>

    {detail && <section style={card}>
      <div style={{ display: 'flex', justifyContent: 'space-between', gap: 12 }}><h2 style={{ marginTop: 0 }}>{detail.request_type === 'new_listino' ? 'Nuova offerta da revisionare' : 'Risposte'} · {detail.supplier_name}</h2><button className="btn" onClick={() => setDetail(null)}>Chiudi</button></div>
      <p>Stato: <strong>{formStatusLabel(detail.status)}</strong>{detail.submitted_at ? ' · inviato ' + new Date(detail.submitted_at).toLocaleString('it-IT') : ''}</p>
      {isQueued(detail) && <p><button type="button" className="btn" style={{ background: '#25D366', borderColor: '#25D366', color: '#fff' }} onClick={() => void shareFormLink(detail)}>Condividi link al fornitore</button></p>}
      {['submitted', 'approved'].includes(detail.status) && <p style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
        <button type="button" className="btn" onClick={() => void downloadPdf(detail)}>⬇️ Scarica PDF prezzi</button>
        <button type="button" className="btn" onClick={() => void sharePdf(detail)}>📄 Condividi PDF su WhatsApp</button>
      </p>}
      {detail.anagrafica_inviata ? <div style={{ ...card, marginBottom: 12, borderColor: 'var(--warn-border)' }}>
        <strong>Dati aziendali inviati dal fornitore</strong>
        <div>Ragione sociale: {detail.anagrafica_inviata.ragione_sociale}</div>
        <div>Partita IVA: {detail.anagrafica_inviata.partita_iva}</div>
        <div>Telefono per gli ordini: {detail.anagrafica_inviata.telefono_ordini}</div>
        {detail.status === 'submitted' && <small style={{ color: 'var(--text-secondary)' }}>Con l’approvazione questi dati sostituiscono il nome provvisorio nell’anagrafica fornitore.</small>}
      </div> : detail.requires_supplier_details && <p style={{ color: 'var(--warn)' }}>Fornitore nuovo: ragione sociale, partita IVA e telefono arriveranno con la risposta.</p>}
      {detail.show_best_price && <p style={{ color: 'var(--warn)' }}>Modulo inviato con il miglior prezzo di mercato visibile al fornitore ({detail.items.filter(i => i.best_price).length} prodotti).</p>}
      <p>Validità indicata dal fornitore: <strong>{detail.validita_inviata_da ? `dal ${new Date(detail.validita_inviata_da + 'T00:00:00').toLocaleDateString('it-IT')}${detail.validita_inviata_a ? ` al ${new Date(detail.validita_inviata_a + 'T00:00:00').toLocaleDateString('it-IT')}` : ' fino a nuova approvazione'}` : 'non ancora indicata'}</strong></p>
      {detail.status === 'submitted' && <div style={{ ...card, marginBottom: 12, borderColor: 'var(--accent-border)' }}>
        <h3 style={{ marginTop: 0 }}>Risposta pronta per la revisione</h3>
        <p style={{ color: 'var(--text-secondary)' }}>Controlla prezzi, marche, formati e unità qui sotto. L’approvazione integra direttamente le offerte nel listino V2: Google Sheet non è necessario.</p>
        <p style={{ color: 'var(--warn)' }}>Più marche o formati restano varianti distinte. I prezzi precedenti vengono conservati nello storico e il nuovo prezzo resta valido fino alla prossima approvazione, salvo la scadenza indicata.</p>
        <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
          <button type="button" className="btn btn-primary" disabled={busy} onClick={() => void approveForm(detail.id)}>{busy ? 'Integrazione…' : 'Approva e integra nel listino V2'}</button>
          <button type="button" className="btn" disabled={busy} onClick={() => void rejectForm(detail.id)}>Rifiuta risposta</button>
        </div>
      </div>}
      <div style={{ display: 'grid', gap: 8 }}>{detail.items.map(i => <div key={i.id} style={{ ...card, padding: 12 }}>
        <strong>{i.descrizione}</strong><small style={{ display: 'block', color: 'var(--text-secondary)' }}>{i.sku_interno}</small>
        {i.prezzo_corrente != null && <div>Pattuito: € {i.prezzo_corrente} {i.unita_corrente ? (i.quantita_corrente && Number(i.quantita_corrente) !== 1 ? `per ${Number(i.quantita_corrente).toLocaleString('it-IT')} ${i.unita_corrente}` : `/ ${i.unita_corrente}`) : '/ unità da completare'}</div>}
        {detail.show_best_price && i.best_price && <div style={{ color: 'var(--text-secondary)' }}>Mostrato al fornitore: {i.recipient_is_best ? '“Siete il prezzo migliore”' : `miglior prezzo ricevuto ${bestPriceText(i.best_price, i.best_price_unit)}`}</div>}
        {i.non_trattato ? <div>Non trattato dal fornitore</div> : i.offerte_inviate?.length ? i.offerte_inviate.map((offer, index) => <div key={offer.id_offerta} style={{ marginTop: 8, padding: 8, borderLeft: '2px solid var(--accent-text)' }}>
          <strong>Offerta {index + 1}: € {offer.prezzo} per confezione da {offer.quantita_confezione} {offer.unita_misura}</strong>
          <div>{offer.dicitura_fornitore}{offer.marca ? ' · Marca: ' + offer.marca : ''}</div><small>ID offerta: {offer.id_offerta}{offer.nota ? ' · Nota: ' + offer.nota : ''}</small>
        </div>) : <><div>Offerta: {i.prezzo_inviato ? '€ ' + i.prezzo_inviato + ' per confezione' : 'in attesa'}</div><div>Dicitura del fornitore: {i.dicitura_inviata || 'da compilare'} · Marca: {i.brand_inviata || 'da compilare'} · Confezione: {i.quantita_inviata || 'da compilare'} {i.unita_inviata || ''}</div></>}
        <div>Esito: {i.esito === 'non_trattato' ? 'Non trattato' : i.esito === 'confermato' ? 'Confermato' : i.esito === 'nuova_offerta' ? 'Nuova offerta da revisionare' : i.esito === 'proposta_variazione' ? 'Proposta di variazione' : 'Da compilare'}{i.nota_fornitore ? ' · Nota: ' + i.nota_fornitore : ''}</div>
      </div>)}</div>
      {['open','submitted','expired'].includes(detail.status) && <button className="btn" disabled={busy} onClick={() => closeForm(detail.id)}>Chiudi link</button>}
      <p style={{ color: 'var(--text-secondary)' }}>Questo flusso è interamente gestito nell’app. Lo Sheet non è necessario per raccogliere o approvare i prezzi dei fornitori.</p>
    </section>}
    {error && <div role="alert" style={{ color: 'var(--crit)' }}>{error}</div>}
  </div>;
}



