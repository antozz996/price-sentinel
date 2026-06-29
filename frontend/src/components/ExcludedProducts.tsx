import { useState, useEffect, useRef } from 'react';
import { EyeOff, Search, ShieldAlert, Plus, Eye, Loader2, X, RotateCcw } from 'lucide-react';
import { fetchWithAuth } from '../api';

interface ExcludedSku {
  sku_interno: string;
  created_at: string;
}

interface SkuItem {
  sku_interno: string;
  nome_prodotto: string;
}

export default function ExcludedProducts() {
  const [excludedList, setExcludedList] = useState<ExcludedSku[]>([]);
  const [availableSkus, setAvailableSkus] = useState<SkuItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [searchQuery, setSearchQuery] = useState('');
  const [dropdownOpen, setDropdownOpen] = useState(false);
  const [message, setMessage] = useState<{ text: string; type: 'success' | 'error' } | null>(null);
  const [submitting, setSubmitting] = useState(false);

  // Multi-selection states
  const [selectedToExclude, setSelectedToExclude] = useState<SkuItem[]>([]);
  const [selectedToRestore, setSelectedToRestore] = useState<string[]>([]);

  const searchContainerRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    loadData();

    // Close dropdown on outside click
    function handleClickOutside(event: MouseEvent) {
      if (searchContainerRef.current && !searchContainerRef.current.contains(event.target as Node)) {
        setDropdownOpen(false);
      }
    }
    document.addEventListener('mousedown', handleClickOutside);
    return () => {
      document.removeEventListener('mousedown', handleClickOutside);
    };
  }, []);

  const loadData = async () => {
    try {
      setLoading(true);
      const [excluded, allSkus] = await Promise.all([
        fetchWithAuth('/sku/excluded'),
        fetchWithAuth('/sku')
      ]);
      
      if (Array.isArray(excluded)) {
        setExcludedList(excluded);
      }
      if (Array.isArray(allSkus)) {
        setAvailableSkus(allSkus);
      }
      setSelectedToRestore([]); // Reset selection on reload
    } catch (err) {
      console.error('Error loading data', err);
    } finally {
      setLoading(false);
    }
  };

  const handleToggleProductToExclude = (skuItem: SkuItem) => {
    const isSelected = selectedToExclude.some(item => item.sku_interno === skuItem.sku_interno);
    if (isSelected) {
      setSelectedToExclude(selectedToExclude.filter(item => item.sku_interno !== skuItem.sku_interno));
    } else {
      setSelectedToExclude([...selectedToExclude, skuItem]);
    }
  };

  const handleRemoveProductToExclude = (sku: string) => {
    setSelectedToExclude(selectedToExclude.filter(item => item.sku_interno !== sku));
  };

  const handleBulkExclude = async () => {
    if (selectedToExclude.length === 0) return;
    setSubmitting(true);
    setMessage(null);
    try {
      await Promise.all(
        selectedToExclude.map(item =>
          fetchWithAuth('/sku/excluded', {
            method: 'POST',
            body: JSON.stringify({ sku_interno: item.sku_interno })
          })
        )
      );
      setMessage({
        text: `Esclusi con successo ${selectedToExclude.length} prodotti dalle analisi.`,
        type: 'success'
      });
      setSelectedToExclude([]);
      loadData();
    } catch (err: any) {
      setMessage({ text: err.message || 'Errore durante l\'esclusione dei prodotti', type: 'error' });
    } finally {
      setSubmitting(false);
    }
  };

  const handleSingleRestore = async (sku: string) => {
    setSubmitting(true);
    setMessage(null);
    try {
      await fetchWithAuth(`/sku/excluded/${sku}`, {
        method: 'DELETE'
      });
      setMessage({ text: `SKU '${sku}' ripristinato con successo.`, type: 'success' });
      loadData();
    } catch (err: any) {
      setMessage({ text: err.message || 'Errore durante il ripristino dello SKU', type: 'error' });
    } finally {
      setSubmitting(false);
    }
  };

  const handleBulkRestore = async () => {
    if (selectedToRestore.length === 0) return;
    setSubmitting(true);
    setMessage(null);
    try {
      await Promise.all(
        selectedToRestore.map(sku =>
          fetchWithAuth(`/sku/excluded/${sku}`, {
            method: 'DELETE'
          })
        )
      );
      setMessage({
        text: `Ripristinati con successo ${selectedToRestore.length} prodotti.`,
        type: 'success'
      });
      loadData();
    } catch (err: any) {
      setMessage({ text: err.message || 'Errore durante il ripristino dei prodotti', type: 'error' });
    } finally {
      setSubmitting(false);
    }
  };

  const handleSelectAllRestore = (checked: boolean) => {
    if (checked) {
      setSelectedToRestore(excludedList.map(item => item.sku_interno));
    } else {
      setSelectedToRestore([]);
    }
  };

  const handleToggleRestoreSelect = (sku: string, checked: boolean) => {
    if (checked) {
      setSelectedToRestore([...selectedToRestore, sku]);
    } else {
      setSelectedToRestore(selectedToRestore.filter(s => s !== sku));
    }
  };

  // Filter available SKUs based on search input (selected ones remain visible in dropdown)
  const filteredAvailable = availableSkus.filter(s =>
    s.sku_interno.toLowerCase().includes(searchQuery.toLowerCase()) ||
    (s.nome_prodotto && s.nome_prodotto.toLowerCase().includes(searchQuery.toLowerCase()))
  );

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: '24px' }}>
      {message && (
        <div style={{
          padding: '16px',
          borderRadius: '12px',
          background: message.type === 'success' ? 'var(--status-green-bg)' : 'var(--status-red-bg)',
          color: message.type === 'success' ? '#10b981' : '#ef4444',
          border: `1px solid ${message.type === 'success' ? 'rgba(16, 185, 129, 0.2)' : 'rgba(239, 68, 68, 0.2)'}`,
          fontSize: '0.9rem'
        }}>
          {message.text}
        </div>
      )}

      {/* Main card */}
      <div className="glass-panel" style={{ padding: '24px', display: 'flex', flexDirection: 'column', gap: '20px', position: 'relative', zIndex: 10 }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', flexWrap: 'wrap', gap: '16px' }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: '12px' }}>
            <div style={{ padding: '10px', borderRadius: '12px', background: 'rgba(239, 68, 68, 0.1)', color: 'var(--status-red)' }}>
              <EyeOff size={24} />
            </div>
            <div>
              <h3 style={{ margin: 0, fontSize: '1.2rem', fontWeight: 600 }}>Esclusione Prodotti (Selezione Multipla)</h3>
              <p style={{ margin: '4px 0 0 0', fontSize: '0.85rem', color: 'var(--text-secondary)' }}>
                Cerca e spunta più prodotti direttamente dal menu a tendina, quindi applica l'esclusione globale in blocco.
              </p>
            </div>
          </div>
        </div>

        {/* Input area */}
        <div style={{ display: 'flex', gap: '12px', alignItems: 'center', position: 'relative', flexWrap: 'wrap' }}>
          <div ref={searchContainerRef} style={{ position: 'relative', flex: 1, minWidth: '280px' }}>
            <Search size={18} style={{ position: 'absolute', left: '12px', top: '50%', transform: 'translateY(-50%)', color: 'var(--text-secondary)' }} />
            <input
              type="text"
              placeholder="Cerca e spunta prodotti da escludere..."
              value={searchQuery}
              onChange={(e) => {
                setSearchQuery(e.target.value);
                setDropdownOpen(true);
              }}
              onFocus={() => setDropdownOpen(true)}
              style={{
                width: '100%',
                boxSizing: 'border-box',
                padding: '12px 12px 12px 38px',
                background: 'rgba(255,255,255,0.03)',
                border: '1px solid var(--border-glass)',
                borderRadius: '8px',
                color: 'white',
                outline: 'none',
                fontSize: '0.9rem',
                transition: 'var(--transition-smooth)'
              }}
            />
            {/* Search Dropdown with Checkboxes */}
            {dropdownOpen && searchQuery.length > 0 && (
              <div style={{
                position: 'absolute',
                top: '100%',
                left: 0,
                right: 0,
                marginTop: '6px',
                maxHeight: '250px',
                overflowY: 'auto',
                background: 'rgba(15, 15, 23, 0.98)',
                backdropFilter: 'blur(10px)',
                border: '1px solid var(--border-glass)',
                borderRadius: '8px',
                boxShadow: '0 10px 25px rgba(0,0,0,0.5)',
                zIndex: 999
              }}>
                {filteredAvailable.length > 0 ? (
                  filteredAvailable.map((s) => {
                    const isSelected = selectedToExclude.some(item => item.sku_interno === s.sku_interno);
                    return (
                      <div
                        key={`avail-${s.sku_interno}`}
                        onClick={() => handleToggleProductToExclude(s)}
                        style={{
                          padding: '10px 14px',
                          cursor: 'pointer',
                          borderBottom: '1px solid rgba(255,255,255,0.03)',
                          transition: 'background 0.2s',
                          display: 'flex',
                          alignItems: 'center',
                          gap: '12px',
                          background: isSelected ? 'rgba(239, 68, 68, 0.05)' : 'transparent'
                        }}
                        className="dropdown-item-hover"
                      >
                        <input
                          type="checkbox"
                          checked={isSelected}
                          onChange={() => {}} // Handled by outer container click
                          style={{ cursor: 'pointer', accentColor: 'var(--status-red)' }}
                        />
                        <div style={{ display: 'flex', flexDirection: 'column', gap: '2px', flex: 1 }}>
                          <span style={{ fontWeight: 500, fontSize: '0.9rem', color: isSelected ? 'white' : 'var(--text-secondary)' }}>
                            {s.nome_prodotto || 'Prodotto senza nome'}
                          </span>
                          <span style={{ fontSize: '0.75rem', color: 'var(--text-secondary)', fontFamily: 'monospace' }}>SKU: {s.sku_interno}</span>
                        </div>
                      </div>
                    );
                  })
                ) : (
                  <div style={{ padding: '14px', color: 'var(--text-secondary)', fontSize: '0.85rem', textAlign: 'center' }}>
                    Nessun prodotto disponibile trovato
                  </div>
                )}
              </div>
            )}
          </div>
          <button
            onClick={handleBulkExclude}
            disabled={selectedToExclude.length === 0 || submitting}
            className="btn btn-primary"
            style={{
              padding: '12px 24px',
              height: '45px',
              display: 'inline-flex',
              alignItems: 'center',
              gap: '8px',
              fontSize: '0.9rem',
              backgroundColor: 'var(--status-red)',
              borderColor: 'var(--status-red)',
              cursor: selectedToExclude.length === 0 ? 'not-allowed' : 'pointer',
              opacity: selectedToExclude.length === 0 ? 0.5 : 1
            }}
          >
            {submitting ? <Loader2 size={16} className="animate-spin" /> : <Plus size={18} />}
            Escludi Selezionati ({selectedToExclude.length})
          </button>
        </div>

        {/* Selected products tags to exclude */}
        {selectedToExclude.length > 0 && (
          <div style={{ display: 'flex', flexWrap: 'wrap', gap: '10px', marginTop: '8px', padding: '12px', background: 'rgba(255,255,255,0.01)', border: '1px solid var(--border-glass)', borderRadius: '8px' }}>
            {selectedToExclude.map(item => (
              <div
                key={`to-ex-${item.sku_interno}`}
                style={{
                  display: 'inline-flex',
                  alignItems: 'center',
                  gap: '8px',
                  background: 'rgba(239, 68, 68, 0.08)',
                  border: '1px solid rgba(239, 68, 68, 0.25)',
                  borderRadius: '999px',
                  padding: '6px 14px',
                  fontSize: '0.85rem',
                  color: 'white'
                }}
              >
                <span style={{ fontWeight: 500 }}>{item.nome_prodotto || item.sku_interno}</span>
                <span style={{ fontSize: '0.75rem', opacity: 0.6 }}>({item.sku_interno})</span>
                <button
                  onClick={() => handleRemoveProductToExclude(item.sku_interno)}
                  style={{
                    background: 'transparent',
                    border: 'none',
                    color: 'var(--text-secondary)',
                    cursor: 'pointer',
                    display: 'flex',
                    alignItems: 'center',
                    justifyContent: 'center',
                    padding: 0
                  }}
                  onMouseEnter={e => e.currentTarget.style.color = '#fff'}
                  onMouseLeave={e => e.currentTarget.style.color = 'var(--text-secondary)'}
                >
                  <X size={14} />
                </button>
              </div>
            ))}
          </div>
        )}
      </div>

      {/* Blacklist Table panel */}
      <div className="glass-panel" style={{ padding: '24px' }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '16px', flexWrap: 'wrap', gap: '12px' }}>
          <h4 style={{ margin: 0, fontSize: '1rem', fontWeight: 600, display: 'flex', alignItems: 'center', gap: '8px' }}>
            <ShieldAlert size={18} style={{ color: 'var(--status-red)' }} /> Prodotti Attualmente Esclusi ({excludedList.length})
          </h4>
          
          {selectedToRestore.length > 0 && (
            <button
              onClick={handleBulkRestore}
              disabled={submitting}
              className="btn btn-primary"
              style={{
                padding: '8px 16px',
                fontSize: '0.85rem',
                backgroundColor: 'rgba(16, 185, 129, 0.2)',
                borderColor: 'rgba(16, 185, 129, 0.3)',
                color: '#10b981',
                display: 'inline-flex',
                alignItems: 'center',
                gap: '6px'
              }}
            >
              {submitting ? <Loader2 size={14} className="animate-spin" /> : <RotateCcw size={14} />}
              Ripristina Selezionati ({selectedToRestore.length})
            </button>
          )}
        </div>

        {loading ? (
          <div style={{ padding: '40px', display: 'flex', justifyContent: 'center', alignItems: 'center', color: 'var(--text-secondary)' }}>
            <Loader2 size={24} className="animate-spin" style={{ marginRight: '8px' }} /> Caricamento blacklist...
          </div>
        ) : excludedList.length === 0 ? (
          <div style={{ padding: '40px', textAlign: 'center', color: 'var(--text-secondary)', background: 'rgba(255,255,255,0.01)', border: '1px dashed var(--border-glass)', borderRadius: '12px' }}>
            <Eye size={36} style={{ marginBottom: '8px', opacity: 0.3 }} />
            <p style={{ margin: 0, fontSize: '0.9rem' }}>Nessun prodotto è attualmente escluso dal sistema.</p>
          </div>
        ) : (
          <div style={{ overflowX: 'auto' }}>
            <table className="table" style={{ width: '100%', borderCollapse: 'collapse' }}>
              <thead>
                <tr style={{ borderBottom: '1px solid var(--border-glass)', textAlign: 'left' }}>
                  <th style={{ padding: '12px 10px', width: '40px' }}>
                    <input
                      type="checkbox"
                      checked={selectedToRestore.length === excludedList.length && excludedList.length > 0}
                      onChange={(e) => handleSelectAllRestore(e.target.checked)}
                      style={{ cursor: 'pointer' }}
                    />
                  </th>
                  <th style={{ padding: '12px 10px', fontWeight: 500 }}>SKU</th>
                  <th style={{ padding: '12px 10px', fontWeight: 500 }}>Data Esclusione</th>
                  <th style={{ padding: '12px 10px', fontWeight: 500, textAlign: 'right' }}>Azioni</th>
                </tr>
              </thead>
              <tbody>
                {excludedList.map((item) => {
                  const isChecked = selectedToRestore.includes(item.sku_interno);
                  const dateStr = new Date(item.created_at).toLocaleDateString('it-IT', {
                    day: '2-digit',
                    month: '2-digit',
                    year: 'numeric',
                    hour: '2-digit',
                    minute: '2-digit'
                  });
                  return (
                    <tr key={`ex-${item.sku_interno}`} style={{ borderBottom: '1px solid rgba(255,255,255,0.03)' }} className="table-row-hover">
                      <td style={{ padding: '12px 10px' }}>
                        <input
                          type="checkbox"
                          checked={isChecked}
                          onChange={(e) => handleToggleRestoreSelect(item.sku_interno, e.target.checked)}
                          style={{ cursor: 'pointer' }}
                        />
                      </td>
                      <td style={{ padding: '12px 10px', fontFamily: 'monospace', fontWeight: 600 }}>{item.sku_interno}</td>
                      <td style={{ padding: '12px 10px', color: 'var(--text-secondary)', fontSize: '0.85rem' }}>{dateStr}</td>
                      <td style={{ padding: '12px 10px', textAlign: 'right' }}>
                        <button
                          onClick={() => handleSingleRestore(item.sku_interno)}
                          disabled={submitting}
                          style={{
                            background: 'rgba(16, 185, 129, 0.1)',
                            border: '1px solid rgba(16, 185, 129, 0.2)',
                            color: '#10b981',
                            padding: '6px 12px',
                            borderRadius: '6px',
                            fontSize: '0.8rem',
                            cursor: 'pointer',
                            display: 'inline-flex',
                            alignItems: 'center',
                            gap: '4px',
                            transition: 'var(--transition-smooth)'
                          }}
                          className="btn-restore-hover"
                        >
                          <Eye size={14} /> Ripristina
                        </button>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </div>
  );
}
