import { useState, useEffect, useMemo } from 'react';
import { 
  ShoppingCart, 
  Search, 
  Copy, 
  Check, 
  Plus, 
  Minus, 
  RefreshCw, 
  Store, 
  Calendar, 
  FileText, 
  Sparkles, 
  Truck, 
  CheckCircle2, 
  AlertCircle,
  ExternalLink,
  MessageSquare,
  Boxes,
  ArrowRight,
  Filter,
  Trash2,
  Phone
} from 'lucide-react';
import { API_BASE, getHeaders } from '../api';

interface ProductItem {
  id: number;
  sku_interno: string | null;
  canonical_name: string;
  order_name: string | null;
  brand: string | null;
  category: string | null;
  subcategory: string | null;
  comparison_unit: string;
  is_active: boolean;
  prezzo_listino?: number | null;
  fornitore_consigliato_id?: number | null;
  fornitore_consigliato_nome?: string | null;
}

interface LocationItem {
  id: number;
  nome_struttura: string;
  indirizzo?: string | null;
  citta?: string | null;
}

interface SupplierOrderItemDetail {
  product_id: number;
  sku_interno?: string | null;
  nome_prodotto: string;
  codice_fornitore?: string | null;
  quantita: number;
  uom: string;
  prezzo_unitario: number;
  subtotale: number;
  is_concordato: boolean;
}

interface SupplierOrderBundle {
  fornitore_id: number;
  fornitore_nome: string;
  partita_iva?: string | null;
  email_contatto?: string | null;
  telefono_contatto?: string | null;
  totale_ordine: number;
  numero_articoli: number;
  totale_colli: number;
  items: SupplierOrderItemDetail[];
  whatsapp_message: string;
  whatsapp_url: string;
}

interface SectorOrderDraftResponse {
  location_id: number;
  location_nome: string;
  location_indirizzo?: string | null;
  settore?: string | null;
  data_consegna?: string | null;
  note?: string | null;
  totale_complessivo: number;
  totale_fornitori_coinvolti: number;
  totale_articoli: number;
  fornitori_ordini: SupplierOrderBundle[];
}

const MACRO_CATEGORIES = [
  { id: 'all', label: 'Tutti i settori', icon: '🌐', color: '#94a3b8' },
  { id: 'Beverage', label: 'Beverage', icon: '🍹', color: '#60a5fa' },
  { id: 'Food', label: 'Food', icon: '🍽️', color: '#f59e0b' },
  { id: 'Materiali di consumo', label: 'Materiali di consumo', icon: '📦', color: '#10b981' }
];

export const SECTOR_UOMS: Record<string, { id: string; label: string; short: string }[]> = {
  Beverage: [
    { id: 'BT', label: 'BT (Bottiglia)', short: 'BT' },
    { id: 'CT', label: 'CT (Cartone)', short: 'CT' },
    { id: 'BOX', label: 'BOX (Box)', short: 'BOX' },
  ],
  'Materiali di consumo': [
    { id: 'PZ', label: 'PZ (Pezzo)', short: 'PZ' },
    { id: 'CT', label: 'CT (Cartone)', short: 'CT' },
    { id: 'BUSTA', label: 'BUSTA (Busta)', short: 'BUSTA' },
  ],
  Food: [
    { id: 'PZ', label: 'PZ (Pezzo)', short: 'PZ' },
    { id: 'CT', label: 'CT (Cartone)', short: 'CT' },
    { id: 'KG', label: 'KG (Chilogrammo)', short: 'KG' },
    { id: 'LT', label: 'LT (Litro)', short: 'LT' },
  ]
};

export function getSectorUoms(category?: string | null): { id: string; label: string; short: string }[] {
  if (category && SECTOR_UOMS[category]) {
    return SECTOR_UOMS[category];
  }
  return [
    { id: 'CT', label: 'CT (Cartone)', short: 'CT' },
    { id: 'BT', label: 'BT (Bottiglia)', short: 'BT' },
    { id: 'PZ', label: 'PZ (Pezzo)', short: 'PZ' },
    { id: 'BOX', label: 'BOX (Box)', short: 'BOX' },
    { id: 'BUSTA', label: 'BUSTA (Busta)', short: 'BUSTA' },
  ];
}

export function normalizeDefaultUom(rawUom?: string | null, category?: string | null): string {
  if (category === 'Beverage') {
    if (!rawUom) return 'CT';
    const u = rawUom.trim().toUpperCase();
    if (u.includes('BOX')) return 'BOX';
    if (u === 'BT' || u.includes('BOTT')) return 'BT';
    return 'CT';
  }
  if (category === 'Materiali di consumo') {
    if (!rawUom) return 'CT';
    const u = rawUom.trim().toUpperCase();
    if (u.includes('BUST')) return 'BUSTA';
    if (u === 'PZ' || u === 'PIECE' || u === 'PEZZO') return 'PZ';
    return 'CT';
  }
  if (!rawUom) return 'CT';
  const u = rawUom.trim().toUpperCase();
  if (u === 'BT' || u.includes('BOTT')) return 'BT';
  if (u === 'PIECE' || u === 'PZ' || u === 'PEZZO') return 'PZ';
  if (u.includes('BUST')) return 'BUSTA';
  if (u.includes('BOX')) return 'BOX';
  return 'CT';
}

