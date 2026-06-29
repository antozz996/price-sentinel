import { useState, useEffect } from 'react';
import { EyeOff, Search, ShieldAlert, Plus, Eye, Loader2 } from 'lucide-react';
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
  const [selectedSku, setSelectedSku] = useState<SkuItem | null>(null);
  const [dropdownOpen, setDropdownOpen] = useState(false);
  const [message, setMessage] = useState<{ text: string; type: 'success' | 'error' } | null>(null);
  const [submitting, setSubmitting] = useState(false);

  useEffect(() => {
    loadData();
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
    } catch (err) {
      console.error('Error loading data', err);
    } finally {
      setLoading(false);
    }
  };

  const handleExclude = async (sku: string) => {
    if (!sku) return;
    setSubmitting(true);
    setMessage(null);
    try {
      await fetchWithAuth('/sku/excluded', {
        method: 'POST',
        body: JSON.stringify({ sku_interno: sku })
      });
      setMessage({ text: `SKU '${sku}' escluso con successo dalle analisi.`, type: 'success' });
      setSelectedSku(null);
      setSearchQuery('');
      loadData();
    } catch (err: any) {
      setMessage({ text: err.message || 'Errore durante l\'esclusione dello SKU', type: 'error' });
    } finally {
      setSubmitting(false);
    }
  };

  const handleRestore = async (sku: string) => {
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

  // Filter available SKUs based on search input
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
              <h3 style={{ margin: 0, fontSize: '1.2rem', fontWeight: 600 }}>Esclusione Prodotti</h3>
              <p style={{ margin: '4px 0 0 0', fontSize: '0.85rem', color: 'var(--text-secondary)' }}>
                Aggiungi o rimuovi SKU dalla blacklist globale per escluderli da anomalie, grafici e statistiche.
              </p>
            </div>
          </div>
        </div>

        {/* Input area */}
        <div style={{ display: 'flex', gap: '12px', alignItems: 'center', position: 'relative', flexWrap: 'wrap' }}>
          <div style={{ position: 'relative', flex: 1, minWidth: '280px' }}>
            <Search size={18} style={{ position: 'absolute', left: '12px', top: '50%', transform: 'translateY(-50%)', color: 'var(--text-secondary)' }} />
            <input
              type="text"
              placeholder="Cerca prodotto o SKU da escludere..."
              value={searchQuery}
              onChange={(e) => {
                setSearchQuery(e.target.value);
                setDropdownOpen(true);
                setSelectedSku(null);
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
            {/* Search Dropdown */}
            {dropdownOpen && searchQuery.length > 0 && (
              <div style={{
                position: 'absolute',
                top: '100%',
                left: 0,
                right: 0,
                marginTop: '6px',
                maxHeight: '220px',
                overflowY: 'auto',
                background: 'rgba(15, 15, 23, 0.95)',
                backdropFilter: 'blur(10px)',
                border: '1px solid var(--border-glass)',
                borderRadius: '8px',
                boxShadow: '0 10px 25px rgba(0,0,0,0.5)',
                zIndex: 999
              }}>
                {filteredAvailable.length > 0 ? (
                  filteredAvailable.map((s) => (
                    <div
                      key={`avail-${s.sku_interno}`}
                      onClick={() => {
                        setSelectedSku(s);
                        setSearchQuery(`${s.nome_prodotto || s.sku_interno} (${s.sku_interno})`);
                        setDropdownOpen(false);
                      }}
                      style={{
                        padding: '10px 14px',
                        cursor: 'pointer',
                        borderBottom: '1px solid rgba(255,255,255,0.03)',
                        transition: 'background 0.2s',
                        display: 'flex',
                        flexDirection: 'column',
                        gap: '2px'
                      }}
                      className="dropdown-item-hover"
                    >
                      <span style={{ fontWeight: 500, fontSize: '0.9rem' }}>{s.nome_prodotto || 'Prodotto senza nome'}</span>
                      <span style={{ fontSize: '0.75rem', color: 'var(--text-secondary)', fontFamily: 'monospace' }}>SKU: {s.sku_interno}</span>
                    </div>
                  ))
                ) : (
                  <div style={{ padding: '14px', color: 'var(--text-secondary)', fontSize: '0.85rem', textAlign: 'center' }}>
                    Nessun prodotto disponibile trovato
                  </div>
                )}
              </div>
            )}
          </div>
          <button
            onClick={() => selectedSku && handleExclude(selectedSku.sku_interno)}
            disabled={!selectedSku || submitting}
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
              cursor: !selectedSku ? 'not-allowed' : 'pointer',
              opacity: !selectedSku ? 0.5 : 1
            }}
          >
            {submitting ? <Loader2 size={16} className="animate-spin" /> : <Plus size={18} />}
            Escludi Prodotto
          </button>
        </div>
      </div>

      {/* Blacklist Table panel */}
      <div className="glass-panel" style={{ padding: '24px' }}>
        <h4 style={{ margin: '0 0 16px 0', fontSize: '1rem', fontWeight: 600, display: 'flex', alignItems: 'center', gap: '8px' }}>
          <ShieldAlert size={18} style={{ color: 'var(--status-red)' }} /> Prodotti Attualmente Esclusi ({excludedList.length})
        </h4>

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
                  <th style={{ padding: '12px 10px', fontWeight: 500 }}>SKU</th>
                  <th style={{ padding: '12px 10px', fontWeight: 500 }}>Data Esclusione</th>
                  <th style={{ padding: '12px 10px', fontWeight: 500, textAlign: 'right' }}>Azioni</th>
                </tr>
              </thead>
              <tbody>
                {excludedList.map((item) => {
                  const dateStr = new Date(item.created_at).toLocaleDateString('it-IT', {
                    day: '2-digit',
                    month: '2-digit',
                    year: 'numeric',
                    hour: '2-digit',
                    minute: '2-digit'
                  });
                  return (
                    <tr key={`ex-${item.sku_interno}`} style={{ borderBottom: '1px solid rgba(255,255,255,0.03)' }} className="table-row-hover">
                      <td style={{ padding: '12px 10px', fontFamily: 'monospace', fontWeight: 600 }}>{item.sku_interno}</td>
                      <td style={{ padding: '12px 10px', color: 'var(--text-secondary)', fontSize: '0.85rem' }}>{dateStr}</td>
                      <td style={{ padding: '12px 10px', textAlign: 'right' }}>
                        <button
                          onClick={() => handleRestore(item.sku_interno)}
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
