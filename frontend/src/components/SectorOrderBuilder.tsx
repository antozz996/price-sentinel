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
  Phone,
  ChevronDown,
  ChevronUp,
  Mail,
  Send,
  X,
  Radio,
} from 'lucide-react';
import { API_BASE, getHeaders } from '../api';

interface ProductOffer {
  supplier_id: number;
  supplier_name: string;
  price: number;
  source_type?: string;
  uom?: string | null;
}

interface SupplierItem {
  id: number;
  nome_azienda: string;
  attivo_whitelist?: boolean;
}

export interface SectorPriceQuoteSupplierDetail {
  supplier_id: number;
  supplier_name: string;
  partita_iva?: string | null;
  email_contatto?: string | null;
  telefono_contatto?: string | null;
  whatsapp_message: string;
  whatsapp_url: string;
  email_subject: string;
  email_body: string;
  email_mailto_url: string;
  has_capability: boolean;
  capability_reason?: string | null;
}

export interface SectorPriceQuoteResponse {
  product_id?: number | null;
  canonical_name: string;
  settore_categoria: string;
  sottocategoria?: string | null;
  brand?: string | null;
  comparison_unit: string;
  location_nome?: string | null;
  total_fornitori_settore: number;
  fornitori_con_whatsapp: number;
  fornitori_con_email: number;
  broadcast_whatsapp_text: string;
  broadcast_email_subject: string;
  broadcast_email_body: string;
  fornitori: SectorPriceQuoteSupplierDetail[];
}

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
  offers?: Record<string, ProductOffer>;
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
  is_omaggio?: boolean;
  note_omaggio?: string | null;
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
    { id: 'CP', label: 'CP (Coppia)', short: 'CP' },
  ],
  'Materiali di consumo': [
    { id: 'PZ', label: 'PZ (Pezzo)', short: 'PZ' },
    { id: 'CT', label: 'CT (Cartone)', short: 'CT' },
    { id: 'BUSTA', label: 'BUSTA (Busta)', short: 'BUSTA' },
    { id: 'CP', label: 'CP (Coppia)', short: 'CP' },
  ],
  Food: [
    { id: 'PZ', label: 'PZ (Pezzo)', short: 'PZ' },
    { id: 'CT', label: 'CT (Cartone)', short: 'CT' },
    { id: 'KG', label: 'KG (Chilogrammo)', short: 'KG' },
    { id: 'LT', label: 'LT (Litro)', short: 'LT' },
    { id: 'CP', label: 'CP (Coppia)', short: 'CP' },
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
    { id: 'CP', label: 'CP (Coppia)', short: 'CP' },
  ];
}

export function normalizeDefaultUom(rawUom?: string | null, category?: string | null): string {
  if (category === 'Beverage') {
    if (!rawUom) return 'CT';
    const u = rawUom.trim().toUpperCase();
    if (u.includes('BOX')) return 'BOX';
    if (u === 'BT' || u.includes('BOTT')) return 'BT';
    if (u === 'CP' || u.includes('COPP') || u.includes('PAIR')) return 'CP';
    return 'CT';
  }
  if (category === 'Materiali di consumo') {
    if (!rawUom) return 'CT';
    const u = rawUom.trim().toUpperCase();
    if (u.includes('BUST')) return 'BUSTA';
    if (u === 'CP' || u.includes('COPP') || u.includes('PAIR')) return 'CP';
    if (u === 'PZ' || u === 'PIECE' || u === 'PEZZO') return 'PZ';
    return 'CT';
  }
  if (category === 'Food') {
    if (!rawUom) return 'PZ';
    const u = rawUom.trim().toUpperCase();
    if (u === 'KG' || u.includes('CHIL') || u === 'GR' || u === 'ETTO') return 'KG';
    if (u === 'LT' || u.includes('LITR')) return 'LT';
    if (u === 'CP' || u.includes('COPP') || u.includes('PAIR')) return 'CP';
    if (u === 'PZ' || u === 'PIECE' || u === 'PEZZO') return 'PZ';
    if (u === 'BT' || u.includes('BOTT')) return 'BT';
    if (u.includes('BUST')) return 'BUSTA';
    if (u.includes('BOX')) return 'BOX';
    return 'CT';
  }
  if (!rawUom) return 'CT';
  const u = rawUom.trim().toUpperCase();
  if (u === 'KG' || u.includes('CHIL')) return 'KG';
  if (u === 'LT' || u.includes('LITR')) return 'LT';
  if (u === 'BT' || u.includes('BOTT')) return 'BT';
  if (u === 'CP' || u.includes('COPP') || u.includes('PAIR')) return 'CP';
  if (u === 'PIECE' || u === 'PZ' || u === 'PEZZO') return 'PZ';
  if (u.includes('BUST')) return 'BUSTA';
  if (u.includes('BOX')) return 'BOX';
  return 'CT';
}

// ── Promozione Acqua 5+1 Helper ─────────────────────────────
const WATER_EXCLUDE_TERMS = [
  'bicchiere', 'bicchieri', 'acquadelle', 'acquavite',
  'salviett', 'monouso', 'tovagli', 'dispenser', 'cannucc',
  'piatto', 'posat'
];

const WATER_BRANDS = [
  'ferrarelle', 'sorgesana', 'electa', 'lete', 'lilia',
  'san benedetto', 'san_benedetto', 's.benedetto', 'sant\'anna',
  'santanna', 'levissima', 'uliveto', 'rocchetta', 'fiuggi',
  'san bernardo', 'lauretana', 'guizza', 'courmayeur', 'perrier',
  'panna', 'vera', 'evian', 'nepi', 'boario', 'fonte'
];

export function isWaterProduct(prod: ProductItem): boolean {
  const name = (prod.canonical_name || '').toLowerCase();
  const oname = (prod.order_name || '').toLowerCase();
  const cat = (prod.category || '').toLowerCase();
  const subcat = (prod.subcategory || '').toLowerCase();

  for (const ex of WATER_EXCLUDE_TERMS) {
    if (name.includes(ex) || oname.includes(ex)) return false;
  }

  if ((cat === 'materiali di consumo' || cat === 'food') && !name.includes('acqua') && !oname.includes('acqua')) {
    return false;
  }

  if (subcat.includes('acqua') || subcat === 'acqua minerale' || subcat === 'acque') return true;
  if (cat === 'acqua' || cat === 'acque' || cat === 'acqua minerale') return true;

  if (/\bacqua\b/i.test(name) || /\bacqua\b/i.test(oname)) return true;
  if (/\bwater\b/i.test(name) || /\bwater\b/i.test(oname)) return true;

  if (cat === 'beverage' || cat === '' || !prod.category) {
    for (const brand of WATER_BRANDS) {
      if (name.includes(brand) || oname.includes(brand)) {
        if (brand === 'panna' && (name.includes('cucina') || cat === 'food')) continue;
        return true;
      }
    }
  }

  return false;
}

export interface SectorOrderUserProfile {
  id: number;
  email: string;
  ruolo: string;
  nome_completo?: string | null;
  ruolo_dettagliato?: string | null;
  settore_abilitato?: string | null;
  location_id?: number | null;
}

interface SectorOrderBuilderProps {
  userProfile?: SectorOrderUserProfile | null;
}

