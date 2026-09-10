import { useState, useEffect, useMemo } from 'react';
import { 
  Boxes, 
  Check, 
  Plus, 
  Pencil, 
  Trash2, 
  RefreshCw, 
  Sparkles, 
  Search, 
  Building2, 
  LayoutGrid, 
  Table, 
  CheckCircle2, 
  AlertCircle,
  Filter,
  X,
  Utensils,
  FolderTree,
  Tag
} from 'lucide-react';
import { API_BASE, getHeaders } from '../api';

interface CategoryItem {
  id: number;
  nome: string;
  descrizione: string | null;
  colore: string;
  is_active: boolean;
  product_count: number;
  supplier_count: number;
  created_at: string;
  updated_at: string;
}

export interface SubcategoryItem {
  id: number;
  categoria_nome: string;
  nome: string;
  descrizione: string | null;
  is_active: boolean;
  product_count: number;
  created_at: string;
  updated_at: string;
}

interface SupplierMatrixRow {
  supplier_id: number;
  supplier_name: string;
  partita_iva: string;
  attivo_whitelist: boolean;
  categories: Record<string, boolean>;
  subcategories?: Record<string, string[]>;
}

const COLOR_PRESETS = [
  { label: 'Azzurro Sky', value: '#0ea5e9' },
  { label: 'Ambra Birra', value: '#f59e0b' },
  { label: 'Viola Alcolici', value: '#8b5cf6' },
  { label: 'Rosa Vini', value: '#ec4899' },
  { label: 'Cyan Acqua', value: '#06b6d4' },
  { label: 'Caffè Marrone', value: '#78350f' },
  { label: 'Smeraldo Monouso', value: '#10b981' },
  { label: 'Teal Detergenza', value: '#14b8a6' },
  { label: 'Grigio Packaging', value: '#64748b' },
  { label: 'Lime Ortofrutta', value: '#84cc16' },
  { label: 'Rosso Carne', value: '#ef4444' },
  { label: 'Blu Mare Pesce', value: '#3b82f6' },
  { label: 'Giallo Formaggi', value: '#facc15' },
  { label: 'Indaco Surgelati', value: '#6366f1' },
  { label: 'Arancio Dispensa', value: '#d97706' },
];

