import { useState, useEffect, useMemo } from 'react';
import {
  Layers,
  Search,
  RefreshCw,
  Plus,
  Link2,
  CheckCircle2,
  AlertTriangle,
  Sparkles,
  Building2,
  EyeOff,
  Check,
  Calendar,
  ChevronDown,
  ChevronUp,
  Loader2,
  Zap,
  MessageSquare,
  Clock,
  Edit3,
  Trash2,
  Store,
  X,
} from 'lucide-react';
import { API_BASE, getHeaders } from '../api';

interface WorkQueueCandidate {
  candidate_id: number;
  product_id: number;
  sku_interno: string | null;
  canonical_name: string;
  score: number;
  reason_json: Record<string, any>;
}

interface WorkQueueItem {
  work_key: string;
  supplier_id: number;
  supplier_name: string;
  supplier_code: string | null;
  raw_description: string;
  normalized_description: string;
  occurrence_count: number;
  invoice_count: number;
  invoice_line_ids: number[];
  latest_invoice_date: string;
  candidate_records: number;
  recommendation: 'associate_existing' | 'create_canonical';
  best_candidate: WorkQueueCandidate | null;
  alternatives: WorkQueueCandidate[];
  prezzo_unitario?: number;
  unita_misura?: string;
  quantita?: number;
  numero_documento?: string;
  data_documento?: string;
  suggested_product: {
    canonical_name: string;
    category: string | null;
    subcategory?: string | null;
    volume_ml: number | null;
    weight_g: number | null;
    unit_count: number;
    container_type: string | null;
    comparison_unit: string;
  };
}

interface WorkQueueResponse {
  summary: {
    work_items: number;
    invoice_lines: number;
    reliable_suggestions: number;
    probable_new_products: number;
    weak_candidates_hidden: number;
  };
  items: WorkQueueItem[];
}

interface ExistingProduct {
  id: number;
  sku_interno: string | null;
  canonical_name: string;
  category: string | null;
  subcategory: string | null;
  comparison_unit: string;
}

interface StandbyQuoteSupplier {
  supplier_id: number;
  supplier_name: string;
  phone?: string | null;
  email?: string | null;
  whatsapp_message?: string | null;
  whatsapp_url?: string | null;
  capability_reason?: string | null;
  quote_price?: number | null;
  quote_uom?: string | null;
  notes?: string | null;
  status: string;
}

interface StandbyQuoteRequestItem {
  id: number;
  product_id?: number | null;
  canonical_name: string;
  order_name?: string | null;
  category?: string | null;
  subcategory?: string | null;
  brand?: string | null;
  comparison_unit: string;
  sku_interno?: string | null;
  status: string;
  notes?: string | null;
  suppliers_data: StandbyQuoteSupplier[];
  created_at: string;
  updated_at: string;
}

const WORK_QUEUE_CACHE_KEY = 'price-sentinel:unlisted-work-queue:v1';

function readCachedWorkQueue(): WorkQueueResponse | null {
  try {
    const raw = sessionStorage.getItem(WORK_QUEUE_CACHE_KEY);
    if (!raw) return null;
    const parsed = JSON.parse(raw) as { savedAt: number; data: WorkQueueResponse };
    // The cached result is only a fast visual bridge while the live request runs.
    // Discard old browser sessions so operational decisions never rely on stale data.
    if (!parsed?.data || Date.now() - parsed.savedAt > 5 * 60 * 1000) {
      sessionStorage.removeItem(WORK_QUEUE_CACHE_KEY);
      return null;
    }
    return parsed.data;
  } catch {
    return null;
  }
}

function cacheWorkQueue(data: WorkQueueResponse) {
  try {
    sessionStorage.setItem(WORK_QUEUE_CACHE_KEY, JSON.stringify({ savedAt: Date.now(), data }));
  } catch {
    // Storage can be unavailable or full; the live request remains authoritative.
  }
}

// Le stesse categorie del catalogo: una proposta del server (es. "Attrezzatura")
// non va più trasformata in "Food" perché assente da questo elenco.
const CATEGORIES = [
  'Food',
  'Beverage',
  'Materiali',
  'Attrezzatura',
  'Gelati confezionati',
];
const LEGACY_CATEGORY: Record<string, string> = {
  'Materiali di consumo': 'Materiali',
  'Detergenti & Sanificazione': 'Materiali',
  'Monouso & Packaging': 'Materiali',
  'Alcolici & Liquori': 'Beverage',
  'Birre': 'Beverage',
  'Vini & Spumanti': 'Beverage',
  'Soft Drink & Acque': 'Beverage',
  'Caffetteria': 'Beverage',
};

// Unità ammesse dal server (normalization.canonical_unit): Pz, Kg, Lt, CT.
const UNITS = ['Pz', 'Kg', 'Lt', 'CT'];
const UNIT_SYNONYMS: Record<string, string> = {
  pz: 'Pz', pezzo: 'Pz', pezzi: 'Pz', piece: 'Pz', nr: 'Pz', n: 'Pz', bt: 'Pz', btl: 'Pz', bottiglia: 'Pz', fl: 'Pz',
  kg: 'Kg', k: 'Kg', chili: 'Kg', kilo: 'Kg',
  l: 'Lt', lt: 'Lt', litro: 'Lt', litri: 'Lt',
  ct: 'CT', cartone: 'CT', cs: 'CT', cassa: 'CT', crt: 'CT', cf: 'CT', cnf: 'CT', conf: 'CT', confezione: 'CT',
};
function canonicalUnit(value?: string | null): string | null {
  const key = (value || '').trim().toLowerCase().replace(/\.+$/, '');
  return UNIT_SYNONYMS[key] || null;
}

function errorText(detail: any, fallback: string): string {
  if (!detail) return fallback;
  if (typeof detail === 'string') return detail;
  if (detail.message) return detail.message;
  return fallback;
}

