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
  X
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

interface SupplierMatrixRow {
  supplier_id: number;
  supplier_name: string;
  partita_iva: string;
  attivo_whitelist: boolean;
  categories: Record<string, boolean>;
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
  const [subTab, setSubTab] = useState<'matrix' | 'categories'>('matrix');
  const [viewMode, setViewMode] = useState<'cards' | 'table'>('cards');
  const [loading, setLoading] = useState(true);
  const [actionLoading, setActionLoading] = useState(false);
  const [message, setMessage] = useState<{ text: string; type: 'success' | 'error' } | null>(null);

  // Data states
  const [categories, setCategories] = useState<CategoryItem[]>([]);
  const [suppliers, setSuppliers] = useState<SupplierMatrixRow[]>([]);
  const [searchFilter, setSearchFilter] = useState('');
  const [selectedCategoryFilter, setSelectedCategoryFilter] = useState<string>('all');

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
      const res = await fetch(`${API_BASE}/categories/matrix`, { headers });
      if (!res.ok) throw new Error('Errore nel caricamento della matrice categorie');
      const data = await res.json();
      setCategories(data.categories || []);
      setSuppliers(data.suppliers || []);
    } catch (err: any) {
      console.error(err);
      setMessage({ text: err.message || 'Errore di connessione', type: 'error' });
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    loadData();
  }, []);

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

            <button
              onClick={loadData}
              disabled={loading}
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
              <RefreshCw size={15} className={loading ? 'animate-spin' : ''} />
            </button>
          </div>
        </div>

        {/* Search & Quick Filter Bar */}
        <div style={{ display: 'flex', gap: '14px', alignItems: 'center', flexWrap: 'wrap' }}>
          <div style={{ position: 'relative', flex: '1', minWidth: '240px' }}>
            <Search size={16} style={{ position: 'absolute', left: '12px', top: '50%', transform: 'translateY(-50%)', color: 'var(--text-secondary)' }} />
            <input
              type="text"
              placeholder={subTab === 'matrix' ? 'Cerca fornitore o P.IVA...' : 'Cerca categoria...'}
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

    </div>
  );
}
