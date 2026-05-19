import { useState, useEffect } from 'react';
import { Tag, Edit2, Search, Check, X } from 'lucide-react';
import { fetchWithAuth } from '../api';

interface SkuItem {
  sku_interno: string;
  nome_prodotto: string;
  total_acquisti: number;
}

export default function SkuManager() {
  const [skus, setSkus] = useState<SkuItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [search, setSearch] = useState('');
  
  const [editingSku, setEditingSku] = useState<string | null>(null);
  const [newSkuName, setNewSkuName] = useState('');
  const [message, setMessage] = useState<{ text: string, type: 'success' | 'error' } | null>(null);
  const [submitting, setSubmitting] = useState(false);

  useEffect(() => {
    loadSkus();
  }, []);

  async function loadSkus() {
    try {
      setLoading(true);
      const data = await fetchWithAuth('/sku');
      if (Array.isArray(data)) {
        setSkus(data);
      }
    } catch (err) {
      console.error("Error loading SKUs", err);
    } finally {
      setLoading(false);
    }
  }

  const handleRename = async (oldSku: string) => {
    if (!newSkuName.trim() || newSkuName.trim() === oldSku) {
      setEditingSku(null);
      return;
    }

    setSubmitting(true);
    setMessage(null);
    try {
      await fetchWithAuth('/sku/rename', {
        method: 'PUT',
        body: JSON.stringify({ old_sku: oldSku, new_sku: newSkuName.trim() })
      });
      
      setMessage({ text: 'SKU rinominato con successo!', type: 'success' });
      setEditingSku(null);
      loadSkus();
    } catch (err: any) {
      setMessage({ text: err.message || 'Errore durante la ridenominazione', type: 'error' });
    } finally {
      setSubmitting(false);
    }
  };

  const filteredSkus = skus.filter(s => 
    s.sku_interno.toLowerCase().includes(search.toLowerCase()) || 
    (s.nome_prodotto && s.nome_prodotto.toLowerCase().includes(search.toLowerCase()))
  );

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: '24px' }}>
      {message && (
        <div style={{ 
          padding: '16px', 
          borderRadius: '12px', 
          background: message.type === 'success' ? 'var(--status-green-bg)' : 'var(--status-red-bg)',
          color: message.type === 'success' ? '#10b981' : '#ef4444',
          border: `1px solid ${message.type === 'success' ? 'rgba(16, 185, 129, 0.2)' : 'rgba(239, 68, 68, 0.2)'}`
        }}>
          {message.text}
        </div>
      )}

      <div className="glass-panel" style={{ padding: '24px', display: 'flex', flexDirection: 'column', gap: '20px' }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: '12px' }}>
            <div style={{ padding: '10px', borderRadius: '12px', background: 'rgba(59, 130, 246, 0.1)', color: 'var(--accent-blue)' }}>
              <Tag size={24} />
            </div>
            <div>
              <h3 style={{ margin: 0, fontSize: '1.2rem', fontWeight: 600 }}>Gestione SKU Catalogo</h3>
              <p style={{ margin: '4px 0 0 0', fontSize: '0.85rem', color: 'var(--text-secondary)' }}>
                Visualizza e rinomina gli SKU interni. Le modifiche si applicheranno a tutte le fatture e listini passati.
              </p>
            </div>
          </div>
          
          <div style={{ position: 'relative', width: '300px' }}>
            <Search size={18} style={{ position: 'absolute', left: '12px', top: '50%', transform: 'translateY(-50%)', color: 'var(--text-secondary)' }} />
            <input 
              type="text" 
              placeholder="Cerca SKU o Prodotto..." 
              value={search}
              onChange={e => setSearch(e.target.value)}
              style={{
                width: '100%', padding: '10px 12px 10px 38px', borderRadius: '8px',
                border: '1px solid var(--border-glass)', background: 'rgba(255,255,255,0.03)',
                color: 'white', outline: 'none', boxSizing: 'border-box'
              }}
            />
          </div>
        </div>

        <div style={{ overflowX: 'auto', borderRadius: '8px', border: '1px solid rgba(255,255,255,0.05)' }}>
          <table style={{ width: '100%', borderCollapse: 'collapse' }}>
            <thead>
              <tr style={{ background: 'rgba(255,255,255,0.02)', color: 'var(--text-secondary)', fontSize: '0.8rem', textAlign: 'left' }}>
                <th style={{ padding: '16px', borderBottom: '1px solid rgba(255,255,255,0.05)' }}>Codice SKU Interno</th>
                <th style={{ padding: '16px', borderBottom: '1px solid rgba(255,255,255,0.05)' }}>Nome Prodotto (Riferimento)</th>
                <th style={{ padding: '16px', textAlign: 'center', borderBottom: '1px solid rgba(255,255,255,0.05)' }}>Volumi Acquisto</th>
                <th style={{ padding: '16px', textAlign: 'right', borderBottom: '1px solid rgba(255,255,255,0.05)' }}>Azioni</th>
              </tr>
            </thead>
            <tbody>
              {loading ? (
                <tr><td colSpan={4} style={{ padding: '24px', textAlign: 'center' }}>Caricamento in corso...</td></tr>
              ) : filteredSkus.length === 0 ? (
                <tr><td colSpan={4} style={{ padding: '24px', textAlign: 'center', color: 'var(--text-secondary)' }}>Nessuno SKU trovato.</td></tr>
              ) : (
                filteredSkus.map(s => (
                  <tr key={s.sku_interno} style={{ borderBottom: '1px solid rgba(255,255,255,0.02)', transition: 'background 0.2s' }}>
                    <td style={{ padding: '16px', fontWeight: 600 }}>
                      {editingSku === s.sku_interno ? (
                        <input
                          type="text"
                          value={newSkuName}
                          onChange={e => setNewSkuName(e.target.value)}
                          autoFocus
                          style={{
                            width: '100%', padding: '8px', borderRadius: '6px',
                            border: '1px solid var(--accent-blue)', background: 'rgba(255,255,255,0.1)',
                            color: 'white', outline: 'none', boxSizing: 'border-box'
                          }}
                        />
                      ) : (
                        <span style={{ color: 'var(--accent-blue)', background: 'rgba(59, 130, 246, 0.1)', padding: '4px 8px', borderRadius: '6px', fontSize: '0.9rem' }}>
                          {s.sku_interno}
                        </span>
                      )}
                    </td>
                    <td style={{ padding: '16px', color: 'var(--text-secondary)' }}>{s.nome_prodotto || 'N/A'}</td>
                    <td style={{ padding: '16px', textAlign: 'center' }}>
                      <span style={{ background: 'rgba(255,255,255,0.05)', padding: '4px 10px', borderRadius: '12px', fontSize: '0.8rem' }}>
                        {s.total_acquisti} acquisti
                      </span>
                    </td>
                    <td style={{ padding: '16px', textAlign: 'right' }}>
                      {editingSku === s.sku_interno ? (
                        <div style={{ display: 'flex', gap: '8px', justifyContent: 'flex-end' }}>
                          <button 
                            onClick={() => handleRename(s.sku_interno)}
                            disabled={submitting}
                            style={{ background: '#10b981', color: 'white', border: 'none', padding: '6px', borderRadius: '6px', cursor: 'pointer', display: 'flex', alignItems: 'center' }}
                            title="Salva"
                          >
                            <Check size={16} />
                          </button>
                          <button 
                            onClick={() => setEditingSku(null)}
                            disabled={submitting}
                            style={{ background: 'rgba(255,255,255,0.1)', color: 'white', border: 'none', padding: '6px', borderRadius: '6px', cursor: 'pointer', display: 'flex', alignItems: 'center' }}
                            title="Annulla"
                          >
                            <X size={16} />
                          </button>
                        </div>
                      ) : (
                        <button 
                          onClick={() => { setEditingSku(s.sku_interno); setNewSkuName(s.sku_interno); }}
                          style={{ background: 'transparent', color: 'var(--text-secondary)', border: '1px solid rgba(255,255,255,0.1)', padding: '6px 12px', borderRadius: '6px', cursor: 'pointer', display: 'flex', alignItems: 'center', gap: '6px', marginLeft: 'auto', transition: 'all 0.2s' }}
                          onMouseEnter={e => { e.currentTarget.style.color = 'white'; e.currentTarget.style.background = 'rgba(255,255,255,0.05)'; }}
                          onMouseLeave={e => { e.currentTarget.style.color = 'var(--text-secondary)'; e.currentTarget.style.background = 'transparent'; }}
                        >
                          <Edit2 size={14} /> Rinomina
                        </button>
                      )}
                    </td>
                  </tr>
                ))
              )}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}
