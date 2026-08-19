import { useState, useEffect, useMemo } from 'react';
import {
  ShoppingCart,
  Search,
  Truck,
  RefreshCw,
  Eye,
  Copy,
  Check,
  X,
  Package,
  Layers,
  Send
} from 'lucide-react';
import { API_BASE, getHeaders } from '../api';

interface OrderItemSummary {
  id: number;
  fornitore_id: number;
  fornitore_nome: string;
  location_id: number;
  location_nome: string;
  user_id: number | null;
  user_nome: string;
  user_ruolo: string | null;
  settore: string;
  data_ordine: string;
  data_consegna: string | null;
  note: string | null;
  whatsapp_message: string | null;
  spesa_totale: number;
  stato: string;
  n_righe: number;
  totale_colli: number;
}

interface OrderDetailRow {
  id: number;
  product_id: number | null;
  sku_interno: string;
  descrizione: string;
  quantita: number;
  uom: string;
  prezzo_pattuito: number;
  prezzo_inserito: number;
  subtotale: number;
  stato_ottimizzazione: string;
}

interface OrderDetailResponse extends OrderItemSummary {
  fornitore_piva: string | null;
  righe: OrderDetailRow[];
}

export default function OrderRegistry(props?: { isAdmin?: boolean; selectedOrderId?: number | null; onOrderClose?: () => void }) {
  const [orders, setOrders] = useState<OrderItemSummary[]>([]);
  const [loading, setLoading] = useState(true);
  const [search, setSearch] = useState('');
  const [selectedLocation, setSelectedLocation] = useState<string>('all');
  const [selectedSector, setSelectedSector] = useState<string>('all');
  const [selectedStatus, setSelectedStatus] = useState<string>('all');
  const [locations, setLocations] = useState<{ id: number; nome_struttura: string }[]>([]);

  // Selected order for detailed modal
  const [activeOrderDetail, setActiveOrderDetail] = useState<OrderDetailResponse | null>(null);
  const [copiedText, setCopiedText] = useState(false);

  const headers = getHeaders();

  useEffect(() => {
    loadLocations();
    loadOrders();
  }, []);

  useEffect(() => {
    if (props?.selectedOrderId) {
      handleOpenDetail(props.selectedOrderId);
    }
  }, [props?.selectedOrderId]);

  const loadLocations = async () => {
    try {
      const res = await fetch(`${API_BASE}/location/`, { headers });
      if (res.ok) {
        const data = await res.json();
        setLocations(data);
      }
    } catch (e) {
      console.error(e);
    }
  };

  const loadOrders = async () => {
    setLoading(true);
    try {
      const params = new URLSearchParams();
      if (selectedLocation !== 'all') params.append('location_id', selectedLocation);
      if (selectedSector !== 'all') params.append('settore', selectedSector);
      if (selectedStatus !== 'all') params.append('stato', selectedStatus);
      if (search.trim()) params.append('search', search.trim());

      const res = await fetch(`${API_BASE}/ordini/?${params.toString()}`, { headers });
      if (res.ok) {
        const data = await res.json();
        setOrders(data);
      }
    } catch (e) {
      console.error(e);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    loadOrders();
  }, [selectedLocation, selectedSector, selectedStatus]);

  const handleOpenDetail = async (orderId: number) => {
    try {
      const res = await fetch(`${API_BASE}/ordini/${orderId}`, { headers });
      if (res.ok) {
        const data = await res.json();
        setActiveOrderDetail(data);
      }
    } catch (e) {
      console.error(e);
    }
  };

  const handleCloseModal = () => {
    setActiveOrderDetail(null);
    if (props?.onOrderClose) props.onOrderClose();
  };

  const handleCopyMessage = (text: string) => {
    navigator.clipboard.writeText(text);
    setCopiedText(true);
    setTimeout(() => setCopiedText(false), 2500);
  };

  // KPIs
  const totalSpend = useMemo(() => orders.reduce((sum, o) => sum + (o.spesa_totale || 0), 0), [orders]);
  const totalPackages = useMemo(() => orders.reduce((sum, o) => sum + (o.totale_colli || 0), 0), [orders]);
  const totalSuppliersCount = useMemo(() => new Set(orders.map(o => o.fornitore_id)).size, [orders]);

  const getSectorBadge = (settore: string) => {
    const s = (settore || '').toLowerCase();
    if (s.includes('beverage')) return { bg: 'rgba(59, 130, 246, 0.15)', color: '#60a5fa', label: '🍹 Beverage' };
    if (s.includes('food')) return { bg: 'rgba(16, 185, 129, 0.15)', color: '#34d399', label: '🍽️ Food' };
    if (s.includes('material')) return { bg: 'rgba(245, 158, 11, 0.15)', color: '#fbbf24', label: '📦 Materiali' };
    return { bg: 'rgba(255, 255, 255, 0.08)', color: '#e2e8f0', label: settore || 'Generico' };
  };

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: '24px' }}>
      
      {/* Top Header & Overview KPIs */}
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(220px, 1fr))', gap: '16px' }}>
        <div className="glass-panel" style={{ padding: '18px 20px', display: 'flex', alignItems: 'center', gap: '14px' }}>
          <div style={{ width: '44px', height: '44px', borderRadius: '12px', background: 'rgba(59, 130, 246, 0.15)', color: 'var(--accent-blue)', display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
            <ShoppingCart size={22} />
          </div>
          <div>
            <div style={{ color: 'var(--text-secondary)', fontSize: '0.8rem', fontWeight: 600 }}>Ordini Registrati</div>
            <div style={{ fontSize: '1.4rem', fontWeight: 800, color: 'white' }}>{orders.length}</div>
          </div>
        </div>

        <div className="glass-panel" style={{ padding: '18px 20px', display: 'flex', alignItems: 'center', gap: '14px' }}>
          <div style={{ width: '44px', height: '44px', borderRadius: '12px', background: 'rgba(16, 185, 129, 0.15)', color: 'var(--status-green)', display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
            <Package size={22} />
          </div>
          <div>
            <div style={{ color: 'var(--text-secondary)', fontSize: '0.8rem', fontWeight: 600 }}>Valore Totale Ordinato</div>
            <div style={{ fontSize: '1.4rem', fontWeight: 800, color: 'white' }}>€ {totalSpend.toFixed(2)}</div>
          </div>
        </div>

        <div className="glass-panel" style={{ padding: '18px 20px', display: 'flex', alignItems: 'center', gap: '14px' }}>
          <div style={{ width: '44px', height: '44px', borderRadius: '12px', background: 'rgba(245, 158, 11, 0.15)', color: '#f59e0b', display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
            <Layers size={22} />
          </div>
          <div>
            <div style={{ color: 'var(--text-secondary)', fontSize: '0.8rem', fontWeight: 600 }}>Totale Colli Ordinati</div>
            <div style={{ fontSize: '1.4rem', fontWeight: 800, color: 'white' }}>{totalPackages}</div>
          </div>
        </div>

        <div className="glass-panel" style={{ padding: '18px 20px', display: 'flex', alignItems: 'center', gap: '14px' }}>
          <div style={{ width: '44px', height: '44px', borderRadius: '12px', background: 'rgba(139, 92, 246, 0.15)', color: '#a78bfa', display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
            <Truck size={22} />
          </div>
          <div>
            <div style={{ color: 'var(--text-secondary)', fontSize: '0.8rem', fontWeight: 600 }}>Fornitori Coinvolti</div>
            <div style={{ fontSize: '1.4rem', fontWeight: 800, color: 'white' }}>{totalSuppliersCount}</div>
          </div>
        </div>
      </div>

      {/* Filters Bar */}
      <div className="glass-panel" style={{ padding: '16px 20px', display: 'flex', gap: '12px', flexWrap: 'wrap', alignItems: 'center', justifyContent: 'space-between' }}>
        <div style={{ display: 'flex', gap: '12px', flexWrap: 'wrap', alignItems: 'center', flex: 1, minWidth: '300px' }}>
          {/* Fast Search */}
          <div style={{ position: 'relative', flex: 1, minWidth: '220px' }}>
            <Search size={16} style={{ position: 'absolute', left: '12px', top: '50%', transform: 'translateY(-50%)', color: 'var(--text-secondary)' }} />
            <input
              type="text"
              placeholder="Cerca ordine, fornitore, sede o operatore..."
              value={search}
              onChange={e => setSearch(e.target.value)}
              onKeyDown={e => e.key === 'Enter' && loadOrders()}
              style={{
                width: '100%',
                boxSizing: 'border-box',
                padding: '9px 12px 9px 36px',
                background: 'rgba(0,0,0,0.3)',
                border: '1px solid var(--border-glass)',
                borderRadius: '8px',
                color: 'white',
                fontSize: '0.88rem',
                outline: 'none'
              }}
            />
          </div>

          {/* Location Filter */}
          <select
            value={selectedLocation}
            onChange={e => setSelectedLocation(e.target.value)}
            style={{
              padding: '9px 12px',
              background: 'rgba(0,0,0,0.3)',
              border: '1px solid var(--border-glass)',
              borderRadius: '8px',
              color: 'white',
              fontSize: '0.85rem',
              outline: 'none',
              cursor: 'pointer'
            }}
          >
            <option value="all" style={{ background: '#13131c' }}>Tutte le sedi</option>
            {locations.map(loc => (
              <option key={loc.id} value={loc.id} style={{ background: '#13131c' }}>
                {loc.nome_struttura}
              </option>
            ))}
          </select>

          {/* Sector Filter */}
          <select
            value={selectedSector}
            onChange={e => setSelectedSector(e.target.value)}
            style={{
              padding: '9px 12px',
              background: 'rgba(0,0,0,0.3)',
              border: '1px solid var(--border-glass)',
              borderRadius: '8px',
              color: 'white',
              fontSize: '0.85rem',
              outline: 'none',
              cursor: 'pointer'
            }}
          >
            <option value="all" style={{ background: '#13131c' }}>Tutti i reparti</option>
            <option value="Beverage" style={{ background: '#13131c' }}>🍹 Beverage</option>
            <option value="Materiali di consumo" style={{ background: '#13131c' }}>📦 Materiali di consumo</option>
            <option value="Food" style={{ background: '#13131c' }}>🍽️ Food</option>
          </select>

          {/* Status Filter */}
          <select
            value={selectedStatus}
            onChange={e => setSelectedStatus(e.target.value)}
            style={{
              padding: '9px 12px',
              background: 'rgba(0,0,0,0.3)',
              border: '1px solid var(--border-glass)',
              borderRadius: '8px',
              color: 'white',
              fontSize: '0.85rem',
              outline: 'none',
              cursor: 'pointer'
            }}
          >
            <option value="all" style={{ background: '#13131c' }}>Tutti gli stati</option>
            <option value="inviato" style={{ background: '#13131c' }}>Inviato</option>
            <option value="consegnato" style={{ background: '#13131c' }}>Consegnato</option>
            <option value="riconciliato" style={{ background: '#13131c' }}>Riconciliato</option>
          </select>
        </div>

        <button
          onClick={loadOrders}
          className="btn"
          style={{ background: 'rgba(255,255,255,0.03)', border: '1px solid var(--border-glass)', fontSize: '0.85rem', display: 'flex', alignItems: 'center', gap: '6px' }}
        >
          <RefreshCw size={14} className={loading ? 'spinner' : ''} />
          Aggiorna
        </button>
      </div>

      {/* Orders Table */}
      <div className="glass-panel" style={{ padding: '0', overflow: 'hidden' }}>
        {loading ? (
          <div style={{ padding: '60px', textAlign: 'center', color: 'var(--text-secondary)' }}>
            <RefreshCw className="spinner" size={28} style={{ margin: '0 auto 12px' }} />
            <div>Caricamento registro ordini in corso...</div>
          </div>
        ) : orders.length === 0 ? (
          <div style={{ padding: '60px 20px', textAlign: 'center', color: 'var(--text-secondary)' }}>
            <ShoppingCart size={42} style={{ margin: '0 auto 12px', opacity: 0.4 }} />
            <h3 style={{ margin: '0 0 6px', color: 'white' }}>Nessun ordine trovato</h3>
            <p style={{ fontSize: '0.85rem', margin: 0 }}>
              Non sono ancora stati registrati ordini corrispondenti ai filtri selezionati.
            </p>
          </div>
        ) : (
          <div style={{ overflowX: 'auto' }}>
            <table style={{ width: '100%', borderCollapse: 'collapse', textAlign: 'left', fontSize: '0.85rem' }}>
              <thead>
                <tr style={{ background: 'rgba(255,255,255,0.03)', borderBottom: '1px solid var(--border-glass)', color: 'var(--text-secondary)' }}>
                  <th style={{ padding: '14px 18px', fontWeight: 700 }}>ID Ordine</th>
                  <th style={{ padding: '14px 18px', fontWeight: 700 }}>Data Creazione</th>
                  <th style={{ padding: '14px 18px', fontWeight: 700 }}>Sede</th>
                  <th style={{ padding: '14px 18px', fontWeight: 700 }}>Reparto</th>
                  <th style={{ padding: '14px 18px', fontWeight: 700 }}>Fornitore Destinatario</th>
                  <th style={{ padding: '14px 18px', fontWeight: 700 }}>Operatore</th>
                  <th style={{ padding: '14px 18px', fontWeight: 700, textAlign: 'center' }}>Articoli / Colli</th>
                  <th style={{ padding: '14px 18px', fontWeight: 700, textAlign: 'right' }}>Totale Stimato</th>
                  <th style={{ padding: '14px 18px', fontWeight: 700, textAlign: 'center' }}>Stato</th>
                  <th style={{ padding: '14px 18px', fontWeight: 700, textAlign: 'right' }}>Azioni</th>
                </tr>
              </thead>
              <tbody>
                {orders.map(o => {
                  const sBadge = getSectorBadge(o.settore);
                  const formattedDate = o.data_ordine 
                    ? new Date(o.data_ordine).toLocaleDateString('it-IT', { day: '2-digit', month: '2-digit', year: 'numeric', hour: '2-digit', minute: '2-digit' })
                    : 'N/D';

                  return (
                    <tr 
                      key={o.id}
                      style={{ 
                        borderBottom: '1px solid rgba(255,255,255,0.03)',
                        transition: 'background 0.15s'
                      }}
                      onMouseEnter={e => e.currentTarget.style.background = 'rgba(255,255,255,0.02)'}
                      onMouseLeave={e => e.currentTarget.style.background = 'transparent'}
                    >
                      <td style={{ padding: '14px 18px', fontWeight: 800, color: 'var(--accent-blue)' }}>
                        #{o.id}
                      </td>

                      <td style={{ padding: '14px 18px', color: 'var(--text-secondary)', whiteSpace: 'nowrap' }}>
                        {formattedDate}
                      </td>

                      <td style={{ padding: '14px 18px', fontWeight: 600, color: 'white' }}>
                        {o.location_nome}
                      </td>

                      <td style={{ padding: '14px 18px' }}>
                        <span style={{
                          padding: '3px 8px',
                          borderRadius: '6px',
                          background: sBadge.bg,
                          color: sBadge.color,
                          fontWeight: 700,
                          fontSize: '0.75rem',
                          whiteSpace: 'nowrap'
                        }}>
                          {sBadge.label}
                        </span>
                      </td>

                      <td style={{ padding: '14px 18px', fontWeight: 700, color: 'white' }}>
                        {o.fornitore_nome}
                      </td>

                      <td style={{ padding: '14px 18px', color: 'var(--text-secondary)' }}>
                        {o.user_nome}
                      </td>

                      <td style={{ padding: '14px 18px', textAlign: 'center', color: 'var(--text-secondary)' }}>
                        <strong style={{ color: 'white' }}>{o.n_righe}</strong> art. ({o.totale_colli} colli)
                      </td>

                      <td style={{ padding: '14px 18px', textAlign: 'right', fontWeight: 800, color: 'var(--status-green)' }}>
                        € {o.spesa_totale.toFixed(2)}
                      </td>

                      <td style={{ padding: '14px 18px', textAlign: 'center' }}>
                        <span style={{
                          padding: '3px 8px',
                          borderRadius: '6px',
                          background: 'rgba(16, 185, 129, 0.15)',
                          color: '#34d399',
                          fontWeight: 700,
                          fontSize: '0.75rem',
                          textTransform: 'uppercase'
                        }}>
                          {o.stato}
                        </span>
                      </td>

                      <td style={{ padding: '14px 18px', textAlign: 'right' }}>
                        <button
                          type="button"
                          onClick={() => handleOpenDetail(o.id)}
                          className="btn"
                          style={{
                            background: 'rgba(59, 130, 246, 0.1)',
                            border: '1px solid rgba(59, 130, 246, 0.3)',
                            color: '#60a5fa',
                            padding: '6px 12px',
                            fontSize: '0.8rem',
                            fontWeight: 700,
                            display: 'inline-flex',
                            alignItems: 'center',
                            gap: '6px'
                          }}
                        >
                          <Eye size={14} /> Dettagli
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

      {/* Order Detail Modal */}
      {activeOrderDetail && (
        <div style={{
          position: 'fixed',
          top: 0,
          left: 0,
          right: 0,
          bottom: 0,
          background: 'rgba(0,0,0,0.8)',
          backdropFilter: 'blur(8px)',
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
          zIndex: 9999,
          padding: '20px'
        }}>
          <div className="glass-panel" style={{
            width: '100%',
            maxWidth: '900px',
            maxHeight: '90vh',
            display: 'flex',
            flexDirection: 'column',
            borderRadius: '16px',
            border: '1px solid var(--border-glass)',
            boxShadow: '0 25px 50px rgba(0,0,0,0.7)',
            overflow: 'hidden'
          }}>
            {/* Header */}
            <div style={{
              padding: '20px 24px',
              borderBottom: '1px solid var(--border-glass)',
              display: 'flex',
              justifyContent: 'space-between',
              alignItems: 'center',
              background: 'rgba(255,255,255,0.02)'
            }}>
              <div>
                <div style={{ display: 'flex', alignItems: 'center', gap: '10px' }}>
                  <h3 style={{ margin: 0, color: 'white', fontSize: '1.25rem' }}>
                    Ordine #{activeOrderDetail.id} — {activeOrderDetail.fornitore_nome}
                  </h3>
                  <span style={{
                    padding: '3px 8px',
                    borderRadius: '6px',
                    background: 'rgba(16, 185, 129, 0.15)',
                    color: '#34d399',
                    fontSize: '0.75rem',
                    fontWeight: 700
                  }}>
                    {activeOrderDetail.stato.toUpperCase()}
                  </span>
                </div>
                <div style={{ color: 'var(--text-secondary)', fontSize: '0.8rem', marginTop: '4px' }}>
                  Sede: <strong style={{ color: 'white' }}>{activeOrderDetail.location_nome}</strong> • Reparto: <strong style={{ color: '#93c5fd' }}>{activeOrderDetail.settore}</strong> • Operatore: {activeOrderDetail.user_nome}
                </div>
              </div>

              <button
                type="button"
                onClick={() => setActiveOrderDetail(null)}
                style={{ background: 'transparent', border: 'none', color: 'var(--text-secondary)', cursor: 'pointer', padding: '6px' }}
              >
                <X size={20} />
              </button>
            </div>

            {/* Body */}
            <div style={{ padding: '20px 24px', overflowY: 'auto', flex: 1, display: 'flex', flexDirection: 'column', gap: '18px' }}>
              
              {/* Top Details Info Cards */}
              <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(200px, 1fr))', gap: '12px' }}>
                <div style={{ padding: '12px 14px', borderRadius: '8px', background: 'rgba(255,255,255,0.02)', border: '1px solid var(--border-glass)' }}>
                  <div style={{ fontSize: '0.75rem', color: 'var(--text-secondary)' }}>Data Registrazione</div>
                  <div style={{ fontWeight: 700, color: 'white', marginTop: '2px' }}>
                    {activeOrderDetail.data_ordine ? new Date(activeOrderDetail.data_ordine).toLocaleDateString('it-IT', { day: '2-digit', month: '2-digit', year: 'numeric', hour: '2-digit', minute: '2-digit' }) : 'N/D'}
                  </div>
                </div>

                <div style={{ padding: '12px 14px', borderRadius: '8px', background: 'rgba(255,255,255,0.02)', border: '1px solid var(--border-glass)' }}>
                  <div style={{ fontSize: '0.75rem', color: 'var(--text-secondary)' }}>Consegna Richiesta</div>
                  <div style={{ fontWeight: 700, color: '#60a5fa', marginTop: '2px' }}>
                    {activeOrderDetail.data_consegna || 'Prima possibile'}
                  </div>
                </div>

                <div style={{ padding: '12px 14px', borderRadius: '8px', background: 'rgba(255,255,255,0.02)', border: '1px solid var(--border-glass)' }}>
                  <div style={{ fontSize: '0.75rem', color: 'var(--text-secondary)' }}>Totale Stimato</div>
                  <div style={{ fontWeight: 800, color: 'var(--status-green)', fontSize: '1.1rem', marginTop: '2px' }}>
                    € {activeOrderDetail.spesa_totale.toFixed(2)}
                  </div>
                </div>
              </div>

              {/* Order Notes if present */}
              {activeOrderDetail.note && (
                <div style={{ padding: '12px 16px', borderRadius: '8px', background: 'rgba(59, 130, 246, 0.08)', border: '1px solid rgba(59, 130, 246, 0.2)', fontSize: '0.85rem' }}>
                  <strong style={{ color: '#93c5fd' }}>Note sull'ordine:</strong>
                  <div style={{ color: 'white', marginTop: '2px' }}>{activeOrderDetail.note}</div>
                </div>
              )}

              {/* Order Lines Table */}
              <div>
                <h4 style={{ margin: '0 0 10px', color: 'white', fontSize: '0.95rem' }}>
                  Articoli Ordinati ({activeOrderDetail.righe?.length || 0})
                </h4>
                <div style={{ borderRadius: '8px', overflow: 'hidden', border: '1px solid var(--border-glass)' }}>
                  <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: '0.85rem', textAlign: 'left' }}>
                    <thead>
                      <tr style={{ background: 'rgba(255,255,255,0.03)', borderBottom: '1px solid var(--border-glass)', color: 'var(--text-secondary)' }}>
                        <th style={{ padding: '10px 14px' }}>SKU</th>
                        <th style={{ padding: '10px 14px' }}>Descrizione Prodotto</th>
                        <th style={{ padding: '10px 14px', textAlign: 'center' }}>Quantità</th>
                        <th style={{ padding: '10px 14px', textAlign: 'center' }}>UoM</th>
                        <th style={{ padding: '10px 14px', textAlign: 'right' }}>Prezzo Unit.</th>
                        <th style={{ padding: '10px 14px', textAlign: 'right' }}>Subtotale</th>
                      </tr>
                    </thead>
                    <tbody>
                      {activeOrderDetail.righe?.map(r => (
                        <tr key={r.id} style={{ borderBottom: '1px solid rgba(255,255,255,0.02)' }}>
                          <td style={{ padding: '10px 14px', color: 'var(--text-secondary)', fontFamily: 'monospace' }}>
                            {r.sku_interno}
                          </td>
                          <td style={{ padding: '10px 14px', fontWeight: 600, color: 'white' }}>
                            {r.descrizione}
                          </td>
                          <td style={{ padding: '10px 14px', textAlign: 'center', fontWeight: 800, color: '#60a5fa' }}>
                            {r.quantita}
                          </td>
                          <td style={{ padding: '10px 14px', textAlign: 'center', fontWeight: 700, color: '#93c5fd' }}>
                            {r.uom}
                          </td>
                          <td style={{ padding: '10px 14px', textAlign: 'right', color: 'var(--text-secondary)' }}>
                            € {r.prezzo_inserito.toFixed(2)}
                          </td>
                          <td style={{ padding: '10px 14px', textAlign: 'right', fontWeight: 700, color: 'white' }}>
                            € {r.subtotale.toFixed(2)}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </div>

              {/* Formatted WhatsApp Message Preview */}
              {activeOrderDetail.whatsapp_message && (
                <div>
                  <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '8px' }}>
                    <span style={{ fontSize: '0.85rem', fontWeight: 700, color: 'white' }}>
                      💬 Messaggio WhatsApp Generato
                    </span>
                    <button
                      type="button"
                      onClick={() => handleCopyMessage(activeOrderDetail.whatsapp_message || '')}
                      className="btn"
                      style={{
                        padding: '4px 10px',
                        fontSize: '0.75rem',
                        background: 'rgba(255,255,255,0.05)',
                        border: '1px solid var(--border-glass)',
                        display: 'flex',
                        alignItems: 'center',
                        gap: '6px'
                      }}
                    >
                      {copiedText ? <Check size={12} color="#10b981" /> : <Copy size={12} />}
                      <span>{copiedText ? 'Copiato!' : 'Copia Testo'}</span>
                    </button>
                  </div>
                  <pre style={{
                    padding: '14px',
                    borderRadius: '8px',
                    background: '#0d1117',
                    border: '1px solid rgba(16, 185, 129, 0.2)',
                    color: '#a7f3d0',
                    fontSize: '0.8rem',
                    whiteSpace: 'pre-wrap',
                    fontFamily: 'monospace',
                    margin: 0
                  }}>
                    {activeOrderDetail.whatsapp_message}
                  </pre>
                </div>
              )}

            </div>

            {/* Footer */}
            <div style={{
              padding: '16px 24px',
              borderTop: '1px solid var(--border-glass)',
              display: 'flex',
              justifyContent: 'space-between',
              alignItems: 'center',
              background: 'rgba(255,255,255,0.02)'
            }}>
              {activeOrderDetail.whatsapp_message && (
                <a
                  href={`https://api.whatsapp.com/send?text=${encodeURIComponent(activeOrderDetail.whatsapp_message)}`}
                  target="_blank"
                  rel="noreferrer"
                  className="btn btn-primary"
                  style={{ background: '#16a34a', border: 'none', display: 'flex', alignItems: 'center', gap: '8px' }}
                >
                  <Send size={15} /> Apri Chat WhatsApp
                </a>
              )}

              <button
                type="button"
                onClick={handleCloseModal}
                className="btn"
                style={{ background: 'transparent', border: '1px solid var(--border-glass)', marginLeft: 'auto' }}
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