export default function CategorySupplierManager() {
  const [subTab, setSubTab] = useState<'matrix' | 'categories' | 'subcategories'>('matrix');
  const [viewMode, setViewMode] = useState<'cards' | 'table'>('cards');
  const [loading, setLoading] = useState(true);
  const [actionLoading, setActionLoading] = useState(false);
  const [message, setMessage] = useState<{ text: string; type: 'success' | 'error' } | null>(null);

  // Data states
  const [categories, setCategories] = useState<CategoryItem[]>([]);
  const [suppliers, setSuppliers] = useState<SupplierMatrixRow[]>([]);
  const [allSubcategories, setAllSubcategories] = useState<SubcategoryItem[]>([]);
  const [searchFilter, setSearchFilter] = useState('');
  const [selectedCategoryFilter, setSelectedCategoryFilter] = useState<string>('all');

  // Subcategories state (Food and other categories)
  const [subcategories, setSubcategories] = useState<SubcategoryItem[]>([]);
  const [subcatParentCategory, setSubcatParentCategory] = useState<string>('Food');
  const [subcatLoading, setSubcatLoading] = useState(false);
  const [showSubcatModal, setShowSubcatModal] = useState(false);
  const [editingSubcat, setEditingSubcat] = useState<SubcategoryItem | null>(null);
  const [subcatFormNome, setSubcatFormNome] = useState('');
  const [subcatFormDesc, setSubcatFormDesc] = useState('');
  const [subcatFormIsActive, setSubcatFormIsActive] = useState(true);

  // Modals
  const [showCatModal, setShowCatModal] = useState(false);
  const [editingCategory, setEditingCategory] = useState<CategoryItem | null>(null);
  const [catFormNome, setCatFormNome] = useState('');
  const [catFormDesc, setCatFormDesc] = useState('');
  const [catFormColor, setCatFormColor] = useState('#3b82f6');

  const headers = getHeaders();

  const loadData = async () => {
    setLoading(true);
    try {
      const [matrixRes, subcatsRes] = await Promise.all([
        fetch(`${API_BASE}/categories/matrix`, { headers }),
        fetch(`${API_BASE}/categories/subcategories`, { headers })
      ]);
      if (!matrixRes.ok) throw new Error('Errore nel caricamento della matrice categorie');
      const data = await matrixRes.json();
      setCategories(data.categories || []);
      setSuppliers(data.suppliers || []);

      if (subcatsRes.ok) {
        const subData = await subcatsRes.json();
        setAllSubcategories(subData || []);
      }
    } catch (err: any) {
      console.error(err);
      setMessage({ text: err.message || 'Errore di connessione', type: 'error' });
    } finally {
      setLoading(false);
    }
  };

  const loadSubcategories = async (parentCat = subcatParentCategory) => {
    setSubcatLoading(true);
    try {
      const res = await fetch(`${API_BASE}/categories/subcategories?categoria_nome=${encodeURIComponent(parentCat)}`, { headers });
      if (!res.ok) throw new Error('Errore nel caricamento delle sottocategorie');
      const data = await res.json();
      setSubcategories(data || []);
    } catch (err: any) {
      console.error(err);
      setMessage({ text: err.message || 'Errore caricamento sottocategorie', type: 'error' });
    } finally {
      setSubcatLoading(false);
    }
  };

  const subcategoriesByCategory = useMemo(() => {
    const map: Record<string, SubcategoryItem[]> = {};
    for (const sub of allSubcategories) {
      const key = sub.categoria_nome;
      if (!map[key]) map[key] = [];
      map[key].push(sub);
    }
    return map;
  }, [allSubcategories]);

  useEffect(() => {
    loadData();
    loadSubcategories('Food');
  }, []);

  useEffect(() => {
    if (subTab === 'subcategories') {
      loadSubcategories(subcatParentCategory);
    }
  }, [subTab, subcatParentCategory]);

  // Quick feedback timeout
  useEffect(() => {
    if (message) {
      const timer = setTimeout(() => setMessage(null), 4000);
      return () => clearTimeout(timer);
    }
  }, [message]);

  // Handle single toggle
  const handleToggleCapability = async (supplierId: number, categoryName: string, currentVal: boolean) => {
    const newVal = !currentVal;
    
    // Optimistic UI update
    setSuppliers(prev => prev.map(s => {
      if (s.supplier_id !== supplierId) return s;
      return {
        ...s,
        categories: {
          ...s.categories,
          [categoryName]: newVal
        }
      };
    }));

    // Update category supplier count optimistically
    setCategories(prev => prev.map(c => {
      if (c.nome.toLowerCase() !== categoryName.toLowerCase()) return c;
      return {
        ...c,
        supplier_count: Math.max(0, c.supplier_count + (newVal ? 1 : -1))
      };
    }));

    try {
      const res = await fetch(`${API_BASE}/categories/toggle`, {
        method: 'POST',
        headers,
        body: JSON.stringify({
          supplier_id: supplierId,
          category: categoryName,
          enabled: newVal
        })
      });
      if (!res.ok) {
        throw new Error("Errore durante l'aggiornamento dell'abilitazione");
      }
    } catch (err: any) {
      console.error(err);
      setMessage({ text: err.message, type: 'error' });
      // Revert on error
      loadData();
    }
  };

  // Handle subcategory toggle for a supplier
  const handleToggleSubcategory = async (
    supplierId: number,
    categoryName: string,
    subcategoryName: string,
    currentEnabled: boolean
  ) => {
    const newEnabled = !currentEnabled;

    // Optimistic UI update
    setSuppliers(prev => prev.map(s => {
      if (s.supplier_id !== supplierId) return s;
      const currentSubs = s.subcategories?.[categoryName] || [];
      const newSubs = newEnabled
        ? [...currentSubs, subcategoryName]
        : currentSubs.filter(name => name.toLowerCase() !== subcategoryName.toLowerCase());
      return {
        ...s,
        subcategories: {
          ...(s.subcategories || {}),
          [categoryName]: newSubs
        }
      };
    }));

    try {
      const res = await fetch(`${API_BASE}/categories/supplier-subcategories/toggle`, {
        method: 'POST',
        headers,
        body: JSON.stringify({
          supplier_id: supplierId,
          category: categoryName,
          subcategory: subcategoryName,
          enabled: newEnabled
        })
      });
      if (!res.ok) {
        throw new Error("Errore durante l'aggiornamento della sottocategoria");
      }
    } catch (err: any) {
      console.error(err);
      setMessage({ text: err.message, type: 'error' });
      await loadData();
    }
  };

  // Bulk subcategories for a supplier
  const handleBulkSubcategories = async (
    supplierId: number,
    categoryName: string,
    enableAll: boolean
  ) => {
    const catSubs = (subcategoriesByCategory[categoryName] || []).map(s => s.nome);
    const newSubs = enableAll ? catSubs : [];

    // Optimistic UI update
    setSuppliers(prev => prev.map(s => {
      if (s.supplier_id !== supplierId) return s;
      return {
        ...s,
        subcategories: {
          ...(s.subcategories || {}),
          [categoryName]: newSubs
        }
      };
    }));

    try {
      const res = await fetch(`${API_BASE}/categories/supplier-subcategories/bulk`, {
        method: 'PUT',
        headers,
        body: JSON.stringify({
          supplier_id: supplierId,
          category: categoryName,
          subcategories: newSubs
        })
      });
      if (!res.ok) {
        throw new Error("Errore durante l'aggiornamento massivo delle sottocategorie");
      }
    } catch (err: any) {
      console.error(err);
      setMessage({ text: err.message, type: 'error' });
      await loadData();
    }
  };

  // Bulk enable/disable for a single supplier
  const handleBulkSupplierCategories = async (supplierId: number, enableAll: boolean) => {
    setActionLoading(true);
    try {
      const capabilities = categories.map(c => ({
        category: c.nome,
        enabled: enableAll
      }));

      const res = await fetch(`${API_BASE}/categories/matrix`, {
        method: 'PUT',
        headers,
        body: JSON.stringify({
          supplier_id: supplierId,
          capabilities
        })
      });

      if (!res.ok) throw new Error("Errore durante l'aggiornamento massivo");
      setMessage({ 
        text: enableAll ? 'Tutte le categorie abilitate per il fornitore' : 'Tutte le categorie disabilitate', 
        type: 'success' 
      });
      await loadData();
    } catch (err: any) {
      setMessage({ text: err.message, type: 'error' });
    } finally {
      setActionLoading(false);
    }
  };

  // Seed default categories
  const handleSeedDefaults = async () => {
    setActionLoading(true);
    try {
      const res = await fetch(`${API_BASE}/categories/seed-defaults`, {
        method: 'POST',
        headers
      });
      if (!res.ok) throw new Error('Errore durante la creazione delle categorie predefinite');
      const data = await res.json();
      setMessage({ text: data.message || 'Categorie caricate con successo', type: 'success' });
      await loadData();
    } catch (err: any) {
      setMessage({ text: err.message, type: 'error' });
    } finally {
      setActionLoading(false);
    }
  };

  // Open Add/Edit category modal
  const openCategoryModal = (cat?: CategoryItem) => {
    if (cat) {
      setEditingCategory(cat);
      setCatFormNome(cat.nome);
      setCatFormDesc(cat.descrizione || '');
      setCatFormColor(cat.colore || '#3b82f6');
    } else {
      setEditingCategory(null);
      setCatFormNome('');
      setCatFormDesc('');
      setCatFormColor('#3b82f6');
    }
    setShowCatModal(true);
  };

  // Save Category (Create or Update)
  const handleSaveCategory = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!catFormNome.trim()) {
      setMessage({ text: 'Inserisci il nome della categoria', type: 'error' });
      return;
    }

    setActionLoading(true);
    try {
      let res;
      if (editingCategory) {
        res = await fetch(`${API_BASE}/categories/${editingCategory.id}`, {
          method: 'PUT',
          headers,
          body: JSON.stringify({
            nome: catFormNome.trim(),
            descrizione: catFormDesc.trim() || null,
            colore: catFormColor
          })
        });
      } else {
        res = await fetch(`${API_BASE}/categories/`, {
          method: 'POST',
          headers,
          body: JSON.stringify({
            nome: catFormNome.trim(),
            descrizione: catFormDesc.trim() || null,
            colore: catFormColor,
            is_active: true
          })
        });
      }

      if (!res.ok) {
        const errData = await res.json();
        throw new Error(errData.detail || 'Errore nel salvataggio della categoria');
      }

      setShowCatModal(false);
      setMessage({ 
        text: editingCategory ? 'Categoria aggiornata con successo' : 'Nuova categoria creata', 
        type: 'success' 
      });
      await loadData();
    } catch (err: any) {
      setMessage({ text: err.message, type: 'error' });
    } finally {
      setActionLoading(false);
    }
  };

  // Delete category
  const handleDeleteCategory = async (cat: CategoryItem) => {
    if (!window.confirm(`Sei sicuro di voler eliminare la categoria "${cat.nome}"?`)) return;

    setActionLoading(true);
    try {
      const res = await fetch(`${API_BASE}/categories/${cat.id}`, {
        method: 'DELETE',
        headers
      });
      if (!res.ok) {
        const errData = await res.json();
        throw new Error(errData.detail || "Errore nell'eliminazione della categoria");
      }
      setMessage({ text: `Categoria "${cat.nome}" eliminata`, type: 'success' });
      await loadData();
    } catch (err: any) {
      setMessage({ text: err.message, type: 'error' });
    } finally {
      setActionLoading(false);
    }
  };

  // Subcategory management functions
  const openSubcategoryModal = (sub?: SubcategoryItem) => {
    if (sub) {
      setEditingSubcat(sub);
      setSubcatFormNome(sub.nome);
      setSubcatFormDesc(sub.descrizione || '');
      setSubcatFormIsActive(sub.is_active);
    } else {
      setEditingSubcat(null);
      setSubcatFormNome('');
      setSubcatFormDesc('');
      setSubcatFormIsActive(true);
    }
    setShowSubcatModal(true);
  };

  const handleSaveSubcategory = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!subcatFormNome.trim()) {
      setMessage({ text: 'Inserisci il nome della sottocategoria', type: 'error' });
      return;
    }

    setActionLoading(true);
    try {
      let res;
      if (editingSubcat) {
        res = await fetch(`${API_BASE}/categories/subcategories/${editingSubcat.id}`, {
          method: 'PUT',
          headers,
          body: JSON.stringify({
            nome: subcatFormNome.trim(),
            descrizione: subcatFormDesc.trim() || null,
            is_active: subcatFormIsActive,
          }),
        });
      } else {
        res = await fetch(`${API_BASE}/categories/subcategories`, {
          method: 'POST',
          headers,
          body: JSON.stringify({
            categoria_nome: subcatParentCategory,
            nome: subcatFormNome.trim(),
            descrizione: subcatFormDesc.trim() || null,
            is_active: subcatFormIsActive,
          }),
        });
      }

      if (!res.ok) {
        const errData = await res.json();
        throw new Error(errData.detail || 'Errore nel salvataggio della sottocategoria');
      }

      setShowSubcatModal(false);
      setMessage({
        text: editingSubcat ? 'Sottocategoria aggiornata con successo' : 'Nuova sottocategoria creata',
        type: 'success',
      });
      await loadSubcategories(subcatParentCategory);
    } catch (err: any) {
      setMessage({ text: err.message, type: 'error' });
    } finally {
      setActionLoading(false);
    }
  };

  const handleDeleteSubcategory = async (sub: SubcategoryItem) => {
    if (!window.confirm(`Sei sicuro di voler eliminare la sottocategoria "${sub.nome}"?`)) return;

    setActionLoading(true);
    try {
      const res = await fetch(`${API_BASE}/categories/subcategories/${sub.id}`, {
        method: 'DELETE',
        headers,
      });
      if (!res.ok) {
        const errData = await res.json();
        throw new Error(errData.detail || "Errore nell'eliminazione della sottocategoria");
      }
      setMessage({ text: `Sottocategoria "${sub.nome}" eliminata`, type: 'success' });
      await loadSubcategories(subcatParentCategory);
    } catch (err: any) {
      setMessage({ text: err.message, type: 'error' });
    } finally {
      setActionLoading(false);
    }
  };

  const handleToggleSubcatActive = async (sub: SubcategoryItem) => {
    setActionLoading(true);
    try {
      const res = await fetch(`${API_BASE}/categories/subcategories/${sub.id}`, {
        method: 'PUT',
        headers,
        body: JSON.stringify({
          is_active: !sub.is_active,
        }),
      });
      if (!res.ok) throw new Error('Errore nel cambio stato');
      await loadSubcategories(subcatParentCategory);
    } catch (err: any) {
      setMessage({ text: err.message, type: 'error' });
    } finally {
      setActionLoading(false);
    }
  };

  const handleSeedFoodSubcategories = async () => {
    setActionLoading(true);
    try {
      const res = await fetch(`${API_BASE}/categories/subcategories/seed-food-defaults`, {
        method: 'POST',
        headers,
      });
      if (!res.ok) throw new Error('Errore durante la creazione delle sottocategorie predefinite');
      const data = await res.json();
      setMessage({ text: data.message || 'Sottocategorie Food create con successo', type: 'success' });
      await loadSubcategories('Food');
    } catch (err: any) {
      setMessage({ text: err.message, type: 'error' });
    } finally {
      setActionLoading(false);
    }
  };

  // Filtered suppliers
  const filteredSuppliers = useMemo(() => {
    return suppliers.filter(s => {
      const matchSearch = s.supplier_name.toLowerCase().includes(searchFilter.toLowerCase()) ||
                          s.partita_iva.includes(searchFilter);
      
      if (!matchSearch) return false;
      if (selectedCategoryFilter === 'all') return true;
      return !!s.categories[selectedCategoryFilter];
    });
  }, [suppliers, searchFilter, selectedCategoryFilter]);

  // Filtered categories
  const filteredCategories = useMemo(() => {
    return categories.filter(c => 
      c.nome.toLowerCase().includes(searchFilter.toLowerCase()) ||
      (c.descrizione || '').toLowerCase().includes(searchFilter.toLowerCase())
    );
  }, [categories, searchFilter]);

  // Filtered subcategories
  const filteredSubcategories = useMemo(() => {
    return subcategories.filter(s => 
      s.nome.toLowerCase().includes(searchFilter.toLowerCase()) ||
      (s.descrizione || '').toLowerCase().includes(searchFilter.toLowerCase())
    );
  }, [subcategories, searchFilter]);

  // Statistics
  const totalCategories = categories.length;
  const totalSuppliers = suppliers.length;
  const mappedSuppliersCount = suppliers.filter(s => Object.values(s.categories).some(v => v)).length;
  const coveragePercent = totalSuppliers > 0 ? Math.round((mappedSuppliersCount / totalSuppliers) * 100) : 0;

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: '24px' }}>
      
      {/* Alert Notifications */}
      {message && (
        <div style={{
          padding: '12px 16px',
          borderRadius: '8px',
          display: 'flex',
          alignItems: 'center',
          gap: '10px',
          fontSize: '0.9rem',
          background: message.type === 'success' ? 'var(--status-green-bg, rgba(16,185,129,0.15))' : 'var(--status-red-bg, rgba(239,68,68,0.15))',
          color: message.type === 'success' ? 'var(--status-green, #10b981)' : 'var(--status-red, #ef4444)',
          border: `1px solid ${message.type === 'success' ? 'rgba(16,185,129,0.3)' : 'rgba(239,68,68,0.3)'}`
        }}>
          {message.type === 'success' ? <CheckCircle2 size={18} /> : <AlertCircle size={18} />}
          <span>{message.text}</span>
        </div>
      )}

      {/* KPI Stats Bar */}
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(220px, 1fr))', gap: '16px' }}>
        <div className="glass-panel" style={{ padding: '18px 20px', display: 'flex', alignItems: 'center', gap: '16px' }}>
          <div style={{ width: '44px', height: '44px', borderRadius: '10px', background: 'rgba(14,165,233,0.15)', color: '#0ea5e9', display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
            <Boxes size={22} />
          </div>
          <div>
            <div style={{ fontSize: '0.8rem', color: 'var(--text-secondary)' }}>Categorie Master</div>
            <div style={{ fontSize: '1.4rem', fontWeight: 700, marginTop: '2px' }}>{totalCategories}</div>
          </div>
        </div>

        <div className="glass-panel" style={{ padding: '18px 20px', display: 'flex', alignItems: 'center', gap: '16px' }}>
          <div style={{ width: '44px', height: '44px', borderRadius: '10px', background: 'rgba(139,92,246,0.15)', color: '#8b5cf6', display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
            <Building2 size={22} />
          </div>
          <div>
            <div style={{ fontSize: '0.8rem', color: 'var(--text-secondary)' }}>Fornitori Attivi</div>
            <div style={{ fontSize: '1.4rem', fontWeight: 700, marginTop: '2px' }}>{totalSuppliers}</div>
          </div>
        </div>

        <div className="glass-panel" style={{ padding: '18px 20px', display: 'flex', alignItems: 'center', gap: '16px' }}>
          <div style={{ width: '44px', height: '44px', borderRadius: '10px', background: 'rgba(16,185,129,0.15)', color: '#10b981', display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
            <CheckCircle2 size={22} />
          </div>
          <div>
            <div style={{ fontSize: '0.8rem', color: 'var(--text-secondary)' }}>Fornitori Mappati</div>
            <div style={{ fontSize: '1.4rem', fontWeight: 700, marginTop: '2px' }}>{mappedSuppliersCount} <span style={{ fontSize: '0.85rem', color: 'var(--text-secondary)', fontWeight: 400 }}>({coveragePercent}%)</span></div>
          </div>
        </div>
      </div>

      {/* Main Container */}
      <div className="glass-panel" style={{ padding: '24px', display: 'flex', flexDirection: 'column', gap: '20px' }}>
        
        {/* Navigation Tabs & Header Actions */}
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', flexWrap: 'wrap', gap: '16px', borderBottom: '1px solid var(--border-glass)', paddingBottom: '16px' }}>
          
          <div style={{ display: 'flex', gap: '12px' }}>
            <button
              onClick={() => setSubTab('matrix')}
              style={{
                padding: '10px 18px',
                borderRadius: '8px',
                border: 'none',
                cursor: 'pointer',
                fontWeight: 600,
                fontSize: '0.9rem',
                display: 'flex',
                alignItems: 'center',
                gap: '8px',
                background: subTab === 'matrix' ? 'var(--accent-blue, #3b82f6)' : 'rgba(255,255,255,0.05)',
                color: 'white',
                transition: 'all 0.15s ease'
              }}
            >
              <Building2 size={16} />
              Mappatura Fornitori ↔ Categorie
            </button>

            <button
              onClick={() => setSubTab('categories')}
              style={{
                padding: '10px 18px',
                borderRadius: '8px',
                border: 'none',
                cursor: 'pointer',
                fontWeight: 600,
                fontSize: '0.9rem',
                display: 'flex',
                alignItems: 'center',
                gap: '8px',
                background: subTab === 'categories' ? 'var(--accent-blue, #3b82f6)' : 'rgba(255,255,255,0.05)',
                color: 'white',
                transition: 'all 0.15s ease'
              }}
            >
              <Boxes size={16} />
              Catalogo Categorie Master ({categories.length})
            </button>

            <button
              onClick={() => setSubTab('subcategories')}
              style={{
                padding: '10px 18px',
                borderRadius: '8px',
                border: 'none',
                cursor: 'pointer',
                fontWeight: 600,
                fontSize: '0.9rem',
                display: 'flex',
                alignItems: 'center',
                gap: '8px',
                background: subTab === 'subcategories' ? 'var(--accent-blue, #3b82f6)' : 'rgba(255,255,255,0.05)',
                color: 'white',
                transition: 'all 0.15s ease'
              }}
            >
              <Utensils size={16} />
              Sottocategorie Food & Reparti ({subcategories.length})
            </button>
          </div>

          {/* Action buttons on the right */}
          <div style={{ display: 'flex', alignItems: 'center', gap: '10px' }}>
            {subTab === 'matrix' && (
              <div style={{ display: 'flex', background: 'rgba(0,0,0,0.3)', borderRadius: '8px', padding: '3px', border: '1px solid var(--border-glass)' }}>
                <button
                  onClick={() => setViewMode('cards')}
                  title="Vista Schede"
                  style={{
                    background: viewMode === 'cards' ? 'rgba(255,255,255,0.15)' : 'transparent',
                    border: 'none',
                    borderRadius: '6px',
                    padding: '6px 10px',
                    color: 'white',
                    cursor: 'pointer',
                    display: 'flex',
                    alignItems: 'center',
                    gap: '6px',
                    fontSize: '0.8rem'
                  }}
                >
                  <LayoutGrid size={14} />
                  Schede
                </button>
                <button
                  onClick={() => setViewMode('table')}
                  title="Vista Griglia Matrice"
                  style={{
                    background: viewMode === 'table' ? 'rgba(255,255,255,0.15)' : 'transparent',
                    border: 'none',
                    borderRadius: '6px',
                    padding: '6px 10px',
                    color: 'white',
                    cursor: 'pointer',
                    display: 'flex',
                    alignItems: 'center',
                    gap: '6px',
                    fontSize: '0.8rem'
                  }}
                >
                  <Table size={14} />
                  Matrice
                </button>
              </div>
            )}

            {subTab === 'subcategories' && (
              <>
                <button
                  onClick={handleSeedFoodSubcategories}
                  disabled={actionLoading}
                  className="btn btn-secondary"
                  style={{ display: 'flex', alignItems: 'center', gap: '8px', fontSize: '0.85rem' }}
                  title="Carica le sottocategorie alimentari standard Ho.Re.Ca (Carni, Pesce, Latticini, Salumi, Surgelati, ecc.)"
                >
                  <Sparkles size={15} style={{ color: '#f59e0b' }} />
                  Carica Predefinite Food
                </button>
                <button
                  onClick={() => openSubcategoryModal()}
                  className="btn btn-primary"
                  style={{ display: 'flex', alignItems: 'center', gap: '8px', fontSize: '0.85rem' }}
                >
                  <Plus size={16} />
                  Nuova Sottocategoria
                </button>
              </>
            )}

            {subTab === 'categories' && (
              <>
                {categories.length === 0 && (
                  <button
                    onClick={handleSeedDefaults}
                    disabled={actionLoading}
                    className="btn btn-secondary"
                    style={{ display: 'flex', alignItems: 'center', gap: '8px', fontSize: '0.85rem' }}
                  >
                    <Sparkles size={15} style={{ color: '#f59e0b' }} />
                    Carica Categorie Ho.Re.Ca.
                  </button>
                )}

                <button
                  onClick={() => openCategoryModal()}
                  className="btn btn-primary"
                  style={{ display: 'flex', alignItems: 'center', gap: '8px', fontSize: '0.85rem' }}
                >
                  <Plus size={16} />
                  Nuova Categoria
                </button>
              </>
            )}

            <button
              onClick={() => {
                if (subTab === 'subcategories') loadSubcategories(subcatParentCategory);
                else loadData();
              }}
              disabled={loading || subcatLoading}
              title="Ricarica dati"
              style={{
                background: 'rgba(255,255,255,0.05)',
                border: '1px solid var(--border-glass)',
                borderRadius: '8px',
                padding: '9px 12px',
                color: 'var(--text-secondary)',
                cursor: 'pointer',
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'center'
              }}
            >
              <RefreshCw size={15} className={(loading || subcatLoading) ? 'animate-spin' : ''} />
            </button>
          </div>
        </div>

        {/* Search & Quick Filter Bar */}
        <div style={{ display: 'flex', gap: '14px', alignItems: 'center', flexWrap: 'wrap' }}>
          <div style={{ position: 'relative', flex: '1', minWidth: '240px' }}>
            <Search size={16} style={{ position: 'absolute', left: '12px', top: '50%', transform: 'translateY(-50%)', color: 'var(--text-secondary)' }} />
            <input
              type="text"
              placeholder={subTab === 'matrix' ? 'Cerca fornitore o P.IVA...' : subTab === 'categories' ? 'Cerca categoria...' : 'Cerca sottocategoria o descrizione...'}
              value={searchFilter}
              onChange={e => setSearchFilter(e.target.value)}
              style={{
                width: '100%',
                boxSizing: 'border-box',
                padding: '10px 12px 10px 38px',
                background: 'rgba(0,0,0,0.25)',
                border: '1px solid var(--border-glass)',
                borderRadius: '8px',
                color: 'white',
                fontSize: '0.85rem'
              }}
            />
          </div>

          {subTab === 'matrix' && (
            <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
              <Filter size={15} style={{ color: 'var(--text-secondary)' }} />
              <select
                value={selectedCategoryFilter}
                onChange={e => setSelectedCategoryFilter(e.target.value)}
                style={{
                  padding: '9px 12px',
                  background: '#13131c',
                  border: '1px solid var(--border-glass)',
                  borderRadius: '8px',
                  color: 'white',
                  fontSize: '0.85rem'
                }}
              >
                <option value="all">Tutti i settori merci</option>
                {categories.map(c => (
                  <option key={c.id} value={c.nome}>Filtra per: {c.nome}</option>
                ))}
              </select>
            </div>
          )}

          {subTab === 'subcategories' && (
            <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
              <span style={{ fontSize: '0.85rem', color: 'var(--text-secondary)', fontWeight: 500 }}>Categoria Padre:</span>
              <select
                value={subcatParentCategory}
                onChange={e => setSubcatParentCategory(e.target.value)}
                style={{
                  padding: '9px 12px',
                  background: '#13131c',
                  border: '1px solid var(--border-glass)',
                  borderRadius: '8px',
                  color: 'white',
                  fontSize: '0.85rem',
                  fontWeight: 600
                }}
              >
                <option value="Food">Food (Alimentari)</option>
                {categories.filter(c => c.nome.toLowerCase() !== 'food').map(c => (
                  <option key={c.id} value={c.nome}>{c.nome}</option>
                ))}
              </select>
            </div>
          )}
        </div>

        {/* ──────────────────────────────────────────────────────────── */}
        {/* SUBTAB 1: MAPPATURA FORNITORI ↔ CATEGORIE                    */}
        {/* ──────────────────────────────────────────────────────────── */}
        {subTab === 'matrix' && (
          <div>
            {loading ? (
              <div style={{ textAlign: 'center', padding: '60px 0', color: 'var(--text-secondary)' }}>
                <RefreshCw size={24} className="animate-spin" style={{ margin: '0 auto 12px' }} />
                Caricamento matrice fornitori...
              </div>
            ) : suppliers.length === 0 ? (
              <div style={{ textAlign: 'center', padding: '60px 0', color: 'var(--text-secondary)' }}>
                <Building2 size={36} style={{ margin: '0 auto 12px', opacity: 0.4 }} />
                <p style={{ margin: 0, fontSize: '1rem', fontWeight: 600 }}>Nessun fornitore registrato</p>
                <p style={{ margin: '6px 0 0', fontSize: '0.85rem' }}>Aggiungi prima i fornitori nella sezione Impostazioni / Fornitori.</p>
              </div>
            ) : categories.length === 0 ? (
              <div style={{ textAlign: 'center', padding: '60px 0', color: 'var(--text-secondary)' }}>
                <Boxes size={36} style={{ margin: '0 auto 12px', opacity: 0.4 }} />
                <p style={{ margin: 0, fontSize: '1rem', fontWeight: 600 }}>Nessuna categoria definita</p>
                <p style={{ margin: '6px 0 16px', fontSize: '0.85rem' }}>Carica le categorie standard per iniziare ad associarle ai tuoi fornitori.</p>
                <button onClick={handleSeedDefaults} className="btn btn-primary" style={{ margin: '0 auto' }}>
                  <Sparkles size={16} />
                  Carica Categorie Standard Ho.Re.Ca.
                </button>
              </div>
            ) : viewMode === 'cards' ? (
              /* CARDS VIEW */
              <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(360px, 1fr))', gap: '18px' }}>
                {filteredSuppliers.map(supplier => {
                  const enabledCount = Object.values(supplier.categories).filter(Boolean).length;
                  return (
                    <div 
                      key={supplier.supplier_id} 
                      className="glass-panel" 
                      style={{ 
                        padding: '20px', 
                        display: 'flex', 
                        flexDirection: 'column', 
                        gap: '16px',
                        border: '1px solid rgba(255,255,255,0.08)',
                        background: 'rgba(255,255,255,0.02)'
                      }}
                    >
                      {/* Supplier Card Header */}
                      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', gap: '10px' }}>
                        <div>
                          <div style={{ fontWeight: 700, fontSize: '1.05rem', color: 'white' }}>{supplier.supplier_name}</div>
                          <div style={{ fontSize: '0.78rem', color: 'var(--text-secondary)', marginTop: '2px' }}>
                            P.IVA: {supplier.partita_iva}
                          </div>
                        </div>
                        <span style={{
                          fontSize: '0.75rem',
                          padding: '3px 8px',
                          borderRadius: '12px',
                          background: enabledCount > 0 ? 'rgba(59,130,246,0.15)' : 'rgba(255,255,255,0.05)',
                          color: enabledCount > 0 ? '#3b82f6' : 'var(--text-secondary)',
                          fontWeight: 600
                        }}>
                          {enabledCount} {enabledCount === 1 ? 'settore' : 'settori'}
                        </span>
                      </div>

                      {/* Category Chips Toggle Grid */}
                      <div>
                        <div style={{ fontSize: '0.75rem', color: 'var(--text-secondary)', marginBottom: '8px', textTransform: 'uppercase', letterSpacing: '0.5px' }}>
                          Settori Merceologici Abilitati:
                        </div>
                        <div style={{ display: 'flex', flexWrap: 'wrap', gap: '6px' }}>
                          {categories.map(cat => {
                            const isEnabled = !!supplier.categories[cat.nome];
                            return (
                              <button
                                key={cat.id}
                                type="button"
                                onClick={() => handleToggleCapability(supplier.supplier_id, cat.nome, isEnabled)}
                                style={{
                                  padding: '5px 10px',
                                  borderRadius: '6px',
                                  fontSize: '0.78rem',
                                  cursor: 'pointer',
                                  border: isEnabled ? `1px solid ${cat.colore || '#3b82f6'}` : '1px solid rgba(255,255,255,0.1)',
                                  background: isEnabled ? `${cat.colore || '#3b82f6'}25` : 'rgba(0,0,0,0.2)',
                                  color: isEnabled ? '#ffffff' : 'rgba(255,255,255,0.4)',
                                  fontWeight: isEnabled ? 600 : 400,
                                  display: 'flex',
                                  alignItems: 'center',
                                  gap: '5px',
                                  transition: 'all 0.12s ease'
                                }}
                                title={isEnabled ? `Disabilita ${cat.nome}` : `Abilita ${cat.nome}`}
                              >
                                <span style={{
                                  width: '6px',
                                  height: '6px',
                                  borderRadius: '50%',
                                  background: isEnabled ? (cat.colore || '#3b82f6') : 'rgba(255,255,255,0.2)'
                                }} />
                                {cat.nome}
                                {isEnabled && <Check size={12} style={{ color: cat.colore || '#3b82f6' }} />}
                              </button>
                            );
                          })}
                        </div>
                      </div>

                      {/* Subcategories Breakdown for Enabled Categories */}
                      {categories.filter(cat => supplier.categories[cat.nome] && (subcategoriesByCategory[cat.nome]?.length || 0) > 0).map(cat => {
                        const catSubs = subcategoriesByCategory[cat.nome] || [];
                        const enabledSubs = supplier.subcategories?.[cat.nome] || [];
                        const allEnabledByDefault = enabledSubs.length === 0;

                        return (
                          <div
                            key={`subs-${supplier.supplier_id}-${cat.nome}`}
                            style={{
                              marginTop: '4px',
                              padding: '12px 14px',
                              background: 'rgba(0,0,0,0.25)',
                              borderRadius: '8px',
                              border: `1px solid ${cat.colore || '#3b82f6'}35`,
                              display: 'flex',
                              flexDirection: 'column',
                              gap: '8px'
                            }}
                          >
                            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', flexWrap: 'wrap', gap: '6px' }}>
                              <div style={{ display: 'flex', alignItems: 'center', gap: '6px', fontSize: '0.78rem', fontWeight: 600, color: cat.colore || '#3b82f6' }}>
                                <FolderTree size={14} />
                                <span>Sottocategorie {cat.nome}:</span>
                                <span style={{
                                  fontSize: '0.7rem',
                                  padding: '1px 7px',
                                  borderRadius: '10px',
                                  background: allEnabledByDefault ? 'rgba(255,255,255,0.08)' : `${cat.colore || '#3b82f6'}25`,
                                  color: allEnabledByDefault ? 'var(--text-secondary)' : 'white',
                                  fontWeight: 500
                                }}>
                                  {allEnabledByDefault ? 'Tutte (default)' : `${enabledSubs.length} di ${catSubs.length} attive`}
                                </span>
                              </div>

                              <div style={{ display: 'flex', gap: '8px', fontSize: '0.72rem' }}>
                                <button
                                  type="button"
                                  onClick={() => handleBulkSubcategories(supplier.supplier_id, cat.nome, true)}
                                  style={{ background: 'none', border: 'none', color: cat.colore || '#3b82f6', cursor: 'pointer', padding: 0 }}
                                >
                                  Tutte
                                </button>
                                <span style={{ color: 'rgba(255,255,255,0.2)' }}>•</span>
                                <button
                                  type="button"
                                  onClick={() => handleBulkSubcategories(supplier.supplier_id, cat.nome, false)}
                                  style={{ background: 'none', border: 'none', color: 'var(--text-secondary)', cursor: 'pointer', padding: 0 }}
                                  title="Deseleziona per abilitare tutte di default"
                                >
                                  Resetta
                                </button>
                              </div>
                            </div>

                            {/* Subcategory Pills */}
                            <div style={{ display: 'flex', flexWrap: 'wrap', gap: '6px' }}>
                              {catSubs.map(sub => {
                                const isSubEnabled = enabledSubs.some(s => s.toLowerCase() === sub.nome.toLowerCase());
                                return (
                                  <button
                                    key={sub.id}
                                    type="button"
                                    onClick={() => handleToggleSubcategory(supplier.supplier_id, cat.nome, sub.nome, isSubEnabled)}
                                    style={{
                                      padding: '4px 9px',
                                      borderRadius: '6px',
                                      fontSize: '0.74rem',
                                      cursor: 'pointer',
                                      border: isSubEnabled ? `1px solid ${cat.colore || '#3b82f6'}` : '1px solid rgba(255,255,255,0.08)',
                                      background: isSubEnabled ? `${cat.colore || '#3b82f6'}30` : 'rgba(255,255,255,0.02)',
                                      color: isSubEnabled ? '#ffffff' : 'rgba(255,255,255,0.5)',
                                      fontWeight: isSubEnabled ? 600 : 400,
                                      display: 'flex',
                                      alignItems: 'center',
                                      gap: '4px',
                                      transition: 'all 0.1s ease'
                                    }}
                                    title={isSubEnabled ? `Disabilita ${sub.nome}` : `Abilita ${sub.nome}`}
                                  >
                                    {isSubEnabled ? (
                                      <Check size={11} style={{ color: cat.colore || '#3b82f6' }} />
                                    ) : (
                                      <span style={{ width: '4px', height: '4px', borderRadius: '50%', background: 'rgba(255,255,255,0.2)' }} />
                                    )}
                                    {sub.nome}
                                  </button>
                                );
                              })}
                            </div>
                          </div>
                        );
                      })}

                      {/* Card Footer Quick Actions */}
                      <div style={{ display: 'flex', justifyContent: 'flex-end', gap: '8px', paddingTop: '10px', borderTop: '1px solid rgba(255,255,255,0.05)', fontSize: '0.75rem' }}>
                        <button
                          type="button"
                          onClick={() => handleBulkSupplierCategories(supplier.supplier_id, true)}
                          style={{ background: 'none', border: 'none', color: '#0ea5e9', cursor: 'pointer', padding: 0 }}
                        >
                          Abilita tutte
                        </button>
                        <span style={{ color: 'var(--border-glass)' }}>•</span>
                        <button
                          type="button"
                          onClick={() => handleBulkSupplierCategories(supplier.supplier_id, false)}
                          style={{ background: 'none', border: 'none', color: 'var(--text-secondary)', cursor: 'pointer', padding: 0 }}
                        >
                          Deseleziona tutte
                        </button>
                      </div>
                    </div>
                  );
                })}
              </div>
            ) : (
              /* MATRIX TABLE VIEW */
              <div style={{ overflowX: 'auto', borderRadius: '8px', border: '1px solid var(--border-glass)' }}>
                <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: '0.82rem', textAlign: 'left' }}>
                  <thead>
                    <tr style={{ background: 'rgba(0,0,0,0.4)', borderBottom: '1px solid var(--border-glass)' }}>
                      <th style={{ padding: '12px 16px', position: 'sticky', left: 0, background: '#101018', zIndex: 2, minWidth: '200px' }}>
                        Fornitore
                      </th>
                      {categories.map(cat => (
                        <th 
                          key={cat.id} 
                          style={{ 
                            padding: '12px 10px', 
                            textAlign: 'center', 
                            whiteSpace: 'nowrap',
                            color: cat.colore || 'white'
                          }}
                        >
                          {cat.nome}
                        </th>
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    {filteredSuppliers.map((supplier, idx) => (
                      <tr 
                        key={supplier.supplier_id} 
                        style={{ 
                          borderBottom: '1px solid rgba(255,255,255,0.05)',
                          background: idx % 2 === 0 ? 'transparent' : 'rgba(255,255,255,0.01)'
                        }}
                      >
                        <td style={{ padding: '12px 16px', position: 'sticky', left: 0, background: '#101018', zIndex: 1 }}>
                          <div style={{ fontWeight: 600, color: 'white' }}>{supplier.supplier_name}</div>
                          <div style={{ fontSize: '0.72rem', color: 'var(--text-secondary)' }}>{supplier.partita_iva}</div>
                        </td>
                        {categories.map(cat => {
                          const isEnabled = !!supplier.categories[cat.nome];
                          return (
                            <td key={cat.id} style={{ padding: '12px 10px', textAlign: 'center' }}>
                              <button
                                type="button"
                                onClick={() => handleToggleCapability(supplier.supplier_id, cat.nome, isEnabled)}
                                style={{
                                  width: '26px',
                                  height: '26px',
                                  borderRadius: '6px',
                                  border: isEnabled ? `1px solid ${cat.colore || '#3b82f6'}` : '1px solid rgba(255,255,255,0.1)',
                                  background: isEnabled ? `${cat.colore || '#3b82f6'}30` : 'transparent',
                                  color: isEnabled ? (cat.colore || '#3b82f6') : 'transparent',
                                  cursor: 'pointer',
                                  display: 'inline-flex',
                                  alignItems: 'center',
                                  justifyContent: 'center',
                                  transition: 'all 0.1s ease'
                                }}
                              >
                                {isEnabled ? <Check size={14} /> : <span style={{ width: '4px', height: '4px', borderRadius: '50%', background: 'rgba(255,255,255,0.2)' }} />}
                              </button>
                            </td>
                          );
                        })}
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </div>
        )}

        {/* ──────────────────────────────────────────────────────────── */}
        {/* SUBTAB 2: CATALOGO CATEGORIE MASTER                          */}
        {/* ──────────────────────────────────────────────────────────── */}
        {subTab === 'categories' && (
          <div>
            {loading ? (
              <div style={{ textAlign: 'center', padding: '60px 0', color: 'var(--text-secondary)' }}>
                <RefreshCw size={24} className="animate-spin" style={{ margin: '0 auto 12px' }} />
                Caricamento categorie...
              </div>
            ) : categories.length === 0 ? (
              <div style={{ textAlign: 'center', padding: '60px 0', color: 'var(--text-secondary)' }}>
                <Boxes size={36} style={{ margin: '0 auto 12px', opacity: 0.4 }} />
                <p style={{ margin: 0, fontSize: '1rem', fontWeight: 600 }}>Nessuna categoria creata</p>
                <p style={{ margin: '6px 0 16px', fontSize: '0.85rem' }}>Puoi caricare la suite completa Ho.Re.Ca. o crearne una su misura.</p>
                <button onClick={handleSeedDefaults} className="btn btn-primary" style={{ margin: '0 auto' }}>
                  <Sparkles size={16} />
                  Carica Categorie Standard Ho.Re.Ca.
                </button>
              </div>
            ) : (
              <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(320px, 1fr))', gap: '16px' }}>
                {filteredCategories.map(cat => (
                  <div 
                    key={cat.id} 
                    className="glass-panel" 
                    style={{ 
                      padding: '18px 20px', 
                      display: 'flex', 
                      flexDirection: 'column', 
                      justifyContent: 'space-between',
                      gap: '14px',
                      borderLeft: `4px solid ${cat.colore || '#3b82f6'}`,
                      background: 'rgba(255,255,255,0.02)'
                    }}
                  >
                    <div>
                      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', gap: '8px' }}>
                        <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                          <span style={{ width: '10px', height: '10px', borderRadius: '50%', background: cat.colore || '#3b82f6' }} />
                          <div style={{ fontWeight: 700, fontSize: '1rem', color: 'white' }}>{cat.nome}</div>
                        </div>

                        <div style={{ display: 'flex', gap: '6px' }}>
                          <button
                            type="button"
                            onClick={() => openCategoryModal(cat)}
                            title="Modifica categoria"
                            style={{
                              background: 'rgba(255,255,255,0.05)',
                              border: '1px solid var(--border-glass)',
                              borderRadius: '6px',
                              padding: '5px',
                              color: 'var(--text-secondary)',
                              cursor: 'pointer'
                            }}
                          >
                            <Pencil size={13} />
                          </button>
                          <button
                            type="button"
                            onClick={() => handleDeleteCategory(cat)}
                            title="Elimina categoria"
                            style={{
                              background: 'rgba(239,68,68,0.1)',
                              border: '1px solid rgba(239,68,68,0.2)',
                              borderRadius: '6px',
                              padding: '5px',
                              color: 'var(--status-red, #ef4444)',
                              cursor: 'pointer'
                            }}
                          >
                            <Trash2 size={13} />
                          </button>
                        </div>
                      </div>

                      {cat.descrizione && (
                        <p style={{ margin: '8px 0 0', fontSize: '0.8rem', color: 'var(--text-secondary)', lineHeight: 1.4 }}>
                          {cat.descrizione}
                        </p>
                      )}
                    </div>

                    <div style={{ display: 'flex', gap: '16px', paddingTop: '10px', borderTop: '1px solid rgba(255,255,255,0.05)', fontSize: '0.78rem', color: 'var(--text-secondary)' }}>
                      <div>
                        <strong>{cat.supplier_count}</strong> {cat.supplier_count === 1 ? 'fornitore abilitato' : 'fornitori abilitati'}
                      </div>
                      <div>
                        <strong>{cat.product_count}</strong> {cat.product_count === 1 ? 'prodotto a listino' : 'prodotti a listino'}
                      </div>
                    </div>
                  </div>
                ))}
              </div>
            )}
          </div>
        )}

        {/* ──────────────────────────────────────────────────────────── */}
        {/* SUBTAB 3: SOTTOCATEGORIE FOOD & REPARTI                      */}
        {/* ──────────────────────────────────────────────────────────── */}
        {subTab === 'subcategories' && (
          <div style={{ display: 'flex', flexDirection: 'column', gap: '20px' }}>
            {/* Info Banner */}
            <div style={{
              padding: '16px 20px',
              borderRadius: '12px',
              background: 'linear-gradient(135deg, rgba(239, 68, 68, 0.08), rgba(245, 158, 11, 0.08))',
              border: '1px solid rgba(245, 158, 11, 0.25)',
              display: 'flex',
              justifyContent: 'space-between',
              alignItems: 'center',
              flexWrap: 'wrap',
              gap: '14px'
            }}>
              <div>
                <div style={{ display: 'flex', alignItems: 'center', gap: '8px', fontWeight: 700, fontSize: '1.05rem', color: '#f59e0b' }}>
                  <Utensils size={18} />
                  Suddivisione Sottocategorie & Reparti: {subcatParentCategory}
                </div>
                <p style={{ margin: '4px 0 0', fontSize: '0.84rem', color: 'var(--text-secondary)' }}>
                  Organizza i prodotti alimentari in sottocategorie personalizzate (Carni, Ittico, Latticini, Salumi, Surgelati, ecc.) per facilitare la gestione ordini, listini e catalogazione.
                </p>
              </div>

              <div style={{ display: 'flex', gap: '10px', alignItems: 'center' }}>
                <button
                  onClick={handleSeedFoodSubcategories}
                  disabled={actionLoading}
                  className="btn btn-secondary"
                  style={{ display: 'flex', alignItems: 'center', gap: '8px', fontSize: '0.84rem' }}
                >
                  <Sparkles size={15} style={{ color: '#f59e0b' }} />
                  Carica Predefinite Food Ho.Re.Ca.
                </button>
                <button
                  onClick={() => openSubcategoryModal()}
                  className="btn btn-primary"
                  style={{ display: 'flex', alignItems: 'center', gap: '8px', fontSize: '0.84rem' }}
                >
                  <Plus size={16} />
                  Nuova Sottocategoria
                </button>
              </div>
            </div>

            {/* Content Cards */}
            {subcatLoading ? (
              <div style={{ textAlign: 'center', padding: '60px 0', color: 'var(--text-secondary)' }}>
                <RefreshCw size={24} className="animate-spin" style={{ margin: '0 auto 12px' }} />
                Caricamento sottocategorie in corso...
              </div>
            ) : filteredSubcategories.length === 0 ? (
              <div style={{ textAlign: 'center', padding: '60px 20px', color: 'var(--text-secondary)', display: 'flex', flexDirection: 'column', alignItems: 'center', gap: '14px' }}>
                <FolderTree size={40} style={{ opacity: 0.3 }} />
                <div>
                  <h4 style={{ margin: '0 0 6px', color: 'white', fontSize: '1.1rem' }}>Nessuna sottocategoria trovata</h4>
                  <p style={{ margin: 0, fontSize: '0.85rem' }}>
                    Non hai ancora creato sottocategorie per <strong>{subcatParentCategory}</strong> oppure i filtri applicati non producono risultati.
                  </p>
                </div>
                <div style={{ display: 'flex', gap: '12px', marginTop: '10px' }}>
                  <button
                    onClick={handleSeedFoodSubcategories}
                    disabled={actionLoading}
                    className="btn btn-primary"
                    style={{ display: 'flex', alignItems: 'center', gap: '8px', fontSize: '0.85rem' }}
                  >
                    <Sparkles size={16} />
                    Inizializza Sottocategorie Predefinite Food
                  </button>
                  <button
                    onClick={() => openSubcategoryModal()}
                    className="btn btn-secondary"
                    style={{ display: 'flex', alignItems: 'center', gap: '8px', fontSize: '0.85rem' }}
                  >
                    <Plus size={16} />
                    Crea Manualmente
                  </button>
                </div>
              </div>
            ) : (
              <div style={{
                display: 'grid',
                gridTemplateColumns: 'repeat(auto-fill, minmax(300px, 1fr))',
                gap: '16px'
              }}>
                {filteredSubcategories.map(sub => (
                  <div
                    key={sub.id}
                    style={{
                      background: 'rgba(255,255,255,0.03)',
                      border: '1px solid var(--border-glass)',
                      borderRadius: '12px',
                      padding: '18px',
                      display: 'flex',
                      flexDirection: 'column',
                      justifyContent: 'space-between',
                      gap: '14px',
                      transition: 'all 0.15s ease'
                    }}
                  >
                    <div>
                      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', gap: '10px' }}>
                        <div style={{ display: 'flex', alignItems: 'center', gap: '10px' }}>
                          <div style={{
                            width: '36px',
                            height: '36px',
                            borderRadius: '8px',
                            background: 'rgba(245, 158, 11, 0.15)',
                            color: '#f59e0b',
                            display: 'flex',
                            alignItems: 'center',
                            justifyContent: 'center'
                          }}>
                            <Tag size={18} />
                          </div>
                          <div>
                            <h4 style={{ margin: 0, fontSize: '1rem', fontWeight: 600, color: 'white' }}>
                              {sub.nome}
                            </h4>
                            <span style={{ fontSize: '0.75rem', color: 'var(--text-secondary)' }}>
                              Categoria: {sub.categoria_nome}
                            </span>
                          </div>
                        </div>

                        <div style={{ display: 'flex', gap: '6px' }}>
                          <button
                            type="button"
                            onClick={() => openSubcategoryModal(sub)}
                            title="Modifica sottocategoria"
                            style={{
                              background: 'rgba(255,255,255,0.05)',
                              border: '1px solid var(--border-glass)',
                              borderRadius: '6px',
                              padding: '6px',
                              color: 'var(--text-secondary)',
                              cursor: 'pointer'
                            }}
                          >
                            <Pencil size={13} />
                          </button>
                          <button
                            type="button"
                            onClick={() => handleDeleteSubcategory(sub)}
                            title="Elimina sottocategoria"
                            style={{
                              background: 'rgba(239,68,68,0.1)',
                              border: '1px solid rgba(239,68,68,0.2)',
                              borderRadius: '6px',
                              padding: '6px',
                              color: 'var(--status-red, #ef4444)',
                              cursor: 'pointer'
                            }}
                          >
                            <Trash2 size={13} />
                          </button>
                        </div>
                      </div>

                      {sub.descrizione && (
                        <p style={{ margin: '10px 0 0', fontSize: '0.82rem', color: 'var(--text-secondary)', lineHeight: 1.4 }}>
                          {sub.descrizione}
                        </p>
                      )}
                    </div>

                    <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', paddingTop: '10px', borderTop: '1px solid rgba(255,255,255,0.05)', fontSize: '0.8rem' }}>
                      <div style={{ display: 'flex', alignItems: 'center', gap: '6px', color: 'var(--text-secondary)' }}>
                        <Boxes size={14} />
                        <span><strong>{sub.product_count}</strong> {sub.product_count === 1 ? 'prodotto associato' : 'prodotti associati'}</span>
                      </div>

                      <button
                        type="button"
                        onClick={() => handleToggleSubcatActive(sub)}
                        style={{
                          background: sub.is_active ? 'rgba(16,185,129,0.15)' : 'rgba(255,255,255,0.05)',
                          border: `1px solid ${sub.is_active ? 'rgba(16,185,129,0.3)' : 'var(--border-glass)'}`,
                          borderRadius: '6px',
                          padding: '3px 8px',
                          color: sub.is_active ? 'var(--status-green, #10b981)' : 'var(--text-secondary)',
                          fontSize: '0.75rem',
                          fontWeight: 600,
                          cursor: 'pointer'
                        }}
                      >
                        {sub.is_active ? 'Attiva' : 'Disattivata'}
                      </button>
                    </div>
                  </div>
                ))}
              </div>
            )}
          </div>
        )}
      </div>

      {/* ──────────────────────────────────────────────────────────── */}
      {/* MODAL: NUOVA / MODIFICA CATEGORIA                            */}
      {/* ──────────────────────────────────────────────────────────── */}
      {showCatModal && (
        <div style={{
          position: 'fixed',
          inset: 0,
          background: 'rgba(0,0,0,0.75)',
          zIndex: 1100,
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
          padding: '20px'
        }}>
          <div className="glass-panel" style={{ width: '100%', maxWidth: '500px', padding: '28px', display: 'flex', flexDirection: 'column', gap: '20px', border: '1px solid rgba(255,255,255,0.15)' }}>
            
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
              <h3 style={{ margin: 0, fontSize: '1.2rem', fontWeight: 700 }}>
                {editingCategory ? 'Modifica Categoria' : 'Nuova Categoria Master'}
              </h3>
              <button 
                type="button" 
                onClick={() => setShowCatModal(false)}
                style={{ background: 'none', border: 'none', color: 'var(--text-secondary)', cursor: 'pointer' }}
              >
                <X size={20} />
              </button>
            </div>

            <form onSubmit={handleSaveCategory} style={{ display: 'flex', flexDirection: 'column', gap: '16px' }}>
              
              <label style={{ display: 'flex', flexDirection: 'column', gap: '6px', fontSize: '0.82rem', color: 'var(--text-secondary)' }}>
                Nome Categoria *
                <input
                  type="text"
                  required
                  placeholder="Es. Beverage, Birre, Packaging, Carni..."
                  value={catFormNome}
                  onChange={e => setCatFormNome(e.target.value)}
                  style={{
                    padding: '11px',
                    background: 'rgba(0,0,0,0.25)',
                    border: '1px solid var(--border-glass)',
                    borderRadius: '8px',
                    color: 'white'
                  }}
                />
              </label>

              <label style={{ display: 'flex', flexDirection: 'column', gap: '6px', fontSize: '0.82rem', color: 'var(--text-secondary)' }}>
                Descrizione facoltativa
                <textarea
                  rows={2}
                  placeholder="Note sul tipo di prodotti inclusi in questa categoria..."
                  value={catFormDesc}
                  onChange={e => setCatFormDesc(e.target.value)}
                  style={{
                    padding: '11px',
                    background: 'rgba(0,0,0,0.25)',
                    border: '1px solid var(--border-glass)',
                    borderRadius: '8px',
                    color: 'white',
                    resize: 'vertical'
                  }}
                />
              </label>

              {/* Color Presets */}
              <div style={{ display: 'flex', flexDirection: 'column', gap: '8px' }}>
                <span style={{ fontSize: '0.82rem', color: 'var(--text-secondary)' }}>Colore Identificativo</span>
                <div style={{ display: 'flex', flexWrap: 'wrap', gap: '8px' }}>
                  {COLOR_PRESETS.map(preset => (
                    <button
                      key={preset.value}
                      type="button"
                      onClick={() => setCatFormColor(preset.value)}
                      style={{
                        width: '28px',
                        height: '28px',
                        borderRadius: '50%',
                        background: preset.value,
                        border: catFormColor === preset.value ? '3px solid white' : '2px solid transparent',
                        cursor: 'pointer',
                        transform: catFormColor === preset.value ? 'scale(1.15)' : 'scale(1)',
                        transition: 'transform 0.1s ease'
                      }}
                      title={preset.label}
                    />
                  ))}
                </div>
              </div>

              <div style={{ display: 'flex', justifyContent: 'flex-end', gap: '10px', marginTop: '10px' }}>
                <button 
                  type="button" 
                  className="btn btn-secondary" 
                  disabled={actionLoading} 
                  onClick={() => setShowCatModal(false)}
                >
                  Annulla
                </button>
                <button 
                  type="submit" 
                  className="btn btn-primary" 
                  disabled={actionLoading}
                >
                  {actionLoading ? <RefreshCw className="animate-spin" size={16} /> : <Check size={16} />}
                  {editingCategory ? 'Aggiorna Categoria' : 'Crea Categoria'}
                </button>
              </div>
            </form>
          </div>
        </div>
      )}

      {/* ──────────────────────────────────────────────────────────── */}
      {/* MODAL: NUOVA / MODIFICA SOTTOCATEGORIA                       */}
      {/* ──────────────────────────────────────────────────────────── */}
      {showSubcatModal && (
        <div style={{
          position: 'fixed',
          inset: 0,
          background: 'rgba(0,0,0,0.75)',
          zIndex: 1100,
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
          padding: '20px'
        }}>
          <div className="glass-panel" style={{ width: '100%', maxWidth: '480px', padding: '28px', display: 'flex', flexDirection: 'column', gap: '20px', border: '1px solid rgba(255,255,255,0.15)' }}>
            
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: '10px' }}>
                <div style={{ width: '36px', height: '36px', borderRadius: '8px', background: 'rgba(245, 158, 11, 0.15)', color: '#f59e0b', display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
                  <Utensils size={18} />
                </div>
                <h3 style={{ margin: 0, fontSize: '1.15rem', fontWeight: 700 }}>
                  {editingSubcat ? 'Modifica Sottocategoria' : `Nuova Sottocategoria ${subcatParentCategory}`}
                </h3>
              </div>
              <button 
                type="button" 
                onClick={() => setShowSubcatModal(false)}
                style={{ background: 'none', border: 'none', color: 'var(--text-secondary)', cursor: 'pointer' }}
              >
                <X size={20} />
              </button>
            </div>

            <form onSubmit={handleSaveSubcategory} style={{ display: 'flex', flexDirection: 'column', gap: '16px' }}>
              
              <label style={{ display: 'flex', flexDirection: 'column', gap: '6px', fontSize: '0.82rem', color: 'var(--text-secondary)' }}>
                Categoria Padre
                <input
                  type="text"
                  disabled
                  value={subcatParentCategory}
                  style={{
                    padding: '11px',
                    background: 'rgba(255,255,255,0.05)',
                    border: '1px solid var(--border-glass)',
                    borderRadius: '8px',
                    color: '#93c5fd',
                    fontWeight: 600
                  }}
                />
              </label>

              <label style={{ display: 'flex', flexDirection: 'column', gap: '6px', fontSize: '0.82rem', color: 'var(--text-secondary)' }}>
                Nome Sottocategoria *
                <input
                  type="text"
                  required
                  placeholder="Es. Carni & Hamburger, Ittico, Latticini, Surgelati, Salumi..."
                  value={subcatFormNome}
                  onChange={e => setSubcatFormNome(e.target.value)}
                  style={{
                    padding: '11px',
                    background: 'rgba(0,0,0,0.25)',
                    border: '1px solid var(--border-glass)',
                    borderRadius: '8px',
                    color: 'white'
                  }}
                />
              </label>

              <label style={{ display: 'flex', flexDirection: 'column', gap: '6px', fontSize: '0.82rem', color: 'var(--text-secondary)' }}>
                Descrizione o Note
                <textarea
                  rows={2}
                  placeholder="Descrivi la tipologia di prodotti compresi in questo raggruppamento..."
                  value={subcatFormDesc}
                  onChange={e => setSubcatFormDesc(e.target.value)}
                  style={{
                    padding: '11px',
                    background: 'rgba(0,0,0,0.25)',
                    border: '1px solid var(--border-glass)',
                    borderRadius: '8px',
                    color: 'white',
                    resize: 'vertical'
                  }}
                />
              </label>

              <label style={{ display: 'flex', alignItems: 'center', gap: '10px', fontSize: '0.85rem', color: 'white', cursor: 'pointer' }}>
                <input
                  type="checkbox"
                  checked={subcatFormIsActive}
                  onChange={e => setSubcatFormIsActive(e.target.checked)}
                  style={{ width: '16px', height: '16px', accentColor: '#10b981' }}
                />
                Sottocategoria attiva e visibile nei listini e ordini
              </label>

              <div style={{ display: 'flex', justifyContent: 'flex-end', gap: '10px', marginTop: '10px' }}>
                <button 
                  type="button" 
                  className="btn btn-secondary" 
                  disabled={actionLoading} 
                  onClick={() => setShowSubcatModal(false)}
                >
                  Annulla
                </button>
                <button 
                  type="submit" 
                  className="btn btn-primary" 
                  disabled={actionLoading}
                >
                  {actionLoading ? <RefreshCw className="animate-spin" size={16} /> : <Check size={16} />}
                  {editingSubcat ? 'Aggiorna Sottocategoria' : 'Crea Sottocategoria'}
                </button>
              </div>
            </form>
          </div>
        </div>
      )}

    </div>
  );
}