export default function UnlistedProductsResolver({ onNavigate }: { onNavigate?: (tab: string) => void }) {
  const [queueData, setQueueData] = useState<WorkQueueResponse | null>(() => readCachedWorkQueue());
  const [existingProducts, setExistingProducts] = useState<ExistingProduct[]>([]);
  const [loading, setLoading] = useState(() => !readCachedWorkQueue());
  const [refreshing, setRefreshing] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [actionSuccess, setActionSuccess] = useState<string | null>(null);

  // Main view tab: 'unlisted' vs 'standby'
  const [activeMainTab, setActiveMainTab] = useState<'unlisted' | 'standby'>('unlisted');
  const [standbyItems, setStandbyItems] = useState<StandbyQuoteRequestItem[]>([]);
  const [loadingStandby, setLoadingStandby] = useState(false);
  const [standbyStatusFilter, setStandbyStatusFilter] = useState<'all' | 'standby' | 'completed'>('all');
  const [standbySearch, setStandbySearch] = useState('');

  // Standby item compile modal state
  const [compilingItem, setCompilingItem] = useState<StandbyQuoteRequestItem | null>(null);
  const [compileForm, setCompileForm] = useState({
    supplier_id: 0,
    prezzo_concordato: '',
    unita_misura: 'Pz',
    sku_interno: '',
    category: '',
    subcategory: '',
    brand: '',
    notes: ''
  });
  const [submittingCompile, setSubmittingCompile] = useState(false);

  // Filters
  const [searchTerm, setSearchTerm] = useState('');
  const [selectedSupplierId, setSelectedSupplierId] = useState<string>('all');
  const [statusFilter, setStatusFilter] = useState<'all' | 'suggested' | 'unmatched'>('all');

  // Active expanded item for resolution
  const [activeItemKey, setActiveItemKey] = useState<string | null>(null);
  const [activeMode, setActiveMode] = useState<'create' | 'associate'>('create');

  // Form State for "Create as New in Price List"
  const [createForm, setCreateForm] = useState({
    canonical_name: '',
    sku_interno: '',
    category: '',
    subcategory: '',
    comparison_unit: 'Pz',
    prezzo_listino: '',
    unita_misura_listino: 'Pz',
    data_inizio_validita: '',
  });

  // Form State for "Associate to Existing"
  const [associateSearch, setAssociateSearch] = useState('');
  const [selectedExistingId, setSelectedExistingId] = useState<number | null>(null);
  const [associatePriceListino, setAssociatePriceListino] = useState<string>('');
  const [associateUomListino, setAssociateUomListino] = useState<string>('Pz');

  // Loading indicator for resolution in flight
  const [resolvingKey, setResolvingKey] = useState<string | null>(null);

  // Bulk selection and resolution state
  const [selectedKeys, setSelectedKeys] = useState<Set<string>>(new Set());
  const [bulkNewCategory, setBulkNewCategory] = useState('');
  const [bulkResolving, setBulkResolving] = useState(false);
  const [showSmartPlan, setShowSmartPlan] = useState(false);
  const [smartPlanTab, setSmartPlanTab] = useState<'safe' | 'review' | 'new'>('safe');
  const [approvedAssociationKeys, setApprovedAssociationKeys] = useState<Set<string>>(new Set());
  const [selectedCandidateIds, setSelectedCandidateIds] = useState<Record<string, number>>({});
  const [includeNewProducts, setIncludeNewProducts] = useState(false);

  // Dynamic subcategories (Food and other sectors)
  const [availableSubcategories, setAvailableSubcategories] = useState<string[]>([]);
  const [showInlineNewSubcat, setShowInlineNewSubcat] = useState(false);
  const [inlineNewSubcatName, setInlineNewSubcatName] = useState('');
  const [creatingSubcat, setCreatingSubcat] = useState(false);

  const fetchSubcategories = async (catName: string) => {
    try {
      const res = await fetch(`${API_BASE}/categories/subcategories?categoria_nome=${encodeURIComponent(catName)}`, {
        headers: getHeaders(),
      });
      if (res.ok) {
        const data = await res.json();
        setAvailableSubcategories(data.map((d: any) => d.nome));
      } else {
        setAvailableSubcategories([]);
      }
    } catch {
      setAvailableSubcategories([]);
    }
  };

  useEffect(() => {
    if (createForm.category) {
      fetchSubcategories(createForm.category);
    }
  }, [createForm.category]);

  const handleCreateInlineSubcategory = async () => {
    if (!inlineNewSubcatName.trim()) return;
    if (!createForm.category) {
      alert('Scegli prima la categoria');
      return;
    }
    setCreatingSubcat(true);
    try {
      const res = await fetch(`${API_BASE}/categories/subcategories`, {
        method: 'POST',
        headers: getHeaders(),
        body: JSON.stringify({
          categoria_nome: createForm.category,
          nome: inlineNewSubcatName.trim(),
          is_active: true,
        }),
      });
      if (res.ok) {
        const created = await res.json();
        setAvailableSubcategories(prev => [...prev.filter(n => n !== created.nome), created.nome].sort());
        setCreateForm(prev => ({ ...prev, subcategory: created.nome }));
        setShowInlineNewSubcat(false);
        setInlineNewSubcatName('');
      } else {
        const err = await res.json();
        alert(err.detail || 'Errore nella creazione della sottocategoria');
      }
    } catch (err: any) {
      alert(err.message || 'Errore di connessione');
    } finally {
      setCreatingSubcat(false);
    }
  };

  useEffect(() => {
    loadAll();
  // Initial resolver bootstrap; mutations invoke reload explicitly.
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    if (activeMainTab === 'standby' && standbyItems.length === 0 && !loadingStandby) {
      void loadStandbyData();
    }
  // Standby is intentionally lazy-loaded only when the operator opens its tab.
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [activeMainTab]);

  const loadAll = async () => {
    const hasVisibleData = queueData !== null;
    if (hasVisibleData) setRefreshing(true);
    else setLoading(true);
    setError(null);
    try {
      // The catalog is useful only when the operator opens manual association.
      // Load it independently so a large product list cannot block the queue UI.
      void fetch(`${API_BASE}/products`, { headers: getHeaders() })
        .then(async response => {
          if (response.ok) setExistingProducts(await response.json());
        })
        .catch(() => undefined);

      const queueRes = await fetch(`${API_BASE}/product-identity/match-candidates/work-queue`, {
        headers: getHeaders(),
      });

      if (!queueRes.ok) throw new Error('Errore nel caricamento delle voci fuori listino');
      const qData: WorkQueueResponse = await queueRes.json();
      setQueueData(qData);
      cacheWorkQueue(qData);
    } catch (err: any) {
      setError(err.message || 'Errore di connessione');
    } finally {
      setLoading(false);
      setRefreshing(false);
    }
  };

  const loadStandbyData = async () => {
    setLoadingStandby(true);
    try {
      const res = await fetch(`${API_BASE}/ordini/settore/richieste-prezzo/standby`, {
        headers: getHeaders(),
      });
      if (res.ok) {
        const data = await res.json();
        setStandbyItems(data);
      }
    } catch (err: any) {
      console.error("Errore caricamento dati standby:", err);
    } finally {
      setLoadingStandby(false);
    }
  };

  const handleOpenCompileModal = (item: StandbyQuoteRequestItem) => {
    setCompilingItem(item);
    const firstSupplierId = item.suppliers_data[0]?.supplier_id || 0;
    setCompileForm({
      supplier_id: firstSupplierId,
      prezzo_concordato: '',
      unita_misura: item.comparison_unit || 'Pz',
      sku_interno: item.sku_interno || '',
      category: item.category || '',
      subcategory: item.subcategory || '',
      brand: item.brand || '',
      notes: ''
    });
  };

  const handleSaveCompile = async () => {
    if (!compilingItem) return;
    if (!compileForm.supplier_id) {
      alert("Seleziona il fornitore che ha fornito la quotazione.");
      return;
    }
    const priceVal = parseFloat(compileForm.prezzo_concordato);
    if (isNaN(priceVal) || priceVal <= 0) {
      alert("Inserisci un prezzo concordato valido maggiore di 0.");
      return;
    }

    setSubmittingCompile(true);
    try {
      const payload = {
        supplier_id: compileForm.supplier_id,
        prezzo_concordato: priceVal,
        unita_misura: compileForm.unita_misura,
        sku_interno: compileForm.sku_interno.trim() || undefined,
        category: compileForm.category.trim() || undefined,
        subcategory: compileForm.subcategory.trim() || undefined,
        brand: compileForm.brand.trim() || undefined,
        notes: compileForm.notes.trim() || undefined
      };

      const res = await fetch(`${API_BASE}/ordini/settore/richieste-prezzo/standby/${compilingItem.id}/completa`, {
        method: 'POST',
        headers: getHeaders(),
        body: JSON.stringify(payload)
      });

      const data = await res.json();
      if (!res.ok) throw new Error(data.detail || "Errore durante il completamento del prodotto.");

      setActionSuccess(`✅ Prodotto "${compilingItem.canonical_name}" compilato con successo, salvato in archivio ed inserito nel listino del fornitore!`);
      setTimeout(() => setActionSuccess(null), 6000);
      setCompilingItem(null);
      await Promise.all([loadAll(), loadStandbyData()]);
    } catch (err: any) {
      alert(err.message || "Impossibile completare la scheda prodotto");
    } finally {
      setSubmittingCompile(false);
    }
  };

  const handleDeleteStandby = async (id: number, canonicalName: string) => {
    if (!window.confirm(`Sei sicuro di voler eliminare la richiesta in standby per "${canonicalName}"?`)) {
      return;
    }
    try {
      const res = await fetch(`${API_BASE}/ordini/settore/richieste-prezzo/standby/${id}`, {
        method: 'DELETE',
        headers: getHeaders()
      });
      if (!res.ok) throw new Error("Errore eliminazione");
      setActionSuccess("Richiesta in standby eliminata.");
      setTimeout(() => setActionSuccess(null), 3000);
      await loadStandbyData();
    } catch (err: any) {
      alert(err.message || "Errore durante l'eliminazione");
    }
  };

  const filteredStandbyItems = useMemo(() => {
    return standbyItems.filter(item => {
      if (standbyStatusFilter !== 'all' && item.status !== standbyStatusFilter) {
        return false;
      }
      if (standbySearch.trim()) {
        const q = standbySearch.toLowerCase();
        const matchName = item.canonical_name.toLowerCase().includes(q);
        const matchCat = (item.category || '').toLowerCase().includes(q);
        const matchBrand = (item.brand || '').toLowerCase().includes(q);
        const matchSupp = item.suppliers_data.some(s => s.supplier_name.toLowerCase().includes(q));
        if (!matchName && !matchCat && !matchBrand && !matchSupp) return false;
      }
      return true;
    });
  }, [standbyItems, standbyStatusFilter, standbySearch]);

  // Open item form and prepopulate fields
  const handleOpenItem = (item: WorkQueueItem, defaultMode?: 'create' | 'associate') => {
    if (activeItemKey === item.work_key) {
      setActiveItemKey(null);
      return;
    }

    setActiveItemKey(item.work_key);
    const initialMode = defaultMode || (item.best_candidate ? 'associate' : 'create');
    setActiveMode(initialMode);

    // Auto-generate a clean internal SKU based on description or supplier code
    const baseCode = (item.supplier_code || item.raw_description.slice(0, 8))
      .toUpperCase()
      .replace(/[^A-Z0-9]/g, '')
      .slice(0, 10);
    const autoSku = `SKU-${baseCode}-${Math.floor(100 + Math.random() * 900)}`;

    const rawPrice = item.prezzo_unitario !== undefined && item.prezzo_unitario > 0 
      ? item.prezzo_unitario.toFixed(2) 
      : '';
    // Unità della fattura riportata a Pz/Kg/Lt/CT: "K." -> Kg, "NR" -> Pz, "conf" -> CT.
    const rawUom = canonicalUnit(item.unita_misura) || 'Pz';
    const invoiceDate = item.data_documento || item.latest_invoice_date || new Date().toISOString().split('T')[0];

    // Nessuna categoria preselezionata per ripiego: se il server non sa proporla,
    // l'operatore la sceglie (prima finiva tutto in "Food").
    const suggestedCategory = item.suggested_product.category || '';
    const initialCategory = CATEGORIES.includes(suggestedCategory)
      ? suggestedCategory
      : (LEGACY_CATEGORY[suggestedCategory] || '');
    const initialSubcategory = item.suggested_product.subcategory || '';
    if (initialCategory) fetchSubcategories(initialCategory);

    // Populate create form
    setCreateForm({
      canonical_name: item.suggested_product.canonical_name || item.raw_description,
      sku_interno: autoSku,
      category: initialCategory,
      subcategory: initialSubcategory,
      comparison_unit: canonicalUnit(item.unita_misura) || canonicalUnit(item.suggested_product.comparison_unit) || 'Pz',
      prezzo_listino: rawPrice,
      unita_misura_listino: rawUom,
      data_inizio_validita: invoiceDate,
    });

    // Populate associate form
    if (item.best_candidate) {
      setSelectedExistingId(item.best_candidate.product_id);
      setAssociateSearch(item.best_candidate.canonical_name);
    } else {
      setSelectedExistingId(null);
      setAssociateSearch('');
    }
    setAssociatePriceListino(rawPrice);
    setAssociateUomListino(rawUom);
  };

  // Submit: Inserisci in listino come nuovo
  const handleResolveCreateNew = async (item: WorkQueueItem, allowSimilar = false) => {
    if (!createForm.canonical_name.trim()) {
      alert('Inserisci il nome del prodotto');
      return;
    }
    if (!createForm.category) {
      alert('Scegli la categoria del nuovo prodotto');
      return;
    }

    setResolvingKey(item.work_key);
    setError(null);
    try {
      const payload = {
        invoice_line_ids: item.invoice_line_ids,
        action: 'create_canonical',
        allow_similar: allowSimilar,
        canonical_data: {
          canonical_name: createForm.canonical_name.trim(),
          sku_interno: createForm.sku_interno.trim() || undefined,
          category: createForm.category,
          subcategory: createForm.subcategory.trim() || undefined,
          comparison_unit: canonicalUnit(createForm.comparison_unit) || 'Pz',
          prezzo_listino: createForm.prezzo_listino ? parseFloat(createForm.prezzo_listino) : undefined,
          unita_misura_listino: canonicalUnit(createForm.unita_misura_listino) || undefined,
          data_inizio_validita: createForm.data_inizio_validita || undefined,
        },
        insert_in_listino: true,
        prezzo_listino: createForm.prezzo_listino ? parseFloat(createForm.prezzo_listino) : undefined,
        unita_misura_listino: canonicalUnit(createForm.unita_misura_listino) || undefined,
        data_inizio_validita: createForm.data_inizio_validita || undefined,
      };

      const res = await fetch(`${API_BASE}/product-identity/match-candidates/work-queue/resolve`, {
        method: 'POST',
        headers: getHeaders(),
        body: JSON.stringify(payload),
      });

      const data = await res.json();
      if (res.status === 409 && data.detail?.code === 'similar_products') {
        // Controllo doppioni sul catalogo: l'operatore conferma che è davvero un prodotto nuovo,
        // altrimenti passa all'associazione con il primo simile già selezionato.
        const similar: { product_id: number; canonical_name: string; score: number }[] = data.detail.similar_products || [];
        const list = similar.map(s => `• ${s.canonical_name} (${Math.round(s.score)}%)`).join('\n');
        if (window.confirm(`A catalogo esistono già prodotti simili:\n${list}\n\nOK = è un prodotto diverso, crealo comunque.\nAnnulla = associa la riga a un prodotto esistente.`)) {
          setResolvingKey(null);
          await handleResolveCreateNew(item, true);
          return;
        }
        if (similar.length) {
          setActiveMode('associate');
          setSelectedExistingId(similar[0].product_id);
          setAssociateSearch(similar[0].canonical_name);
        }
        return;
      }
      if (!res.ok) throw new Error(errorText(data.detail, 'Errore durante la creazione del prodotto in listino'));

      setActionSuccess(
        `✅ Prodotto "${createForm.canonical_name}" inserito con successo in Listino Master e associato al fornitore ${item.supplier_name}!`
      );
      setTimeout(() => setActionSuccess(null), 5000);

      // Remove from active list
      setActiveItemKey(null);
      await loadAll();
    } catch (err: any) {
      setError(err.message || 'Errore durante la registrazione');
    } finally {
      setResolvingKey(null);
    }
  };

  // Submit: Associa ad uno già esistente
  const handleResolveAssociateExisting = async (item: WorkQueueItem) => {
    if (!selectedExistingId) {
      alert('Seleziona un prodotto esistente dal catalogo a cui associare la voce');
      return;
    }

    setResolvingKey(item.work_key);
    setError(null);
    try {
      const payload = {
        invoice_line_ids: item.invoice_line_ids,
        action: 'associate_existing',
        product_id: selectedExistingId,
        insert_in_listino: true,
        prezzo_listino: associatePriceListino ? parseFloat(associatePriceListino) : undefined,
        unita_misura_listino: associateUomListino || 'Pz',
        data_inizio_validita: item.data_documento || item.latest_invoice_date || undefined,
      };

      const res = await fetch(`${API_BASE}/product-identity/match-candidates/work-queue/resolve`, {
        method: 'POST',
        headers: getHeaders(),
        body: JSON.stringify(payload),
      });

      const data = await res.json();
      if (!res.ok) throw new Error(data.detail || "Errore durante l'associazione del prodotto");

      const matchedProd = existingProducts.find(p => p.id === selectedExistingId);
      setActionSuccess(
        `🔗 Voce "${item.raw_description}" associata permanentemente a "${matchedProd?.canonical_name || 'Prodotto'}". Le future fatture verranno riconosciute automaticamente!`
      );
      setTimeout(() => setActionSuccess(null), 5000);

      setActiveItemKey(null);
      await loadAll();
    } catch (err: any) {
      setError(err.message || "Errore durante l'associazione");
    } finally {
      setResolvingKey(null);
    }
  };

  // Ignore / non monitorare
  const handleResolveIgnore = async (item: WorkQueueItem) => {
    if (!window.confirm(`Sei sicuro di voler ignorare la voce "${item.raw_description}"? Non verrà monitorata a listino.`)) {
      return;
    }

    setResolvingKey(item.work_key);
    try {
      const res = await fetch(`${API_BASE}/product-identity/match-candidates/work-queue/resolve`, {
        method: 'POST',
        headers: getHeaders(),
        body: JSON.stringify({
          invoice_line_ids: item.invoice_line_ids,
          action: 'ignore',
        }),
      });
      if (!res.ok) throw new Error("Errore durante l'operazione");
      setActiveItemKey(null);
      await loadAll();
    } catch (err: any) {
      setError(err.message || 'Errore');
    } finally {
      setResolvingKey(null);
    }
  };

  // Bulk Selection Helpers
  const toggleSelectAll = () => {
    if (selectedKeys.size === filteredItems.length) {
      setSelectedKeys(new Set());
    } else {
      setSelectedKeys(new Set(filteredItems.map(i => i.work_key)));
    }
  };

  const toggleSelectItem = (workKey: string) => {
    setSelectedKeys(prev => {
      const next = new Set(prev);
      if (next.has(workKey)) next.delete(workKey);
      else next.add(workKey);
      return next;
    });
  };

  // Bulk Resolve: Accept All / Selected Suggestions
  const handleResolveBulkSuggestions = async (targetItems?: WorkQueueItem[]) => {
    const itemsToResolve = targetItems || queueData?.items.filter(i => i.best_candidate) || [];
    if (itemsToResolve.length === 0) {
      alert('Nessun prodotto con suggerimento valido da risolvere.');
      return;
    }

    if (!window.confirm(`Sei sicuro di voler associare e risolvere ${itemsToResolve.length} prodotti con i rispettivi suggerimenti?`)) {
      return;
    }

    setBulkResolving(true);
    setError(null);
    try {
      const payload = {
        items: itemsToResolve.map(item => ({
          invoice_line_ids: item.invoice_line_ids,
          action: 'associate_existing',
          product_id: item.best_candidate!.product_id,
          insert_in_listino: true,
          prezzo_listino: item.prezzo_unitario || undefined,
          unita_misura_listino: canonicalUnit(item.unita_misura) || undefined,
          data_inizio_validita: item.data_documento || item.latest_invoice_date || undefined,
        }))
      };

      const res = await fetch(`${API_BASE}/product-identity/match-candidates/work-queue/resolve-bulk`, {
        method: 'POST',
        headers: getHeaders(),
        body: JSON.stringify(payload),
      });

      const data = await res.json();
      if (res.status === 401) {
        localStorage.removeItem('token');
        window.dispatchEvent(new Event('unauthorized'));
        throw new Error('Sessione scaduta. Accedi nuovamente per continuare.');
      }
      if (!res.ok) throw new Error(data.detail || 'Errore durante la risoluzione massiva');

      setActionSuccess(`✅ Risolti con successo ${data.resolved_items || itemsToResolve.length} prodotti (${data.resolved_lines || 0} righe fattura)!`);
      setTimeout(() => setActionSuccess(null), 6000);
      setSelectedKeys(new Set());
      await loadAll();
    } catch (err: any) {
      setError(err.message || 'Errore durante la risoluzione massiva');
    } finally {
      setBulkResolving(false);
    }
  };

  // Le risoluzioni massive proseguono anche se una voce viene rifiutata (doppione,
  // categoria mancante): le voci rifiutate restano in coda e vanno mostrate.
  const reportBulkErrors = (data: any) => {
    const details: any[] = data?.error_details || [];
    if (!details.length) return;
    const similar = details.filter(d => d.detail?.code === 'similar_products').length;
    const other = details.length - similar;
    setError(
      `${details.length} voci non risolte e rimaste in coda` +
      (similar ? `: ${similar} hanno già un prodotto simile a catalogo (aprirle una per una)` : '') +
      (other ? `${similar ? ';' : ':'} ${other} per altri motivi (es. categoria mancante)` : '') + '.'
    );
  };

  // Bulk Resolve: Insert All / Selected as New Products in Listino
  const handleResolveBulkAsNew = async (targetItems?: WorkQueueItem[], categoryOverride?: string) => {
    const itemsToResolve = targetItems || queueData?.items.filter(i => !i.best_candidate) || [];
    if (itemsToResolve.length === 0) {
      alert('Nessun prodotto da inserire come nuovo.');
      return;
    }

    const bulkCategory = categoryOverride?.trim();
    if (!bulkCategory || !CATEGORIES.includes(bulkCategory)) {
      alert('Seleziona la categoria da applicare a tutti i prodotti scelti.');
      return;
    }

    if (!window.confirm(`Sei sicuro di voler creare ${itemsToResolve.length} nuovi prodotti nel listino master con categoria "${bulkCategory}"?`)) {
      return;
    }

    setBulkResolving(true);
    setError(null);
    try {
      const payload = {
        items: itemsToResolve.map(item => {
          const rawClean = item.raw_description.trim();
          const cat = bulkCategory;
          const subcat = item.suggested_product.subcategory || '';
          const rawPrice = item.prezzo_unitario && item.prezzo_unitario > 0 ? item.prezzo_unitario : undefined;
          const rawUom = canonicalUnit(item.unita_misura) || undefined;
          const invoiceDate = item.data_documento || item.latest_invoice_date || undefined;

          return {
            invoice_line_ids: item.invoice_line_ids,
            action: 'create_canonical',
            canonical_data: {
              canonical_name: rawClean,
              category: cat,
              subcategory: subcat || undefined,
              comparison_unit: canonicalUnit(item.unita_misura) || canonicalUnit(item.suggested_product.comparison_unit) || 'Pz',
              prezzo_listino: rawPrice,
              unita_misura_listino: rawUom,
              data_inizio_validita: invoiceDate,
            },
            insert_in_listino: true,
            prezzo_listino: rawPrice,
            unita_misura_listino: rawUom,
            data_inizio_validita: invoiceDate,
          };
        })
      };

      const res = await fetch(`${API_BASE}/product-identity/match-candidates/work-queue/resolve-bulk`, {
        method: 'POST',
        headers: getHeaders(),
        body: JSON.stringify(payload),
      });

      const data = await res.json();
      if (!res.ok) throw new Error(errorText(data.detail, 'Errore durante la creazione massiva'));

      setActionSuccess(`✅ Creati e inseriti a listino ${data.resolved_items ?? 0} nuovi prodotti!`);
      setTimeout(() => setActionSuccess(null), 6000);
      setSelectedKeys(new Set());
      setBulkNewCategory('');
      await loadAll();
      reportBulkErrors(data);
    } catch (err: any) {
      setError(err.message || 'Errore durante la registrazione massiva');
    } finally {
      setBulkResolving(false);
    }
  };

  // Smart triage: only high-confidence matches are accepted automatically.
  // Medium-confidence matches always remain in the queue for human review.
  const smartPlan = useMemo(() => {
    const items = queueData?.items || [];
    return {
      safeMatches: items.filter(item => (item.best_candidate?.score || 0) >= 85),
      needsReview: items.filter(item => {
        const score = item.best_candidate?.score || 0;
        return score > 0 && score < 85;
      }),
      newProducts: items.filter(item => !item.best_candidate),
    };
  }, [queueData]);

  const smartPlanRows = smartPlanTab === 'safe'
    ? smartPlan.safeMatches
    : smartPlanTab === 'review'
      ? smartPlan.needsReview
      : smartPlan.newProducts;

  const selectedDecisionCount = approvedAssociationKeys.size + (includeNewProducts ? smartPlan.newProducts.length : 0);

  const openSmartPlan = () => {
    const initialCandidates: Record<string, number> = {};
    [...smartPlan.safeMatches, ...smartPlan.needsReview].forEach(item => {
      if (item.best_candidate) initialCandidates[item.work_key] = item.best_candidate.product_id;
    });
    setSelectedCandidateIds(initialCandidates);
    setApprovedAssociationKeys(new Set());
    setIncludeNewProducts(false);
    setSmartPlanTab(smartPlan.safeMatches.length ? 'safe' : smartPlan.needsReview.length ? 'review' : 'new');
    setShowSmartPlan(true);
  };

  const executeSmartPlan = async () => {
    const associationItems = [...smartPlan.safeMatches, ...smartPlan.needsReview]
      .filter(item => approvedAssociationKeys.has(item.work_key));
    const productsToCreate = includeNewProducts ? smartPlan.newProducts : [];
    const actionableItems = associationItems.length + productsToCreate.length;
    if (actionableItems === 0) {
      setShowSmartPlan(false);
      return;
    }

    setBulkResolving(true);
    setError(null);
    try {
      const associationPayload = associationItems.map(item => ({
        invoice_line_ids: item.invoice_line_ids,
        action: 'associate_existing',
        product_id: selectedCandidateIds[item.work_key],
        insert_in_listino: true,
        prezzo_listino: item.prezzo_unitario || undefined,
        unita_misura_listino: canonicalUnit(item.unita_misura) || undefined,
        data_inizio_validita: item.data_documento || item.latest_invoice_date || undefined,
      }));

      const creationPayload = productsToCreate.map(item => {
        const suggestedUnit = item.suggested_product.comparison_unit;
        return {
          invoice_line_ids: item.invoice_line_ids,
          action: 'create_canonical',
          canonical_data: {
            canonical_name: item.raw_description.trim(),
            // The backend generates the unique SKU from trusted server-side data.
            // Never generate random identifiers in the browser.
            category: item.suggested_product.category || undefined,
            subcategory: item.suggested_product.subcategory || undefined,
            comparison_unit: canonicalUnit(item.unita_misura) || canonicalUnit(suggestedUnit) || 'Pz',
            prezzo_listino: item.prezzo_unitario && item.prezzo_unitario > 0 ? item.prezzo_unitario : undefined,
            unita_misura_listino: canonicalUnit(item.unita_misura) || undefined,
            data_inizio_validita: item.data_documento || item.latest_invoice_date || undefined,
          },
          insert_in_listino: true,
          prezzo_listino: item.prezzo_unitario && item.prezzo_unitario > 0 ? item.prezzo_unitario : undefined,
          unita_misura_listino: canonicalUnit(item.unita_misura) || undefined,
          data_inizio_validita: item.data_documento || item.latest_invoice_date || undefined,
        };
      });

      const res = await fetch(`${API_BASE}/product-identity/match-candidates/work-queue/resolve-bulk`, {
        method: 'POST',
        headers: getHeaders(),
        body: JSON.stringify({ items: [...associationPayload, ...creationPayload] }),
      });
      const data = await res.json();
      if (!res.ok) throw new Error(errorText(data.detail, 'Errore durante la risoluzione intelligente'));

      setShowSmartPlan(false);
      setSelectedKeys(new Set());
      setActionSuccess(
        `Piano completato: ${associationItems.length} associazioni approvate, ` +
        `${productsToCreate.length} nuovi prodotti e ${data.resolved_lines || 0} righe fattura risolte. ` +
        `${smartPlan.safeMatches.length + smartPlan.needsReview.length - associationItems.length} suggerimenti restano da controllare.`
      );
      setTimeout(() => setActionSuccess(null), 9000);
      await loadAll();
      reportBulkErrors(data);
    } catch (err: any) {
      setError(err.message || 'Errore durante la risoluzione intelligente');
    } finally {
      setBulkResolving(false);
    }
  };

  // Suppliers list for dropdown filter
  const suppliersList = useMemo(() => {
    if (!queueData?.items) return [];
    const map = new Map<number, string>();
    queueData.items.forEach(it => map.set(it.supplier_id, it.supplier_name));
    return Array.from(map.entries()).map(([id, name]) => ({ id, name }));
  }, [queueData]);

  // Filtered items
  const filteredItems = useMemo(() => {
    if (!queueData?.items) return [];
    return queueData.items.filter(item => {
      // Search
      if (searchTerm) {
        const term = searchTerm.toLowerCase();
        const matchDesc = item.raw_description.toLowerCase().includes(term);
        const matchCode = (item.supplier_code || '').toLowerCase().includes(term);
        const matchSupp = item.supplier_name.toLowerCase().includes(term);
        if (!matchDesc && !matchCode && !matchSupp) return false;
      }

      // Supplier
      if (selectedSupplierId !== 'all') {
        if (item.supplier_id !== parseInt(selectedSupplierId, 10)) return false;
      }

      // Status
      if (statusFilter === 'suggested' && !item.best_candidate) return false;
      if (statusFilter === 'unmatched' && item.best_candidate) return false;

      return true;
    });
  }, [queueData, searchTerm, selectedSupplierId, statusFilter]);

  const selectedItems = useMemo(
    () => filteredItems.filter(item => selectedKeys.has(item.work_key)),
    [filteredItems, selectedKeys]
  );

  const selectedSuggestedItems = useMemo(
    () => selectedItems.filter(item => Boolean(item.best_candidate)),
    [selectedItems]
  );

  // Autocomplete suggestions for Existing Products
  const searchResultsProducts = useMemo(() => {
    if (!associateSearch || associateSearch.length < 2) {
      return existingProducts.slice(0, 15);
    }
    const q = associateSearch.toLowerCase();
    return existingProducts
      .filter(p => 
        p.canonical_name.toLowerCase().includes(q) ||
        (p.sku_interno && p.sku_interno.toLowerCase().includes(q)) ||
        (p.category && p.category.toLowerCase().includes(q))
      )
      .slice(0, 20);
  }, [existingProducts, associateSearch]);

  return (
    <div style={{ padding: '24px', display: 'flex', flexDirection: 'column', gap: '24px', maxWidth: '1400px', margin: '0 auto', width: '100%' }}>
      
      {/* Header Banner */}
      <div className="glass-panel" style={{ padding: '28px', position: 'relative', overflow: 'hidden' }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', flexWrap: 'wrap', gap: '16px' }}>
          <div>
            <div style={{ display: 'flex', alignItems: 'center', gap: '12px', marginBottom: '8px' }}>
              <div style={{
                background: 'var(--accent-bg)',
                padding: '10px',
                borderRadius: 'var(--radius-lg)',
                border: '1px solid var(--accent-border)',
                color: 'var(--accent-blue)',
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'center'
              }}>
                <Layers size={26} />
              </div>
              <div>
                <h1 style={{ fontSize: '1.6rem', fontWeight: 700, margin: 0, letterSpacing: '-0.02em' }}>
                  Prodotti Fuori Listino da Fatture
                </h1>
                <p style={{ color: 'var(--text-secondary)', fontSize: '0.9rem', marginTop: '2px' }}>
                  Riconcilia e insegna al sistema le voci non riconosciute: inseriscile a listino come nuovi articoli o associale a prodotti esistenti per le fatture future.
                </p>
              </div>
            </div>
          </div>

          <button
            onClick={loadAll}
            disabled={loading || refreshing}
            style={{
              display: 'flex',
              alignItems: 'center',
              gap: '8px',
              padding: '10px 16px',
              background: 'var(--bg-elevated)',
              border: '1px solid var(--border-glass)',
              borderRadius: 'var(--border-radius-sm)',
              color: 'var(--text-primary)',
              cursor: loading || refreshing ? 'not-allowed' : 'pointer',
              fontSize: '0.85rem',
              fontWeight: 500,
              transition: 'var(--transition-smooth)'
            }}
          >
            <RefreshCw size={16} className={loading || refreshing ? 'spin' : ''} />
            {refreshing ? 'Aggiornamento…' : 'Aggiorna Dati'}
          </button>
        </div>

        {/* Stats Metrics Grid */}
        {queueData && (
          <div style={{
            display: 'grid',
            gridTemplateColumns: 'repeat(auto-fit, minmax(200px, 1fr))',
            gap: '16px',
            marginTop: '24px',
            paddingTop: '20px',
            borderTop: '1px solid var(--border-glass)'
          }}>
            <div style={{ background: 'var(--bg-inset)', padding: '14px 18px', borderRadius: 'var(--radius-md)', border: '1px solid var(--line)' }}>
              <div style={{ fontSize: '0.75rem', color: 'var(--text-secondary)', textTransform: 'uppercase', letterSpacing: '0.5px' }}>Voci Fuori Listino</div>
              <div style={{ fontSize: '1.8rem', fontWeight: 700, color: queueData.summary.work_items > 0 ? 'var(--status-yellow)' : 'var(--status-green)', marginTop: '4px' }}>
                {queueData.summary.work_items}
              </div>
            </div>

            <div style={{ background: 'var(--bg-inset)', padding: '14px 18px', borderRadius: 'var(--radius-md)', border: '1px solid var(--line)' }}>
              <div style={{ fontSize: '0.75rem', color: 'var(--text-secondary)', textTransform: 'uppercase', letterSpacing: '0.5px' }}>Righe Fattura Coinvolte</div>
              <div style={{ fontSize: '1.8rem', fontWeight: 700, color: 'var(--text-primary)', marginTop: '4px' }}>
                {queueData.summary.invoice_lines}
              </div>
            </div>

            <div style={{ background: 'var(--bg-inset)', padding: '14px 18px', borderRadius: 'var(--radius-md)', border: '1px solid var(--line)' }}>
              <div style={{ fontSize: '0.75rem', color: 'var(--text-secondary)', textTransform: 'uppercase', letterSpacing: '0.5px' }}>Suggerimenti Intelligenti</div>
              <div style={{ fontSize: '1.8rem', fontWeight: 700, color: 'var(--accent-blue)', marginTop: '4px' }}>
                {queueData.summary.reliable_suggestions}
              </div>
            </div>

            <div style={{ background: 'var(--bg-inset)', padding: '14px 18px', borderRadius: 'var(--radius-md)', border: '1px solid var(--line)' }}>
              <div style={{ fontSize: '0.75rem', color: 'var(--text-secondary)', textTransform: 'uppercase', letterSpacing: '0.5px' }}>Fornitori con Prodotti Sospesi</div>
              <div style={{ fontSize: '1.8rem', fontWeight: 700, color: 'var(--text-primary)', marginTop: '4px' }}>
                {suppliersList.length}
              </div>
            </div>
          </div>
        )}
      </div>

      {/* Success Notification Banner */}
      {actionSuccess && (
        <div style={{
          padding: '16px 20px',
          background: 'var(--ok-bg)',
          border: '1px solid var(--ok-border)',
          borderRadius: 'var(--border-radius-md)',
          color: 'var(--ok)',
          display: 'flex',
          alignItems: 'center',
          gap: '12px',
          animation: 'fadeIn 0.3s ease',
          fontSize: '0.95rem'
        }}>
          <CheckCircle2 size={20} />
          <span>{actionSuccess}</span>
        </div>
      )}

      {/* Error Notification */}
      {error && (
        <div style={{
          padding: '16px 20px',
          background: 'var(--status-red-bg)',
          border: '1px solid var(--crit-border)',
          borderRadius: 'var(--border-radius-md)',
          color: 'var(--status-red)',
          display: 'flex',
          alignItems: 'center',
          gap: '12px',
          fontSize: '0.95rem'
        }}>
          <AlertTriangle size={20} />
          <span>{error}</span>
        </div>
      )}

      {/* Main Navigation Tabs Bar */}
      <div style={{ display: 'flex', gap: '12px', flexWrap: 'wrap' }}>
        <button
          type="button"
          onClick={() => setActiveMainTab('unlisted')}
          style={{
            padding: '12px 24px',
            borderRadius: 'var(--radius-lg)',
            border: activeMainTab === 'unlisted' ? '1px solid var(--accent-border)' : '1px solid var(--border-glass)',
            background: activeMainTab === 'unlisted' ? 'var(--accent-bg)' : 'var(--bg-inset)',
            color: activeMainTab === 'unlisted' ? 'var(--text-primary)' : 'var(--text-secondary)',
            fontWeight: 700,
            fontSize: '0.92rem',
            cursor: 'pointer',
            display: 'flex',
            alignItems: 'center',
            gap: '10px',
            boxShadow: activeMainTab === 'unlisted' ? 'none' : 'none',
            transition: 'all 0.2s'
          }}
        >
          <Layers size={18} color={activeMainTab === 'unlisted' ? 'var(--accent-text)' : 'currentColor'} />
          <span>Voci Fuori Listino da Fatture</span>
          <span style={{
            padding: '2px 8px', borderRadius: 'var(--radius-lg)',
            background: activeMainTab === 'unlisted' ? 'var(--bg-elevated)' : 'var(--bg-elevated)',
            fontSize: '0.78rem'
          }}>
            {queueData?.summary.work_items || 0}
          </span>
        </button>

        <button
          type="button"
          onClick={() => {
            setActiveMainTab('standby');
            loadStandbyData();
          }}
          style={{
            padding: '12px 24px',
            borderRadius: 'var(--radius-lg)',
            border: activeMainTab === 'standby' ? '1px solid rgba(37, 211, 102, 0.6)' : '1px solid var(--border-glass)',
            background: activeMainTab === 'standby' ? 'rgba(37, 211, 102, 0.12)' : 'var(--bg-inset)',
            color: activeMainTab === 'standby' ? 'var(--text-primary)' : 'var(--text-secondary)',
            fontWeight: 700,
            fontSize: '0.92rem',
            cursor: 'pointer',
            display: 'flex',
            alignItems: 'center',
            gap: '10px',
            boxShadow: activeMainTab === 'standby' ? 'none' : 'none',
            transition: 'all 0.2s'
          }}
        >
          <Clock size={18} color={activeMainTab === 'standby' ? 'var(--ok)' : 'currentColor'} />
          <span>💬 Storico Standby Fornitori (Prodotti Nuovi)</span>
          <span style={{
            padding: '2px 8px', borderRadius: 'var(--radius-lg)',
            background: activeMainTab === 'standby' ? 'var(--bg-elevated)' : 'var(--bg-elevated)',
            fontSize: '0.78rem'
          }}>
            {standbyItems.filter(i => i.status === 'standby').length}
          </span>
        </button>
      </div>

      {activeMainTab === 'unlisted' && (
        <>
          {/* Filters Bar */}
          <div className="glass-panel" style={{ padding: '18px 24px', display: 'flex', gap: '16px', flexWrap: 'wrap', alignItems: 'center', justifyContent: 'space-between' }}>
        <div style={{ display: 'flex', gap: '16px', flexWrap: 'wrap', flex: 1, minWidth: '300px' }}>
          {/* Search Input */}
          <div style={{ position: 'relative', flex: 1, minWidth: '240px' }}>
            <Search size={16} style={{ position: 'absolute', left: '12px', top: '50%', transform: 'translateY(-50%)', color: 'var(--text-secondary)' }} />
            <input
              type="text"
              placeholder="Cerca per descrizione, codice o fornitore..."
              value={searchTerm}
              onChange={e => setSearchTerm(e.target.value)}
              style={{
                width: '100%',
                padding: '10px 14px 10px 38px',
                background: 'var(--bg-inset)',
                border: '1px solid var(--border-glass)',
                borderRadius: 'var(--radius-md)',
                color: 'var(--text-primary)',
                fontSize: '0.9rem',
                outline: 'none'
              }}
            />
          </div>

          {/* Supplier Dropdown */}
          <div style={{ minWidth: '200px' }}>
            <select
              value={selectedSupplierId}
              onChange={e => setSelectedSupplierId(e.target.value)}
              style={{
                width: '100%',
                padding: '10px 14px',
                background: 'var(--bg-secondary)',
                border: '1px solid var(--border-glass)',
                borderRadius: 'var(--radius-md)',
                color: 'var(--text-primary)',
                fontSize: '0.9rem',
                outline: 'none'
              }}
            >
              <option value="all">Tutti i Fornitori ({suppliersList.length})</option>
              {suppliersList.map(s => (
                <option key={s.id} value={s.id}>{s.name}</option>
              ))}
            </select>
          </div>
        </div>

        {/* Status Filter Buttons */}
        <div style={{ display: 'flex', gap: '8px', background: 'var(--bg-inset)', padding: '4px', borderRadius: 'var(--radius-md)', border: '1px solid var(--border-glass)' }}>
          <button
            onClick={() => setStatusFilter('all')}
            style={{
              padding: '6px 14px',
              borderRadius: 'var(--radius-sm)',
              border: 'none',
              background: statusFilter === 'all' ? 'var(--accent-blue)' : 'transparent',
              color: statusFilter === 'all' ? 'var(--text-primary)' : 'var(--text-secondary)',
              cursor: 'pointer',
              fontSize: '0.85rem',
              fontWeight: 500,
              transition: 'var(--transition-smooth)'
            }}
          >
            Tutti ({queueData?.items.length || 0})
          </button>
          <button
            onClick={() => setStatusFilter('suggested')}
            style={{
              padding: '6px 14px',
              borderRadius: 'var(--radius-sm)',
              border: 'none',
              background: statusFilter === 'suggested' ? 'var(--accent-blue)' : 'transparent',
              color: statusFilter === 'suggested' ? 'var(--text-primary)' : 'var(--text-secondary)',
              cursor: 'pointer',
              fontSize: '0.85rem',
              fontWeight: 500,
              transition: 'var(--transition-smooth)'
            }}
          >
            Con Suggerimento ({queueData?.summary.reliable_suggestions || 0})
          </button>
          <button
            onClick={() => setStatusFilter('unmatched')}
            style={{
              padding: '6px 14px',
              borderRadius: 'var(--radius-sm)',
              border: 'none',
              background: statusFilter === 'unmatched' ? 'var(--accent-blue)' : 'transparent',
              color: statusFilter === 'unmatched' ? 'var(--text-primary)' : 'var(--text-secondary)',
              cursor: 'pointer',
              fontSize: '0.85rem',
              fontWeight: 500,
              transition: 'var(--transition-smooth)'
            }}
          >
            Nuovi Senza Match ({queueData?.summary.probable_new_products || 0})
          </button>
        </div>
      </div>

      {!loading && (queueData?.summary.work_items || 0) > 0 && (
        <div className="glass-panel" style={{
          padding: '18px 20px',
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'space-between',
          gap: '18px',
          flexWrap: 'wrap',
          border: '1px solid var(--accent-border)',
          background: 'var(--accent-bg)',
        }}>
          <div>
            <div style={{ display: 'flex', alignItems: 'center', gap: '8px', color: 'var(--text-primary)', fontWeight: 700 }}>
              <Sparkles size={18} color="var(--accent-text)" />
              Risoluzione intelligente
            </div>
            <div style={{ marginTop: '5px', color: 'var(--text-secondary)', fontSize: '0.84rem' }}>
              Prepara automaticamente associazioni sicure e nuovi prodotti. I casi dubbi restano separati per la revisione.
            </div>
          </div>
          <button
            className="btn btn-primary"
            onClick={openSmartPlan}
            disabled={bulkResolving}
            style={{ display: 'flex', alignItems: 'center', gap: '8px', minWidth: '190px', justifyContent: 'center' }}
          >
            {bulkResolving ? <Loader2 size={16} className="spin" /> : <Zap size={16} />}
            Analizza e prepara
          </button>
        </div>
      )}

      {showSmartPlan && (
        <div style={{
          position: 'fixed', inset: 0, zIndex: 1000,
          background: 'var(--bg-overlay)',
          display: 'flex', alignItems: 'center', justifyContent: 'center', padding: '20px',
        }} onClick={() => !bulkResolving && setShowSmartPlan(false)}>
          <div className="glass-panel" style={{
            width: 'min(720px, 100%)', maxHeight: '90vh', overflowY: 'auto', padding: '26px',
            border: '1px solid var(--accent-border)', background: 'var(--bg-card)', boxShadow: 'var(--shadow-pop)',
          }} onClick={event => event.stopPropagation()}>
            <div style={{ display: 'flex', justifyContent: 'space-between', gap: '16px', alignItems: 'flex-start' }}>
              <div>
                <div style={{ display: 'flex', alignItems: 'center', gap: '9px' }}>
                  <Sparkles size={22} color="var(--accent-text)" />
                  <h3 style={{ margin: 0, fontSize: '1.2rem' }}>Anteprima del piano</h3>
                </div>
                <p style={{ color: 'var(--text-secondary)', margin: '8px 0 0', fontSize: '0.88rem' }}>
                  Nessuna associazione è preselezionata: verranno applicate soltanto quelle che approvi qui.
                </p>
              </div>
              <button onClick={() => setShowSmartPlan(false)} disabled={bulkResolving} aria-label="Chiudi"
                style={{ border: 0, background: 'transparent', color: 'var(--text-secondary)', cursor: 'pointer' }}>
                <X size={21} />
              </button>
            </div>

            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(180px, 1fr))', gap: '12px', margin: '22px 0' }}>
              <div role="button" tabIndex={0} onClick={() => setSmartPlanTab('safe')} onKeyDown={event => event.key === 'Enter' && setSmartPlanTab('safe')}
                style={{ padding: '16px', borderRadius: 'var(--radius-md)', cursor: 'pointer', border: smartPlanTab === 'safe' ? '2px solid var(--ok)' : '1px solid var(--ok-border)', background: 'var(--ok-bg)' }}>
                <div style={{ color: 'var(--ok)', fontSize: '0.78rem', textTransform: 'uppercase' }}>Suggerimenti forti</div>
                <div style={{ fontSize: '1.65rem', fontWeight: 700, marginTop: '4px' }}>{smartPlan.safeMatches.length}</div>
                <div style={{ color: 'var(--text-secondary)', fontSize: '0.76rem' }}>clicca per vedere · almeno 85%</div>
              </div>
              <div role="button" tabIndex={0} onClick={() => setSmartPlanTab('review')} onKeyDown={event => event.key === 'Enter' && setSmartPlanTab('review')}
                style={{ padding: '16px', borderRadius: 'var(--radius-md)', cursor: 'pointer', border: smartPlanTab === 'review' ? '2px solid var(--warn)' : '1px solid var(--warn-border)', background: 'var(--warn-bg)' }}>
                <div style={{ color: 'var(--warn)', fontSize: '0.78rem', textTransform: 'uppercase' }}>Da controllare</div>
                <div style={{ fontSize: '1.65rem', fontWeight: 700, marginTop: '4px' }}>{smartPlan.needsReview.length}</div>
                <div style={{ color: 'var(--text-secondary)', fontSize: '0.76rem' }}>clicca per vedere · non modificati</div>
              </div>
              <div role="button" tabIndex={0} onClick={() => setSmartPlanTab('new')} onKeyDown={event => event.key === 'Enter' && setSmartPlanTab('new')}
                style={{ padding: '16px', borderRadius: 'var(--radius-md)', cursor: 'pointer', border: smartPlanTab === 'new' ? '2px solid var(--accent-text)' : '1px solid var(--accent-border)', background: 'var(--accent-bg)' }}>
                <div style={{ color: 'var(--accent-text)', fontSize: '0.78rem', textTransform: 'uppercase' }}>Nuovi prodotti</div>
                <div style={{ fontSize: '1.65rem', fontWeight: 700, marginTop: '4px' }}>{smartPlan.newProducts.length}</div>
                <div style={{ color: 'var(--text-secondary)', fontSize: '0.76rem' }}>clicca per vedere · dati fattura</div>
              </div>
            </div>

            <div style={{ border: '1px solid var(--border-glass)', borderRadius: 'var(--radius-md)', overflow: 'hidden', marginBottom: '14px' }}>
              <div style={{ padding: '10px 14px', background: 'var(--bg-inset)', display: 'flex', justifyContent: 'space-between', gap: '12px' }}>
                <strong style={{ fontSize: '0.84rem' }}>
                  {smartPlanTab === 'safe' ? 'Suggerimenti forti da approvare' : smartPlanTab === 'review' ? 'Corrispondenze da verificare manualmente' : 'Prodotti senza corrispondenza trovata'}
                </strong>
                <div style={{ display: 'flex', alignItems: 'center', gap: '10px' }}>
                  {smartPlanTab === 'safe' && smartPlan.safeMatches.length > 0 && (
                    <button type="button" className="btn" onClick={() => {
                      const safeKeys = smartPlan.safeMatches.map(item => item.work_key);
                      const allSelected = safeKeys.every(key => approvedAssociationKeys.has(key));
                      setApprovedAssociationKeys(previous => {
                        const next = new Set(previous);
                        safeKeys.forEach(key => allSelected ? next.delete(key) : next.add(key));
                        return next;
                      });
                    }} style={{ padding: '5px 9px', fontSize: '0.72rem' }}>
                      {smartPlan.safeMatches.every(item => approvedAssociationKeys.has(item.work_key)) ? 'Deseleziona sicuri' : 'Seleziona tutti i sicuri'}
                    </button>
                  )}
                  <span style={{ color: 'var(--text-secondary)', fontSize: '0.78rem' }}>{smartPlanRows.length} voci</span>
                </div>
              </div>
              {smartPlanTab === 'new' && (
                <label style={{ display: 'flex', alignItems: 'center', gap: '10px', padding: '12px 14px', background: 'var(--accent-bg)', cursor: 'pointer', borderTop: '1px solid var(--border-glass)' }}>
                  <input type="checkbox" checked={includeNewProducts} onChange={event => setIncludeNewProducts(event.target.checked)} />
                  <span style={{ fontSize: '0.82rem', fontWeight: 700 }}>Crea in listino questi {smartPlan.newProducts.length} prodotti senza corrispondenza</span>
                </label>
              )}
              <div style={{ maxHeight: '280px', overflowY: 'auto' }}>
                {smartPlanRows.length === 0 ? (
                  <div style={{ padding: '24px', textAlign: 'center', color: 'var(--text-secondary)', fontSize: '0.83rem' }}>Nessuna voce in questo gruppo.</div>
                ) : smartPlanRows.map(item => (
                  <div key={item.work_key} style={{ padding: '11px 14px', borderTop: '1px solid var(--border-glass)', display: 'grid', gridTemplateColumns: item.best_candidate ? 'auto minmax(0, 1fr)' : 'minmax(0, 1fr) auto', gap: '12px', alignItems: 'start', opacity: !item.best_candidate && !includeNewProducts ? 0.55 : 1 }}>
                    {item.best_candidate && (
                      <input
                        type="checkbox"
                        aria-label={`Approva associazione per ${item.raw_description}`}
                        checked={approvedAssociationKeys.has(item.work_key)}
                        onChange={event => setApprovedAssociationKeys(previous => {
                          const next = new Set(previous);
                          if (event.target.checked) next.add(item.work_key);
                          else next.delete(item.work_key);
                          return next;
                        })}
                        style={{ marginTop: '3px', width: '17px', height: '17px', cursor: 'pointer' }}
                      />
                    )}
                    <div style={{ minWidth: 0 }}>
                      <div style={{ fontSize: '0.84rem', fontWeight: 650, overflowWrap: 'anywhere' }}>{item.raw_description}</div>
                      <div style={{ color: 'var(--text-secondary)', fontSize: '0.72rem', marginTop: '3px' }}>
                        {item.supplier_name}{item.supplier_code ? ` · codice ${item.supplier_code}` : ''} · {item.occurrence_count} righe fattura
                      </div>
                      {item.best_candidate && (
                        <div style={{ marginTop: '5px' }}>
                          {item.alternatives.map((candidate, candidateIndex) => (
                            <label key={`${item.work_key}-${candidate.product_id}`} style={{ display: 'flex', alignItems: 'flex-start', gap: '7px', color: candidateIndex === 0 ? (smartPlanTab === 'safe' ? 'var(--ok)' : 'var(--warn)') : 'var(--text-secondary)', fontSize: candidateIndex === 0 ? '0.76rem' : '0.71rem', marginTop: candidateIndex ? '6px' : 0, cursor: 'pointer' }}>
                              <input
                                type="radio"
                                name={`candidate-${item.work_key}`}
                                checked={selectedCandidateIds[item.work_key] === candidate.product_id}
                                onChange={() => setSelectedCandidateIds(previous => ({ ...previous, [item.work_key]: candidate.product_id }))}
                              />
                              <span>{candidateIndex === 0 ? 'Proposta' : `Alternativa ${candidateIndex}`}: {candidate.canonical_name}
                                {candidate.sku_interno ? ` · ${candidate.sku_interno}` : ''} · {Math.round(candidate.score)}%</span>
                            </label>
                          ))}
                        </div>
                      )}
                    </div>
                    {!item.best_candidate && <div style={{ fontWeight: 700, color: 'var(--accent-text)', whiteSpace: 'nowrap' }}>NUOVO</div>}
                  </div>
                ))}
              </div>
            </div>

            <div style={{ padding: '14px 16px', borderRadius: '9px', background: 'var(--bg-inset)', color: 'var(--text-secondary)', fontSize: '0.83rem', lineHeight: 1.55 }}>
              <strong style={{ color: 'var(--text-primary)' }}>{approvedAssociationKeys.size} associazioni approvate</strong>
              {' · '}{includeNewProducts ? smartPlan.newProducts.length : 0} nuovi prodotti da creare. Le voci non selezionate resteranno da lavorare. I dati mancanti non saranno inventati.
            </div>

            <div style={{ display: 'flex', justifyContent: 'flex-end', gap: '10px', marginTop: '22px', flexWrap: 'wrap' }}>
              <button className="btn" onClick={() => setShowSmartPlan(false)} disabled={bulkResolving}>Annulla</button>
              <button className="btn btn-primary" onClick={executeSmartPlan} disabled={bulkResolving || selectedDecisionCount === 0}
                style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                {bulkResolving ? <Loader2 size={15} className="spin" /> : <CheckCircle2 size={15} />}
                {bulkResolving ? 'Registrazione in corso…' : `Conferma ${selectedDecisionCount} decisioni`}
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Bulk Action & Selection Toolbar */}
      {!loading && filteredItems.length > 0 && (
        <div className="glass-panel" style={{
          padding: '14px 20px',
          display: 'flex',
          justifyContent: 'space-between',
          alignItems: 'center',
          flexWrap: 'wrap',
          gap: '14px',
          background: 'var(--bg-inset)',
          border: '1px solid var(--border-glass)'
        }}>
          {/* Left: Select All Checkbox & Count */}
          <div style={{ display: 'flex', alignItems: 'center', gap: '12px' }}>
            <label style={{ display: 'flex', alignItems: 'center', gap: '8px', cursor: 'pointer', fontSize: '0.9rem', color: 'var(--text-primary)', fontWeight: 500 }}>
              <input
                type="checkbox"
                checked={selectedKeys.size > 0 && selectedKeys.size === filteredItems.length}
                onChange={toggleSelectAll}
                style={{ width: '16px', height: '16px', accentColor: 'var(--accent)', cursor: 'pointer' }}
              />
              <span>Seleziona tutti ({filteredItems.length})</span>
            </label>

            {selectedKeys.size > 0 && (
              <span style={{
                background: 'var(--accent-bg)',
                color: 'var(--accent-text)',
                padding: '2px 8px',
                borderRadius: '4px',
                fontSize: '0.8rem',
                fontWeight: 600
              }}>
                {selectedKeys.size} selezionati
              </span>
            )}
          </div>

          {/* Right: Quick Bulk Action Buttons */}
          <div style={{ display: 'flex', gap: '10px', alignItems: 'center', flexWrap: 'wrap' }}>
            {/* If items are selected */}
            {selectedKeys.size > 0 && (
              <>
                <button
                  onClick={() => {
                    handleResolveBulkSuggestions(selectedSuggestedItems);
                  }}
                  disabled={bulkResolving || selectedSuggestedItems.length === 0}
                  className="btn btn-primary"
                  style={{
                    display: 'flex',
                    alignItems: 'center',
                    gap: '6px',
                    fontSize: '0.82rem',
                    padding: '8px 14px'
                  }}
                >
                  {bulkResolving ? <Loader2 size={14} className="spin" /> : <Zap size={14} />}
                  Associa selezionati ai suggerimenti ({selectedSuggestedItems.length})
                </button>

                <select
                  value={bulkNewCategory}
                  onChange={event => setBulkNewCategory(event.target.value)}
                  disabled={bulkResolving}
                  aria-label="Categoria per i nuovi prodotti selezionati"
                  title="Questa categoria verrà applicata a tutti i prodotti creati come nuovi"
                  style={{
                    minWidth: '190px',
                    padding: '8px 12px',
                    background: 'var(--bg-card)',
                    border: `1px solid ${bulkNewCategory ? 'var(--ok-border)' : 'var(--warn-bg)'}`,
                    borderRadius: 'var(--radius-md)',
                    color: bulkNewCategory ? 'var(--ok)' : 'var(--warn)',
                    fontSize: '0.82rem',
                    fontWeight: 600,
                    cursor: 'pointer'
                  }}
                >
                  <option value="">Scegli categoria…</option>
                  {CATEGORIES.map(category => <option key={category} value={category}>{category}</option>)}
                </select>

                <button
                  onClick={() => {
                    handleResolveBulkAsNew(selectedItems, bulkNewCategory);
                  }}
                  disabled={bulkResolving || selectedItems.length === 0 || !bulkNewCategory}
                  style={{
                    display: 'flex',
                    alignItems: 'center',
                    gap: '6px',
                    fontSize: '0.82rem',
                    padding: '8px 14px',
                    background: 'var(--ok-bg)',
                    border: '1px solid var(--ok-border)',
                    borderRadius: 'var(--radius-md)',
                    color: 'var(--ok)',
                    fontWeight: 600,
                    cursor: bulkNewCategory ? 'pointer' : 'not-allowed',
                    opacity: bulkNewCategory ? 1 : 0.55
                  }}
                >
                  {bulkResolving ? <Loader2 size={14} className="spin" /> : <Plus size={14} />}
                  Crea come Nuovi Selezionati ({selectedItems.length})
                </button>

                <button
                  onClick={() => setSelectedKeys(new Set())}
                  style={{
                    background: 'transparent',
                    border: '1px solid var(--border-glass)',
                    color: 'var(--text-secondary)',
                    padding: '8px 12px',
                    borderRadius: 'var(--radius-md)',
                    fontSize: '0.82rem',
                    cursor: 'pointer'
                  }}
                >
                  Deseleziona
                </button>
              </>
            )}
          </div>
        </div>
      )}

      {/* Main Items List */}
      {loading ? (
        <div className="glass-panel" style={{ padding: '60px', textAlign: 'center', color: 'var(--text-secondary)' }}>
          <Loader2 size={36} className="spin" style={{ margin: '0 auto 16px', color: 'var(--accent-blue)' }} />
          <p>Caricamento prodotti fuori listino in corso...</p>
        </div>
      ) : filteredItems.length === 0 ? (
        <div className="glass-panel" style={{ padding: '60px', textAlign: 'center' }}>
          <div style={{
            width: '64px',
            height: '64px',
            borderRadius: '50%',
            background: 'var(--ok-bg)',
            color: 'var(--status-green)',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            margin: '0 auto 16px'
          }}>
            <CheckCircle2 size={36} />
          </div>
          <h3 style={{ fontSize: '1.25rem', fontWeight: 600, marginBottom: '8px' }}>
            Nessun Prodotto Fuori Listino da Risolvere!
          </h3>
          <p style={{ color: 'var(--text-secondary)', maxWidth: '500px', margin: '0 auto', fontSize: '0.9rem' }}>
            Tutte le fatture caricate nel sistema contengono prodotti regolarmente abbinati a catalogo e a listino.
          </p>
          {onNavigate && (
            <button
              onClick={() => onNavigate('upload')}
              style={{
                marginTop: '20px',
                padding: '10px 20px',
                background: 'var(--accent-blue)',
                border: 'none',
                borderRadius: 'var(--radius-md)',
                color: 'var(--text-primary)',
                fontWeight: 600,
                cursor: 'pointer',
                fontSize: '0.9rem'
              }}
            >
              Carica Nuove Fatture
            </button>
          )}
        </div>
      ) : (
        <div style={{ display: 'flex', flexDirection: 'column', gap: '16px' }}>
          {filteredItems.map(item => {
            const isExpanded = activeItemKey === item.work_key;
            const isResolving = resolvingKey === item.work_key;

            return (
              <div
                key={item.work_key}
                className="glass-panel"
                style={{
                  border: isExpanded ? '1px solid var(--accent-border)' : '1px solid var(--border-glass)',
                  borderRadius: 'var(--border-radius-md)',
                  overflow: 'hidden',
                  transition: 'var(--transition-smooth)',
                  boxShadow: isExpanded ? 'none' : undefined
                }}
              >
                {/* Item Card Header */}
                <div style={{ padding: '20px 24px', display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', flexWrap: 'wrap', gap: '16px' }}>
                  <div style={{ display: 'flex', gap: '14px', alignItems: 'flex-start', flex: 1, minWidth: '280px' }}>
                    <input
                      type="checkbox"
                      checked={selectedKeys.has(item.work_key)}
                      onChange={() => toggleSelectItem(item.work_key)}
                      style={{
                        width: '18px',
                        height: '18px',
                        accentColor: 'var(--accent)',
                        cursor: 'pointer',
                        marginTop: '4px'
                      }}
                      title="Seleziona riga"
                    />

                    <div style={{ display: 'flex', flexDirection: 'column', gap: '8px', flex: 1 }}>
                      {/* Badges Bar */}
                      <div style={{ display: 'flex', alignItems: 'center', gap: '10px', flexWrap: 'wrap' }}>
                        <span style={{
                          display: 'inline-flex',
                          alignItems: 'center',
                          gap: '6px',
                          background: 'var(--accent-bg)',
                          color: 'var(--accent-blue)',
                          padding: '4px 10px',
                          borderRadius: 'var(--radius-sm)',
                          fontSize: '0.8rem',
                          fontWeight: 600
                        }}>
                          <Building2 size={13} />
                          {item.supplier_name}
                        </span>

                        {item.supplier_code && (
                          <span style={{
                            background: 'var(--bg-elevated)',
                            color: 'var(--text-secondary)',
                            padding: '4px 8px',
                            borderRadius: 'var(--radius-sm)',
                            fontSize: '0.75rem',
                            fontFamily: 'monospace'
                          }}>
                            Cod: {item.supplier_code}
                          </span>
                        )}

                        <span style={{
                          display: 'inline-flex',
                          alignItems: 'center',
                          gap: '4px',
                          background: 'var(--bg-inset)',
                          color: 'var(--text-secondary)',
                          padding: '4px 8px',
                          borderRadius: 'var(--radius-sm)',
                          fontSize: '0.75rem'
                        }}>
                          <Calendar size={12} />
                          {item.data_documento || item.latest_invoice_date}
                        </span>

                        <span style={{
                          background: item.occurrence_count > 1 ? 'var(--warn-bg)' : 'var(--bg-elevated)',
                          color: item.occurrence_count > 1 ? 'var(--status-yellow)' : 'var(--text-secondary)',
                          padding: '3px 8px',
                          borderRadius: 'var(--radius-sm)',
                          fontSize: '0.75rem',
                          fontWeight: 600
                        }}>
                          {item.occurrence_count} {item.occurrence_count === 1 ? 'riga fattura' : 'righe fattura'}
                        </span>
                      </div>

                      {/* Raw Product Name in Invoice */}
                      <div style={{ marginTop: '4px' }}>
                        <h3 style={{ fontSize: '1.2rem', fontWeight: 600, color: 'var(--text-primary)', margin: 0 }}>
                          {item.raw_description}
                        </h3>
                      </div>

                      {/* Invoice Price Snapshot */}
                      <div style={{ display: 'flex', alignItems: 'center', gap: '16px', fontSize: '0.85rem', color: 'var(--text-secondary)', marginTop: '2px' }}>
                        <span>Prezzo Rilevato in Fattura: <strong style={{ color: 'var(--text-primary)', fontSize: '0.95rem', fontFamily: 'var(--font-mono)', fontVariantNumeric: 'tabular-nums' }}>€{item.prezzo_unitario !== undefined ? item.prezzo_unitario.toFixed(2) : '0.00'}</strong> / {item.unita_misura || 'Pz'}</span>
                        {item.quantita !== undefined && item.quantita > 0 && (
                          <span>Quantità: <strong style={{ color: 'var(--text-primary)', fontFamily: 'var(--font-mono)', fontVariantNumeric: 'tabular-nums' }}>{item.quantita}</strong></span>
                        )}
                      </div>
                    </div>
                  </div>

                  {/* Actions Buttons */}
                  <div style={{ display: 'flex', alignItems: 'center', gap: '10px' }}>
                    <button
                      onClick={() => handleOpenItem(item, 'create')}
                      disabled={isResolving}
                      style={{
                        display: 'flex',
                        alignItems: 'center',
                        gap: '6px',
                        padding: '8px 14px',
                        borderRadius: 'var(--radius-md)',
                        border: isExpanded && activeMode === 'create' ? '1px solid var(--ok)' : '1px solid var(--ok-border)',
                        background: isExpanded && activeMode === 'create' ? 'var(--ok-bg)' : 'var(--ok-bg)',
                        color: 'var(--ok)',
                        fontWeight: 600,
                        fontSize: '0.85rem',
                        cursor: 'pointer',
                        transition: 'var(--transition-smooth)'
                      }}
                    >
                      <Plus size={16} />
                      Inserisci in Listino come Nuovo
                    </button>

                    <button
                      onClick={() => handleOpenItem(item, 'associate')}
                      disabled={isResolving}
                      style={{
                        display: 'flex',
                        alignItems: 'center',
                        gap: '6px',
                        padding: '8px 14px',
                        borderRadius: 'var(--radius-md)',
                        border: isExpanded && activeMode === 'associate' ? '1px solid var(--accent-text)' : '1px solid var(--accent-border)',
                        background: isExpanded && activeMode === 'associate' ? 'var(--accent-bg)' : 'var(--accent-bg)',
                        color: 'var(--accent-text)',
                        fontWeight: 600,
                        fontSize: '0.85rem',
                        cursor: 'pointer',
                        transition: 'var(--transition-smooth)'
                      }}
                    >
                      <Link2 size={16} />
                      Associa ad Esistente
                    </button>

                    <button
                      onClick={() => handleOpenItem(item)}
                      style={{
                        background: 'transparent',
                        border: 'none',
                        color: 'var(--text-secondary)',
                        cursor: 'pointer',
                        padding: '6px',
                        display: 'flex',
                        alignItems: 'center',
                        justifyContent: 'center'
                      }}
                      title="Espandi/Riduci dettagli"
                    >
                      {isExpanded ? <ChevronUp size={20} /> : <ChevronDown size={20} />}
                    </button>
                  </div>
                </div>

                {/* AI Smart Suggestion Banner if Available */}
                {item.best_candidate && (
                  <div style={{
                    margin: '0 24px 16px',
                    padding: '12px 18px',
                    borderRadius: 'var(--radius-md)',
                    background: 'var(--accent-bg)',
                    border: '1px solid var(--accent-border)',
                    display: 'flex',
                    alignItems: 'center',
                    justifyContent: 'space-between',
                    flexWrap: 'wrap',
                    gap: '12px'
                  }}>
                    <div style={{ display: 'flex', alignItems: 'center', gap: '10px' }}>
                      <Sparkles size={18} color="var(--accent-text)" />
                      <div>
                        <span style={{ fontSize: '0.85rem', color: 'var(--text-secondary)' }}>Suggerimento corrispondenza: </span>
                        <strong style={{ color: 'var(--text-primary)', fontSize: '0.9rem' }}>{item.best_candidate.canonical_name}</strong>
                        {item.best_candidate.sku_interno && (
                          <span style={{ marginLeft: '8px', color: 'var(--text-secondary)', fontSize: '0.8rem', fontFamily: 'monospace' }}>
                            ({item.best_candidate.sku_interno})
                          </span>
                        )}
                        <span style={{
                          marginLeft: '10px',
                          background: 'var(--accent-bg)',
                          color: 'var(--accent-text)',
                          padding: '2px 8px',
                          borderRadius: '4px',
                          fontSize: '0.75rem',
                          fontWeight: 600
                        }}>
                          Confidenza {item.best_candidate.score}%
                        </span>
                      </div>
                    </div>

                    <button
                      onClick={() => {
                        handleOpenItem(item, 'associate');
                        if (item.best_candidate) {
                          setSelectedExistingId(item.best_candidate.product_id);
                          setAssociateSearch(item.best_candidate.canonical_name);
                        }
                      }}
                      style={{
                        padding: '6px 12px',
                        background: 'var(--accent-bg)',
                        border: '1px solid var(--accent-border)',
                        borderRadius: 'var(--radius-sm)',
                        color: 'var(--text-primary)',
                        fontSize: '0.8rem',
                        fontWeight: 600,
                        cursor: 'pointer'
                      }}
                    >
                      Usa questo suggerimento ➔
                    </button>
                  </div>
                )}

                {/* Expanded Resolution Work Area */}
                {isExpanded && (
                  <div style={{
                    padding: '24px',
                    background: 'var(--bg-inset)',
                    borderTop: '1px solid var(--border-glass)',
                    display: 'flex',
                    flexDirection: 'column',
                    gap: '20px'
                  }}>
                    
                    {/* Tabs switcher inside expanded card */}
                    <div style={{ display: 'flex', gap: '12px', borderBottom: '1px solid var(--border-glass)', paddingBottom: '14px' }}>
                      <button
                        onClick={() => setActiveMode('create')}
                        style={{
                          display: 'flex',
                          alignItems: 'center',
                          gap: '8px',
                          padding: '8px 16px',
                          borderRadius: 'var(--radius-md)',
                          border: 'none',
                          background: activeMode === 'create' ? 'var(--ok-bg)' : 'transparent',
                          color: activeMode === 'create' ? 'var(--ok)' : 'var(--text-secondary)',
                          cursor: 'pointer',
                          fontWeight: 600,
                          fontSize: '0.9rem',
                          transition: 'var(--transition-smooth)'
                        }}
                      >
                        <Plus size={16} />
                        Opzione 1: Inserisci in Listino come Nuovo
                      </button>

                      <button
                        onClick={() => setActiveMode('associate')}
                        style={{
                          display: 'flex',
                          alignItems: 'center',
                          gap: '8px',
                          padding: '8px 16px',
                          borderRadius: 'var(--radius-md)',
                          border: 'none',
                          background: activeMode === 'associate' ? 'var(--accent-bg)' : 'transparent',
                          color: activeMode === 'associate' ? 'var(--accent-text)' : 'var(--text-secondary)',
                          cursor: 'pointer',
                          fontWeight: 600,
                          fontSize: '0.9rem',
                          transition: 'var(--transition-smooth)'
                        }}
                      >
                        <Link2 size={16} />
                        Opzione 2: Associa a Prodotto Già Esistente
                      </button>
                    </div>

                    {/* FORM MODE 1: CREATE AS NEW IN LISTINO */}
                    {activeMode === 'create' && (
                      <div style={{ display: 'flex', flexDirection: 'column', gap: '18px' }}>
                        <div style={{
                          padding: '12px 16px',
                          borderRadius: 'var(--radius-md)',
                          background: 'var(--ok-bg)',
                          border: '1px solid var(--ok-border)',
                          color: 'var(--ok)',
                          fontSize: '0.85rem'
                        }}>
                          💡 Verrà creato il prodotto nel catalogo generale, memorizzato l'alias fornitore per il riconoscimento automatico futuro e inserita la riga nel <strong>Listino Master</strong> di <strong>{item.supplier_name}</strong>.
                        </div>

                        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(280px, 1fr))', gap: '16px' }}>
                          <div>
                            <label style={{ display: 'block', fontSize: '0.8rem', color: 'var(--text-secondary)', marginBottom: '6px', fontWeight: 500 }}>
                              Nome Prodotto Canonico *
                            </label>
                            <input
                              type="text"
                              value={createForm.canonical_name}
                              onChange={e => setCreateForm({ ...createForm, canonical_name: e.target.value })}
                              placeholder="Es. Coca Cola 33cl lattina"
                              style={{
                                width: '100%',
                                padding: '10px 14px',
                                background: 'var(--bg-elevated)',
                                border: '1px solid var(--border-glass)',
                                borderRadius: 'var(--radius-md)',
                                color: 'var(--text-primary)',
                                fontSize: '0.9rem',
                                outline: 'none'
                              }}
                            />
                          </div>

                          <div>
                            <label style={{ display: 'block', fontSize: '0.8rem', color: 'var(--text-secondary)', marginBottom: '6px', fontWeight: 500 }}>
                              SKU Interno (Codice Univoco) *
                            </label>
                            <input
                              type="text"
                              value={createForm.sku_interno}
                              onChange={e => setCreateForm({ ...createForm, sku_interno: e.target.value })}
                              placeholder="Es. SKU-BEV-001"
                              style={{
                                width: '100%',
                                padding: '10px 14px',
                                background: 'var(--bg-elevated)',
                                border: '1px solid var(--border-glass)',
                                borderRadius: 'var(--radius-md)',
                                color: 'var(--text-primary)',
                                fontSize: '0.9rem',
                                outline: 'none',
                                fontFamily: 'monospace'
                              }}
                            />
                          </div>

                          <div>
                            <label style={{ display: 'block', fontSize: '0.8rem', color: 'var(--text-secondary)', marginBottom: '6px', fontWeight: 500 }}>
                              Categoria Merceologica
                            </label>
                            <select
                              value={createForm.category}
                              onChange={e => {
                                const newCat = e.target.value;
                                setCreateForm(prev => ({ ...prev, category: newCat, subcategory: '' }));
                                fetchSubcategories(newCat);
                              }}
                              style={{
                                width: '100%',
                                padding: '10px 14px',
                                background: 'var(--bg-secondary)',
                                border: '1px solid var(--border-glass)',
                                borderRadius: 'var(--radius-md)',
                                color: 'var(--text-primary)',
                                fontSize: '0.9rem',
                                outline: 'none'
                              }}
                            >
                              <option value="" disabled>Scegli categoria…</option>
                              {CATEGORIES.map(cat => (
                                <option key={cat} value={cat}>{cat}</option>
                              ))}
                            </select>
                          </div>

                          <div>
                            <label style={{ display: 'block', fontSize: '0.8rem', color: 'var(--text-secondary)', marginBottom: '6px', fontWeight: 500 }}>
                              Unità di confronto *
                            </label>
                            <select
                              value={createForm.comparison_unit}
                              onChange={e => setCreateForm(prev => ({ ...prev, comparison_unit: e.target.value }))}
                              style={{
                                width: '100%',
                                padding: '10px 14px',
                                background: 'var(--bg-secondary)',
                                border: '1px solid var(--border-glass)',
                                borderRadius: 'var(--radius-md)',
                                color: 'var(--text-primary)',
                                fontSize: '0.9rem',
                                outline: 'none'
                              }}
                            >
                              {UNITS.map(unit => (
                                <option key={unit} value={unit}>{unit}</option>
                              ))}
                            </select>
                          </div>

                          <div>
                            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '6px' }}>
                              <label style={{ fontSize: '0.8rem', color: 'var(--text-secondary)', fontWeight: 500 }}>
                                Sottocategoria ({createForm.category})
                              </label>
                              {!showInlineNewSubcat && (
                                <button
                                  type="button"
                                  onClick={() => setShowInlineNewSubcat(true)}
                                  style={{
                                    background: 'transparent',
                                    border: 'none',
                                    color: 'var(--accent-text)',
                                    fontSize: '0.75rem',
                                    cursor: 'pointer',
                                    display: 'flex',
                                    alignItems: 'center',
                                    gap: '4px',
                                    padding: '0 4px'
                                  }}
                                >
                                  <Plus size={12} /> + Nuova Sottocategoria
                                </button>
                              )}
                            </div>

                            {showInlineNewSubcat ? (
                              <div style={{ display: 'flex', gap: '8px' }}>
                                <input
                                  type="text"
                                  autoFocus
                                  value={inlineNewSubcatName}
                                  onChange={e => setInlineNewSubcatName(e.target.value)}
                                  placeholder="Es. Carni, Ittico, Surgelati..."
                                  style={{
                                    flex: 1,
                                    padding: '9px 12px',
                                    background: 'var(--bg-elevated)',
                                    border: '1px solid var(--accent)',
                                    borderRadius: 'var(--radius-md)',
                                    color: 'var(--text-primary)',
                                    fontSize: '0.85rem',
                                    outline: 'none'
                                  }}
                                  onKeyDown={e => {
                                    if (e.key === 'Enter') {
                                      e.preventDefault();
                                      handleCreateInlineSubcategory();
                                    }
                                  }}
                                />
                                <button
                                  type="button"
                                  onClick={handleCreateInlineSubcategory}
                                  disabled={creatingSubcat || !inlineNewSubcatName.trim()}
                                  style={{
                                    padding: '0 12px',
                                    background: 'var(--ok)',
                                    border: 'none',
                                    borderRadius: 'var(--radius-md)',
                                    color: 'var(--text-primary)',
                                    fontSize: '0.8rem',
                                    fontWeight: 600,
                                    cursor: 'pointer'
                                  }}
                                >
                                  {creatingSubcat ? <Loader2 size={13} className="spin" /> : 'Salva'}
                                </button>
                                <button
                                  type="button"
                                  onClick={() => {
                                    setShowInlineNewSubcat(false);
                                    setInlineNewSubcatName('');
                                  }}
                                  style={{
                                    padding: '0 10px',
                                    background: 'var(--bg-elevated)',
                                    border: '1px solid var(--border-glass)',
                                    borderRadius: 'var(--radius-md)',
                                    color: 'var(--text-secondary)',
                                    fontSize: '0.8rem',
                                    cursor: 'pointer'
                                  }}
                                >
                                  Annulla
                                </button>
                              </div>
                            ) : (
                              <select
                                value={createForm.subcategory}
                                onChange={e => setCreateForm({ ...createForm, subcategory: e.target.value })}
                                style={{
                                  width: '100%',
                                  padding: '10px 14px',
                                  background: 'var(--bg-secondary)',
                                  border: '1px solid var(--border-glass)',
                                  borderRadius: 'var(--radius-md)',
                                  color: 'var(--text-primary)',
                                  fontSize: '0.9rem',
                                  outline: 'none'
                                }}
                              >
                                <option value="">-- Nessuna / Generale --</option>
                                {Array.from(new Set([
                                  ...(createForm.subcategory ? [createForm.subcategory] : []),
                                  ...availableSubcategories
                                ])).map(sub => (
                                  <option key={sub} value={sub}>{sub}</option>
                                ))}
                              </select>
                            )}
                          </div>

                          <div>
                            <label style={{ display: 'block', fontSize: '0.8rem', color: 'var(--text-secondary)', marginBottom: '6px', fontWeight: 500 }}>
                              Prezzo Concordato a Listino (€) *
                            </label>
                            <div style={{ position: 'relative' }}>
                              <span style={{ position: 'absolute', left: '12px', top: '50%', transform: 'translateY(-50%)', color: 'var(--text-secondary)' }}>€</span>
                              <input
                                type="number"
                                step="0.01"
                                value={createForm.prezzo_listino}
                                onChange={e => setCreateForm({ ...createForm, prezzo_listino: e.target.value })}
                                placeholder="0.00"
                                style={{
                                  width: '100%',
                                  padding: '10px 14px 10px 30px',
                                  background: 'var(--bg-elevated)',
                                  border: '1px solid var(--border-glass)',
                                  borderRadius: 'var(--radius-md)',
                                  color: 'var(--text-primary)',
                                  fontSize: '0.9rem',
                                  outline: 'none',
                                  fontWeight: 600
                                }}
                              />
                            </div>
                          </div>

                          <div>
                            <label style={{ display: 'block', fontSize: '0.8rem', color: 'var(--text-secondary)', marginBottom: '6px', fontWeight: 500 }}>
                              Unità di Misura Listino
                            </label>
                            <select
                              value={createForm.unita_misura_listino}
                              onChange={e => setCreateForm({ ...createForm, unita_misura_listino: e.target.value })}
                              style={{
                                width: '100%',
                                padding: '10px 14px',
                                background: 'var(--bg-elevated)',
                                border: '1px solid var(--border-glass)',
                                borderRadius: 'var(--radius-md)',
                                color: 'var(--text-primary)',
                                fontSize: '0.9rem',
                                outline: 'none'
                              }}
                            >
                              {UNITS.map(unit => (
                                <option key={unit} value={unit}>{unit}</option>
                              ))}
                            </select>
                          </div>

                          <div>
                            <label style={{ display: 'block', fontSize: '0.8rem', color: 'var(--text-secondary)', marginBottom: '6px', fontWeight: 500 }}>
                              Data Decorrenza Listino
                            </label>
                            <input
                              type="date"
                              value={createForm.data_inizio_validita}
                              onChange={e => setCreateForm({ ...createForm, data_inizio_validita: e.target.value })}
                              style={{
                                width: '100%',
                                padding: '10px 14px',
                                background: 'var(--bg-elevated)',
                                border: '1px solid var(--border-glass)',
                                borderRadius: 'var(--radius-md)',
                                color: 'var(--text-primary)',
                                fontSize: '0.9rem',
                                outline: 'none'
                              }}
                            />
                          </div>
                        </div>

                        {/* Confirm Button */}
                        <div style={{ display: 'flex', justifyContent: 'flex-end', gap: '12px', marginTop: '10px' }}>
                          <button
                            onClick={() => setActiveItemKey(null)}
                            style={{
                              padding: '10px 18px',
                              background: 'transparent',
                              border: '1px solid var(--border-glass)',
                              borderRadius: 'var(--radius-md)',
                              color: 'var(--text-secondary)',
                              cursor: 'pointer',
                              fontSize: '0.85rem'
                            }}
                          >
                            Annulla
                          </button>

                          <button
                            onClick={() => handleResolveCreateNew(item)}
                            disabled={isResolving}
                            style={{
                              padding: '10px 22px',
                              background: 'var(--ok)',
                              border: 'none',
                              borderRadius: 'var(--radius-md)',
                              color: 'var(--text-primary)',
                              fontWeight: 600,
                              cursor: isResolving ? 'not-allowed' : 'pointer',
                              display: 'flex',
                              alignItems: 'center',
                              gap: '8px',
                              fontSize: '0.9rem',
                              boxShadow: 'none'
                            }}
                          >
                            {isResolving ? <Loader2 size={16} className="spin" /> : <Plus size={16} />}
                            Salva in Listino Master e Mappa Fornitore
                          </button>
                        </div>
                      </div>
                    )}

                    {/* FORM MODE 2: ASSOCIATE TO EXISTING */}
                    {activeMode === 'associate' && (
                      <div style={{ display: 'flex', flexDirection: 'column', gap: '18px' }}>
                        <div style={{
                          padding: '12px 16px',
                          borderRadius: 'var(--radius-md)',
                          background: 'var(--accent-bg)',
                          border: '1px solid var(--accent-border)',
                          color: 'var(--accent-text)',
                          fontSize: '0.85rem'
                        }}>
                          🔗 Seleziona il prodotto dal catalogo a cui corrisponde la voce "{item.raw_description}". Verrà salvato l'alias per <strong>{item.supplier_name}</strong> così tutte le prossime fatture lo riconosceranno istantaneamente.
                        </div>

                        <div>
                          <label style={{ display: 'block', fontSize: '0.8rem', color: 'var(--text-secondary)', marginBottom: '6px', fontWeight: 500 }}>
                            Cerca Prodotto nel Catalogo Generale *
                          </label>
                          <div style={{ position: 'relative' }}>
                            <Search size={16} style={{ position: 'absolute', left: '12px', top: '50%', transform: 'translateY(-50%)', color: 'var(--text-secondary)' }} />
                            <input
                              type="text"
                              value={associateSearch}
                              onChange={e => setAssociateSearch(e.target.value)}
                              placeholder="Digita per cercare tra i prodotti esistenti..."
                              style={{
                                width: '100%',
                                padding: '10px 14px 10px 38px',
                                background: 'var(--bg-elevated)',
                                border: '1px solid var(--border-glass)',
                                borderRadius: 'var(--radius-md)',
                                color: 'var(--text-primary)',
                                fontSize: '0.9rem',
                                outline: 'none'
                              }}
                            />
                          </div>

                          {/* Autocomplete selection list */}
                          <div style={{
                            marginTop: '8px',
                            maxHeight: '200px',
                            overflowY: 'auto',
                            background: 'var(--bg-secondary)',
                            border: '1px solid var(--border-glass)',
                            borderRadius: 'var(--radius-md)',
                            display: 'flex',
                            flexDirection: 'column'
                          }}>
                            {searchResultsProducts.length === 0 ? (
                              <div style={{ padding: '12px', textAlign: 'center', color: 'var(--text-secondary)', fontSize: '0.85rem' }}>
                                Nessun prodotto trovato per "{associateSearch}". Prova a creare un nuovo prodotto dall'Opzione 1.
                              </div>
                            ) : (
                              searchResultsProducts.map(p => {
                                const isSelected = selectedExistingId === p.id;
                                return (
                                  <div
                                    key={p.id}
                                    onClick={() => {
                                      setSelectedExistingId(p.id);
                                      setAssociateSearch(p.canonical_name);
                                    }}
                                    style={{
                                      padding: '10px 14px',
                                      borderBottom: '1px solid var(--line)',
                                      cursor: 'pointer',
                                      background: isSelected ? 'var(--accent-bg)' : 'transparent',
                                      display: 'flex',
                                      alignItems: 'center',
                                      justifyContent: 'space-between',
                                      transition: 'var(--transition-smooth)'
                                    }}
                                  >
                                    <div>
                                      <strong style={{ color: isSelected ? 'var(--accent-text)' : 'var(--text-primary)', fontSize: '0.9rem' }}>
                                        {p.canonical_name}
                                      </strong>
                                      {p.sku_interno && (
                                        <span style={{ marginLeft: '8px', fontSize: '0.75rem', color: 'var(--text-secondary)', fontFamily: 'monospace' }}>
                                          [{p.sku_interno}]
                                        </span>
                                      )}
                                      {p.category && (
                                        <span style={{ marginLeft: '8px', fontSize: '0.75rem', background: 'var(--bg-elevated)', padding: '2px 6px', borderRadius: '4px', color: 'var(--text-secondary)' }}>
                                          {p.category}
                                        </span>
                                      )}
                                    </div>
                                    {isSelected && <Check size={16} color="var(--accent-text)" />}
                                  </div>
                                );
                              })
                            )}
                          </div>
                        </div>

                        {/* Optional price list update */}
                        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(220px, 1fr))', gap: '16px' }}>
                          <div>
                            <label style={{ display: 'block', fontSize: '0.8rem', color: 'var(--text-secondary)', marginBottom: '6px', fontWeight: 500 }}>
                              Prezzo Concordato a Listino Fornitore (€)
                            </label>
                            <div style={{ position: 'relative' }}>
                              <span style={{ position: 'absolute', left: '12px', top: '50%', transform: 'translateY(-50%)', color: 'var(--text-secondary)' }}>€</span>
                              <input
                                type="number"
                                step="0.01"
                                value={associatePriceListino}
                                onChange={e => setAssociatePriceListino(e.target.value)}
                                placeholder="0.00"
                                style={{
                                  width: '100%',
                                  padding: '10px 14px 10px 30px',
                                  background: 'var(--bg-elevated)',
                                  border: '1px solid var(--border-glass)',
                                  borderRadius: 'var(--radius-md)',
                                  color: 'var(--text-primary)',
                                  fontSize: '0.9rem',
                                  outline: 'none',
                                  fontWeight: 600
                                }}
                              />
                            </div>
                            <span style={{ fontSize: '0.75rem', color: 'var(--text-secondary)', marginTop: '4px', display: 'block' }}>
                              Verrà inserito o verificato nel listino del fornitore per il controllo anomalie.
                            </span>
                          </div>

                          <div>
                            <label style={{ display: 'block', fontSize: '0.8rem', color: 'var(--text-secondary)', marginBottom: '6px', fontWeight: 500 }}>
                              Unità di Misura Listino
                            </label>
                            <select
                              value={associateUomListino}
                              onChange={e => setAssociateUomListino(e.target.value)}
                              style={{
                                width: '100%',
                                padding: '10px 14px',
                                background: 'var(--bg-elevated)',
                                border: '1px solid var(--border-glass)',
                                borderRadius: 'var(--radius-md)',
                                color: 'var(--text-primary)',
                                fontSize: '0.9rem',
                                outline: 'none'
                              }}
                            >
                              {UNITS.map(unit => (
                                <option key={unit} value={unit}>{unit}</option>
                              ))}
                            </select>
                          </div>
                        </div>

                        {/* Action buttons */}
                        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginTop: '10px' }}>
                          <button
                            onClick={() => handleResolveIgnore(item)}
                            style={{
                              padding: '8px 14px',
                              background: 'transparent',
                              border: '1px solid var(--crit-border)',
                              borderRadius: 'var(--radius-md)',
                              color: 'var(--status-red)',
                              cursor: 'pointer',
                              fontSize: '0.8rem',
                              display: 'flex',
                              alignItems: 'center',
                              gap: '6px'
                            }}
                          >
                            <EyeOff size={14} />
                            Ignora (Non monitorare)
                          </button>

                          <div style={{ display: 'flex', gap: '12px' }}>
                            <button
                              onClick={() => setActiveItemKey(null)}
                              style={{
                                padding: '10px 18px',
                                background: 'transparent',
                                border: '1px solid var(--border-glass)',
                                borderRadius: 'var(--radius-md)',
                                color: 'var(--text-secondary)',
                                cursor: 'pointer',
                                fontSize: '0.85rem'
                              }}
                            >
                              Annulla
                            </button>

                            <button
                              onClick={() => handleResolveAssociateExisting(item)}
                              disabled={isResolving || !selectedExistingId}
                              style={{
                                padding: '10px 22px',
                                background: selectedExistingId ? 'var(--accent)' : 'var(--bg-elevated)',
                                border: 'none',
                                borderRadius: 'var(--radius-md)',
                                color: selectedExistingId ? 'var(--text-primary)' : 'var(--text-secondary)',
                                fontWeight: 600,
                                cursor: selectedExistingId && !isResolving ? 'pointer' : 'not-allowed',
                                display: 'flex',
                                alignItems: 'center',
                                gap: '8px',
                                fontSize: '0.9rem',
                                boxShadow: selectedExistingId ? 'none' : undefined
                              }}
                            >
                              {isResolving ? <Loader2 size={16} className="spin" /> : <Check size={16} />}
                              Conferma Associazione e Memorizza Alias
                            </button>
                          </div>
                        </div>
                      </div>
                    )}
                  </div>
                )}
              </div>
            );
          })}
        </div>
      )}
      </>
      )}

      {/* ─────────────────────────────────────────────────────────────
          SEZIONE STORICO STANDBY FORNITORI / PREVENTIVI NUOVI PRODOTTI
      ───────────────────────────────────────────────────────────── */}
      {activeMainTab === 'standby' && (
        <div style={{ display: 'flex', flexDirection: 'column', gap: '20px' }}>
          {/* Filters Bar Standby */}
          <div className="glass-panel" style={{ padding: '18px 24px', display: 'flex', gap: '16px', flexWrap: 'wrap', alignItems: 'center', justifyContent: 'space-between' }}>
            <div style={{ display: 'flex', gap: '16px', flexWrap: 'wrap', flex: 1, minWidth: '300px' }}>
              <div style={{ position: 'relative', flex: 1, minWidth: '240px' }}>
                <Search size={16} style={{ position: 'absolute', left: '12px', top: '50%', transform: 'translateY(-50%)', color: 'var(--text-secondary)' }} />
                <input
                  type="text"
                  placeholder="Cerca prodotto nuovo in standby, brand, fornitore..."
                  value={standbySearch}
                  onChange={e => setStandbySearch(e.target.value)}
                  style={{
                    width: '100%',
                    padding: '10px 14px 10px 38px',
                    background: 'var(--bg-inset)',
                    border: '1px solid var(--border-glass)',
                    borderRadius: 'var(--radius-md)',
                    color: 'var(--text-primary)',
                    fontSize: '0.9rem',
                    outline: 'none'
                  }}
                />
              </div>

              <div style={{ minWidth: '200px' }}>
                <select
                  value={standbyStatusFilter}
                  onChange={e => setStandbyStatusFilter(e.target.value as any)}
                  style={{
                    width: '100%',
                    padding: '10px 14px',
                    background: 'var(--bg-inset)',
                    border: '1px solid var(--border-glass)',
                    borderRadius: 'var(--radius-md)',
                    color: 'var(--text-primary)',
                    fontSize: '0.88rem',
                    outline: 'none',
                    cursor: 'pointer'
                  }}
                >
                  <option value="all" style={{ background: 'var(--bg-card)' }}>Tutti gli Stati ({standbyItems.length})</option>
                  <option value="standby" style={{ background: 'var(--bg-card)' }}>⏳ Standby WhatsApp ({standbyItems.filter(i => i.status === 'standby').length})</option>
                  <option value="completed" style={{ background: 'var(--bg-card)' }}>✅ Attivati a Listino ({standbyItems.filter(i => i.status === 'completed').length})</option>
                </select>
              </div>
            </div>

            <button
              onClick={loadStandbyData}
              disabled={loadingStandby}
              style={{
                display: 'flex',
                alignItems: 'center',
                gap: '8px',
                padding: '9px 14px',
                background: 'var(--bg-elevated)',
                border: '1px solid var(--border-glass)',
                borderRadius: 'var(--radius-md)',
                color: 'var(--text-primary)',
                cursor: loadingStandby ? 'not-allowed' : 'pointer',
                fontSize: '0.82rem',
                fontWeight: 600
              }}
            >
              <RefreshCw size={14} className={loadingStandby ? 'spin' : ''} />
              <span>Aggiorna Storico Standby</span>
            </button>
          </div>

          {/* Standby Items Cards Grid */}
          {loadingStandby ? (
            <div className="glass-panel" style={{ padding: '60px', textAlign: 'center', color: 'var(--text-secondary)' }}>
              <RefreshCw size={36} className="spin" style={{ color: '#25D366', margin: '0 auto 16px' }} />
              <div>Caricamento dello storico dei prodotti in Standby Preventivo...</div>
            </div>
          ) : filteredStandbyItems.length === 0 ? (
            <div className="glass-panel" style={{ padding: '60px', textAlign: 'center', color: 'var(--text-secondary)' }}>
              <Clock size={42} style={{ color: 'var(--text-muted)', margin: '0 auto 16px' }} />
              <h3 style={{ color: 'var(--text-primary)', margin: '0 0 8px', fontSize: '1.2rem' }}>Nessun Prodotto in Standby</h3>
              <p style={{ margin: 0, fontSize: '0.9rem', maxWidth: '500px', marginInline: 'auto' }}>
                Quando richiedi una quotazione a nuovi fornitori per un articolo non catalogato (es. dallo Sviluppo Ordini Settore), il prodotto comparirà qui in standby con i relativi pulsanti WhatsApp e form di compilazione finale.
              </p>
            </div>
          ) : (
            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(290px, 1fr))', gap: '16px' }}>
              {filteredStandbyItems.map(item => {
                const isStandby = item.status === 'standby';
                const createdDate = item.created_at ? new Date(item.created_at).toLocaleDateString('it-IT', { day: '2-digit', month: '2-digit', year: 'numeric', hour: '2-digit', minute: '2-digit' }) : '';

                return (
                  <div
                    key={item.id}
                    className="glass-panel"
                    style={{
                      padding: '22px',
                      display: 'flex',
                      flexDirection: 'column',
                      gap: '16px',
                      border: isStandby ? '1px solid rgba(37, 211, 102, 0.35)' : '1px solid var(--ok-border)',
                      boxShadow: isStandby ? 'none' : 'none',
                      position: 'relative'
                    }}
                  >
                    {/* Status Badge & Actions */}
                    <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', gap: '12px' }}>
                      <div style={{ display: 'flex', alignItems: 'center', gap: '8px', flexWrap: 'wrap' }}>
                        <span style={{
                          padding: '4px 10px',
                          borderRadius: 'var(--radius-lg)',
                          background: isStandby ? 'rgba(37, 211, 102, 0.18)' : 'var(--ok-bg)',
                          color: isStandby ? 'var(--ok)' : 'var(--ok)',
                          border: isStandby ? '1px solid rgba(37, 211, 102, 0.4)' : '1px solid var(--ok)',
                          fontSize: '0.78rem',
                          fontWeight: 700,
                          display: 'flex',
                          alignItems: 'center',
                          gap: '5px'
                        }}>
                          {isStandby ? <Clock size={13} /> : <CheckCircle2 size={13} />}
                          <span>{isStandby ? '⏳ Standby WhatsApp (In attesa)' : '✅ Attivato in Listino'}</span>
                        </span>

                        {item.category && (
                          <span style={{ padding: '3px 8px', borderRadius: 'var(--radius-sm)', background: 'var(--accent-bg)', color: 'var(--accent-text)', fontSize: '0.75rem', fontWeight: 600 }}>
                            {item.category} {item.subcategory ? `> ${item.subcategory}` : ''}
                          </span>
                        )}
                      </div>

                      <button
                        onClick={() => handleDeleteStandby(item.id, item.canonical_name)}
                        style={{
                          background: 'var(--crit-bg)',
                          border: '1px solid var(--crit-border)',
                          borderRadius: 'var(--radius-sm)',
                          color: 'var(--crit)',
                          padding: '5px',
                          cursor: 'pointer'
                        }}
                        title="Rimuovi dallo storico standby"
                      >
                        <Trash2 size={14} />
                      </button>
                    </div>

                    {/* Title & Product Info */}
                    <div>
                      <h3 style={{ margin: '0 0 6px', fontSize: '1.15rem', fontWeight: 700, color: 'var(--text-primary)' }}>
                        {item.canonical_name}
                      </h3>
                      <div style={{ display: 'flex', gap: '10px', flexWrap: 'wrap', fontSize: '0.8rem', color: 'var(--text-secondary)' }}>
                        {item.sku_interno && <span>SKU: <strong style={{ color: 'var(--accent-text)' }}>{item.sku_interno}</strong></span>}
                        {item.brand && <span>Brand: <strong style={{ color: 'var(--text-primary)' }}>{item.brand}</strong></span>}
                        <span>UoM: <strong style={{ color: 'var(--warn)' }}>{item.comparison_unit}</strong></span>
                        {createdDate && <span>Inviato il: {createdDate}</span>}
                      </div>
                      {item.notes && (
                        <div style={{ marginTop: '8px', fontSize: '0.78rem', color: 'var(--text-secondary)', background: 'var(--bg-inset)', padding: '6px 10px', borderRadius: 'var(--radius-sm)' }}>
                          📝 {item.notes}
                        </div>
                      )}
                    </div>

                    {/* Suppliers Requested Section with Standby WhatsApp buttons */}
                    <div style={{ background: 'var(--bg-inset)', padding: '12px 14px', borderRadius: 'var(--radius-md)', display: 'flex', flexDirection: 'column', gap: '10px' }}>
                      <div style={{ fontSize: '0.8rem', fontWeight: 700, color: 'var(--accent-text)', display: 'flex', alignItems: 'center', gap: '6px' }}>
                        <Store size={14} />
                        <span>Fornitori Inoltrati ({item.suppliers_data?.length || 0}):</span>
                      </div>

                      <div style={{ display: 'flex', flexDirection: 'column', gap: '8px', maxHeight: '200px', overflowY: 'auto' }}>
                        {item.suppliers_data?.map(sup => {
                          const waUrl = sup.whatsapp_url || (sup.phone ? `https://wa.me/39${sup.phone.replace(/\D/g, '')}` : '');

                          return (
                            <div
                              key={sup.supplier_id}
                              style={{
                                padding: '8px 12px',
                                borderRadius: 'var(--radius-md)',
                                background: 'var(--bg-inset)',
                                border: '1px solid var(--line)',
                                display: 'flex',
                                justifyContent: 'space-between',
                                alignItems: 'center',
                                gap: '8px'
                              }}
                            >
                              <div>
                                <div style={{ fontSize: '0.85rem', fontWeight: 700, color: 'var(--text-primary)' }}>
                                  {sup.supplier_name}
                                </div>
                                <div style={{ fontSize: '0.75rem', color: 'var(--text-secondary)' }}>
                                  {sup.phone ? `📞 ${sup.phone}` : ''} {sup.email ? `✉️ ${sup.email}` : ''}
                                </div>
                              </div>

                              {waUrl && (
                                <a
                                  href={waUrl}
                                  target="_blank"
                                  rel="noopener noreferrer"
                                  style={{
                                    padding: '5px 10px',
                                    borderRadius: 'var(--radius-sm)',
                                    background: '#25D366',
                                    color: 'var(--text-primary)',
                                    fontSize: '0.75rem',
                                    fontWeight: 700,
                                    textDecoration: 'none',
                                    display: 'flex',
                                    alignItems: 'center',
                                    gap: '5px',
                                    boxShadow: 'none'
                                  }}
                                >
                                  <MessageSquare size={12} />
                                  <span>Standby WhatsApp</span>
                                </a>
                              )}
                            </div>
                          );
                        })}
                      </div>
                    </div>

                    {/* Main Action Button: Compila Dati Prodotto */}
                    <div style={{ marginTop: 'auto', paddingTop: '10px' }}>
                      <button
                        onClick={() => handleOpenCompileModal(item)}
                        style={{
                          width: '100%',
                          padding: '11px',
                          borderRadius: 'var(--radius-md)',
                          border: isStandby ? 'none' : '1px solid var(--line)',
                          background: isStandby 
                            ? 'var(--accent)' 
                            : 'var(--bg-elevated)',
                          color: 'var(--text-primary)',
                          fontWeight: 700,
                          fontSize: '0.88rem',
                          cursor: 'pointer',
                          display: 'flex',
                          alignItems: 'center',
                          justifyContent: 'center',
                          gap: '8px',
                          boxShadow: isStandby ? 'none' : 'none',
                          transition: 'all 0.2s'
                        }}
                      >
                        <Edit3 size={15} />
                        <span>{isStandby ? '✏️ Compila Dati Prodotto con Risposta Fornitori' : '✏️ Aggiorna Dati Prodotto'}</span>
                      </button>
                    </div>
                  </div>
                );
              })}
            </div>
          )}
        </div>
      )}

      {/* ─────────────────────────────────────────────────────────────
          MODAL: COMPILA DATI PRODOTTO STANDBY CON RISPOSTA FORNITORI
      ───────────────────────────────────────────────────────────── */}
      {compilingItem && (
        <div style={{
          position: 'fixed',
          top: 0, left: 0, right: 0, bottom: 0,
          backgroundColor: 'var(--bg-overlay)',
          zIndex: 9999,
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
          padding: '16px'
        }}>
          <div style={{
            background: 'var(--bg-card)',
            border: '1px solid rgba(37, 211, 102, 0.4)',
            borderRadius: 'var(--radius-lg)',
            width: '100%',
            maxWidth: '650px',
            maxHeight: '92vh',
            overflowY: 'auto',
            boxShadow: 'var(--shadow-pop)',
            padding: '26px',
            color: 'var(--text-primary)',
            display: 'flex',
            flexDirection: 'column',
            gap: '20px'
          }}>
            {/* Modal Header */}
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start' }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: '12px' }}>
                <div style={{
                  width: '44px', height: '44px', borderRadius: 'var(--radius-lg)',
                  background: '#25D366',
                  display: 'flex', alignItems: 'center', justifyContent: 'center',
                  boxShadow: 'none'
                }}>
                  <Edit3 size={22} color="white" />
                </div>
                <div>
                  <h3 style={{ margin: 0, fontSize: '1.25rem', fontWeight: 700 }}>
                    Compila Dati Prodotto Ricevuti dai Fornitori
                  </h3>
                  <p style={{ margin: '3px 0 0', fontSize: '0.8rem', color: 'var(--text-secondary)' }}>
                    Articolo: <strong style={{ color: 'var(--text-primary)' }}>{compilingItem.canonical_name}</strong>
                  </p>
                </div>
              </div>
              <button
                type="button"
                onClick={() => setCompilingItem(null)}
                style={{
                  background: 'var(--bg-elevated)',
                  border: 'none',
                  borderRadius: 'var(--radius-md)',
                  color: 'var(--text-secondary)',
                  padding: '6px',
                  cursor: 'pointer'
                }}
              >
                <X size={18} />
              </button>
            </div>

            {/* Modal Form */}
            <div style={{ display: 'flex', flexDirection: 'column', gap: '14px' }}>
              {/* Fornitore aggiudicatario / che ha risposto */}
              <div style={{ display: 'flex', flexDirection: 'column', gap: '6px' }}>
                <label style={{ fontSize: '0.85rem', fontWeight: 700, color: 'var(--ok)' }}>
                  Fornitore con Offerta / Quotazione *
                </label>
                <select
                  value={compileForm.supplier_id}
                  onChange={e => setCompileForm({ ...compileForm, supplier_id: Number(e.target.value) })}
                  style={{
                    padding: '10px 14px',
                    background: 'var(--bg-inset)',
                    border: '1px solid var(--border-glass)',
                    borderRadius: 'var(--radius-md)',
                    color: 'var(--text-primary)',
                    fontSize: '0.9rem',
                    outline: 'none',
                    fontWeight: 700,
                    cursor: 'pointer'
                  }}
                >
                  <option value={0} style={{ background: 'var(--bg-card)' }}>-- Seleziona Fornitore --</option>
                  {compilingItem.suppliers_data?.map(s => (
                    <option key={s.supplier_id} value={s.supplier_id} style={{ background: 'var(--bg-card)' }}>
                      {s.supplier_name} {s.phone ? `(${s.phone})` : ''}
                    </option>
                  ))}
                </select>
              </div>

              {/* Prezzo e Unità di misura */}
              <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '12px' }}>
                <div style={{ display: 'flex', flexDirection: 'column', gap: '5px' }}>
                  <label style={{ fontSize: '0.8rem', fontWeight: 700, color: 'var(--accent-text)' }}>
                    Prezzo Netto Concordato (€) *
                  </label>
                  <input
                    type="number"
                    step="0.01"
                    min="0"
                    placeholder="Es. 14.50"
                    value={compileForm.prezzo_concordato}
                    onChange={e => setCompileForm({ ...compileForm, prezzo_concordato: e.target.value })}
                    style={{
                      padding: '10px 12px',
                      background: 'var(--accent-bg)',
                      border: '1px solid var(--accent-border)',
                      borderRadius: 'var(--radius-md)',
                      color: 'var(--text-primary)',
                      fontWeight: 700,
                      fontSize: '0.95rem',
                      outline: 'none'
                    }}
                    autoFocus
                  />
                </div>

                <div style={{ display: 'flex', flexDirection: 'column', gap: '5px' }}>
                  <label style={{ fontSize: '0.8rem', fontWeight: 600, color: 'var(--text-secondary)' }}>
                    Unità di Misura d'Acquisto
                  </label>
                  <input
                    type="text"
                    placeholder="Es. Pz, Ct, Kg, Bot, L..."
                    value={compileForm.unita_misura}
                    onChange={e => setCompileForm({ ...compileForm, unita_misura: e.target.value })}
                    style={{
                      padding: '10px 12px',
                      background: 'var(--bg-inset)',
                      border: '1px solid var(--border-glass)',
                      borderRadius: 'var(--radius-md)',
                      color: 'var(--text-primary)',
                      fontSize: '0.9rem',
                      outline: 'none'
                    }}
                  />
                </div>
              </div>

              {/* SKU & Brand */}
              <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '12px' }}>
                <div style={{ display: 'flex', flexDirection: 'column', gap: '5px' }}>
                  <label style={{ fontSize: '0.8rem', fontWeight: 600, color: 'var(--text-secondary)' }}>
                    SKU Interno Prodotto
                  </label>
                  <input
                    type="text"
                    placeholder="Auto-generato se vuoto"
                    value={compileForm.sku_interno}
                    onChange={e => setCompileForm({ ...compileForm, sku_interno: e.target.value })}
                    style={{
                      padding: '9px 12px',
                      background: 'var(--bg-inset)',
                      border: '1px solid var(--border-glass)',
                      borderRadius: 'var(--radius-md)',
                      color: 'var(--text-primary)',
                      fontSize: '0.85rem',
                      outline: 'none'
                    }}
                  />
                </div>

                <div style={{ display: 'flex', flexDirection: 'column', gap: '5px' }}>
                  <label style={{ fontSize: '0.8rem', fontWeight: 600, color: 'var(--text-secondary)' }}>
                    Brand / Marchio
                  </label>
                  <input
                    type="text"
                    placeholder="Es. San Pellegrino..."
                    value={compileForm.brand}
                    onChange={e => setCompileForm({ ...compileForm, brand: e.target.value })}
                    style={{
                      padding: '9px 12px',
                      background: 'var(--bg-inset)',
                      border: '1px solid var(--border-glass)',
                      borderRadius: 'var(--radius-md)',
                      color: 'var(--text-primary)',
                      fontSize: '0.85rem',
                      outline: 'none'
                    }}
                  />
                </div>
              </div>

              {/* Categoria e Sottocategoria */}
              <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '12px' }}>
                <div style={{ display: 'flex', flexDirection: 'column', gap: '5px' }}>
                  <label style={{ fontSize: '0.8rem', fontWeight: 600, color: 'var(--text-secondary)' }}>
                    Categoria / Settore
                  </label>
                  <select
                    value={compileForm.category}
                    onChange={e => setCompileForm({ ...compileForm, category: e.target.value })}
                    style={{
                      padding: '9px 12px',
                      background: 'var(--bg-inset)',
                      border: '1px solid var(--border-glass)',
                      borderRadius: 'var(--radius-md)',
                      color: 'var(--text-primary)',
                      fontSize: '0.85rem',
                      outline: 'none',
                      cursor: 'pointer'
                    }}
                  >
                    {CATEGORIES.map(c => (
                      <option key={c} value={c} style={{ background: 'var(--bg-card)' }}>{c}</option>
                    ))}
                  </select>
                </div>

                <div style={{ display: 'flex', flexDirection: 'column', gap: '5px' }}>
                  <label style={{ fontSize: '0.8rem', fontWeight: 600, color: 'var(--text-secondary)' }}>
                    Sottocategoria
                  </label>
                  <input
                    type="text"
                    placeholder="Es. Birre, Detergenza..."
                    value={compileForm.subcategory}
                    onChange={e => setCompileForm({ ...compileForm, subcategory: e.target.value })}
                    style={{
                      padding: '9px 12px',
                      background: 'var(--bg-inset)',
                      border: '1px solid var(--border-glass)',
                      borderRadius: 'var(--radius-md)',
                      color: 'var(--text-primary)',
                      fontSize: '0.85rem',
                      outline: 'none'
                    }}
                  />
                </div>
              </div>
            </div>

            {/* Modal Actions */}
            <div style={{ display: 'flex', justifyContent: 'flex-end', gap: '10px', marginTop: '10px' }}>
              <button
                type="button"
                className="btn btn-secondary"
                onClick={() => setCompilingItem(null)}
                disabled={submittingCompile}
                style={{ padding: '10px 16px', fontSize: '0.85rem' }}
              >
                Annulla
              </button>

              <button
                type="button"
                onClick={handleSaveCompile}
                disabled={submittingCompile || !compileForm.supplier_id || !compileForm.prezzo_concordato}
                style={{
                  padding: '11px 22px',
                  borderRadius: 'var(--radius-md)',
                  border: 'none',
                  background: 'var(--ok)',
                  color: 'var(--text-primary)',
                  fontWeight: 700,
                  fontSize: '0.9rem',
                  cursor: submittingCompile || !compileForm.supplier_id || !compileForm.prezzo_concordato ? 'not-allowed' : 'pointer',
                  display: 'flex',
                  alignItems: 'center',
                  gap: '8px',
                  boxShadow: 'none',
                  opacity: submittingCompile || !compileForm.supplier_id || !compileForm.prezzo_concordato ? 0.6 : 1,
                  transition: 'all 0.2s'
                }}
              >
                {submittingCompile ? <RefreshCw className="spinner" size={16} /> : <CheckCircle2 size={16} />}
                <span>🚀 Salva & Attiva in Archivio Listino</span>
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

