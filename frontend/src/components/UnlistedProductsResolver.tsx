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
  FileText,
  EyeOff,
  Check,
  Calendar,
  ChevronDown,
  ChevronUp,
  Loader2,
  Zap,
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

const CATEGORIES = [
  'Beverage',
  'Food',
  'Materiali di consumo',
  'Alcolici & Liquori',
  'Birre',
  'Vini & Spumanti',
  'Soft Drink & Acque',
  'Caffetteria',
  'Detergenti & Sanificazione',
  'Monouso & Packaging',
  'Altro',
];

export default function UnlistedProductsResolver({ onNavigate }: { onNavigate?: (tab: string) => void }) {
  const [queueData, setQueueData] = useState<WorkQueueResponse | null>(null);
  const [existingProducts, setExistingProducts] = useState<ExistingProduct[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [actionSuccess, setActionSuccess] = useState<string | null>(null);

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
    category: 'Beverage',
    subcategory: '',
    comparison_unit: 'piece',
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
  const [bulkResolving, setBulkResolving] = useState(false);

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
    setCreatingSubcat(true);
    try {
      const res = await fetch(`${API_BASE}/categories/subcategories`, {
        method: 'POST',
        headers: getHeaders(),
        body: JSON.stringify({
          categoria_nome: createForm.category || 'Food',
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
  }, []);

  const loadAll = async () => {
    setLoading(true);
    setError(null);
    try {
      const [queueRes, prodRes] = await Promise.all([
        fetch(`${API_BASE}/product-identity/match-candidates/work-queue`, {
          headers: getHeaders(),
        }),
        fetch(`${API_BASE}/products`, {
          headers: getHeaders(),
        }),
      ]);

      if (!queueRes.ok) throw new Error('Errore nel caricamento delle voci fuori listino');
      const qData: WorkQueueResponse = await queueRes.json();
      setQueueData(qData);

      if (prodRes.ok) {
        const pData: ExistingProduct[] = await prodRes.json();
        setExistingProducts(pData);
      }
    } catch (err: any) {
      setError(err.message || 'Errore di connessione');
    } finally {
      setLoading(false);
    }
  };

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
    const rawUom = item.unita_misura || 'Pz';
    const invoiceDate = item.data_documento || item.latest_invoice_date || new Date().toISOString().split('T')[0];

    const initialCategory = item.suggested_product.category || 'Food';
    const initialSubcategory = item.suggested_product.subcategory || '';
    fetchSubcategories(initialCategory);

    // Populate create form
    setCreateForm({
      canonical_name: item.suggested_product.canonical_name || item.raw_description,
      sku_interno: autoSku,
      category: initialCategory,
      subcategory: initialSubcategory,
      comparison_unit: item.suggested_product.comparison_unit || 'piece',
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
  const handleResolveCreateNew = async (item: WorkQueueItem) => {
    if (!createForm.canonical_name.trim()) {
      alert('Inserisci il nome del prodotto');
      return;
    }

    setResolvingKey(item.work_key);
    setError(null);
    try {
      const payload = {
        invoice_line_ids: item.invoice_line_ids,
        action: 'create_canonical',
        canonical_data: {
          canonical_name: createForm.canonical_name.trim(),
          sku_interno: createForm.sku_interno.trim() || undefined,
          category: createForm.category || undefined,
          subcategory: createForm.subcategory.trim() || undefined,
          comparison_unit: createForm.comparison_unit || 'piece',
          prezzo_listino: createForm.prezzo_listino ? parseFloat(createForm.prezzo_listino) : undefined,
          unita_misura_listino: createForm.unita_misura_listino || 'Pz',
          data_inizio_validita: createForm.data_inizio_validita || undefined,
        },
        insert_in_listino: true,
        prezzo_listino: createForm.prezzo_listino ? parseFloat(createForm.prezzo_listino) : undefined,
        unita_misura_listino: createForm.unita_misura_listino || 'Pz',
        data_inizio_validita: createForm.data_inizio_validita || undefined,
      };

      const res = await fetch(`${API_BASE}/product-identity/match-candidates/work-queue/resolve`, {
        method: 'POST',
        headers: getHeaders(),
        body: JSON.stringify(payload),
      });

      const data = await res.json();
      if (!res.ok) throw new Error(data.detail || 'Errore durante la creazione del prodotto in listino');

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
          unita_misura_listino: item.unita_misura || 'Pz',
          data_inizio_validita: item.data_documento || item.latest_invoice_date || undefined,
        }))
      };

      const res = await fetch(`${API_BASE}/product-identity/match-candidates/work-queue/resolve-bulk`, {
        method: 'POST',
        headers: getHeaders(),
        body: JSON.stringify(payload),
      });

      const data = await res.json();
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

  // Bulk Resolve: Insert All / Selected as New Products in Listino
  const handleResolveBulkAsNew = async (targetItems?: WorkQueueItem[], bulkCategory = 'Food') => {
    const itemsToResolve = targetItems || queueData?.items.filter(i => !i.best_candidate) || [];
    if (itemsToResolve.length === 0) {
      alert('Nessun prodotto da inserire come nuovo.');
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
          const baseCode = rawClean.replace(/[^a-zA-Z0-9]/g, '').toUpperCase().slice(0, 8);
          const autoSku = `SKU-${baseCode}-${Math.floor(100 + Math.random() * 900)}`;
          const cat = item.suggested_product.category || bulkCategory;
          const subcat = item.suggested_product.subcategory || '';
          const rawPrice = item.prezzo_unitario && item.prezzo_unitario > 0 ? item.prezzo_unitario : undefined;
          const rawUom = item.unita_misura || 'Pz';
          const invoiceDate = item.data_documento || item.latest_invoice_date || undefined;

          return {
            invoice_line_ids: item.invoice_line_ids,
            action: 'create_canonical',
            canonical_data: {
              canonical_name: rawClean,
              sku_interno: autoSku,
              category: cat,
              subcategory: subcat || undefined,
              comparison_unit: item.suggested_product.comparison_unit || 'piece',
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
      if (!res.ok) throw new Error(data.detail || 'Errore durante la creazione massiva');

      setActionSuccess(`✅ Creati e inseriti a listino ${data.resolved_items || itemsToResolve.length} nuovi prodotti!`);
      setTimeout(() => setActionSuccess(null), 6000);
      setSelectedKeys(new Set());
      await loadAll();
    } catch (err: any) {
      setError(err.message || 'Errore durante la registrazione massiva');
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
                background: 'linear-gradient(135deg, rgba(59, 130, 246, 0.2), rgba(16, 185, 129, 0.2))',
                padding: '10px',
                borderRadius: '12px',
                border: '1px solid rgba(59, 130, 246, 0.3)',
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
            disabled={loading}
            style={{
              display: 'flex',
              alignItems: 'center',
              gap: '8px',
              padding: '10px 16px',
              background: 'rgba(255, 255, 255, 0.05)',
              border: '1px solid var(--border-glass)',
              borderRadius: 'var(--border-radius-sm)',
              color: 'var(--text-primary)',
              cursor: loading ? 'not-allowed' : 'pointer',
              fontSize: '0.85rem',
              fontWeight: 500,
              transition: 'var(--transition-smooth)'
            }}
          >
            <RefreshCw size={16} className={loading ? 'spin' : ''} />
            Aggiorna Dati
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
            <div style={{ background: 'rgba(255, 255, 255, 0.02)', padding: '14px 18px', borderRadius: '10px', border: '1px solid rgba(255, 255, 255, 0.05)' }}>
              <div style={{ fontSize: '0.75rem', color: 'var(--text-secondary)', textTransform: 'uppercase', letterSpacing: '0.5px' }}>Voci Fuori Listino</div>
              <div style={{ fontSize: '1.8rem', fontWeight: 700, color: queueData.summary.work_items > 0 ? 'var(--status-yellow)' : 'var(--status-green)', marginTop: '4px' }}>
                {queueData.summary.work_items}
              </div>
            </div>

            <div style={{ background: 'rgba(255, 255, 255, 0.02)', padding: '14px 18px', borderRadius: '10px', border: '1px solid rgba(255, 255, 255, 0.05)' }}>
              <div style={{ fontSize: '0.75rem', color: 'var(--text-secondary)', textTransform: 'uppercase', letterSpacing: '0.5px' }}>Righe Fattura Coinvolte</div>
              <div style={{ fontSize: '1.8rem', fontWeight: 700, color: 'var(--text-primary)', marginTop: '4px' }}>
                {queueData.summary.invoice_lines}
              </div>
            </div>

            <div style={{ background: 'rgba(255, 255, 255, 0.02)', padding: '14px 18px', borderRadius: '10px', border: '1px solid rgba(255, 255, 255, 0.05)' }}>
              <div style={{ fontSize: '0.75rem', color: 'var(--text-secondary)', textTransform: 'uppercase', letterSpacing: '0.5px' }}>Suggerimenti Intelligenti</div>
              <div style={{ fontSize: '1.8rem', fontWeight: 700, color: 'var(--accent-blue)', marginTop: '4px' }}>
                {queueData.summary.reliable_suggestions}
              </div>
            </div>

            <div style={{ background: 'rgba(255, 255, 255, 0.02)', padding: '14px 18px', borderRadius: '10px', border: '1px solid rgba(255, 255, 255, 0.05)' }}>
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
          background: 'rgba(16, 185, 129, 0.15)',
          border: '1px solid rgba(16, 185, 129, 0.3)',
          borderRadius: 'var(--border-radius-md)',
          color: '#34d399',
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
          border: '1px solid rgba(239, 68, 68, 0.3)',
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
                background: 'rgba(255, 255, 255, 0.04)',
                border: '1px solid var(--border-glass)',
                borderRadius: '8px',
                color: 'white',
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
                borderRadius: '8px',
                color: 'white',
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
        <div style={{ display: 'flex', gap: '8px', background: 'rgba(255,255,255,0.03)', padding: '4px', borderRadius: '8px', border: '1px solid var(--border-glass)' }}>
          <button
            onClick={() => setStatusFilter('all')}
            style={{
              padding: '6px 14px',
              borderRadius: '6px',
              border: 'none',
              background: statusFilter === 'all' ? 'var(--accent-blue)' : 'transparent',
              color: statusFilter === 'all' ? '#fff' : 'var(--text-secondary)',
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
              borderRadius: '6px',
              border: 'none',
              background: statusFilter === 'suggested' ? 'var(--accent-blue)' : 'transparent',
              color: statusFilter === 'suggested' ? '#fff' : 'var(--text-secondary)',
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
              borderRadius: '6px',
              border: 'none',
              background: statusFilter === 'unmatched' ? 'var(--accent-blue)' : 'transparent',
              color: statusFilter === 'unmatched' ? '#fff' : 'var(--text-secondary)',
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

      {/* Bulk Action & Selection Toolbar */}
      {!loading && filteredItems.length > 0 && (
        <div className="glass-panel" style={{
          padding: '14px 20px',
          display: 'flex',
          justifyContent: 'space-between',
          alignItems: 'center',
          flexWrap: 'wrap',
          gap: '14px',
          background: 'rgba(255, 255, 255, 0.02)',
          border: '1px solid var(--border-glass)'
        }}>
          {/* Left: Select All Checkbox & Count */}
          <div style={{ display: 'flex', alignItems: 'center', gap: '12px' }}>
            <label style={{ display: 'flex', alignItems: 'center', gap: '8px', cursor: 'pointer', fontSize: '0.9rem', color: 'white', fontWeight: 500 }}>
              <input
                type="checkbox"
                checked={selectedKeys.size > 0 && selectedKeys.size === filteredItems.length}
                onChange={toggleSelectAll}
                style={{ width: '16px', height: '16px', accentColor: '#3b82f6', cursor: 'pointer' }}
              />
              <span>Seleziona tutti ({filteredItems.length})</span>
            </label>

            {selectedKeys.size > 0 && (
              <span style={{
                background: 'rgba(59, 130, 246, 0.2)',
                color: '#93c5fd',
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
            {selectedKeys.size > 0 ? (
              <>
                <button
                  onClick={() => {
                    const selItems = filteredItems.filter(i => selectedKeys.has(i.work_key) && i.best_candidate);
                    handleResolveBulkSuggestions(selItems);
                  }}
                  disabled={bulkResolving || filteredItems.filter(i => selectedKeys.has(i.work_key) && i.best_candidate).length === 0}
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
                  Accetta Suggerimenti per Selezionati ({filteredItems.filter(i => selectedKeys.has(i.work_key) && i.best_candidate).length})
                </button>

                <button
                  onClick={() => {
                    const selItems = filteredItems.filter(i => selectedKeys.has(i.work_key) && !i.best_candidate);
                    handleResolveBulkAsNew(selItems, 'Food');
                  }}
                  disabled={bulkResolving || filteredItems.filter(i => selectedKeys.has(i.work_key) && !i.best_candidate).length === 0}
                  style={{
                    display: 'flex',
                    alignItems: 'center',
                    gap: '6px',
                    fontSize: '0.82rem',
                    padding: '8px 14px',
                    background: 'rgba(16, 185, 129, 0.2)',
                    border: '1px solid rgba(16, 185, 129, 0.4)',
                    borderRadius: '8px',
                    color: '#34d399',
                    fontWeight: 600,
                    cursor: 'pointer'
                  }}
                >
                  {bulkResolving ? <Loader2 size={14} className="spin" /> : <Plus size={14} />}
                  Crea in Listino Selezionati ({filteredItems.filter(i => selectedKeys.has(i.work_key) && !i.best_candidate).length})
                </button>

                <button
                  onClick={() => setSelectedKeys(new Set())}
                  style={{
                    background: 'transparent',
                    border: '1px solid var(--border-glass)',
                    color: 'var(--text-secondary)',
                    padding: '8px 12px',
                    borderRadius: '8px',
                    fontSize: '0.82rem',
                    cursor: 'pointer'
                  }}
                >
                  Deseleziona
                </button>
              </>
            ) : (
              /* Global Quick Bulk Action Buttons */
              <>
                {(queueData?.summary.reliable_suggestions || 0) > 0 && (
                  <button
                    onClick={() => handleResolveBulkSuggestions()}
                    disabled={bulkResolving}
                    style={{
                      display: 'flex',
                      alignItems: 'center',
                      gap: '8px',
                      fontSize: '0.84rem',
                      padding: '8px 16px',
                      background: 'linear-gradient(135deg, #2563eb, #1d4ed8)',
                      border: 'none',
                      borderRadius: '8px',
                      color: 'white',
                      fontWeight: 600,
                      cursor: bulkResolving ? 'not-allowed' : 'pointer',
                      boxShadow: '0 4px 12px rgba(37, 99, 235, 0.3)'
                    }}
                  >
                    {bulkResolving ? <Loader2 size={14} className="spin" /> : <Zap size={14} />}
                    ⚡ Risolvi Tutti i Suggerimenti Affidabili ({queueData?.summary.reliable_suggestions || 0})
                  </button>
                )}

                {(queueData?.summary.probable_new_products || 0) > 0 && (
                  <button
                    onClick={() => handleResolveBulkAsNew(undefined, 'Food')}
                    disabled={bulkResolving}
                    style={{
                      display: 'flex',
                      alignItems: 'center',
                      gap: '8px',
                      fontSize: '0.84rem',
                      padding: '8px 16px',
                      background: 'rgba(16, 185, 129, 0.15)',
                      border: '1px solid rgba(16, 185, 129, 0.4)',
                      borderRadius: '8px',
                      color: '#34d399',
                      fontWeight: 600,
                      cursor: bulkResolving ? 'not-allowed' : 'pointer'
                    }}
                  >
                    {bulkResolving ? <Loader2 size={14} className="spin" /> : <Plus size={14} />}
                    ➕ Inserisci Tutti i Nuovi in Listino ({queueData?.summary.probable_new_products || 0})
                  </button>
                )}
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
            background: 'rgba(16, 185, 129, 0.1)',
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
                borderRadius: '8px',
                color: 'white',
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
                  border: isExpanded ? '1px solid rgba(59, 130, 246, 0.4)' : '1px solid var(--border-glass)',
                  borderRadius: 'var(--border-radius-md)',
                  overflow: 'hidden',
                  transition: 'var(--transition-smooth)',
                  boxShadow: isExpanded ? '0 8px 24px rgba(59, 130, 246, 0.15)' : undefined
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
                        accentColor: '#3b82f6',
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
                          background: 'rgba(59, 130, 246, 0.1)',
                          color: 'var(--accent-blue)',
                          padding: '4px 10px',
                          borderRadius: '6px',
                          fontSize: '0.8rem',
                          fontWeight: 600
                        }}>
                          <Building2 size={13} />
                          {item.supplier_name}
                        </span>

                        {item.supplier_code && (
                          <span style={{
                            background: 'rgba(255, 255, 255, 0.05)',
                            color: 'var(--text-secondary)',
                            padding: '4px 8px',
                            borderRadius: '6px',
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
                          background: 'rgba(255, 255, 255, 0.03)',
                          color: 'var(--text-secondary)',
                          padding: '4px 8px',
                          borderRadius: '6px',
                          fontSize: '0.75rem'
                        }}>
                          <Calendar size={12} />
                          {item.data_documento || item.latest_invoice_date}
                        </span>

                        <span style={{
                          background: item.occurrence_count > 1 ? 'rgba(245, 158, 11, 0.15)' : 'rgba(255, 255, 255, 0.05)',
                          color: item.occurrence_count > 1 ? 'var(--status-yellow)' : 'var(--text-secondary)',
                          padding: '3px 8px',
                          borderRadius: '6px',
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
                        <span>Prezzo Rilevato in Fattura: <strong style={{ color: '#fff', fontSize: '0.95rem' }}>€{item.prezzo_unitario !== undefined ? item.prezzo_unitario.toFixed(2) : '0.00'}</strong> / {item.unita_misura || 'Pz'}</span>
                        {item.quantita !== undefined && item.quantita > 0 && (
                          <span>Quantità: <strong style={{ color: '#fff' }}>{item.quantita}</strong></span>
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
                        borderRadius: '8px',
                        border: isExpanded && activeMode === 'create' ? '1px solid #34d399' : '1px solid rgba(16, 185, 129, 0.3)',
                        background: isExpanded && activeMode === 'create' ? 'rgba(16, 185, 129, 0.25)' : 'rgba(16, 185, 129, 0.1)',
                        color: '#34d399',
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
                        borderRadius: '8px',
                        border: isExpanded && activeMode === 'associate' ? '1px solid #60a5fa' : '1px solid rgba(59, 130, 246, 0.3)',
                        background: isExpanded && activeMode === 'associate' ? 'rgba(59, 130, 246, 0.25)' : 'rgba(59, 130, 246, 0.1)',
                        color: '#60a5fa',
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
                    borderRadius: '8px',
                    background: 'linear-gradient(90deg, rgba(59, 130, 246, 0.12), rgba(16, 185, 129, 0.08))',
                    border: '1px solid rgba(59, 130, 246, 0.25)',
                    display: 'flex',
                    alignItems: 'center',
                    justifyContent: 'space-between',
                    flexWrap: 'wrap',
                    gap: '12px'
                  }}>
                    <div style={{ display: 'flex', alignItems: 'center', gap: '10px' }}>
                      <Sparkles size={18} color="#60a5fa" />
                      <div>
                        <span style={{ fontSize: '0.85rem', color: 'var(--text-secondary)' }}>Suggerimento corrispondenza: </span>
                        <strong style={{ color: '#fff', fontSize: '0.9rem' }}>{item.best_candidate.canonical_name}</strong>
                        {item.best_candidate.sku_interno && (
                          <span style={{ marginLeft: '8px', color: 'var(--text-secondary)', fontSize: '0.8rem', fontFamily: 'monospace' }}>
                            ({item.best_candidate.sku_interno})
                          </span>
                        )}
                        <span style={{
                          marginLeft: '10px',
                          background: 'rgba(59, 130, 246, 0.2)',
                          color: '#93c5fd',
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
                        background: 'rgba(59, 130, 246, 0.2)',
                        border: '1px solid rgba(59, 130, 246, 0.4)',
                        borderRadius: '6px',
                        color: '#fff',
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
                    background: 'rgba(0, 0, 0, 0.25)',
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
                          borderRadius: '8px',
                          border: 'none',
                          background: activeMode === 'create' ? 'rgba(16, 185, 129, 0.2)' : 'transparent',
                          color: activeMode === 'create' ? '#34d399' : 'var(--text-secondary)',
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
                          borderRadius: '8px',
                          border: 'none',
                          background: activeMode === 'associate' ? 'rgba(59, 130, 246, 0.2)' : 'transparent',
                          color: activeMode === 'associate' ? '#60a5fa' : 'var(--text-secondary)',
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
                          borderRadius: '8px',
                          background: 'rgba(16, 185, 129, 0.08)',
                          border: '1px solid rgba(16, 185, 129, 0.2)',
                          color: '#34d399',
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
                                background: 'rgba(255, 255, 255, 0.05)',
                                border: '1px solid var(--border-glass)',
                                borderRadius: '8px',
                                color: 'white',
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
                                background: 'rgba(255, 255, 255, 0.05)',
                                border: '1px solid var(--border-glass)',
                                borderRadius: '8px',
                                color: 'white',
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
                              onChange={e => setCreateForm({ ...createForm, category: e.target.value })}
                              style={{
                                width: '100%',
                                padding: '10px 14px',
                                background: 'var(--bg-secondary)',
                                border: '1px solid var(--border-glass)',
                                borderRadius: '8px',
                                color: 'white',
                                fontSize: '0.9rem',
                                outline: 'none'
                              }}
                            >
                              {CATEGORIES.map(cat => (
                                <option key={cat} value={cat}>{cat}</option>
                              ))}
                            </select>
                          </div>

                          <div>
                            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '6px' }}>
                              <label style={{ fontSize: '0.8rem', color: 'var(--text-secondary)', fontWeight: 500 }}>
                                Sottocategoria {createForm.category === 'Food' ? '(Food)' : ''}
                              </label>
                              {!showInlineNewSubcat && (
                                <button
                                  type="button"
                                  onClick={() => setShowInlineNewSubcat(true)}
                                  style={{
                                    background: 'transparent',
                                    border: 'none',
                                    color: '#60a5fa',
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
                                    background: 'rgba(255, 255, 255, 0.05)',
                                    border: '1px solid #3b82f6',
                                    borderRadius: '8px',
                                    color: 'white',
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
                                    background: '#10b981',
                                    border: 'none',
                                    borderRadius: '8px',
                                    color: 'white',
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
                                    background: 'rgba(255,255,255,0.05)',
                                    border: '1px solid var(--border-glass)',
                                    borderRadius: '8px',
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
                                  borderRadius: '8px',
                                  color: 'white',
                                  fontSize: '0.9rem',
                                  outline: 'none'
                                }}
                              >
                                <option value="">-- Nessuna / Generale --</option>
                                {availableSubcategories.map(sub => (
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
                                  background: 'rgba(255, 255, 255, 0.05)',
                                  border: '1px solid var(--border-glass)',
                                  borderRadius: '8px',
                                  color: 'white',
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
                            <input
                              type="text"
                              value={createForm.unita_misura_listino}
                              onChange={e => setCreateForm({ ...createForm, unita_misura_listino: e.target.value })}
                              placeholder="Pz, Cassa, Kg, Lt, Bottiglia..."
                              style={{
                                width: '100%',
                                padding: '10px 14px',
                                background: 'rgba(255, 255, 255, 0.05)',
                                border: '1px solid var(--border-glass)',
                                borderRadius: '8px',
                                color: 'white',
                                fontSize: '0.9rem',
                                outline: 'none'
                              }}
                            />
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
                                background: 'rgba(255, 255, 255, 0.05)',
                                border: '1px solid var(--border-glass)',
                                borderRadius: '8px',
                                color: 'white',
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
                              borderRadius: '8px',
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
                              background: 'linear-gradient(135deg, #10b981, #059669)',
                              border: 'none',
                              borderRadius: '8px',
                              color: 'white',
                              fontWeight: 600,
                              cursor: isResolving ? 'not-allowed' : 'pointer',
                              display: 'flex',
                              alignItems: 'center',
                              gap: '8px',
                              fontSize: '0.9rem',
                              boxShadow: '0 4px 12px rgba(16, 185, 129, 0.25)'
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
                          borderRadius: '8px',
                          background: 'rgba(59, 130, 246, 0.08)',
                          border: '1px solid rgba(59, 130, 246, 0.2)',
                          color: '#60a5fa',
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
                                background: 'rgba(255, 255, 255, 0.05)',
                                border: '1px solid var(--border-glass)',
                                borderRadius: '8px',
                                color: 'white',
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
                            borderRadius: '8px',
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
                                      borderBottom: '1px solid rgba(255, 255, 255, 0.04)',
                                      cursor: 'pointer',
                                      background: isSelected ? 'rgba(59, 130, 246, 0.2)' : 'transparent',
                                      display: 'flex',
                                      alignItems: 'center',
                                      justifyContent: 'space-between',
                                      transition: 'var(--transition-smooth)'
                                    }}
                                  >
                                    <div>
                                      <strong style={{ color: isSelected ? '#93c5fd' : 'white', fontSize: '0.9rem' }}>
                                        {p.canonical_name}
                                      </strong>
                                      {p.sku_interno && (
                                        <span style={{ marginLeft: '8px', fontSize: '0.75rem', color: 'var(--text-secondary)', fontFamily: 'monospace' }}>
                                          [{p.sku_interno}]
                                        </span>
                                      )}
                                      {p.category && (
                                        <span style={{ marginLeft: '8px', fontSize: '0.75rem', background: 'rgba(255,255,255,0.05)', padding: '2px 6px', borderRadius: '4px', color: 'var(--text-secondary)' }}>
                                          {p.category}
                                        </span>
                                      )}
                                    </div>
                                    {isSelected && <Check size={16} color="#60a5fa" />}
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
                                  background: 'rgba(255, 255, 255, 0.05)',
                                  border: '1px solid var(--border-glass)',
                                  borderRadius: '8px',
                                  color: 'white',
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
                            <input
                              type="text"
                              value={associateUomListino}
                              onChange={e => setAssociateUomListino(e.target.value)}
                              placeholder="Pz, Cassa, Kg..."
                              style={{
                                width: '100%',
                                padding: '10px 14px',
                                background: 'rgba(255, 255, 255, 0.05)',
                                border: '1px solid var(--border-glass)',
                                borderRadius: '8px',
                                color: 'white',
                                fontSize: '0.9rem',
                                outline: 'none'
                              }}
                            />
                          </div>
                        </div>

                        {/* Action buttons */}
                        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginTop: '10px' }}>
                          <button
                            onClick={() => handleResolveIgnore(item)}
                            style={{
                              padding: '8px 14px',
                              background: 'transparent',
                              border: '1px solid rgba(239, 68, 68, 0.2)',
                              borderRadius: '8px',
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
                                borderRadius: '8px',
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
                                background: selectedExistingId ? 'linear-gradient(135deg, #3b82f6, #2563eb)' : 'rgba(255,255,255,0.05)',
                                border: 'none',
                                borderRadius: '8px',
                                color: selectedExistingId ? 'white' : 'var(--text-secondary)',
                                fontWeight: 600,
                                cursor: selectedExistingId && !isResolving ? 'pointer' : 'not-allowed',
                                display: 'flex',
                                alignItems: 'center',
                                gap: '8px',
                                fontSize: '0.9rem',
                                boxShadow: selectedExistingId ? '0 4px 12px rgba(59, 130, 246, 0.25)' : undefined
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
    </div>
  );
}