export default function SectorOrderBuilder() {
  const [locations, setLocations] = useState<LocationItem[]>([]);
  const [selectedLocation, setSelectedLocation] = useState<number | ''>('');
  const [selectedSector, setSelectedSector] = useState<string>('all');
  const [deliveryDate, setDeliveryDate] = useState<string>(() => {
    const d = new Date();
    d.setDate(d.getDate() + 1);
    return d.toISOString().split('T')[0];
  });
  const [orderNotes, setOrderNotes] = useState<string>('');
  
  const [products, setProducts] = useState<ProductItem[]>([]);
  const [loading, setLoading] = useState<boolean>(true);
  const [searchTerm, setSearchTerm] = useState<string>('');
  const [selectedSubcategory, setSelectedSubcategory] = useState<string>('all');

  // Quantities mapped by product_id
  const [quantities, setQuantities] = useState<Record<number, number>>({});

  // Unit of Measure overrides per product_id
  const [selectedUoms, setSelectedUoms] = useState<Record<number, string>>({});

  // Helper for effective UoM
  const getEffectiveUom = (prod: ProductItem) => {
    return selectedUoms[prod.id] || normalizeDefaultUom(prod.comparison_unit, prod.category);
  };

  // Draft resolution state
  const [draftProcessing, setDraftProcessing] = useState<boolean>(false);
  const [draftResult, setDraftResult] = useState<SectorOrderDraftResponse | null>(null);
  const [copiedSupplierId, setCopiedSupplierId] = useState<number | null>(null);
  const [savingOrders, setSavingOrders] = useState<boolean>(false);
  const [saveSuccessMsg, setSaveSuccessMsg] = useState<string | null>(null);
  const [errorMsg, setErrorMsg] = useState<string | null>(null);

  // Phone numbers overrides per supplier
  const [supplierPhones, setSupplierPhones] = useState<Record<number, string>>({});

  const headers = getHeaders();

  useEffect(() => {
    loadData();
  }, []);

  async function loadData() {
    setLoading(true);
    setErrorMsg(null);
    try {
      const [locRes, prodRes, matrixRes] = await Promise.all([
        fetch(`${API_BASE}/location/`, { headers }),
        fetch(`${API_BASE}/products`, { headers }),
        fetch(`${API_BASE}/smart-price-sheet/matrix?category=all&limit=500`, { headers }).catch(() => null)
      ]);

      if (locRes.ok) {
        const locData = await locRes.json();
        if (Array.isArray(locData)) {
          setLocations(locData);
          if (locData.length > 0) setSelectedLocation(locData[0].id);
        }
      }

      let prods: ProductItem[] = [];
      if (prodRes.ok) {
        const prodData = await prodRes.json();
        if (Array.isArray(prodData)) {
          prods = prodData.filter(p => p.is_active);
        }
      }

      // If matrix is available, enrich products with recommended suppliers and prices
      if (matrixRes && matrixRes.ok) {
        try {
          const matrixData = await matrixRes.json();
          const matrixMap = new Map<number, any>();
          (matrixData.rows || []).forEach((r: any) => {
            matrixMap.set(r.product_id, r);
          });

          prods = prods.map(p => {
            const m = matrixMap.get(p.id);
            if (m) {
              const recOffer = m.recommended_supplier_id ? m.offers[String(m.recommended_supplier_id)] : null;
              const selOffer = m.selected_supplier_id ? m.offers[String(m.selected_supplier_id)] : null;
              const offer = selOffer || recOffer;
              return {
                ...p,
                category: m.category || p.category,
                subcategory: m.subcategory || p.subcategory,
                order_name: m.order_name || p.order_name,
                prezzo_listino: offer ? parseFloat(offer.price) : null,
                fornitore_consigliato_id: offer ? offer.supplier_id : null,
                fornitore_consigliato_nome: offer ? offer.supplier_name : null,
              };
            }
            return p;
          });
        } catch (e) {
          console.error("Errore arricchimento listino:", e);
        }
      }

      setProducts(prods);
    } catch (err: any) {
      console.error(err);
      setErrorMsg("Errore durante il caricamento del catalogo prodotti.");
    } finally {
      setLoading(false);
    }
  }

  // Filtered products
  const subcategories = useMemo(() => {
    const filteredBySector = products.filter(p => 
      selectedSector === 'all' || p.category === selectedSector
    );
    const set = new Set<string>();
    filteredBySector.forEach(p => {
      if (p.subcategory && p.subcategory.trim()) set.add(p.subcategory.trim());
    });
    return Array.from(set).sort();
  }, [products, selectedSector]);

  const filteredProducts = useMemo(() => {
    return products.filter(p => {
      const matchSector = selectedSector === 'all' || p.category === selectedSector;
      const matchSubcat = selectedSubcategory === 'all' || p.subcategory === selectedSubcategory;
      const search = searchTerm.toLowerCase().trim();
      const matchSearch = !search 
        || p.canonical_name.toLowerCase().includes(search)
        || (p.order_name && p.order_name.toLowerCase().includes(search))
        || (p.sku_interno && p.sku_interno.toLowerCase().includes(search))
        || (p.brand && p.brand.toLowerCase().includes(search));
      return matchSector && matchSubcat && matchSearch;
    });
  }, [products, selectedSector, selectedSubcategory, searchTerm]);

  // Quantities and Basket Totals
  const basketItems = useMemo(() => {
    const items: { product: ProductItem; quantity: number; uom: string }[] = [];
    Object.entries(quantities).forEach(([prodIdStr, qty]) => {
      if (qty > 0) {
        const prod = products.find(p => p.id === Number(prodIdStr));
        if (prod) {
          const uom = selectedUoms[prod.id] || normalizeDefaultUom(prod.comparison_unit);
          items.push({ product: prod, quantity: qty, uom });
        }
      }
    });
    return items;
  }, [quantities, products, selectedUoms]);

  const basketStats = useMemo(() => {
    const totalItems = basketItems.length;
    const totalUnits = basketItems.reduce((acc, it) => acc + it.quantity, 0);
    const estimatedTotal = basketItems.reduce((acc, it) => {
      const price = it.product.prezzo_listino || 0;
      return acc + (price * it.quantity);
    }, 0);

    const suppliersSet = new Set<string>();
    basketItems.forEach(it => {
      if (it.product.fornitore_consigliato_nome) {
        suppliersSet.add(it.product.fornitore_consigliato_nome);
      }
    });

    return {
      totalItems,
      totalUnits,
      estimatedTotal,
      supplierCount: suppliersSet.size || (totalItems > 0 ? 1 : 0),
      supplierNames: Array.from(suppliersSet)
    };
  }, [basketItems]);

  const handleQtyChange = (productId: number, newQty: number) => {
    const safeQty = Math.max(0, Math.round(newQty * 100) / 100);
    setQuantities(prev => {
      if (safeQty === 0) {
        const next = { ...prev };
        delete next[productId];
        return next;
      }
      return { ...prev, [productId]: safeQty };
    });
  };

  const handleAddPreset = (productId: number, delta: number) => {
    const current = quantities[productId] || 0;
    handleQtyChange(productId, current + delta);
  };

  const handleResetBasket = () => {
    if (basketItems.length === 0 || window.confirm("Sei sicuro di voler azzerare il carrello dell'ordine?")) {
      setQuantities({});
      setSelectedUoms({});
      setDraftResult(null);
      setSaveSuccessMsg(null);
    }
  };

  // Submit Order for Processing
  const handleProcessOrder = async () => {
    if (basketItems.length === 0) {
      alert("Seleziona almeno un articolo con quantità maggiore di 0.");
      return;
    }
    if (!selectedLocation) {
      alert("Seleziona la sede di destinazione per l'ordine.");
      return;
    }

    setDraftProcessing(true);
    setErrorMsg(null);
    setSaveSuccessMsg(null);

    const payload = {
      location_id: Number(selectedLocation),
      settore: selectedSector !== 'all' ? selectedSector : null,
      data_consegna: deliveryDate || null,
      note: orderNotes.trim() || null,
      items: basketItems.map(it => ({
        product_id: it.product.id,
        sku_interno: it.product.sku_interno,
        canonical_name: it.product.canonical_name,
        order_name: it.product.order_name,
        quantita: it.quantity,
        comparison_unit: it.uom,
        category: it.product.category,
        preferred_supplier_id: it.product.fornitore_consigliato_id,
        prezzo_unitario: it.product.prezzo_listino
      }))
    };

    try {
      const res = await fetch(`${API_BASE}/ordini/settore/elabora`, {
        method: 'POST',
        headers: {
          ...headers,
          'Content-Type': 'application/json'
        },
        body: JSON.stringify(payload)
      });

      if (!res.ok) {
        const errData = await res.json().catch(() => ({}));
        throw new Error(errData.detail || "Errore durante l'elaborazione dell'ordine.");
      }

      const data: SectorOrderDraftResponse = await res.json();
      setDraftResult(data);

      // Scroll to bottom/summary
      setTimeout(() => {
        const el = document.getElementById('order-resolution-summary');
        if (el) el.scrollIntoView({ behavior: 'smooth' });
      }, 100);
    } catch (err: any) {
      setErrorMsg(err.message || "Si è verificato un errore.");
    } finally {
      setDraftProcessing(false);
    }
  };

  // Copy WhatsApp Message to Clipboard
  const handleCopyWhatsApp = (supplierId: number, message: string) => {
    navigator.clipboard.writeText(message);
    setCopiedSupplierId(supplierId);
    setTimeout(() => setCopiedSupplierId(null), 3000);
  };

  // Open Direct WhatsApp URL with optional phone override
  const handleOpenWhatsApp = (bundle: SupplierOrderBundle) => {
    const rawPhone = supplierPhones[bundle.fornitore_id] || bundle.telefono_contatto || '';
    const cleanPhone = rawPhone.replace(/\D/g, '');
    
    let url = bundle.whatsapp_url;
    if (cleanPhone.length >= 8) {
      const intlPhone = cleanPhone.startsWith('39') ? cleanPhone : `39${cleanPhone}`;
      const msgEncoded = encodeURIComponent(bundle.whatsapp_message);
      url = `https://wa.me/${intlPhone}?text=${msgEncoded}`;
    }

    window.open(url, '_blank');
  };

  // Save Orders in Database for Invoicing Reconciliation
  const handleSaveOrdersToDb = async () => {
    if (!draftResult) return;

    setSavingOrders(true);
    setErrorMsg(null);
    try {
      const res = await fetch(`${API_BASE}/ordini/settore/salva`, {
        method: 'POST',
        headers: {
          ...headers,
          'Content-Type': 'application/json'
        },
        body: JSON.stringify({
          location_id: draftResult.location_id,
          settore: draftResult.settore,
          data_consegna: draftResult.data_consegna,
          note: draftResult.note,
          bundles: draftResult.fornitori_ordini
        })
      });

      if (!res.ok) {
        const errData = await res.json().catch(() => ({}));
        throw new Error(errData.detail || "Errore durante il salvataggio degli ordini.");
      }

      const data = await res.json();
      setSaveSuccessMsg(`🎉 ${data.ordini_creati} Buoni d'ordine registrati con successo nel sistema! Pronti per la riconciliazione automatica con le fatture future.`);
    } catch (err: any) {
      setErrorMsg(err.message || "Errore durante il salvataggio.");
    } finally {
      setSavingOrders(false);
    }
  };

  const selectedLocObj = locations.find(l => l.id === Number(selectedLocation));

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: '24px', paddingBottom: '120px' }}>
      
      {/* Top Banner / Hero */}
      <div className="glass-panel" style={{ 
        padding: '24px 30px', 
        background: 'linear-gradient(135deg, rgba(30, 41, 59, 0.9) 0%, rgba(15, 23, 42, 0.95) 100%)',
        border: '1px solid rgba(59, 130, 246, 0.25)',
        display: 'flex',
        justifyContent: 'space-between',
        alignItems: 'center',
        flexWrap: 'wrap',
        gap: '20px'
      }}>
        <div>
          <div style={{ display: 'flex', alignItems: 'center', gap: '10px' }}>
            <div style={{ 
              width: '40px', height: '40px', borderRadius: '10px', 
              background: 'linear-gradient(135deg, #3b82f6, #6366f1)',
              display: 'flex', alignItems: 'center', justifyContent: 'center',
              boxShadow: '0 0 20px rgba(59, 130, 246, 0.4)'
            }}>
              <ShoppingCart size={22} color="white" />
            </div>
            <div>
              <h2 style={{ fontSize: '1.4rem', fontWeight: 800, margin: 0, letterSpacing: '-0.02em' }}>
                Sviluppo Ordini Settore
              </h2>
              <p style={{ color: 'var(--text-secondary)', fontSize: '0.85rem', margin: '3px 0 0' }}>
                Compila il fabbisogno merci: il sistema assegna i migliori prezzi fornitore e genera i messaggi WhatsApp pronti per i rappresentanti.
              </p>
            </div>
          </div>
        </div>

        {/* Quick Order Header Controls */}
        <div style={{ display: 'flex', gap: '14px', alignItems: 'center', flexWrap: 'wrap' }}>
          {/* Location Selector */}
          <div style={{ display: 'flex', flexDirection: 'column', gap: '4px' }}>
            <label style={{ fontSize: '0.75rem', fontWeight: 600, color: 'var(--text-secondary)', display: 'flex', alignItems: 'center', gap: '4px' }}>
              <Store size={13} color="var(--accent-blue)" /> Sede di Consegna
            </label>
            <select
              value={selectedLocation}
              onChange={e => setSelectedLocation(e.target.value ? Number(e.target.value) : '')}
              style={{
                padding: '8px 12px',
                background: 'rgba(0,0,0,0.4)',
                border: '1px solid var(--border-glass)',
                borderRadius: '8px',
                color: 'white',
                fontSize: '0.85rem',
                outline: 'none',
                minWidth: '180px'
              }}
            >
              {locations.map(loc => (
                <option key={loc.id} value={loc.id} style={{ background: '#13131c' }}>
                  {loc.nome_struttura}
                </option>
              ))}
            </select>
          </div>

          {/* Delivery Date */}
          <div style={{ display: 'flex', flexDirection: 'column', gap: '4px' }}>
            <label style={{ fontSize: '0.75rem', fontWeight: 600, color: 'var(--text-secondary)', display: 'flex', alignItems: 'center', gap: '4px' }}>
              <Calendar size={13} color="var(--status-green)" /> Data Consegna Richiesta
            </label>
            <input
              type="date"
              value={deliveryDate}
              onChange={e => setDeliveryDate(e.target.value)}
              style={{
                padding: '7px 12px',
                background: 'rgba(0,0,0,0.4)',
                border: '1px solid var(--border-glass)',
                borderRadius: '8px',
                color: 'white',
                fontSize: '0.85rem',
                outline: 'none'
              }}
            />
          </div>

          {/* Optional Order Notes */}
          <div style={{ display: 'flex', flexDirection: 'column', gap: '4px' }}>
            <label style={{ fontSize: '0.75rem', fontWeight: 600, color: 'var(--text-secondary)', display: 'flex', alignItems: 'center', gap: '4px' }}>
              <FileText size={13} color="#f59e0b" /> Note Consegna
            </label>
            <input
              type="text"
              placeholder="Es. Consegna entro le 11:00..."
              value={orderNotes}
              onChange={e => setOrderNotes(e.target.value)}
              style={{
                padding: '7px 12px',
                background: 'rgba(0,0,0,0.4)',
                border: '1px solid var(--border-glass)',
                borderRadius: '8px',
                color: 'white',
                fontSize: '0.85rem',
                outline: 'none',
                minWidth: '200px'
              }}
            />
          </div>
        </div>
      </div>

      {errorMsg && (
        <div style={{ padding: '14px 18px', borderRadius: '10px', background: 'var(--status-red-bg)', color: 'var(--status-red)', border: '1px solid rgba(239, 68, 68, 0.3)', display: 'flex', gap: '10px', alignItems: 'center' }}>
          <AlertCircle size={18} />
          <span style={{ fontSize: '0.9rem' }}>{errorMsg}</span>
        </div>
      )}

      {/* Settore / Macro-Category Pills Selector */}
      <div style={{ display: 'flex', gap: '10px', flexWrap: 'wrap', alignItems: 'center' }}>
        <span style={{ fontSize: '0.85rem', fontWeight: 700, color: 'var(--text-secondary)', marginRight: '4px' }}>
          Settore Attivo:
        </span>
        {MACRO_CATEGORIES.map(cat => {
          const isSelected = selectedSector === cat.id;
          const count = cat.id === 'all' 
            ? products.length 
            : products.filter(p => p.category === cat.id).length;

          return (
            <button
              key={cat.id}
              type="button"
              onClick={() => {
                setSelectedSector(cat.id);
                setSelectedSubcategory('all');
              }}
              style={{
                padding: '9px 18px',
                borderRadius: '30px',
                border: isSelected ? `2px solid ${cat.color}` : '1px solid var(--border-glass)',
                background: isSelected ? 'rgba(255, 255, 255, 0.1)' : 'rgba(255, 255, 255, 0.02)',
                color: isSelected ? 'white' : 'var(--text-secondary)',
                fontWeight: isSelected ? 700 : 500,
                fontSize: '0.9rem',
                cursor: 'pointer',
                display: 'flex',
                alignItems: 'center',
                gap: '8px',
                boxShadow: isSelected ? `0 0 15px ${cat.color}33` : 'none',
                transition: 'all 0.2s'
              }}
            >
              <span>{cat.icon}</span>
              <span>{cat.label}</span>
              <span style={{ 
                fontSize: '0.75rem', 
                padding: '2px 7px', 
                borderRadius: '10px', 
                background: isSelected ? cat.color : 'rgba(255,255,255,0.08)',
                color: isSelected ? '#000' : 'inherit',
                fontWeight: 700
              }}>
                {count}
              </span>
            </button>
          );
        })}
      </div>

      {/* Search & Subcategory Bar */}
      <div className="glass-panel" style={{ padding: '16px 20px', display: 'flex', gap: '14px', flexWrap: 'wrap', alignItems: 'center' }}>
        {/* Search Input */}
        <div style={{ position: 'relative', flex: '1 1 280px' }}>
          <Search size={16} style={{ position: 'absolute', left: '14px', top: '50%', transform: 'translateY(-50%)', color: 'var(--text-secondary)' }} />
          <input
            type="text"
            placeholder="Cerca per nome prodotto, nome rapido, SKU o brand..."
            value={searchTerm}
            onChange={e => setSearchTerm(e.target.value)}
            style={{
              width: '100%',
              boxSizing: 'border-box',
              padding: '10px 14px 10px 42px',
              background: 'rgba(255,255,255,0.04)',
              border: '1px solid var(--border-glass)',
              borderRadius: '8px',
              color: 'white',
              fontSize: '0.9rem',
              outline: 'none'
            }}
          />
        </div>

        {/* Subcategory dropdown if available */}
        {subcategories.length > 0 && (
          <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
            <Filter size={15} color="var(--text-secondary)" />
            <select
              value={selectedSubcategory}
              onChange={e => setSelectedSubcategory(e.target.value)}
              style={{
                padding: '9px 14px',
                background: 'rgba(255,255,255,0.04)',
                border: '1px solid var(--border-glass)',
                borderRadius: '8px',
                color: 'white',
                fontSize: '0.85rem',
                outline: 'none',
                cursor: 'pointer'
              }}
            >
              <option value="all" style={{ background: '#13131c' }}>Tutte le sottocategorie ({subcategories.length})</option>
              {subcategories.map(sub => (
                <option key={sub} value={sub} style={{ background: '#13131c' }}>
                  {sub}
                </option>
              ))}
            </select>
          </div>
        )}

        <div style={{ color: 'var(--text-secondary)', fontSize: '0.85rem', marginLeft: 'auto' }}>
          Visualizzati: <strong>{filteredProducts.length}</strong> prodotti
        </div>
      </div>

      {/* Products Catalog Cards Grid */}
      {loading ? (
        <div style={{ padding: '60px', textAlign: 'center', color: 'var(--text-secondary)' }}>
          <RefreshCw className="spinner" size={28} style={{ margin: '0 auto 12px' }} />
          <div>Caricamento catalogo prodotti e listini in corso...</div>
        </div>
      ) : filteredProducts.length === 0 ? (
        <div className="glass-panel" style={{ padding: '60px 20px', textAlign: 'center', color: 'var(--text-secondary)' }}>
          <Boxes size={40} style={{ margin: '0 auto 12px', opacity: 0.4 }} />
          <h3 style={{ margin: '0 0 6px', color: 'white' }}>Nessun prodotto trovato</h3>
          <p style={{ fontSize: '0.85rem', margin: 0 }}>Prova a modificare i filtri di ricerca o il settore selezionato.</p>
        </div>
      ) : (
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(320px, 1fr))', gap: '14px' }}>
          {filteredProducts.map(prod => {
            const currentQty = quantities[prod.id] || 0;
            const hasQty = currentQty > 0;
            const unitPrice = prod.prezzo_listino;
            const lineTotal = unitPrice ? unitPrice * currentQty : 0;

            return (
              <div
                key={prod.id}
                style={{
                  padding: '16px 18px',
                  borderRadius: '12px',
                  border: hasQty ? '1px solid var(--accent-blue)' : '1px solid var(--border-glass)',
                  background: hasQty ? 'rgba(59, 130, 246, 0.08)' : 'rgba(255, 255, 255, 0.02)',
                  display: 'flex',
                  flexDirection: 'column',
                  justifyContent: 'space-between',
                  gap: '12px',
                  boxShadow: hasQty ? '0 0 20px rgba(59, 130, 246, 0.15)' : 'none',
                  transition: 'all 0.2s'
                }}
              >
                {/* Product Title & Badges */}
                <div>
                  <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', gap: '10px' }}>
                    <div>
                      <div style={{ fontWeight: 800, fontSize: '0.98rem', color: 'white', lineHeight: '1.3' }}>
                        {prod.order_name || prod.canonical_name}
                      </div>
                      {prod.order_name && prod.canonical_name !== prod.order_name && (
                        <div style={{ color: 'var(--text-secondary)', fontSize: '0.78rem', marginTop: '2px' }}>
                          {prod.canonical_name}
                        </div>
                      )}
                    </div>

                    {hasQty && (
                      <span style={{ 
                        padding: '3px 8px', 
                        borderRadius: '6px', 
                        background: 'var(--accent-blue)', 
                        color: 'white', 
                        fontSize: '0.75rem', 
                        fontWeight: 800,
                        whiteSpace: 'nowrap'
                      }}>
                        {currentQty} {getEffectiveUom(prod)}
                      </span>
                    )}
                  </div>

                  <div style={{ display: 'flex', gap: '6px', alignItems: 'center', flexWrap: 'wrap', marginTop: '8px', fontSize: '0.75rem' }}>
                    <span style={{ color: 'var(--text-secondary)' }}>
                      SKU: <code>{prod.sku_interno || 'N/D'}</code>
                    </span>
                    {prod.subcategory && (
                      <>
                        <span style={{ color: 'rgba(255,255,255,0.2)' }}>•</span>
                        <span style={{ color: '#93c5fd' }}>{prod.subcategory}</span>
                      </>
                    )}
                  </div>

                  {/* Recommended Supplier & Price info */}
                  <div style={{ 
                    marginTop: '10px', 
                    padding: '8px 10px', 
                    borderRadius: '8px', 
                    background: 'rgba(0, 0, 0, 0.25)', 
                    border: '1px solid rgba(255, 255, 255, 0.05)',
                    display: 'flex', 
                    justifyContent: 'space-between', 
                    alignItems: 'center', 
                    fontSize: '0.8rem'
                  }}>
                    <div style={{ display: 'flex', alignItems: 'center', gap: '6px' }}>
                      <Truck size={13} color="var(--accent-blue)" />
                      <span style={{ color: 'var(--text-secondary)' }}>Fornitore:</span>
                      <strong style={{ color: 'white' }}>{prod.fornitore_consigliato_nome || 'Miglior Listino'}</strong>
                    </div>
                    {unitPrice ? (
                      <div style={{ textAlign: 'right' }}>
                        <div style={{ fontWeight: 700, color: 'var(--status-green)' }}>
                          € {unitPrice.toFixed(2)} <span style={{ fontSize: '0.7rem', color: 'var(--text-secondary)', fontWeight: 400 }}>/{getEffectiveUom(prod)}</span>
                        </div>
                        {hasQty && (
                          <div style={{ fontSize: '0.72rem', color: '#60a5fa', fontWeight: 700 }}>
                            Tot: € {lineTotal.toFixed(2)}
                          </div>
                        )}
                      </div>
                    ) : (
                      <div style={{ color: 'var(--text-secondary)', fontSize: '0.75rem' }}>A listino</div>
                    )}
                  </div>
                </div>

                {/* Quantity Controls & UoM Selector */}
                <div>
                  <div style={{ display: 'flex', alignItems: 'center', gap: '6px' }}>
                    <button
                      type="button"
                      onClick={() => handleAddPreset(prod.id, -1)}
                      disabled={currentQty <= 0}
                      style={{
                        width: '34px', height: '34px', borderRadius: '8px',
                        border: '1px solid var(--border-glass)',
                        background: 'rgba(255,255,255,0.05)',
                        color: 'white', display: 'flex', alignItems: 'center', justifyContent: 'center',
                        cursor: currentQty <= 0 ? 'not-allowed' : 'pointer',
                        opacity: currentQty <= 0 ? 0.3 : 1
                      }}
                    >
                      <Minus size={14} />
                    </button>

                    <input
                      type="number"
                      min="0"
                      step="1"
                      value={currentQty === 0 ? '' : currentQty}
                      placeholder="0"
                      onChange={e => handleQtyChange(prod.id, parseFloat(e.target.value) || 0)}
                      style={{
                        flex: 1,
                        padding: '6px 8px',
                        textAlign: 'center',
                        fontWeight: 800,
                        fontSize: '1rem',
                        background: hasQty ? 'rgba(59, 130, 246, 0.15)' : 'rgba(0,0,0,0.3)',
                        border: hasQty ? '1px solid var(--accent-blue)' : '1px solid var(--border-glass)',
                        borderRadius: '8px',
                        color: hasQty ? '#60a5fa' : 'white',
                        outline: 'none',
                        minWidth: '40px'
                      }}
                    />

                    <button
                      type="button"
                      onClick={() => handleAddPreset(prod.id, 1)}
                      style={{
                        width: '34px', height: '34px', borderRadius: '8px',
                        border: '1px solid var(--border-glass)',
                        background: 'rgba(59, 130, 246, 0.2)',
                        color: 'white', display: 'flex', alignItems: 'center', justifyContent: 'center',
                        cursor: 'pointer'
                      }}
                    >
                      <Plus size={14} />
                    </button>

                    {/* UoM Select Dropdown */}
                    <select
                      value={getEffectiveUom(prod)}
                      onChange={e => setSelectedUoms(prev => ({ ...prev, [prod.id]: e.target.value }))}
                      title="Unità di misura"
                      style={{
                        padding: '6px 8px',
                        borderRadius: '8px',
                        background: 'rgba(59, 130, 246, 0.15)',
                        border: '1px solid rgba(59, 130, 246, 0.4)',
                        color: '#93c5fd',
                        fontWeight: 800,
                        fontSize: '0.82rem',
                        outline: 'none',
                        cursor: 'pointer'
                      }}
                    >
                      {getSectorUoms(prod.category).map(u => (
                        <option key={u.id} value={u.id} style={{ background: '#13131c', color: 'white' }}>
                          {u.short}
                        </option>
                      ))}
                    </select>
                  </div>

                  {/* Quick Preset Buttons */}
                  <div style={{ display: 'flex', gap: '5px', marginTop: '8px' }}>
                    {[1, 5, 10, 20].map(preset => (
                      <button
                        key={preset}
                        type="button"
                        onClick={() => handleAddPreset(prod.id, preset)}
                        style={{
                          flex: 1,
                          padding: '4px 0',
                          fontSize: '0.75rem',
                          borderRadius: '6px',
                          border: '1px solid rgba(255,255,255,0.06)',
                          background: 'rgba(255,255,255,0.03)',
                          color: 'var(--text-secondary)',
                          cursor: 'pointer'
                        }}
                      >
                        +{preset}
                      </button>
                    ))}
                    {hasQty && (
                      <button
                        type="button"
                        onClick={() => handleQtyChange(prod.id, 0)}
                        title="Azzera quantità"
                        style={{
                          padding: '4px 8px',
                          fontSize: '0.75rem',
                          borderRadius: '6px',
                          border: '1px solid rgba(239, 68, 68, 0.3)',
                          background: 'rgba(239, 68, 68, 0.1)',
                          color: 'var(--status-red)',
                          cursor: 'pointer'
                        }}
                      >
                        <Trash2 size={12} />
                      </button>
                    )}
                  </div>
                </div>
              </div>
            );
          })}
        </div>
      )}

      {/* Floating Bottom Action Bar for Cart */}
      {basketItems.length > 0 && (
        <div style={{
          position: 'fixed',
          bottom: '20px',
          left: '50%',
          transform: 'translateX(-50%)',
          width: 'calc(100% - 60px)',
          maxWidth: '1100px',
          zIndex: 1000,
          background: 'rgba(15, 23, 42, 0.95)',
          border: '1px solid var(--accent-blue)',
          borderRadius: '16px',
          padding: '16px 24px',
          boxShadow: '0 20px 50px rgba(0, 0, 0, 0.8), 0 0 30px rgba(59, 130, 246, 0.3)',
          backdropFilter: 'blur(12px)',
          display: 'flex',
          justifyContent: 'space-between',
          alignItems: 'center',
          gap: '20px',
          flexWrap: 'wrap'
        }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: '16px', flexWrap: 'wrap' }}>
            <div style={{
              width: '44px', height: '44px', borderRadius: '12px',
              background: 'linear-gradient(135deg, #10b981, #059669)',
              display: 'flex', alignItems: 'center', justifyContent: 'center',
              boxShadow: '0 0 15px rgba(16, 185, 129, 0.4)'
            }}>
              <ShoppingCart size={22} color="white" />
            </div>

            <div>
              <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                <span style={{ fontWeight: 800, fontSize: '1.05rem', color: 'white' }}>
                  Fabbisogno: {basketStats.totalItems} prodotti ({basketStats.totalUnits} colli)
                </span>
                <span style={{ 
                  padding: '2px 8px', borderRadius: '6px', 
                  background: 'rgba(59, 130, 246, 0.2)', color: '#60a5fa', 
                  fontSize: '0.75rem', fontWeight: 700 
                }}>
                  {basketStats.supplierCount} {basketStats.supplierCount === 1 ? 'fornitore' : 'fornitori'} coinvolti
                </span>
              </div>
              <div style={{ fontSize: '0.8rem', color: 'var(--text-secondary)', marginTop: '2px' }}>
                Destinazione: <strong>{selectedLocObj?.nome_struttura || 'Sede'}</strong> · Consegna: <strong>{deliveryDate}</strong>
              </div>
            </div>
          </div>

          <div style={{ display: 'flex', alignItems: 'center', gap: '14px' }}>
            {basketStats.estimatedTotal > 0 && (
              <div style={{ textAlign: 'right', marginRight: '6px' }}>
                <div style={{ fontSize: '0.75rem', color: 'var(--text-secondary)' }}>Spesa stimata</div>
                <div style={{ fontSize: '1.25rem', fontWeight: 800, color: 'var(--status-green)' }}>
                  € {basketStats.estimatedTotal.toFixed(2)}
                </div>
              </div>
            )}

            <button
              type="button"
              className="btn btn-secondary"
              onClick={handleResetBasket}
              style={{ padding: '10px 16px', fontSize: '0.85rem' }}
            >
              Azzera
            </button>

            <button
              type="button"
              className="btn btn-primary"
              disabled={draftProcessing}
              onClick={handleProcessOrder}
              style={{
                padding: '12px 26px',
                fontSize: '0.98rem',
                fontWeight: 800,
                background: 'linear-gradient(135deg, #3b82f6, #6366f1)',
                border: 'none',
                display: 'flex',
                alignItems: 'center',
                gap: '10px',
                boxShadow: '0 0 25px rgba(59, 130, 246, 0.5)'
              }}
            >
              {draftProcessing ? (
                <>
                  <RefreshCw className="spinner" size={18} />
                  <span>Elaborazione in corso...</span>
                </>
              ) : (
                <>
                  <Sparkles size={18} />
                  <span>Elabora Buoni d'Ordine & WhatsApp</span>
                  <ArrowRight size={16} />
                </>
              )}
            </button>
          </div>
        </div>
      )}

      {/* RESOLUTION SECTION: Separate Supplier Bundles with WhatsApp Buttons */}
      {draftResult && (
        <div id="order-resolution-summary" className="glass-panel" style={{ 
          padding: '30px', 
          marginTop: '20px',
          background: 'linear-gradient(135deg, rgba(15, 23, 42, 0.98) 0%, rgba(30, 41, 59, 0.95) 100%)',
          border: '1px solid var(--status-green)',
          boxShadow: '0 0 40px rgba(16, 185, 129, 0.15)'
        }}>
          
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', flexWrap: 'wrap', gap: '16px', borderBottom: '1px solid var(--border-glass)', paddingBottom: '20px' }}>
            <div>
              <div style={{ display: 'flex', alignItems: 'center', gap: '8px', color: 'var(--status-green)', fontWeight: 700, fontSize: '0.85rem', textTransform: 'uppercase', letterSpacing: '0.05em' }}>
                <CheckCircle2 size={18} /> Ordine Elaborato con Successo
              </div>
              <h2 style={{ fontSize: '1.5rem', fontWeight: 800, margin: '6px 0 0' }}>
                Buoni d'Ordine Suddivisi per Fornitore ({draftResult.fornitori_ordini.length})
              </h2>
              <p style={{ color: 'var(--text-secondary)', fontSize: '0.85rem', margin: '4px 0 0' }}>
                Clicca sul pulsante verde <strong>"Invia su WhatsApp"</strong> di ciascun fornitore per inviare l'ordine istantaneamente al rispettivo rappresentante.
              </p>
            </div>

            <div style={{ textAlign: 'right' }}>
              <div style={{ fontSize: '0.8rem', color: 'var(--text-secondary)' }}>Totale Complessivo Ordine</div>
              <div style={{ fontSize: '1.6rem', fontWeight: 800, color: 'var(--status-green)' }}>
                € {draftResult.totale_complessivo.toFixed(2)} <span style={{ fontSize: '0.8rem', fontWeight: 400, color: 'var(--text-secondary)' }}>+ IVA</span>
              </div>
            </div>
          </div>

          {saveSuccessMsg && (
            <div style={{ marginTop: '20px', padding: '16px 20px', borderRadius: '10px', background: 'rgba(16, 185, 129, 0.15)', color: 'var(--status-green)', border: '1px solid var(--status-green)', fontWeight: 600 }}>
              {saveSuccessMsg}
            </div>
          )}

          {/* Supplier Cards List */}
          <div style={{ display: 'flex', flexDirection: 'column', gap: '24px', marginTop: '24px' }}>
            {draftResult.fornitori_ordini.map((bundle, idx) => {
              const isCopied = copiedSupplierId === bundle.fornitore_id;

              return (
                <div 
                  key={bundle.fornitore_id}
                  style={{
                    padding: '24px',
                    borderRadius: '14px',
                    background: 'rgba(0, 0, 0, 0.35)',
                    border: '1px solid var(--border-glass)',
                    display: 'flex',
                    flexDirection: 'column',
                    gap: '18px'
                  }}
                >
                  {/* Supplier Header */}
                  <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', flexWrap: 'wrap', gap: '14px' }}>
                    <div style={{ display: 'flex', alignItems: 'center', gap: '12px' }}>
                      <div style={{ 
                        width: '36px', height: '36px', borderRadius: '8px', 
                        background: 'rgba(59, 130, 246, 0.15)', color: '#60a5fa',
                        display: 'flex', alignItems: 'center', justifyContent: 'center',
                        fontWeight: 800, fontSize: '0.9rem'
                      }}>
                        #{idx + 1}
                      </div>
                      <div>
                        <h3 style={{ fontSize: '1.2rem', fontWeight: 800, margin: 0 }}>
                          {bundle.fornitore_nome}
                        </h3>
                        <div style={{ fontSize: '0.78rem', color: 'var(--text-secondary)', marginTop: '2px' }}>
                          {bundle.numero_articoli} articoli · {bundle.totale_colli} colli complessivi
                        </div>
                      </div>
                    </div>

                    <div style={{ display: 'flex', alignItems: 'center', gap: '14px' }}>
                      <div style={{ textAlign: 'right' }}>
                        <div style={{ fontSize: '0.75rem', color: 'var(--text-secondary)' }}>Importo Fornitore</div>
                        <div style={{ fontSize: '1.2rem', fontWeight: 800, color: 'white' }}>
                          € {bundle.totale_ordine.toFixed(2)}
                        </div>
                      </div>

                      {/* Phone override input */}
                      <div style={{ position: 'relative', width: '160px' }}>
                        <Phone size={13} style={{ position: 'absolute', left: '10px', top: '50%', transform: 'translateY(-50%)', color: 'var(--text-secondary)' }} />
                        <input
                          type="text"
                          placeholder="Tel. WhatsApp..."
                          value={supplierPhones[bundle.fornitore_id] || bundle.telefono_contatto || ''}
                          onChange={e => setSupplierPhones({ ...supplierPhones, [bundle.fornitore_id]: e.target.value })}
                          style={{
                            width: '100%',
                            boxSizing: 'border-box',
                            padding: '8px 8px 8px 30px',
                            background: 'rgba(255,255,255,0.05)',
                            border: '1px solid var(--border-glass)',
                            borderRadius: '8px',
                            color: 'white',
                            fontSize: '0.8rem',
                            outline: 'none'
                          }}
                        />
                      </div>

                      {/* Copy WhatsApp text button */}
                      <button
                        type="button"
                        className="btn btn-secondary"
                        onClick={() => handleCopyWhatsApp(bundle.fornitore_id, bundle.whatsapp_message)}
                        style={{ padding: '9px 14px', fontSize: '0.85rem', display: 'flex', alignItems: 'center', gap: '6px' }}
                      >
                        {isCopied ? <Check size={15} color="var(--status-green)" /> : <Copy size={15} />}
                        <span>{isCopied ? 'Copiato!' : 'Copia Testo'}</span>
                      </button>

                      {/* MAIN WHATSAPP BUTTON */}
                      <button
                        type="button"
                        onClick={() => handleOpenWhatsApp(bundle)}
                        style={{
                          padding: '10px 20px',
                          borderRadius: '10px',
                          border: 'none',
                          background: 'linear-gradient(135deg, #25D366, #128C7E)',
                          color: 'white',
                          fontWeight: 800,
                          fontSize: '0.9rem',
                          display: 'flex',
                          alignItems: 'center',
                          gap: '8px',
                          cursor: 'pointer',
                          boxShadow: '0 0 20px rgba(37, 211, 102, 0.4)',
                          transition: 'all 0.2s'
                        }}
                      >
                        <MessageSquare size={17} />
                        <span>Invia a {bundle.fornitore_nome.split(' ')[0]} su WhatsApp</span>
                        <ExternalLink size={14} />
                      </button>
                    </div>
                  </div>

                  {/* Items Table */}
                  <div style={{ overflowX: 'auto', borderRadius: '8px', border: '1px solid var(--border-glass)' }}>
                    <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: '0.85rem' }}>
                      <thead>
                        <tr style={{ background: 'rgba(255,255,255,0.03)', textAlign: 'left', color: 'var(--text-secondary)' }}>
                          <th style={{ padding: '10px 14px' }}>Articolo</th>
                          <th style={{ padding: '10px 14px', textAlign: 'center' }}>Codice Fornitore</th>
                          <th style={{ padding: '10px 14px', textAlign: 'center' }}>Quantità</th>
                          <th style={{ padding: '10px 14px', textAlign: 'right' }}>Prezzo Unitario</th>
                          <th style={{ padding: '10px 14px', textAlign: 'right' }}>Subtotale</th>
                        </tr>
                      </thead>
                      <tbody>
                        {bundle.items.map((it, iIdx) => (
                          <tr key={iIdx} style={{ borderTop: '1px solid rgba(255,255,255,0.04)' }}>
                            <td style={{ padding: '10px 14px', fontWeight: 600, color: 'white' }}>
                              {it.nome_prodotto}
                            </td>
                            <td style={{ padding: '10px 14px', textAlign: 'center', color: 'var(--text-secondary)' }}>
                              <code>{it.codice_fornitore || it.sku_interno || '—'}</code>
                            </td>
                            <td style={{ padding: '10px 14px', textAlign: 'center', fontWeight: 700, color: '#60a5fa' }}>
                              {it.quantita} {it.uom}
                            </td>
                            <td style={{ padding: '10px 14px', textAlign: 'right', color: 'var(--text-secondary)' }}>
                              € {it.prezzo_unitario.toFixed(2)}
                            </td>
                            <td style={{ padding: '10px 14px', textAlign: 'right', fontWeight: 700, color: 'white' }}>
                              € {it.subtotale.toFixed(2)}
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>

                  {/* Preview of the formatted WhatsApp text box */}
                  <details style={{ background: 'rgba(0,0,0,0.2)', padding: '10px 14px', borderRadius: '8px', fontSize: '0.8rem', color: 'var(--text-secondary)' }}>
                    <summary style={{ cursor: 'pointer', fontWeight: 600, color: 'var(--accent-blue)' }}>
                      👁️ Mostra anteprima del messaggio formattato
                    </summary>
                    <pre style={{ 
                      marginTop: '10px', 
                      padding: '12px', 
                      background: '#0d1117', 
                      borderRadius: '6px', 
                      whiteSpace: 'pre-wrap', 
                      color: '#a7f3d0', 
                      fontSize: '0.8rem',
                      fontFamily: 'monospace'
                    }}>
                      {bundle.whatsapp_message}
                    </pre>
                  </details>
                </div>
              );
            })}
          </div>

          {/* Bottom Save DB Button */}
          <div style={{ marginTop: '30px', display: 'flex', justifyContent: 'flex-end', gap: '14px', alignItems: 'center', borderTop: '1px solid var(--border-glass)', paddingTop: '20px' }}>
            <span style={{ fontSize: '0.85rem', color: 'var(--text-secondary)' }}>
              Vuoi memorizzare questi ordini per la riconciliazione automatica con le fatture elettroniche future?
            </span>
            <button
              type="button"
              className="btn btn-primary"
              disabled={savingOrders || !!saveSuccessMsg}
              onClick={handleSaveOrdersToDb}
              style={{
                padding: '12px 24px',
                fontSize: '0.95rem',
                fontWeight: 700,
                display: 'flex',
                alignItems: 'center',
                gap: '8px'
              }}
            >
              {savingOrders ? <RefreshCw className="spinner" size={16} /> : <FileText size={16} />}
              <span>{saveSuccessMsg ? '✓ Ordini Registrati' : 'Salva Ordini nel Gestionale'}</span>
            </button>
          </div>

        </div>
      )}

    </div>
  );
}