export default function SectorOrderBuilder({ userProfile }: SectorOrderBuilderProps = {}) {
  const allowedSectors = useMemo(() => {
    if (!userProfile?.settore_abilitato || userProfile.settore_abilitato === 'all') {
      return ['Beverage', 'Materiali di consumo', 'Food'];
    }
    return userProfile.settore_abilitato.split(',').map(s => s.trim()).filter(Boolean);
  }, [userProfile]);

  const [locations, setLocations] = useState<LocationItem[]>([]);
  const [selectedLocation, setSelectedLocation] = useState<number | ''>(() => userProfile?.location_id || '');
  const [selectedSector, setSelectedSector] = useState<string>(() => {
    if (userProfile?.settore_abilitato && userProfile.settore_abilitato !== 'all') {
      const parts = userProfile.settore_abilitato.split(',').map(s => s.trim()).filter(Boolean);
      return parts.length === 1 ? parts[0] : (parts[0] || 'all');
    }
    return 'all';
  });
  const [deliveryDate, setDeliveryDate] = useState<string>(() => {
    const d = new Date();
    d.setDate(d.getDate() + 1);
    return d.toISOString().split('T')[0];
  });
  const [orderNotes, setOrderNotes] = useState<string>('');
  
  const [products, setProducts] = useState<ProductItem[]>([]);
  const [allSuppliers, setAllSuppliers] = useState<SupplierItem[]>([]);
  const [loading, setLoading] = useState<boolean>(true);
  const [searchTerm, setSearchTerm] = useState<string>('');
  const [selectedSubcategory, setSelectedSubcategory] = useState<string>('all');

  // Quantities mapped by product_id
  const [quantities, setQuantities] = useState<Record<number, number>>({});

  // Unit of Measure overrides per product_id
  const [selectedUoms, setSelectedUoms] = useState<Record<number, string>>({});

  // Supplier overrides per product_id: { supplier_id, supplier_name, price }
  const [selectedSuppliers, setSelectedSuppliers] = useState<Record<number, { supplier_id: number; supplier_name: string; price: number | null }>>({});

  // Freebie product selection for water 5+1 promo
  const [selectedWaterFreebieId, setSelectedWaterFreebieId] = useState<number | null>(null);

  // Helper for effective UoM
  const getEffectiveUom = (prod: ProductItem) => {
    return selectedUoms[prod.id] || normalizeDefaultUom(prod.comparison_unit, prod.category);
  };

  // Helper for effective Supplier & Price
  const getEffectiveSupplier = (prod: ProductItem) => {
    if (selectedSuppliers[prod.id]) {
      return selectedSuppliers[prod.id];
    }
    return {
      supplier_id: prod.fornitore_consigliato_id || null,
      supplier_name: prod.fornitore_consigliato_nome || 'Miglior Listino',
      price: prod.prezzo_listino ?? null
    };
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
  
  // Mobile expandable details in floating bottom bar
  const [mobileDetailsOpen, setMobileDetailsOpen] = useState<boolean>(false);
  
  // New Product Modal & RFQ Price Quote Modal States
  const [isAddProductModalOpen, setIsAddProductModalOpen] = useState<boolean>(false);
  const [isPriceQuoteModalOpen, setIsPriceQuoteModalOpen] = useState<boolean>(false);
  const [quoteProductTarget, setQuoteProductTarget] = useState<ProductItem | null>(null);
  const [quoteData, setQuoteData] = useState<SectorPriceQuoteResponse | null>(null);
  const [loadingQuote, setLoadingQuote] = useState<boolean>(false);
  const [savingProduct, setSavingProduct] = useState<boolean>(false);
  const [quoteCopied, setQuoteCopied] = useState<boolean>(false);
  const [quoteSupplierPhones, setQuoteSupplierPhones] = useState<Record<number, string>>({});
  const [quoteSupplierEmails, setQuoteSupplierEmails] = useState<Record<number, string>>({});
  const [quoteSuccessMsg, setQuoteSuccessMsg] = useState<string | null>(null);
  
  // New Product Form State
  const [newProductForm, setNewProductForm] = useState<{
    canonical_name: string;
    order_name: string;
    category: string;
    subcategory: string;
    brand: string;
    comparison_unit: string;
    sku_interno: string;
    initial_quantity: number | '';
    specifiche_extra: string;
  }>({
    canonical_name: '',
    order_name: '',
    category: 'Beverage',
    subcategory: '',
    brand: '',
    comparison_unit: 'CT',
    sku_interno: '',
    initial_quantity: '',
    specifiche_extra: ''
  });

  // Responsive screen detection (<= 1024px) for adaptive bottom bar
  const [isMobileScreen, setIsMobileScreen] = useState<boolean>(() => {
    if (typeof window === 'undefined') return false;
    return window.innerWidth <= 1024;
  });

  useEffect(() => {
    const handleResize = () => {
      setIsMobileScreen(window.innerWidth <= 1024);
    };
    window.addEventListener('resize', handleResize);
    return () => window.removeEventListener('resize', handleResize);
  }, []);

  const headers = getHeaders();

  useEffect(() => {
    loadData();
  }, []);

  async function loadData() {
    setLoading(true);
    setErrorMsg(null);
    try {
      const [locRes, prodRes, matrixRes, fornitoriRes] = await Promise.all([
        fetch(`${API_BASE}/location/`, { headers }),
        fetch(`${API_BASE}/products`, { headers }),
        fetch(`${API_BASE}/smart-price-sheet/matrix?limit=500`, { headers }).catch(() => null),
        fetch(`${API_BASE}/fornitori?attivi=true`, { headers }).catch(() => null)
      ]);

      if (locRes.ok) {
        const locData = await locRes.json();
        if (Array.isArray(locData)) {
          setLocations(locData);
          if (locData.length > 0) setSelectedLocation(locData[0].id);
        }
      }

      if (fornitoriRes && fornitoriRes.ok) {
        const fornitoriData = await fornitoriRes.json();
        if (Array.isArray(fornitoriData)) {
          setAllSuppliers(fornitoriData);
        }
      }

      let prods: ProductItem[] = [];
      if (prodRes.ok) {
        const prodData = await prodRes.json();
        if (Array.isArray(prodData)) {
          prods = prodData.filter(p => p.is_active);
        }
      }

      // If matrix is available, enrich products with recommended/forced suppliers and prices
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
              const selSupplierId = m.selected_supplier_id || m.recommended_supplier_id;
              const selOffer = selSupplierId && m.offers ? m.offers[String(selSupplierId)] : null;
              const anyOffer = selOffer || Object.values(m.offers || {})[0] as any;
              
              const finalSupId = selSupplierId || (anyOffer ? anyOffer.supplier_id : null);
              const finalSupName = anyOffer ? anyOffer.supplier_name : null;
              const finalPrice = anyOffer ? parseFloat(anyOffer.price) : null;

              const parsedOffers: Record<string, ProductOffer> = {};
              if (m.offers) {
                Object.entries(m.offers).forEach(([sIdStr, off]: [string, any]) => {
                  parsedOffers[sIdStr] = {
                    supplier_id: Number(sIdStr),
                    supplier_name: off.supplier_name,
                    price: parseFloat(off.price) || 0,
                    source_type: off.source_type,
                    uom: off.uom
                  };
                });
              }

              return {
                ...p,
                category: m.category || p.category,
                subcategory: m.subcategory || p.subcategory,
                order_name: m.order_name || p.order_name,
                prezzo_listino: finalPrice,
                fornitore_consigliato_id: finalSupId,
                fornitore_consigliato_nome: finalSupName,
                offers: parsedOffers
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
      const effSup = getEffectiveSupplier(p);
      const matchSearch = !search 
        || p.canonical_name.toLowerCase().includes(search)
        || (p.order_name && p.order_name.toLowerCase().includes(search))
        || (p.sku_interno && p.sku_interno.toLowerCase().includes(search))
        || (p.brand && p.brand.toLowerCase().includes(search))
        || (effSup.supplier_name && effSup.supplier_name.toLowerCase().includes(search))
        || (p.offers && Object.values(p.offers).some(o => o.supplier_name.toLowerCase().includes(search)));
      return matchSector && matchSubcat && matchSearch;
    });
  }, [products, selectedSector, selectedSubcategory, searchTerm, selectedSuppliers]);

  // Quantities and Basket Totals
  const basketItems = useMemo(() => {
    const items: { 
      product: ProductItem; 
      quantity: number; 
      uom: string; 
      supplier_id?: number | null; 
      supplier_name?: string | null; 
      unit_price?: number | null 
    }[] = [];

    Object.entries(quantities).forEach(([prodIdStr, qty]) => {
      if (qty > 0) {
        const prod = products.find(p => p.id === Number(prodIdStr));
        if (prod) {
          const uom = selectedUoms[prod.id] || normalizeDefaultUom(prod.comparison_unit, prod.category);
          const effSup = getEffectiveSupplier(prod);
          items.push({ 
            product: prod, 
            quantity: qty, 
            uom,
            supplier_id: effSup.supplier_id,
            supplier_name: effSup.supplier_name,
            unit_price: effSup.price
          });
        }
      }
    });
    return items;
  }, [quantities, products, selectedUoms, selectedSuppliers]);

  const basketStats = useMemo(() => {
    const totalItems = basketItems.length;
    const totalUnits = basketItems.reduce((acc, it) => acc + it.quantity, 0);
    const estimatedTotal = basketItems.reduce((acc, it) => {
      const price = it.unit_price || 0;
      return acc + (price * it.quantity);
    }, 0);

    const suppliersSet = new Set<string>();
    basketItems.forEach(it => {
      if (it.supplier_name) {
        suppliersSet.add(it.supplier_name);
      }
    });

    // Calcolo Promozione Acqua 5+1 (1 box omaggio ogni 5 box di acqua qualsiasi tipo)
    const waterItems = basketItems.filter(it => 
      isWaterProduct(it.product) && !['BT', 'PZ', 'PIECE', 'BOTTIGLIA'].includes(it.uom.toUpperCase())
    );
    const totalWaterBoxes = waterItems.reduce((acc, it) => acc + it.quantity, 0);
    const waterFreebies = Math.floor(totalWaterBoxes / 5);
    const waterMissingForNext = 5 - (totalWaterBoxes % 5);
    const waterProductsInBasket = waterItems.map(it => it.product);

    return {
      totalItems,
      totalUnits,
      estimatedTotal,
      supplierCount: suppliersSet.size || (totalItems > 0 ? 1 : 0),
      supplierNames: Array.from(suppliersSet),
      totalWaterBoxes,
      waterFreebies,
      waterMissingForNext,
      waterProductsInBasket
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
      setSelectedSuppliers({});
      setSelectedWaterFreebieId(null);
      setDraftResult(null);
      setSaveSuccessMsg(null);
      setMobileDetailsOpen(false);
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
      water_freebie_product_id: selectedWaterFreebieId || (basketStats.waterProductsInBasket.length > 0 ? basketStats.waterProductsInBasket[0].id : null),
      items: basketItems.map(it => ({
        product_id: it.product.id,
        sku_interno: it.product.sku_interno,
        canonical_name: it.product.canonical_name,
        order_name: it.product.order_name,
        quantita: it.quantity,
        comparison_unit: it.uom,
        category: it.product.category,
        preferred_supplier_id: it.supplier_id,
        prezzo_unitario: it.unit_price
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

  // Open Add New Product Modal
  const handleOpenAddProduct = () => {
    const defaultCat = selectedSector !== 'all' ? selectedSector : (allowedSectors[0] || 'Beverage');
    const uoms = getSectorUoms(defaultCat);
    setNewProductForm({
      canonical_name: '',
      order_name: '',
      category: defaultCat,
      subcategory: selectedSubcategory !== 'all' ? selectedSubcategory : '',
      brand: '',
      comparison_unit: uoms[0]?.id || 'CT',
      sku_interno: '',
      initial_quantity: 1,
      specifiche_extra: ''
    });
    setErrorMsg(null);
    setIsAddProductModalOpen(true);
  };

  // Open Multi-Supplier Price Quote Modal (RFQ)
  const handleOpenPriceQuote = async (prod: ProductItem) => {
    setQuoteProductTarget(prod);
    setIsPriceQuoteModalOpen(true);
    setLoadingQuote(true);
    setQuoteData(null);
    setErrorMsg(null);
    setQuoteSuccessMsg(null);

    try {
      const res = await fetch(`${API_BASE}/ordini/settore/richiesta-prezzo`, {
        method: 'POST',
        headers: {
          ...headers,
          'Content-Type': 'application/json'
        },
        body: JSON.stringify({
          product_id: prod.id,
          canonical_name: prod.canonical_name,
          order_name: prod.order_name,
          category: prod.category,
          subcategory: prod.subcategory,
          brand: prod.brand,
          comparison_unit: getEffectiveUom(prod),
          sku_interno: prod.sku_interno,
          location_id: selectedLocation ? Number(selectedLocation) : null,
          quantita_stimata: quantities[prod.id] || 1
        })
      });

      if (!res.ok) {
        const errData = await res.json().catch(() => ({}));
        throw new Error(errData.detail || "Errore nel calcolo dei fornitori del settore.");
      }

      const data: SectorPriceQuoteResponse = await res.json();
      setQuoteData(data);
      
      const phoneMap: Record<number, string> = {};
      const emailMap: Record<number, string> = {};
      data.fornitori.forEach(f => {
        if (f.telefono_contatto) phoneMap[f.supplier_id] = f.telefono_contatto;
        if (f.email_contatto) emailMap[f.supplier_id] = f.email_contatto;
      });
      setQuoteSupplierPhones(phoneMap);
      setQuoteSupplierEmails(emailMap);
    } catch (err: any) {
      console.error(err);
      setErrorMsg(err.message || "Errore durante la generazione della richiesta di prezzo.");
    } finally {
      setLoadingQuote(false);
    }
  };

  // Save New Product in Catalog and optionally launch multi-supplier RFQ
  const handleSaveNewProduct = async (andRequestQuote: boolean) => {
    if (!newProductForm.canonical_name.trim()) {
      alert("Inserisci il nome canonico del prodotto.");
      return;
    }

    setSavingProduct(true);
    setErrorMsg(null);

    const payload = {
      canonical_name: newProductForm.canonical_name.trim(),
      order_name: newProductForm.order_name.trim() || null,
      category: newProductForm.category || (selectedSector !== 'all' ? selectedSector : null),
      subcategory: newProductForm.subcategory.trim() || null,
      brand: newProductForm.brand.trim() || null,
      comparison_unit: newProductForm.comparison_unit || 'CT',
      sku_interno: newProductForm.sku_interno.trim() || null,
      initial_quantity: Number(newProductForm.initial_quantity) || 0
    };

    try {
      const res = await fetch(`${API_BASE}/ordini/settore/prodotti/nuovo`, {
        method: 'POST',
        headers: {
          ...headers,
          'Content-Type': 'application/json'
        },
        body: JSON.stringify(payload)
      });

      if (!res.ok) {
        const errData = await res.json().catch(() => ({}));
        throw new Error(errData.detail || "Errore durante l'importazione del prodotto.");
      }

      const created: any = await res.json();
      
      const newProductItem: ProductItem = {
        id: created.id,
        sku_interno: created.sku_interno,
        canonical_name: created.canonical_name,
        order_name: created.order_name,
        brand: created.brand,
        category: created.category,
        subcategory: created.subcategory,
        comparison_unit: created.comparison_unit,
        is_active: created.is_active,
        prezzo_listino: null,
        fornitore_consigliato_id: null,
        fornitore_consigliato_nome: null,
        offers: {}
      };

      // Add to products list at the beginning
      setProducts(prev => {
        const filtered = prev.filter(p => p.id !== newProductItem.id);
        return [newProductItem, ...filtered];
      });

      // Set initial quantity in basket if specified
      if (Number(newProductForm.initial_quantity) > 0) {
        setQuantities(prev => ({
          ...prev,
          [newProductItem.id]: Number(newProductForm.initial_quantity)
        }));
        setSelectedUoms(prev => ({
          ...prev,
          [newProductItem.id]: newProductItem.comparison_unit
        }));
      }

      setIsAddProductModalOpen(false);

      if (andRequestQuote) {
        // Automatically trigger price quote broadcast for all sector suppliers
        handleOpenPriceQuote(newProductItem);
      } else {
        setSaveSuccessMsg(`Prodotto "${created.canonical_name}" aggiunto con successo al carrello e al catalogo!`);
        setTimeout(() => setSaveSuccessMsg(null), 5000);
      }
    } catch (err: any) {
      setErrorMsg(err.message || "Impossibile salvare il prodotto.");
    } finally {
      setSavingProduct(false);
    }
  };

  // Copy Broadcast WhatsApp text
  const handleCopyBroadcastQuote = () => {
    if (!quoteData) return;
    navigator.clipboard.writeText(quoteData.broadcast_whatsapp_text);
    setQuoteCopied(true);
    setTimeout(() => setQuoteCopied(false), 3000);
  };

  // Send Broadcast Email (BCC/Ccn to all sector suppliers)
  const handleSendBroadcastEmail = () => {
    if (!quoteData) return;
    const emails = quoteData.fornitori
      .map(f => (quoteSupplierEmails[f.supplier_id] || f.email_contatto || '').trim())
      .filter(Boolean);
    
    const subjectEnc = encodeURIComponent(quoteData.broadcast_email_subject);
    const bodyEnc = encodeURIComponent(quoteData.broadcast_email_body);
    
    const mailto = emails.length > 0 
      ? `mailto:?bcc=${emails.join(',')}&subject=${subjectEnc}&body=${bodyEnc}`
      : `mailto:?subject=${subjectEnc}&body=${bodyEnc}`;
      
    window.open(mailto, '_blank');
    setQuoteSuccessMsg("Client email avviato con tutti i fornitori del settore in copia nascosta (Ccn)!");
    setTimeout(() => setQuoteSuccessMsg(null), 5000);
  };

  // Open WhatsApp for single supplier in quote modal
  const handleOpenSingleSupplierWhatsApp = (supplier: SectorPriceQuoteSupplierDetail) => {
    const rawPhone = quoteSupplierPhones[supplier.supplier_id] || supplier.telefono_contatto || '';
    const cleanPhone = rawPhone.replace(/\D/g, '');
    let url = supplier.whatsapp_url;
    if (cleanPhone.length >= 8) {
      const intlPhone = cleanPhone.startsWith('39') ? cleanPhone : `39${cleanPhone}`;
      const msgEncoded = encodeURIComponent(supplier.whatsapp_message);
      url = `https://wa.me/${intlPhone}?text=${msgEncoded}`;
    }
    window.open(url, '_blank');
  };

  // Open Email for single supplier in quote modal
  const handleOpenSingleSupplierEmail = (supplier: SectorPriceQuoteSupplierDetail) => {
    const email = (quoteSupplierEmails[supplier.supplier_id] || supplier.email_contatto || '').trim();
    if (!email) {
      alert("Nessun indirizzo email specificato per questo fornitore.");
      return;
    }
    const subjectEnc = encodeURIComponent(supplier.email_subject);
    const bodyEnc = encodeURIComponent(supplier.email_body);
    window.open(`mailto:${email}?subject=${subjectEnc}&body=${bodyEnc}`, '_blank');
  };

  const selectedLocObj = locations.find(l => l.id === Number(selectedLocation));

  return (
    <div className="sector-builder-container">
      
      {/* Top Banner / Hero */}
      {isMobileScreen ? (
        <div style={{ 
          padding: '12px 14px', 
          background: 'linear-gradient(135deg, rgba(30, 41, 59, 0.8) 0%, rgba(15, 23, 42, 0.9) 100%)',
          border: '1px solid rgba(59, 130, 246, 0.25)',
          borderRadius: '12px',
          display: 'flex',
          flexDirection: 'column',
          gap: '8px'
        }}>
          {/* Location Selector */}
          <div style={{ display: 'flex', flexDirection: 'column', gap: '3px' }}>
            <label style={{ fontSize: '0.72rem', fontWeight: 600, color: 'var(--text-secondary)', display: 'flex', alignItems: 'center', gap: '4px' }}>
              <Store size={12} color="var(--accent-blue)" /> Sede di Consegna
            </label>
            <select
              value={selectedLocation}
              onChange={e => setSelectedLocation(e.target.value ? Number(e.target.value) : '')}
              style={{
                padding: '7px 10px',
                background: 'rgba(0,0,0,0.4)',
                border: '1px solid var(--border-glass)',
                borderRadius: '8px',
                color: 'white',
                fontSize: '0.82rem',
                outline: 'none',
                width: '100%',
                boxSizing: 'border-box'
              }}
            >
              {locations.map(loc => (
                <option key={loc.id} value={loc.id} style={{ background: '#13131c' }}>
                  {loc.nome_struttura}
                </option>
              ))}
            </select>
          </div>

          {/* Delivery Date & Notes in 2-column row */}
          <div style={{ display: 'flex', gap: '8px', alignItems: 'center' }}>
            <div style={{ flex: '0 0 44%', display: 'flex', flexDirection: 'column', gap: '3px' }}>
              <label style={{ fontSize: '0.72rem', fontWeight: 600, color: 'var(--text-secondary)', display: 'flex', alignItems: 'center', gap: '4px' }}>
                <Calendar size={12} color="var(--status-green)" /> Data Consegna
              </label>
              <input
                type="date"
                value={deliveryDate}
                onChange={e => setDeliveryDate(e.target.value)}
                style={{
                  padding: '7px 8px',
                  background: 'rgba(0,0,0,0.4)',
                  border: '1px solid var(--border-glass)',
                  borderRadius: '8px',
                  color: 'white',
                  fontSize: '0.8rem',
                  outline: 'none',
                  width: '100%',
                  boxSizing: 'border-box'
                }}
              />
            </div>

            <div style={{ flex: '1 1 56%', display: 'flex', flexDirection: 'column', gap: '3px' }}>
              <label style={{ fontSize: '0.72rem', fontWeight: 600, color: 'var(--text-secondary)', display: 'flex', alignItems: 'center', gap: '4px' }}>
                <FileText size={12} color="#f59e0b" /> Note
              </label>
              <input
                type="text"
                placeholder="Es. Entro le 11..."
                value={orderNotes}
                onChange={e => setOrderNotes(e.target.value)}
                style={{
                  padding: '7px 10px',
                  background: 'rgba(0,0,0,0.4)',
                  border: '1px solid var(--border-glass)',
                  borderRadius: '8px',
                  color: 'white',
                  fontSize: '0.8rem',
                  outline: 'none',
                  width: '100%',
                  boxSizing: 'border-box'
                }}
              />
            </div>
          </div>
        </div>
      ) : (
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
          <div className="sector-hero-controls">
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
      )}

      {errorMsg && (
        <div style={{ padding: '14px 18px', borderRadius: '10px', background: 'var(--status-red-bg)', color: 'var(--status-red)', border: '1px solid rgba(239, 68, 68, 0.3)', display: 'flex', gap: '10px', alignItems: 'center' }}>
          <AlertCircle size={18} />
          <span style={{ fontSize: '0.9rem' }}>{errorMsg}</span>
        </div>
      )}

      {/* Settore / Macro-Category Pills Selector */}
      <div className="sector-pills-wrapper">
        {!isMobileScreen && (
          <span style={{ fontSize: '0.85rem', fontWeight: 700, color: 'var(--text-secondary)', marginRight: '4px', whiteSpace: 'nowrap' }}>
            Settore Attivo:
          </span>
        )}
        {MACRO_CATEGORIES
          .filter(cat => {
            if (cat.id === 'all') return allowedSectors.length > 1;
            return allowedSectors.includes(cat.id);
          })
          .map(cat => {
            const isSelected = selectedSector === cat.id;
            const count = cat.id === 'all' 
              ? products.filter(p => allowedSectors.includes(p.category || '')).length 
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
                  padding: isMobileScreen ? '6px 12px' : '8px 16px',
                  borderRadius: '30px',
                  border: isSelected ? `2px solid ${cat.color}` : '1px solid var(--border-glass)',
                  background: isSelected ? 'rgba(255, 255, 255, 0.1)' : 'rgba(255, 255, 255, 0.02)',
                  color: isSelected ? 'white' : 'var(--text-secondary)',
                  fontWeight: isSelected ? 700 : 500,
                  fontSize: isMobileScreen ? '0.8rem' : '0.85rem',
                  cursor: 'pointer',
                  display: 'flex',
                  alignItems: 'center',
                  gap: '6px',
                  boxShadow: isSelected ? `0 0 15px ${cat.color}33` : 'none',
                  transition: 'all 0.2s',
                  flexShrink: 0,
                  whiteSpace: 'nowrap'
                }}
              >
                <span>{cat.icon}</span>
                <span>{cat.id === 'all' && allowedSectors.length < 3 ? 'I miei settori' : cat.label}</span>
                <span style={{ 
                  fontSize: '0.72rem', 
                  padding: '2px 6px', 
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
      <div className="glass-panel" style={{ 
        padding: isMobileScreen ? '10px 12px' : '16px 20px', 
        display: 'flex', 
        gap: '8px', 
        flexDirection: isMobileScreen ? 'column' : 'row',
        alignItems: isMobileScreen ? 'stretch' : 'center' 
      }}>
        {/* Search Input */}
        <div style={{ position: 'relative', flex: '1 1 280px', width: '100%' }}>
          <Search size={15} style={{ position: 'absolute', left: '12px', top: '50%', transform: 'translateY(-50%)', color: 'var(--text-secondary)' }} />
          <input
            type="text"
            placeholder="Cerca per prodotto, SKU, brand o fornitore..."
            value={searchTerm}
            onChange={e => setSearchTerm(e.target.value)}
            style={{
              width: '100%',
              boxSizing: 'border-box',
              padding: '8px 12px 8px 36px',
              background: 'rgba(255,255,255,0.04)',
              border: '1px solid var(--border-glass)',
              borderRadius: '8px',
              color: 'white',
              fontSize: '0.85rem',
              outline: 'none'
            }}
          />
        </div>

        {/* Subcategory dropdown and product count & Add Product Action */}
        <div style={{ 
          display: 'flex', 
          alignItems: 'center', 
          justifyContent: 'space-between', 
          gap: '10px',
          flexWrap: 'wrap',
          width: isMobileScreen ? '100%' : 'auto'
        }}>
          {subcategories.length > 0 && (
            <div style={{ display: 'flex', alignItems: 'center', gap: '6px', flex: isMobileScreen ? 1 : 'initial' }}>
              <Filter size={13} color="var(--text-secondary)" />
              <select
                value={selectedSubcategory}
                onChange={e => setSelectedSubcategory(e.target.value)}
                style={{
                  padding: '6px 10px',
                  background: 'rgba(255,255,255,0.04)',
                  border: '1px solid var(--border-glass)',
                  borderRadius: '8px',
                  color: 'white',
                  fontSize: '0.8rem',
                  outline: 'none',
                  cursor: 'pointer',
                  width: isMobileScreen ? '100%' : 'auto',
                  textOverflow: 'ellipsis'
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

          {/* Button to Import / Add New Product and Request Quotes */}
          <button
            type="button"
            onClick={handleOpenAddProduct}
            style={{
              padding: isMobileScreen ? '7px 12px' : '8px 14px',
              borderRadius: '8px',
              border: '1px solid rgba(59, 130, 246, 0.45)',
              background: 'linear-gradient(135deg, rgba(59, 130, 246, 0.25) 0%, rgba(139, 92, 246, 0.35) 100%)',
              color: 'white',
              fontSize: '0.82rem',
              fontWeight: 700,
              cursor: 'pointer',
              display: 'flex',
              alignItems: 'center',
              gap: '6px',
              boxShadow: '0 0 15px rgba(59, 130, 246, 0.2)',
              whiteSpace: 'nowrap',
              transition: 'all 0.2s'
            }}
            title="Aggiungi nuovo articolo al catalogo e invia richiesta di prezzo ai fornitori del settore"
          >
            <Plus size={15} color="#93c5fd" />
            <span>Nuovo Prodotto / Preventivo</span>
            <Sparkles size={13} color="#f59e0b" />
          </button>

          <div style={{ 
            color: 'var(--text-secondary)', 
            fontSize: '0.8rem', 
            marginLeft: (isMobileScreen && subcategories.length === 0) ? '0' : 'auto',
            whiteSpace: 'nowrap'
          }}>
            Visualizzati: <strong>{filteredProducts.length}</strong>
          </div>
        </div>
      </div>

      {/* Promozione Acqua 5+1 Banner Interattivo */}
      {basketStats.totalWaterBoxes > 0 && (
        <div className="glass-panel" style={{
          padding: '16px 20px',
          background: basketStats.waterFreebies > 0 
            ? 'linear-gradient(135deg, rgba(16, 185, 129, 0.16) 0%, rgba(5, 150, 105, 0.22) 100%)'
            : 'linear-gradient(135deg, rgba(59, 130, 246, 0.12) 0%, rgba(37, 99, 235, 0.18) 100%)',
          border: basketStats.waterFreebies > 0 ? '1px solid #10b981' : '1px solid rgba(59, 130, 246, 0.4)',
          display: 'flex',
          justifyContent: 'space-between',
          alignItems: 'center',
          flexWrap: 'wrap',
          gap: '14px',
          boxShadow: basketStats.waterFreebies > 0 ? '0 0 25px rgba(16, 185, 129, 0.2)' : 'none'
        }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: '14px' }}>
            <div style={{
              width: '42px', height: '42px', borderRadius: '12px',
              background: basketStats.waterFreebies > 0 ? 'linear-gradient(135deg, #10b981, #059669)' : 'linear-gradient(135deg, #3b82f6, #2563eb)',
              color: 'white', display: 'flex', alignItems: 'center', justifyContent: 'center',
              fontSize: '1.25rem', boxShadow: '0 0 15px rgba(0,0,0,0.3)'
            }}>
              🎁
            </div>
            <div>
              <div style={{ fontWeight: 800, fontSize: '1rem', color: 'white', display: 'flex', alignItems: 'center', gap: '8px', flexWrap: 'wrap' }}>
                <span>Promozione Acqua 5+1 (1 Box Omaggio ogni 5 Box)</span>
                <span style={{
                  padding: '2px 8px', borderRadius: '6px',
                  background: basketStats.waterFreebies > 0 ? 'rgba(16, 185, 129, 0.3)' : 'rgba(59, 130, 246, 0.3)',
                  color: basketStats.waterFreebies > 0 ? '#a7f3d0' : '#93c5fd',
                  fontSize: '0.75rem', fontWeight: 700
                }}>
                  {basketStats.totalWaterBoxes} box ordinati
                </span>
              </div>
              <div style={{ fontSize: '0.85rem', color: 'var(--text-secondary)', marginTop: '3px' }}>
                {basketStats.waterFreebies > 0 ? (
                  <>
                    🎉 Complimenti! Hai maturato <strong style={{ color: '#34d399' }}>{basketStats.waterFreebies} {basketStats.waterFreebies === 1 ? 'box' : 'box'} in OMAGGIO</strong> (€ 0,00)!
                    {basketStats.totalWaterBoxes % 5 !== 0 && (
                      <span style={{ marginLeft: '4px', opacity: 0.9 }}>
                        (Aggiungi ancora {basketStats.waterMissingForNext} box per sbloccare il prossimo omaggio)
                      </span>
                    )}
                  </>
                ) : (
                  <>
                    Mancano solo <strong style={{ color: '#60a5fa' }}>{basketStats.waterMissingForNext} {basketStats.waterMissingForNext === 1 ? 'box' : 'box'}</strong> di acqua per ricevere <strong>1 BOX IN OMAGGIO</strong>!
                  </>
                )}
              </div>
            </div>
          </div>

          {basketStats.waterFreebies > 0 && basketStats.waterProductsInBasket.length > 1 && (
            <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
              <span style={{ fontSize: '0.8rem', color: 'var(--text-secondary)' }}>Referenza omaggio:</span>
              <select
                value={selectedWaterFreebieId || basketStats.waterProductsInBasket[0]?.id}
                onChange={e => setSelectedWaterFreebieId(Number(e.target.value))}
                style={{
                  padding: '6px 12px',
                  background: 'rgba(0,0,0,0.4)',
                  border: '1px solid #10b981',
                  borderRadius: '8px',
                  color: 'white',
                  fontSize: '0.82rem',
                  fontWeight: 700,
                  outline: 'none',
                  cursor: 'pointer'
                }}
              >
                {basketStats.waterProductsInBasket.map(wp => (
                  <option key={wp.id} value={wp.id} style={{ background: '#13131c' }}>
                    {wp.order_name || wp.canonical_name} (Omaggio)
                  </option>
                ))}
              </select>
            </div>
          )}
        </div>
      )}

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
        <div className="sector-order-grid">
          {filteredProducts.map(prod => {
            const currentQty = quantities[prod.id] || 0;
            const hasQty = currentQty > 0;
            const effSup = getEffectiveSupplier(prod);
            const unitPrice = effSup.price;
            const lineTotal = unitPrice ? unitPrice * currentQty : 0;
            const isSelectedSup = !!selectedSuppliers[prod.id];

            const productOffers = prod.offers ? Object.values(prod.offers) : [];
            const offerSupplierIds = new Set(productOffers.map(o => o.supplier_id));

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
                    {isWaterProduct(prod) && (
                      <>
                        <span style={{ color: 'rgba(255,255,255,0.2)' }}>•</span>
                        <span style={{ 
                          color: '#34d399', 
                          background: 'rgba(16, 185, 129, 0.15)', 
                          padding: '1px 6px', 
                          borderRadius: '4px', 
                          fontWeight: 700,
                          fontSize: '0.7rem' 
                        }}>
                          🎁 Promo 5+1
                        </span>
                      </>
                    )}
                  </div>

                  {/* Recommended / Selected Supplier & Price info */}
                  <div style={{ 
                    marginTop: '10px', 
                    padding: '6px 10px', 
                    borderRadius: '8px', 
                    background: 'rgba(0, 0, 0, 0.3)', 
                    border: isSelectedSup ? '1px solid rgba(59, 130, 246, 0.4)' : '1px solid rgba(255, 255, 255, 0.08)',
                    display: 'flex', 
                    justifyContent: 'space-between', 
                    alignItems: 'center', 
                    gap: '8px',
                    fontSize: '0.8rem'
                  }}>
                    <div style={{ display: 'flex', alignItems: 'center', gap: '5px', flex: 1, minWidth: 0 }}>
                      <Truck size={13} color={isSelectedSup ? 'var(--accent-blue)' : 'var(--text-secondary)'} style={{ flexShrink: 0 }} />
                      <select
                        value={effSup.supplier_id || ''}
                        onChange={(e) => {
                          const val = e.target.value;
                          if (!val) {
                            setSelectedSuppliers(prev => {
                              const next = { ...prev };
                              delete next[prod.id];
                              return next;
                            });
                            return;
                          }
                          const sId = Number(val);
                          const matchingOffer = prod.offers ? prod.offers[String(sId)] : null;
                          const matchingSup = allSuppliers.find(s => s.id === sId);
                          setSelectedSuppliers(prev => ({
                            ...prev,
                            [prod.id]: {
                              supplier_id: sId,
                              supplier_name: matchingOffer?.supplier_name || matchingSup?.nome_azienda || `Fornitore #${sId}`,
                              price: matchingOffer ? matchingOffer.price : (prod.prezzo_listino ?? null)
                            }
                          }));
                        }}
                        style={{
                          background: isSelectedSup ? 'rgba(59, 130, 246, 0.2)' : 'rgba(255, 255, 255, 0.05)',
                          border: isSelectedSup ? '1px solid rgba(59, 130, 246, 0.5)' : '1px solid rgba(255, 255, 255, 0.12)',
                          borderRadius: '6px',
                          color: isSelectedSup ? '#93c5fd' : 'white',
                          fontSize: '0.78rem',
                          fontWeight: 700,
                          padding: '3px 6px',
                          outline: 'none',
                          cursor: 'pointer',
                          flex: 1,
                          minWidth: 0,
                          textOverflow: 'ellipsis',
                          overflow: 'hidden',
                          whiteSpace: 'nowrap'
                        }}
                        title="Cambia fornitore per questo articolo"
                      >
                        {/* Option when no supplier id or default */}
                        {(!effSup.supplier_id || (!productOffers.some(o => o.supplier_id === effSup.supplier_id) && !allSuppliers.some(s => s.id === effSup.supplier_id))) && (
                          <option value="" style={{ background: '#13131c', color: 'white' }}>
                            {effSup.supplier_name || 'Seleziona fornitore'}
                          </option>
                        )}

                        {/* Offers with known prices first */}
                        {productOffers.length > 0 && (
                          <optgroup label="Offerte e listini" style={{ background: '#13131c', color: '#93c5fd' }}>
                            {productOffers.map(off => (
                              <option key={off.supplier_id} value={off.supplier_id} style={{ background: '#13131c', color: 'white' }}>
                                {off.supplier_name} {off.price > 0 ? `(€ ${off.price.toFixed(2)})` : ''}
                              </option>
                            ))}
                          </optgroup>
                        )}

                        {/* Other active suppliers */}
                        {allSuppliers.filter(s => !offerSupplierIds.has(s.id)).length > 0 && (
                          <optgroup label="Tutti i fornitori" style={{ background: '#13131c', color: 'var(--text-secondary)' }}>
                            {allSuppliers.filter(s => !offerSupplierIds.has(s.id)).map(sup => (
                              <option key={sup.id} value={sup.id} style={{ background: '#13131c', color: 'white' }}>
                                {sup.nome_azienda}
                              </option>
                            ))}
                          </optgroup>
                        )}
                      </select>
                    </div>

                    {unitPrice !== null && unitPrice !== undefined ? (
                      <div style={{ textAlign: 'right', flexShrink: 0 }}>
                        <div style={{ fontWeight: 700, color: 'var(--status-green)', fontSize: '0.82rem' }}>
                          € {unitPrice.toFixed(2)} <span style={{ fontSize: '0.7rem', color: 'var(--text-secondary)', fontWeight: 400 }}>/{getEffectiveUom(prod)}</span>
                        </div>
                        {hasQty && (
                          <div style={{ fontSize: '0.72rem', color: '#60a5fa', fontWeight: 700 }}>
                            Tot: € {lineTotal.toFixed(2)}
                          </div>
                        )}
                      </div>
                    ) : (
                      <div style={{ color: 'var(--text-secondary)', fontSize: '0.75rem', flexShrink: 0 }}>A listino</div>
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

                  {/* Single-Click RFQ Trigger for this product */}
                  <div style={{ marginTop: '8px', display: 'flex', justifyContent: 'flex-end' }}>
                    <button
                      type="button"
                      onClick={() => handleOpenPriceQuote(prod)}
                      style={{
                        padding: '4px 10px',
                        borderRadius: '6px',
                        border: '1px solid rgba(139, 92, 246, 0.35)',
                        background: 'rgba(139, 92, 246, 0.12)',
                        color: '#c4b5fd',
                        fontSize: '0.72rem',
                        fontWeight: 600,
                        cursor: 'pointer',
                        display: 'flex',
                        alignItems: 'center',
                        gap: '5px',
                        transition: 'all 0.2s',
                        width: '100%',
                        justifyContent: 'center'
                      }}
                      title="Invia richiesta di quotazione prezzo a tutti i fornitori abilitati nel settore"
                    >
                      <Send size={11} color="#a78bfa" />
                      <span>Richiedi Prezzo Fornitori Settore</span>
                    </button>
                  </div>
                </div>
              </div>
            );
          })}
        </div>
      )}

      {/* Floating Bottom Action Bar for Cart */}
      {basketItems.length > 0 && (
        <div 
          className="order-floating-bar"
          style={isMobileScreen ? {
            position: 'fixed',
            bottom: 0,
            left: 0,
            right: 0,
            width: '100%',
            maxWidth: '100vw',
            margin: 0,
            transform: 'none',
            borderRadius: '16px 16px 0 0',
            border: 'none',
            borderTop: '1px solid rgba(59, 130, 246, 0.35)',
            background: 'rgba(11, 15, 25, 0.98)',
            backdropFilter: 'blur(20px)',
            WebkitBackdropFilter: 'blur(20px)',
            padding: '8px 12px calc(8px + env(safe-area-inset-bottom, 12px)) 12px',
            boxShadow: '0 -10px 35px rgba(0, 0, 0, 0.9), 0 0 20px rgba(59, 130, 246, 0.2)',
            zIndex: 9999,
            boxSizing: 'border-box'
          } : undefined}
        >
          {/* MOBILE EXPANDABLE DETAILS DRAWER */}
          {mobileDetailsOpen && (
            <div className="order-floating-bar-mobile-drawer">
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                <div style={{ fontSize: '0.85rem', fontWeight: 800, color: 'white', display: 'flex', alignItems: 'center', gap: '6px' }}>
                  <Store size={14} color="var(--accent-blue)" />
                  <span>{selectedLocObj?.nome_struttura || 'Sede di Consegna'}</span>
                </div>
                <button
                  type="button"
                  onClick={() => setMobileDetailsOpen(false)}
                  style={{
                    background: 'rgba(255,255,255,0.08)',
                    border: 'none',
                    borderRadius: '6px',
                    color: 'var(--text-secondary)',
                    padding: '4px 8px',
                    fontSize: '0.75rem',
                    cursor: 'pointer',
                    display: 'flex',
                    alignItems: 'center',
                    gap: '4px'
                  }}
                >
                  <span>Chiudi</span>
                  <ChevronDown size={14} />
                </button>
              </div>

              <div style={{ display: 'flex', flexWrap: 'wrap', gap: '8px', fontSize: '0.78rem', color: 'var(--text-secondary)' }}>
                <div style={{ display: 'flex', alignItems: 'center', gap: '4px', background: 'rgba(255,255,255,0.04)', padding: '3px 8px', borderRadius: '6px' }}>
                  <Calendar size={12} color="var(--status-green)" /> Consegna: <strong style={{ color: 'white' }}>{deliveryDate}</strong>
                </div>
                <div style={{ display: 'flex', alignItems: 'center', gap: '4px', background: 'rgba(59,130,246,0.15)', color: '#93c5fd', padding: '3px 8px', borderRadius: '6px' }}>
                  <Truck size={12} /> {basketStats.supplierCount} {basketStats.supplierCount === 1 ? 'fornitore' : 'fornitori'}
                </div>
              </div>

              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', paddingTop: '4px' }}>
                <button
                  type="button"
                  onClick={handleResetBasket}
                  style={{
                    background: 'rgba(239, 68, 68, 0.12)',
                    border: '1px solid rgba(239, 68, 68, 0.3)',
                    color: 'var(--status-red)',
                    padding: '6px 12px',
                    borderRadius: '8px',
                    fontSize: '0.78rem',
                    fontWeight: 700,
                    display: 'flex',
                    alignItems: 'center',
                    gap: '5px',
                    cursor: 'pointer'
                  }}
                >
                  <Trash2 size={13} /> Svuota Carrello
                </button>

                {basketStats.estimatedTotal > 0 && (
                  <div style={{ fontSize: '0.85rem', fontWeight: 800, color: 'var(--status-green)' }}>
                    Spesa: € {basketStats.estimatedTotal.toFixed(2)}
                  </div>
                )}
              </div>
            </div>
          )}

          {isMobileScreen ? (
            /* MOBILE COMPACT BAR ROW (<= 1024px) */
            <div className="order-floating-bar-mobile-only" style={{ width: '100%', alignItems: 'center', justifyContent: 'space-between', gap: '8px' }}>
              <div 
                onClick={() => setMobileDetailsOpen(prev => !prev)}
                style={{ 
                  display: 'flex', 
                  alignItems: 'center', 
                  gap: '8px', 
                  cursor: 'pointer', 
                  flex: 1, 
                  minWidth: 0,
                  padding: '4px 6px',
                  borderRadius: '8px',
                  background: mobileDetailsOpen ? 'rgba(59, 130, 246, 0.15)' : 'transparent',
                  transition: 'background 0.2s'
                }}
              >
                <div style={{
                  width: '34px', height: '34px', borderRadius: '8px',
                  background: 'linear-gradient(135deg, #10b981, #059669)',
                  display: 'flex', alignItems: 'center', justifyContent: 'center',
                  boxShadow: '0 0 10px rgba(16, 185, 129, 0.4)',
                  flexShrink: 0
                }}>
                  <ShoppingCart size={16} color="white" />
                </div>
                <div style={{ minWidth: 0, overflow: 'hidden', flex: 1 }}>
                  <div style={{ fontWeight: 800, fontSize: '0.85rem', color: 'white', whiteSpace: 'nowrap', textOverflow: 'ellipsis', overflow: 'hidden', display: 'flex', alignItems: 'center', gap: '5px' }}>
                    <span>{basketStats.totalItems} prod.</span>
                    <span style={{ color: '#93c5fd', fontWeight: 600, fontSize: '0.78rem' }}>({basketStats.totalUnits} c.)</span>
                    {basketStats.waterFreebies > 0 && (
                      <span style={{ 
                        background: 'rgba(16, 185, 129, 0.25)', 
                        color: '#34d399', 
                        padding: '1px 4px', 
                        borderRadius: '4px', 
                        fontSize: '0.7rem', 
                        fontWeight: 800 
                      }}>
                        +{basketStats.waterFreebies}
                      </span>
                    )}
                  </div>
                  <div style={{ fontSize: '0.78rem', display: 'flex', alignItems: 'center', gap: '5px', marginTop: '1px' }}>
                    <span style={{ color: 'var(--status-green)', fontWeight: 800 }}>
                      € {basketStats.estimatedTotal.toFixed(2)}
                    </span>
                    <span style={{ color: 'var(--text-secondary)', fontSize: '0.7rem' }}>
                      · {basketStats.supplierCount} {basketStats.supplierCount === 1 ? 'forn.' : 'forn.'}
                    </span>
                  </div>
                </div>

                <div style={{
                  color: mobileDetailsOpen ? '#93c5fd' : 'var(--text-secondary)',
                  display: 'flex',
                  alignItems: 'center',
                  padding: '2px 4px',
                  flexShrink: 0
                }}>
                  {mobileDetailsOpen ? <ChevronDown size={14} /> : <ChevronUp size={14} />}
                </div>
              </div>

              <button
                type="button"
                className="btn btn-primary"
                disabled={draftProcessing}
                onClick={handleProcessOrder}
                style={{
                  padding: '9px 14px',
                  fontSize: '0.85rem',
                  fontWeight: 800,
                  background: 'linear-gradient(135deg, #3b82f6, #6366f1)',
                  border: 'none',
                  borderRadius: '10px',
                  display: 'flex',
                  alignItems: 'center',
                  gap: '5px',
                  flexShrink: 0,
                  boxShadow: '0 0 15px rgba(59, 130, 246, 0.4)'
                }}
              >
                {draftProcessing ? (
                  <>
                    <RefreshCw className="spinner" size={14} />
                    <span>Invio...</span>
                  </>
                ) : (
                  <>
                    <Sparkles size={14} />
                    <span>Elabora</span>
                    <ArrowRight size={13} />
                  </>
                )}
              </button>
            </div>
          ) : (
            /* DESKTOP ROW (> 1024px) */
            <div className="order-floating-bar-desktop-only" style={{ width: '100%', justifyContent: 'space-between', alignItems: 'center', gap: '16px' }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: '14px', minWidth: 0, flex: 1 }}>
                <div style={{
                  width: '42px', height: '42px', borderRadius: '12px',
                  background: 'linear-gradient(135deg, #10b981, #059669)',
                  display: 'flex', alignItems: 'center', justifyContent: 'center',
                  boxShadow: '0 0 15px rgba(16, 185, 129, 0.4)',
                  flexShrink: 0
                }}>
                  <ShoppingCart size={20} color="white" />
                </div>

                <div style={{ minWidth: 0 }}>
                  <div style={{ display: 'flex', alignItems: 'center', gap: '8px', flexWrap: 'wrap' }}>
                    <span style={{ fontWeight: 800, fontSize: '1rem', color: 'white' }}>
                      Fabbisogno: {basketStats.totalItems} {basketStats.totalItems === 1 ? 'prodotto' : 'prodotti'} ({basketStats.totalUnits} colli)
                    </span>
                    <span style={{ 
                      padding: '2px 8px', borderRadius: '6px', 
                      background: 'rgba(59, 130, 246, 0.2)', color: '#60a5fa', 
                      fontSize: '0.75rem', fontWeight: 700 
                    }}>
                      {basketStats.supplierCount} {basketStats.supplierCount === 1 ? 'fornitore' : 'fornitori'} coinvolti
                    </span>
                    {basketStats.waterFreebies > 0 && (
                      <span style={{ 
                        padding: '2px 8px', borderRadius: '6px', 
                        background: 'rgba(16, 185, 129, 0.25)', color: '#34d399', 
                        fontSize: '0.75rem', fontWeight: 800,
                        border: '1px solid rgba(16, 185, 129, 0.4)'
                      }}>
                        🎁 +{basketStats.waterFreebies} {basketStats.waterFreebies === 1 ? 'box omaggio' : 'box omaggio'}
                      </span>
                    )}
                  </div>
                  <div style={{ fontSize: '0.78rem', color: 'var(--text-secondary)', marginTop: '2px' }}>
                    Destinazione: <strong>{selectedLocObj?.nome_struttura || 'Sede'}</strong> · Consegna: <strong>{deliveryDate}</strong>
                  </div>
                </div>
              </div>

              <div style={{ display: 'flex', alignItems: 'center', gap: '12px', flexShrink: 0 }}>
                {basketStats.estimatedTotal > 0 && (
                  <div style={{ textAlign: 'right', marginRight: '4px' }}>
                    <div style={{ fontSize: '0.72rem', color: 'var(--text-secondary)' }}>Spesa stimata</div>
                    <div style={{ fontSize: '1.2rem', fontWeight: 800, color: 'var(--status-green)' }}>
                      € {basketStats.estimatedTotal.toFixed(2)}
                    </div>
                  </div>
                )}

                <button
                  type="button"
                  className="btn btn-secondary"
                  onClick={handleResetBasket}
                  style={{ padding: '9px 14px', fontSize: '0.82rem' }}
                >
                  Azzera
                </button>

                <button
                  type="button"
                  className="btn btn-primary"
                  disabled={draftProcessing}
                  onClick={handleProcessOrder}
                  style={{
                    padding: '11px 22px',
                    fontSize: '0.92rem',
                    fontWeight: 800,
                    background: 'linear-gradient(135deg, #3b82f6, #6366f1)',
                    border: 'none',
                    display: 'flex',
                    alignItems: 'center',
                    gap: '8px',
                    boxShadow: '0 0 20px rgba(59, 130, 246, 0.4)'
                  }}
                >
                  {draftProcessing ? (
                    <>
                      <RefreshCw className="spinner" size={16} />
                      <span>Elaborazione...</span>
                    </>
                  ) : (
                    <>
                      <Sparkles size={16} />
                      <span>Elabora Ordine & WhatsApp</span>
                      <ArrowRight size={15} />
                    </>
                  )}
                </button>
              </div>
            </div>
          )}
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
                        {bundle.items.map((it, iIdx) => {
                          const isFreebie = it.is_omaggio || it.prezzo_unitario === 0;
                          return (
                            <tr key={iIdx} style={{ borderTop: '1px solid rgba(255,255,255,0.04)', background: isFreebie ? 'rgba(16, 185, 129, 0.08)' : 'transparent' }}>
                              <td style={{ padding: '10px 14px', fontWeight: 600, color: 'white' }}>
                                <div style={{ display: 'flex', alignItems: 'center', gap: '8px', flexWrap: 'wrap' }}>
                                  <span>{it.nome_prodotto}</span>
                                  {isFreebie && (
                                    <span style={{
                                      padding: '2px 8px', borderRadius: '6px',
                                      background: 'rgba(16, 185, 129, 0.25)', color: '#34d399',
                                      fontSize: '0.72rem', fontWeight: 800, border: '1px solid rgba(16, 185, 129, 0.4)'
                                    }}>
                                      🎁 OMAGGIO (Promo 5+1)
                                    </span>
                                  )}
                                </div>
                              </td>
                              <td style={{ padding: '10px 14px', textAlign: 'center', color: 'var(--text-secondary)' }}>
                                <code>{it.codice_fornitore || it.sku_interno || '—'}</code>
                              </td>
                              <td style={{ padding: '10px 14px', textAlign: 'center', fontWeight: 700, color: isFreebie ? '#34d399' : '#60a5fa' }}>
                                {it.quantita} {it.uom}
                              </td>
                              <td style={{ padding: '10px 14px', textAlign: 'right', color: isFreebie ? '#34d399' : 'var(--text-secondary)' }}>
                                {isFreebie ? <strong style={{ color: '#34d399' }}>GRATIS (€ 0,00)</strong> : `€ ${it.prezzo_unitario.toFixed(2)}`}
                              </td>
                              <td style={{ padding: '10px 14px', textAlign: 'right', fontWeight: 700, color: isFreebie ? '#34d399' : 'white' }}>
                                {isFreebie ? <strong style={{ color: '#34d399' }}>€ 0,00</strong> : `€ ${it.subtotale.toFixed(2)}`}
                              </td>
                            </tr>
                          );
                        })}
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

      {/* ─────────────────────────────────────────────────────────────
          MODAL 1: IMPORTA / AGGIUNGI NUOVO PRODOTTO NEL SELETTORE
      ───────────────────────────────────────────────────────────── */}
      {isAddProductModalOpen && (
        <div style={{
          position: 'fixed',
          top: 0, left: 0, right: 0, bottom: 0,
          backgroundColor: 'rgba(0, 0, 0, 0.75)',
          backdropFilter: 'blur(6px)',
          zIndex: 9999,
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
          padding: '16px'
        }}>
          <div style={{
            background: 'linear-gradient(145deg, #182234 0%, #0d1424 100%)',
            border: '1px solid rgba(59, 130, 246, 0.35)',
            borderRadius: '16px',
            width: '100%',
            maxWidth: '650px',
            maxHeight: '92vh',
            overflowY: 'auto',
            boxShadow: '0 25px 50px -12px rgba(0, 0, 0, 0.7), 0 0 35px rgba(59, 130, 246, 0.25)',
            padding: '24px',
            color: 'white',
            display: 'flex',
            flexDirection: 'column',
            gap: '20px'
          }}>
            {/* Modal Header */}
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start' }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: '12px' }}>
                <div style={{
                  width: '42px', height: '42px', borderRadius: '12px',
                  background: 'linear-gradient(135deg, #3b82f6, #8b5cf6)',
                  display: 'flex', alignItems: 'center', justifyContent: 'center',
                  boxShadow: '0 0 15px rgba(59, 130, 246, 0.4)'
                }}>
                  <Plus size={22} color="white" />
                </div>
                <div>
                  <h3 style={{ margin: 0, fontSize: '1.25rem', fontWeight: 800 }}>
                    Nuovo Prodotto nel Selettore
                  </h3>
                  <p style={{ margin: '3px 0 0', fontSize: '0.8rem', color: 'var(--text-secondary)' }}>
                    Aggiungi l'articolo al catalogo e invia la richiesta di prezzo ai fornitori del settore.
                  </p>
                </div>
              </div>
              <button
                type="button"
                onClick={() => setIsAddProductModalOpen(false)}
                style={{
                  background: 'rgba(255,255,255,0.06)',
                  border: 'none',
                  borderRadius: '8px',
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
              {/* Product Canonical Name */}
              <div style={{ display: 'flex', flexDirection: 'column', gap: '5px' }}>
                <label style={{ fontSize: '0.82rem', fontWeight: 700, color: '#93c5fd' }}>
                  Nome Prodotto Completo / Canonico *
                </label>
                <input
                  type="text"
                  placeholder="Es. Gin Mare 70cl, Bicchieri Monouso 200cc..."
                  value={newProductForm.canonical_name}
                  onChange={e => setNewProductForm({ ...newProductForm, canonical_name: e.target.value })}
                  style={{
                    padding: '10px 14px',
                    background: 'rgba(0,0,0,0.4)',
                    border: '1px solid var(--border-glass)',
                    borderRadius: '8px',
                    color: 'white',
                    fontSize: '0.9rem',
                    outline: 'none'
                  }}
                  autoFocus
                />
              </div>

              {/* Order Rapido Name & SKU */}
              <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '12px' }}>
                <div style={{ display: 'flex', flexDirection: 'column', gap: '5px' }}>
                  <label style={{ fontSize: '0.8rem', fontWeight: 600, color: 'var(--text-secondary)' }}>
                    Nome Rapido d'Ordine
                  </label>
                  <input
                    type="text"
                    placeholder="Es. GIN MARE, BICCHIERI 200..."
                    value={newProductForm.order_name}
                    onChange={e => setNewProductForm({ ...newProductForm, order_name: e.target.value })}
                    style={{
                      padding: '9px 12px',
                      background: 'rgba(0,0,0,0.4)',
                      border: '1px solid var(--border-glass)',
                      borderRadius: '8px',
                      color: 'white',
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
                    placeholder="Es. San Benedetto, San Bernardo..."
                    value={newProductForm.brand}
                    onChange={e => setNewProductForm({ ...newProductForm, brand: e.target.value })}
                    style={{
                      padding: '9px 12px',
                      background: 'rgba(0,0,0,0.4)',
                      border: '1px solid var(--border-glass)',
                      borderRadius: '8px',
                      color: 'white',
                      fontSize: '0.85rem',
                      outline: 'none'
                    }}
                  />
                </div>
              </div>

              {/* Category / Settore Pills Selector */}
              <div style={{ display: 'flex', flexDirection: 'column', gap: '6px' }}>
                <label style={{ fontSize: '0.8rem', fontWeight: 600, color: '#93c5fd' }}>
                  Settore / Categoria di Appartenenza *
                </label>
                <div style={{ display: 'flex', gap: '8px', flexWrap: 'wrap' }}>
                  {MACRO_CATEGORIES.filter(c => c.id !== 'all').map(cat => {
                    const isSel = newProductForm.category === cat.id;
                    return (
                      <button
                        key={cat.id}
                        type="button"
                        onClick={() => {
                          const uoms = getSectorUoms(cat.id);
                          setNewProductForm({ 
                            ...newProductForm, 
                            category: cat.id,
                            comparison_unit: uoms[0]?.id || 'CT'
                          });
                        }}
                        style={{
                          padding: '6px 14px',
                          borderRadius: '20px',
                          border: isSel ? `2px solid ${cat.color}` : '1px solid var(--border-glass)',
                          background: isSel ? 'rgba(255,255,255,0.12)' : 'rgba(0,0,0,0.3)',
                          color: isSel ? 'white' : 'var(--text-secondary)',
                          fontSize: '0.82rem',
                          fontWeight: isSel ? 700 : 500,
                          cursor: 'pointer',
                          display: 'flex',
                          alignItems: 'center',
                          gap: '6px',
                          transition: 'all 0.2s'
                        }}
                      >
                        <span>{cat.icon}</span>
                        <span>{cat.label}</span>
                      </button>
                    );
                  })}
                </div>
              </div>

              {/* Subcategory & Unit of Measure */}
              <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '12px' }}>
                <div style={{ display: 'flex', flexDirection: 'column', gap: '5px' }}>
                  <label style={{ fontSize: '0.8rem', fontWeight: 600, color: 'var(--text-secondary)' }}>
                    Sottocategoria
                  </label>
                  <input
                    type="text"
                    placeholder="Es. Birre, Detergenza, Bibite..."
                    value={newProductForm.subcategory}
                    onChange={e => setNewProductForm({ ...newProductForm, subcategory: e.target.value })}
                    style={{
                      padding: '9px 12px',
                      background: 'rgba(0,0,0,0.4)',
                      border: '1px solid var(--border-glass)',
                      borderRadius: '8px',
                      color: 'white',
                      fontSize: '0.85rem',
                      outline: 'none'
                    }}
                  />
                </div>

                <div style={{ display: 'flex', flexDirection: 'column', gap: '5px' }}>
                  <label style={{ fontSize: '0.8rem', fontWeight: 600, color: 'var(--text-secondary)' }}>
                    Unità di Misura d'Ordine *
                  </label>
                  <select
                    value={newProductForm.comparison_unit}
                    onChange={e => setNewProductForm({ ...newProductForm, comparison_unit: e.target.value })}
                    style={{
                      padding: '9px 12px',
                      background: 'rgba(0,0,0,0.4)',
                      border: '1px solid var(--border-glass)',
                      borderRadius: '8px',
                      color: '#93c5fd',
                      fontWeight: 700,
                      fontSize: '0.85rem',
                      outline: 'none',
                      cursor: 'pointer'
                    }}
                  >
                    {getSectorUoms(newProductForm.category).map(u => (
                      <option key={u.id} value={u.id} style={{ background: '#13131c', color: 'white' }}>
                        {u.label}
                      </option>
                    ))}
                  </select>
                </div>
              </div>

              {/* Quantity to add to cart & SKU */}
              <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '12px' }}>
                <div style={{ display: 'flex', flexDirection: 'column', gap: '5px' }}>
                  <label style={{ fontSize: '0.8rem', fontWeight: 600, color: '#34d399' }}>
                    Quantità Iniziale nel Carrello
                  </label>
                  <input
                    type="number"
                    min="0"
                    placeholder="Es. 1"
                    value={newProductForm.initial_quantity}
                    onChange={e => setNewProductForm({ ...newProductForm, initial_quantity: parseFloat(e.target.value) || '' })}
                    style={{
                      padding: '9px 12px',
                      background: 'rgba(16, 185, 129, 0.1)',
                      border: '1px solid rgba(16, 185, 129, 0.4)',
                      borderRadius: '8px',
                      color: '#34d399',
                      fontWeight: 700,
                      fontSize: '0.9rem',
                      outline: 'none'
                    }}
                  />
                </div>

                <div style={{ display: 'flex', flexDirection: 'column', gap: '5px' }}>
                  <label style={{ fontSize: '0.8rem', fontWeight: 600, color: 'var(--text-secondary)' }}>
                    Codice SKU Interno (Opzionale)
                  </label>
                  <input
                    type="text"
                    placeholder="Auto-generato se vuoto"
                    value={newProductForm.sku_interno}
                    onChange={e => setNewProductForm({ ...newProductForm, sku_interno: e.target.value })}
                    style={{
                      padding: '9px 12px',
                      background: 'rgba(0,0,0,0.4)',
                      border: '1px solid var(--border-glass)',
                      borderRadius: '8px',
                      color: 'white',
                      fontSize: '0.85rem',
                      outline: 'none'
                    }}
                  />
                </div>
              </div>
            </div>

            {/* Modal Actions */}
            <div style={{ display: 'flex', justifyContent: 'flex-end', gap: '10px', marginTop: '10px', flexWrap: 'wrap' }}>
              <button
                type="button"
                className="btn btn-secondary"
                onClick={() => setIsAddProductModalOpen(false)}
                disabled={savingProduct}
                style={{ padding: '10px 16px', fontSize: '0.85rem' }}
              >
                Annulla
              </button>

              <button
                type="button"
                className="btn btn-secondary"
                onClick={() => handleSaveNewProduct(false)}
                disabled={savingProduct || !newProductForm.canonical_name.trim()}
                style={{ padding: '10px 18px', fontSize: '0.85rem', fontWeight: 700, display: 'flex', alignItems: 'center', gap: '6px' }}
              >
                {savingProduct ? <RefreshCw className="spinner" size={14} /> : <FileText size={14} />}
                <span>Salva nel Catalogo</span>
              </button>

              {/* UNICO TASTO: SALVA E RICHIEDI PREZZO A TUTTI I FORNITORI DEL SETTORE */}
              <button
                type="button"
                onClick={() => handleSaveNewProduct(true)}
                disabled={savingProduct || !newProductForm.canonical_name.trim()}
                style={{
                  padding: '11px 22px',
                  borderRadius: '10px',
                  border: 'none',
                  background: 'linear-gradient(135deg, #3b82f6 0%, #8b5cf6 100%)',
                  color: 'white',
                  fontWeight: 800,
                  fontSize: '0.9rem',
                  cursor: savingProduct || !newProductForm.canonical_name.trim() ? 'not-allowed' : 'pointer',
                  display: 'flex',
                  alignItems: 'center',
                  gap: '8px',
                  boxShadow: '0 0 25px rgba(139, 92, 246, 0.4)',
                  opacity: savingProduct || !newProductForm.canonical_name.trim() ? 0.6 : 1,
                  transition: 'all 0.2s'
                }}
              >
                {savingProduct ? <RefreshCw className="spinner" size={16} /> : <Send size={16} />}
                <span>Salva e Richiedi Prezzo a Tutti i Fornitori 🚀</span>
              </button>
            </div>
          </div>
        </div>
      )}

      {/* ─────────────────────────────────────────────────────────────
          MODAL 2: RICHIESTA PREZZO MULTI-FORNITORE SETTORE (RFQ)
      ───────────────────────────────────────────────────────────── */}
      {isPriceQuoteModalOpen && (
        <div style={{
          position: 'fixed',
          top: 0, left: 0, right: 0, bottom: 0,
          backgroundColor: 'rgba(0, 0, 0, 0.8)',
          backdropFilter: 'blur(8px)',
          zIndex: 9999,
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
          padding: '16px'
        }}>
          <div style={{
            background: 'linear-gradient(145deg, #161e2e 0%, #0c1220 100%)',
            border: '1px solid rgba(139, 92, 246, 0.4)',
            borderRadius: '16px',
            width: '100%',
            maxWidth: '780px',
            maxHeight: '92vh',
            overflowY: 'auto',
            boxShadow: '0 25px 50px -12px rgba(0, 0, 0, 0.8), 0 0 40px rgba(139, 92, 246, 0.3)',
            padding: '26px',
            color: 'white',
            display: 'flex',
            flexDirection: 'column',
            gap: '20px'
          }}>
            {/* Modal Header */}
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start' }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: '12px' }}>
                <div style={{
                  width: '44px', height: '44px', borderRadius: '12px',
                  background: 'linear-gradient(135deg, #8b5cf6, #3b82f6)',
                  display: 'flex', alignItems: 'center', justifyContent: 'center',
                  boxShadow: '0 0 20px rgba(139, 92, 246, 0.4)'
                }}>
                  <Send size={22} color="white" />
                </div>
                <div>
                  <h3 style={{ margin: 0, fontSize: '1.3rem', fontWeight: 800 }}>
                    Richiesta Prezzo Fornitori del Settore
                  </h3>
                  <p style={{ margin: '3px 0 0', fontSize: '0.82rem', color: 'var(--text-secondary)' }}>
                    Invia la richiesta di quotazione per incrociare i prezzi e agganciare nuove offerte al sistema.
                  </p>
                </div>
              </div>
              <button
                type="button"
                onClick={() => setIsPriceQuoteModalOpen(false)}
                style={{
                  background: 'rgba(255,255,255,0.06)',
                  border: 'none',
                  borderRadius: '8px',
                  color: 'var(--text-secondary)',
                  padding: '6px',
                  cursor: 'pointer'
                }}
              >
                <X size={18} />
              </button>
            </div>

            {quoteSuccessMsg && (
              <div style={{ padding: '12px 16px', borderRadius: '10px', background: 'rgba(16, 185, 129, 0.15)', color: '#34d399', border: '1px solid rgba(16, 185, 129, 0.3)', display: 'flex', gap: '10px', alignItems: 'center' }}>
                <CheckCircle2 size={18} />
                <span style={{ fontSize: '0.85rem', fontWeight: 600 }}>{quoteSuccessMsg}</span>
              </div>
            )}

            {loadingQuote ? (
              <div style={{ padding: '50px', textAlign: 'center', color: 'var(--text-secondary)' }}>
                <RefreshCw className="spinner" size={32} style={{ margin: '0 auto 12px', color: '#8b5cf6' }} />
                <div>Individuazione fornitori del settore per "{quoteProductTarget?.canonical_name || 'questo articolo'}" e generazione messaggi di quotazione...</div>
              </div>
            ) : quoteData ? (
              <div style={{ display: 'flex', flexDirection: 'column', gap: '18px' }}>
                
                {/* Target Product Summary Banner */}
                <div style={{
                  padding: '14px 18px',
                  borderRadius: '12px',
                  background: 'rgba(139, 92, 246, 0.12)',
                  border: '1px solid rgba(139, 92, 246, 0.35)',
                  display: 'flex',
                  justifyContent: 'space-between',
                  alignItems: 'center',
                  flexWrap: 'wrap',
                  gap: '12px'
                }}>
                  <div>
                    <div style={{ fontSize: '1.05rem', fontWeight: 800, color: 'white' }}>
                      {quoteData.canonical_name}
                    </div>
                    <div style={{ display: 'flex', gap: '8px', alignItems: 'center', marginTop: '4px', fontSize: '0.78rem', color: '#c4b5fd' }}>
                      <span>Settore: <strong>{quoteData.settore_categoria}</strong></span>
                      {quoteData.sottocategoria && <span>• {quoteData.sottocategoria}</span>}
                      {quoteData.brand && <span>• Brand: {quoteData.brand}</span>}
                      <span>• UoM: <strong>{quoteData.comparison_unit}</strong></span>
                    </div>
                  </div>

                  <div style={{
                    padding: '6px 12px',
                    borderRadius: '8px',
                    background: 'rgba(0,0,0,0.3)',
                    border: '1px solid rgba(255,255,255,0.1)',
                    fontSize: '0.78rem',
                    color: 'var(--text-secondary)'
                  }}>
                    📍 Sede: <strong style={{ color: 'white' }}>{quoteData.location_nome || 'Tutte'}</strong>
                  </div>
                </div>

                {/* Broadcast Master Action Bar (UNICO TASTO PER TUTTI I FORNITORI) */}
                <div style={{
                  padding: '16px 20px',
                  borderRadius: '12px',
                  background: 'linear-gradient(135deg, rgba(30, 41, 59, 0.8) 0%, rgba(15, 23, 42, 0.95) 100%)',
                  border: '1px solid rgba(59, 130, 246, 0.3)',
                  display: 'flex',
                  flexDirection: 'column',
                  gap: '12px'
                }}>
                  <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', flexWrap: 'wrap', gap: '8px' }}>
                    <div style={{ fontWeight: 700, fontSize: '0.9rem', color: '#93c5fd', display: 'flex', alignItems: 'center', gap: '6px' }}>
                      <Radio size={16} color="#60a5fa" />
                      <span>Invia Richiesta di Prezzo a Tutti i Fornitori del Settore ({quoteData.total_fornitori_settore})</span>
                    </div>
                    <div style={{ fontSize: '0.78rem', color: 'var(--text-secondary)' }}>
                      💬 {quoteData.fornitori_con_whatsapp} WhatsApp · ✉️ {quoteData.fornitori_con_email} Email
                    </div>
                  </div>

                  {/* UNICO TASTO MASTER BROADCAST BUTTONS */}
                  <div style={{ display: 'grid', gridTemplateColumns: isMobileScreen ? '1fr' : '1fr 1fr', gap: '10px' }}>
                    <button
                      type="button"
                      onClick={handleCopyBroadcastQuote}
                      style={{
                        padding: '12px 18px',
                        borderRadius: '10px',
                        border: '1px solid rgba(37, 211, 102, 0.4)',
                        background: 'linear-gradient(135deg, rgba(37, 211, 102, 0.2) 0%, rgba(18, 140, 126, 0.3) 100%)',
                        color: 'white',
                        fontWeight: 800,
                        fontSize: '0.88rem',
                        cursor: 'pointer',
                        display: 'flex',
                        alignItems: 'center',
                        justifyContent: 'center',
                        gap: '8px',
                        boxShadow: '0 0 20px rgba(37, 211, 102, 0.25)',
                        transition: 'all 0.2s'
                      }}
                    >
                      {quoteCopied ? <Check size={16} color="#34d399" /> : <Copy size={16} color="#25D366" />}
                      <span>{quoteCopied ? '✓ Testo Broadcast Copiato!' : '📋 Copia Testo Broadcast WhatsApp'}</span>
                    </button>

                    <button
                      type="button"
                      onClick={handleSendBroadcastEmail}
                      disabled={quoteData.fornitori_con_email === 0}
                      style={{
                        padding: '12px 18px',
                        borderRadius: '10px',
                        border: '1px solid rgba(59, 130, 246, 0.4)',
                        background: 'linear-gradient(135deg, rgba(59, 130, 246, 0.25) 0%, rgba(99, 102, 241, 0.35) 100%)',
                        color: 'white',
                        fontWeight: 800,
                        fontSize: '0.88rem',
                        cursor: quoteData.fornitori_con_email === 0 ? 'not-allowed' : 'pointer',
                        display: 'flex',
                        alignItems: 'center',
                        justifyContent: 'center',
                        gap: '8px',
                        boxShadow: '0 0 20px rgba(59, 130, 246, 0.25)',
                        opacity: quoteData.fornitori_con_email === 0 ? 0.5 : 1,
                        transition: 'all 0.2s'
                      }}
                    >
                      <Mail size={16} color="#93c5fd" />
                      <span>✉️ Invia a Tutti via Email (BCC/Ccn)</span>
                    </button>
                  </div>
                </div>

                {/* Individual Supplier Cards List */}
                <div style={{ display: 'flex', flexDirection: 'column', gap: '10px' }}>
                  <div style={{ fontSize: '0.85rem', fontWeight: 700, color: 'var(--text-secondary)', display: 'flex', alignItems: 'center', gap: '6px' }}>
                    <Store size={14} />
                    <span>Fornitori Abilitati nel Settore "{quoteData.settore_categoria}" ({quoteData.fornitori.length})</span>
                  </div>

                  {quoteData.fornitori.length === 0 ? (
                    <div style={{ padding: '20px', textAlign: 'center', color: 'var(--text-secondary)', background: 'rgba(0,0,0,0.2)', borderRadius: '10px' }}>
                      Nessun fornitore registrato con recapiti in questa categoria.
                    </div>
                  ) : (
                    <div style={{ display: 'flex', flexDirection: 'column', gap: '8px', maxHeight: '320px', overflowY: 'auto', paddingRight: '4px' }}>
                      {quoteData.fornitori.map(sup => {
                        const hasPhone = !!(quoteSupplierPhones[sup.supplier_id] || sup.telefono_contatto);
                        const hasEmail = !!(quoteSupplierEmails[sup.supplier_id] || sup.email_contatto);

                        return (
                          <div
                            key={sup.supplier_id}
                            style={{
                              padding: '12px 16px',
                              borderRadius: '10px',
                              background: 'rgba(255, 255, 255, 0.03)',
                              border: '1px solid var(--border-glass)',
                              display: 'flex',
                              justifyContent: 'space-between',
                              alignItems: 'center',
                              flexWrap: 'wrap',
                              gap: '10px'
                            }}
                          >
                            <div>
                              <div style={{ fontWeight: 800, fontSize: '0.92rem', color: 'white', display: 'flex', alignItems: 'center', gap: '8px' }}>
                                <span>{sup.supplier_name}</span>
                                <span style={{
                                  padding: '1px 6px', borderRadius: '4px',
                                  background: 'rgba(59, 130, 246, 0.15)', color: '#93c5fd',
                                  fontSize: '0.7rem', fontWeight: 600
                                }}>
                                  {sup.capability_reason || 'Settore'}
                                </span>
                              </div>

                              {/* Editable contact pills */}
                              <div style={{ display: 'flex', gap: '10px', alignItems: 'center', marginTop: '6px', fontSize: '0.78rem', color: 'var(--text-secondary)' }}>
                                <div style={{ display: 'flex', alignItems: 'center', gap: '4px' }}>
                                  <Phone size={12} color={hasPhone ? '#25D366' : 'var(--text-secondary)'} />
                                  <input
                                    type="text"
                                    placeholder="Nessun tel."
                                    value={quoteSupplierPhones[sup.supplier_id] ?? (sup.telefono_contatto || '')}
                                    onChange={e => setQuoteSupplierPhones({ ...quoteSupplierPhones, [sup.supplier_id]: e.target.value })}
                                    style={{
                                      padding: '2px 6px',
                                      background: 'rgba(0,0,0,0.3)',
                                      border: '1px solid rgba(255,255,255,0.08)',
                                      borderRadius: '4px',
                                      color: 'white',
                                      fontSize: '0.75rem',
                                      width: '110px'
                                    }}
                                  />
                                </div>

                                <div style={{ display: 'flex', alignItems: 'center', gap: '4px' }}>
                                  <Mail size={12} color={hasEmail ? '#60a5fa' : 'var(--text-secondary)'} />
                                  <input
                                    type="text"
                                    placeholder="Nessuna email"
                                    value={quoteSupplierEmails[sup.supplier_id] ?? (sup.email_contatto || '')}
                                    onChange={e => setQuoteSupplierEmails({ ...quoteSupplierEmails, [sup.supplier_id]: e.target.value })}
                                    style={{
                                      padding: '2px 6px',
                                      background: 'rgba(0,0,0,0.3)',
                                      border: '1px solid rgba(255,255,255,0.08)',
                                      borderRadius: '4px',
                                      color: 'white',
                                      fontSize: '0.75rem',
                                      width: '140px'
                                    }}
                                  />
                                </div>
                              </div>
                            </div>

                            {/* Single Supplier Action Buttons */}
                            <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                              <button
                                type="button"
                                onClick={() => handleOpenSingleSupplierWhatsApp(sup)}
                                style={{
                                  padding: '7px 12px',
                                  borderRadius: '8px',
                                  border: '1px solid rgba(37, 211, 102, 0.4)',
                                  background: 'linear-gradient(135deg, #25D366, #128C7E)',
                                  color: 'white',
                                  fontSize: '0.78rem',
                                  fontWeight: 700,
                                  cursor: 'pointer',
                                  display: 'flex',
                                  alignItems: 'center',
                                  gap: '5px'
                                }}
                                title="Invia richiesta specifica su WhatsApp"
                              >
                                <MessageSquare size={13} />
                                <span>WhatsApp</span>
                              </button>

                              {hasEmail && (
                                <button
                                  type="button"
                                  onClick={() => handleOpenSingleSupplierEmail(sup)}
                                  style={{
                                    padding: '7px 12px',
                                    borderRadius: '8px',
                                    border: '1px solid rgba(59, 130, 246, 0.4)',
                                    background: 'rgba(59, 130, 246, 0.2)',
                                    color: '#93c5fd',
                                    fontSize: '0.78rem',
                                    fontWeight: 700,
                                    cursor: 'pointer',
                                    display: 'flex',
                                    alignItems: 'center',
                                    gap: '5px'
                                  }}
                                  title="Invia email di richiesta prezzo"
                                >
                                  <Mail size={13} />
                                  <span>Email</span>
                                </button>
                              )}
                            </div>
                          </div>
                        );
                      })}
                    </div>
                  )}
                </div>

                {/* Formatted Text Preview */}
                <details style={{ background: 'rgba(0,0,0,0.2)', padding: '10px 14px', borderRadius: '8px', fontSize: '0.8rem', color: 'var(--text-secondary)' }}>
                  <summary style={{ cursor: 'pointer', fontWeight: 600, color: '#93c5fd' }}>
                    👁️ Mostra anteprima del testo di richiesta quotazione
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
                    {quoteData.broadcast_whatsapp_text}
                  </pre>
                </details>

                {/* System enrichment note */}
                <div style={{
                  padding: '10px 14px',
                  borderRadius: '8px',
                  background: 'rgba(59, 130, 246, 0.08)',
                  border: '1px solid rgba(59, 130, 246, 0.2)',
                  fontSize: '0.78rem',
                  color: '#93c5fd',
                  display: 'flex',
                  alignItems: 'center',
                  gap: '8px'
                }}>
                  <Sparkles size={16} color="#f59e0b" style={{ flexShrink: 0 }} />
                  <span>
                    Quando i fornitori risponderanno con i loro listini o fatture, i dati verranno incrociati e agganciati in automatico a questo articolo per aggiornare le matrici e ottimizzare i futuri ordini.
                  </span>
                </div>

              </div>
            ) : null}

            {/* Modal Footer */}
            <div style={{ display: 'flex', justifyContent: 'flex-end', marginTop: '6px' }}>
              <button
                type="button"
                className="btn btn-secondary"
                onClick={() => setIsPriceQuoteModalOpen(false)}
                style={{ padding: '9px 18px', fontSize: '0.85rem' }}
              >
                Chiudi
              </button>
            </div>
          </div>
        </div>
      )}

    </div>
  );
}
