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
  // Initial order/filter bootstrap.
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    if (props?.selectedOrderId) {
      handleOpenDetail(props.selectedOrderId);
    }
  // eslint-disable-next-line react-hooks/exhaustive-deps
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
  // eslint-disable-next-line react-hooks/exhaustive-deps
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
    if (s.includes('beverage')) return { bg: 'var(--accent-bg)', color: 'var(--accent-text)', label: '🍹 Beverage' };
    if (s.includes('food')) return { bg: 'var(--ok-bg)', color: 'var(--ok)', label: '🍽️ Food' };
    if (s.includes('material')) return { bg: 'var(--warn-bg)', color: 'var(--warn)', label: '📦 Materiali' };
    return { bg: 'var(--bg-elevated)', color: 'var(--text-primary)', label: settore || 'Generico' };
  };

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: '24px' }}>
      
      {/* Top Header & Overview KPIs */}
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(220px, 1fr))', gap: '16px' }}>
        <div className="glass-panel" style={{ padding: '18px 20px', display: 'flex', alignItems: 'center', gap: '14px' }}>
          <div style={{ width: '44px', height: '44px', borderRadius: '12px', background: 'var(--accent-bg)', color: 'var(--accent-blue)', display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
            <ShoppingCart size={22} />
          </div>
          <div>
            <div style={{ color: 'var(--text-secondary)', fontSize: '0.8rem', fontWeight: 600 }}>Ordini Registrati</div>
            <div style={{ fontSize: '1.4rem', fontWeight: 600, color: 'var(--text-primary)', fontFamily: 'var(--font-mono)', fontVariantNumeric: 'tabular-nums' }}>{orders.length}</div>
          </div>
        </div>

        <div className="glass-panel" style={{ padding: '18px 20px', display: 'flex', alignItems: 'center', gap: '14px' }}>
          <div style={{ width: '44px', height: '44px', borderRadius: '12px', background: 'var(--ok-bg)', color: 'var(--status-green)', display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
            <Package size={22} />
          </div>
          <div>
            <div style={{ color: 'var(--text-secondary)', fontSize: '0.8rem', fontWeight: 600 }}>Valore Totale Ordinato</div>
            <div style={{ fontSize: '1.4rem', fontWeight: 600, color: 'var(--text-primary)', fontFamily: 'var(--font-mono)', fontVariantNumeric: 'tabular-nums' }}>€ {totalSpend.toFixed(2)}</div>
          </div>
        </div>

        <div className="glass-panel" style={{ padding: '18px 20px', display: 'flex', alignItems: 'center', gap: '14px' }}>
          <div style={{ width: '44px', height: '44px', borderRadius: '12px', background: 'var(--warn-bg)', color: 'var(--warn)', display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
            <Layers size={22} />
          </div>
          <div>
            <div style={{ color: 'var(--text-secondary)', fontSize: '0.8rem', fontWeight: 600 }}>Totale Colli Ordinati</div>
            <div style={{ fontSize: '1.4rem', fontWeight: 600, color: 'var(--text-primary)', fontFamily: 'var(--font-mono)', fontVariantNumeric: 'tabular-nums' }}>{totalPackages}</div>
          </div>
        </div>

        <div className="glass-panel" style={{ padding: '18px 20px', display: 'flex', alignItems: 'center', gap: '14px' }}>
          <div style={{ width: '44px', height: '44px', borderRadius: '12px', background: 'var(--info-bg)', color: 'var(--info)', display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
            <Truck size={22} />
          </div>
          <div>
            <div style={{ color: 'var(--text-secondary)', fontSize: '0.8rem', fontWeight: 600 }}>Fornitori Coinvolti</div>
            <div style={{ fontSize: '1.4rem', fontWeight: 600, color: 'var(--text-primary)', fontFamily: 'var(--font-mono)', fontVariantNumeric: 'tabular-nums' }}>{totalSuppliersCount}</div>
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
                background: 'var(--bg-inset)',
                border: '1px solid var(--line)',
                borderRadius: 'var(--radius-sm)',
                color: 'var(--text-primary)',
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
              background: 'var(--bg-inset)',
              border: '1px solid var(--line)',
              borderRadius: 'var(--radius-sm)',
              color: 'var(--text-primary)',
              fontSize: '0.85rem',
              outline: 'none',
              cursor: 'pointer'
            }}
          >
            <option value="all" style={{ background: 'var(--bg-card)' }}>Tutte le sedi</option>
            {locations.map(loc => (
              <option key={loc.id} value={loc.id} style={{ background: 'var(--bg-card)' }}>
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
              background: 'var(--bg-inset)',
              border: '1px solid var(--line)',
              borderRadius: 'var(--radius-sm)',
              color: 'var(--text-primary)',
              fontSize: '0.85rem',
              outline: 'none',
              cursor: 'pointer'
            }}
          >
            <option value="all" style={{ background: 'var(--bg-card)' }}>Tutti i reparti</option>
            <option value="Beverage" style={{ background: 'var(--bg-card)' }}>🍹 Beverage</option>
            <option value="Materiali di consumo" style={{ background: 'var(--bg-card)' }}>📦 Materiali di consumo</option>
            <option value="Food" style={{ background: 'var(--bg-card)' }}>🍽️ Food</option>
          </select>

          {/* Status Filter */}
          <select
            value={selectedStatus}
            onChange={e => setSelectedStatus(e.target.value)}
            style={{
              padding: '9px 12px',
              background: 'var(--bg-inset)',
              border: '1px solid var(--line)',
              borderRadius: 'var(--radius-sm)',
              color: 'var(--text-primary)',
              fontSize: '0.85rem',
              outline: 'none',
              cursor: 'pointer'
            }}
          >
            <option value="all" style={{ background: 'var(--bg-card)' }}>Tutti gli stati</option>
            <option value="inviato" style={{ background: 'var(--bg-card)' }}>Inviato</option>
            <option value="consegnato" style={{ background: 'var(--bg-card)' }}>Consegnato</option>
            <option value="riconciliato" style={{ background: 'var(--bg-card)' }}>Riconciliato</option>
          </select>
        </div>

        <button
          onClick={loadOrders}
          className="btn"
          style={{ background: 'var(--bg-inset)', border: '1px solid var(--border-glass)', fontSize: '0.85rem', display: 'flex', alignItems: 'center', gap: '6px' }}
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
            <h3 style={{ margin: '0 0 6px', color: 'var(--text-primary)' }}>Nessun ordine trovato</h3>
            <p style={{ fontSize: '0.85rem', margin: 0 }}>
              Non sono ancora stati registrati ordini corrispondenti ai filtri selezionati.
            </p>
          </div>
        ) : (
          <div style={{ overflowX: 'auto' }}>
            <table className="ds-table" style={{ width: '100%', borderCollapse: 'collapse', textAlign: 'left', fontSize: '0.85rem' }}>
              <thead>
                <tr style={{ background: 'var(--bg-inset)', borderBottom: '1px solid var(--border-glass)', color: 'var(--text-secondary)' }}>
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
                        borderBottom: '1px solid var(--line)',
                        transition: 'background 0.15s'
                      }}
                      onMouseEnter={e => e.currentTarget.style.background = 'var(--bg-elevated)'}
                      onMouseLeave={e => e.currentTarget.style.background = 'transparent'}
                    >
                      <td style={{ padding: '14px 18px', fontWeight: 700, color: 'var(--accent-text)', fontFamily: 'var(--font-mono)', fontVariantNumeric: 'tabular-nums' }}>
                        #{o.id}
                      </td>

                      <td style={{ padding: '14px 18px', color: 'var(--text-secondary)', whiteSpace: 'nowrap' }}>
                        {formattedDate}
                      </td>

                      <td style={{ padding: '14px 18px', fontWeight: 600, color: 'var(--text-primary)' }}>
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

                      <td style={{ padding: '14px 18px', fontWeight: 700, color: 'var(--text-primary)' }}>
                        {o.fornitore_nome}
                      </td>

                      <td style={{ padding: '14px 18px', color: 'var(--text-secondary)' }}>
                        {o.user_nome}
                      </td>

                      <td style={{ padding: '14px 18px', textAlign: 'center', color: 'var(--text-secondary)' }}>
                        <strong style={{ color: 'var(--text-primary)', fontFamily: 'var(--font-mono)', fontVariantNumeric: 'tabular-nums' }}>{o.n_righe}</strong> art. ({o.totale_colli} colli)
                      </td>

                      <td style={{ padding: '14px 18px', textAlign: 'right', fontWeight: 700, color: 'var(--status-green)', fontFamily: 'var(--font-mono)', fontVariantNumeric: 'tabular-nums' }}>
                        € {o.spesa_totale.toFixed(2)}
                      </td>

                      <td style={{ padding: '14px 18px', textAlign: 'center' }}>
                        <span style={{
                          padding: '3px 8px',
                          borderRadius: '6px',
                          background: 'var(--ok-bg)',
                          color: 'var(--ok)',
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
                            background: 'var(--accent-bg)',
                            border: '1px solid var(--accent-border)',
                            color: 'var(--accent-text)',
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
          background: 'var(--bg-overlay)',
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
            borderRadius: 'var(--radius-lg)',
            border: '1px solid var(--border-glass)',
            boxShadow: 'var(--shadow-pop)',
            overflow: 'hidden'
          }}>
            {/* Header */}
            <div style={{
              padding: '20px 24px',
              borderBottom: '1px solid var(--border-glass)',
              display: 'flex',
              justifyContent: 'space-between',
              alignItems: 'center',
              background: 'var(--bg-inset)'
            }}>
              <div>
                <div style={{ display: 'flex', alignItems: 'center', gap: '10px' }}>
                  <h3 style={{ margin: 0, color: 'var(--text-primary)', fontSize: '1.25rem' }}>
                    Ordine #{activeOrderDetail.id} — {activeOrderDetail.fornitore_nome}
                  </h3>
                  <span style={{
                    padding: '3px 8px',
                    borderRadius: '6px',
                    background: 'var(--ok-bg)',
                    color: 'var(--ok)',
                    fontSize: '0.75rem',
                    fontWeight: 700
                  }}>
                    {activeOrderDetail.stato.toUpperCase()}
                  </span>
                </div>
                <div style={{ color: 'var(--text-secondary)', fontSize: '0.8rem', marginTop: '4px' }}>
                  Sede: <strong style={{ color: 'var(--text-primary)' }}>{activeOrderDetail.location_nome}</strong> • Reparto: <strong style={{ color: 'var(--accent-text)' }}>{activeOrderDetail.settore}</strong> • Operatore: {activeOrderDetail.user_nome}
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
                <div style={{ padding: '12px 14px', borderRadius: 'var(--radius-md)', background: 'var(--bg-inset)', border: '1px solid var(--line)' }}>
                  <div style={{ fontSize: '0.75rem', color: 'var(--text-secondary)' }}>Data Registrazione</div>
                  <div style={{ fontWeight: 700, color: 'var(--text-primary)', marginTop: '2px' }}>
                    {activeOrderDetail.data_ordine ? new Date(activeOrderDetail.data_ordine).toLocaleDateString('it-IT', { day: '2-digit', month: '2-digit', year: 'numeric', hour: '2-digit', minute: '2-digit' }) : 'N/D'}
                  </div>
                </div>

                <div style={{ padding: '12px 14px', borderRadius: 'var(--radius-md)', background: 'var(--bg-inset)', border: '1px solid var(--line)' }}>
                  <div style={{ fontSize: '0.75rem', color: 'var(--text-secondary)' }}>Consegna Richiesta</div>
                  <div style={{ fontWeight: 700, color: 'var(--accent-text)', marginTop: '2px' }}>
                    {activeOrderDetail.data_consegna || 'Prima possibile'}
                  </div>
                </div>

                <div style={{ padding: '12px 14px', borderRadius: 'var(--radius-md)', background: 'var(--bg-inset)', border: '1px solid var(--line)' }}>
                  <div style={{ fontSize: '0.75rem', color: 'var(--text-secondary)' }}>Totale Stimato</div>
                  <div style={{ fontWeight: 600, color: 'var(--status-green)', fontSize: '1.1rem', marginTop: '2px', fontFamily: 'var(--font-mono)', fontVariantNumeric: 'tabular-nums' }}>
                    € {activeOrderDetail.spesa_totale.toFixed(2)}
                  </div>
                </div>
              </div>

              {/* Order Notes if present */}
              {activeOrderDetail.note && (
                <div style={{ padding: '12px 16px', borderRadius: 'var(--radius-md)', background: 'var(--accent-bg)', border: '1px solid var(--accent-border)', fontSize: '0.85rem' }}>
                  <strong style={{ color: 'var(--accent-text)' }}>Note sull'ordine:</strong>
                  <div style={{ color: 'var(--text-primary)', marginTop: '2px' }}>{activeOrderDetail.note}</div>
                </div>
              )}

              {/* Order Lines Table */}
              <div>
                <h4 style={{ margin: '0 0 10px', color: 'var(--text-primary)', fontSize: '0.95rem' }}>
                  Articoli Ordinati ({activeOrderDetail.righe?.length || 0})
                </h4>
                <div style={{ borderRadius: 'var(--radius-md)', overflow: 'hidden', border: '1px solid var(--line)' }}>
                  <table className="ds-table" style={{ width: '100%', borderCollapse: 'collapse', fontSize: '0.85rem', textAlign: 'left' }}>
                    <thead>
                      <tr style={{ background: 'var(--bg-inset)', borderBottom: '1px solid var(--border-glass)', color: 'var(--text-secondary)' }}>
                        <th style={{ padding: '10px 14px' }}>SKU</th>
                        <th style={{ padding: '10px 14px' }}>Descrizione Prodotto</th>
                        <th style={{ padding: '10px 14px', textAlign: 'center' }}>Quantità</th>
                        <th style={{ padding: '10px 14px', textAlign: 'center' }}>UoM</th>
                        <th style={{ padding: '10px 14px', textAlign: 'right' }}>Prezzo Unit.</th>
                        <th style={{ padding: '10px 14px', textAlign: 'right' }}>Subtotale</th>
                      </tr>
                    </thead>
                    <tbody>
                      {activeOrderDetail.righe?.map(r => {
                        const isFreebie = r.stato_ottimizzazione === 'omaggio' || r.prezzo_inserito === 0 || (r as any).is_omaggio;
                        return (
                          <tr key={r.id} style={{ borderBottom: '1px solid var(--line)', background: isFreebie ? 'var(--ok-bg)' : 'transparent' }}>
                            <td style={{ padding: '10px 14px', color: 'var(--text-secondary)', fontFamily: 'var(--font-mono)' }}>
                              {r.sku_interno}
                            </td>
                            <td style={{ padding: '10px 14px', fontWeight: 600, color: 'var(--text-primary)' }}>
                              <div style={{ display: 'flex', alignItems: 'center', gap: '8px', flexWrap: 'wrap' }}>
                                <span>{r.descrizione}</span>
                                {isFreebie && (
                                  <span style={{
                                    padding: '2px 8px', borderRadius: '6px',
                                    background: 'var(--ok-bg)', color: 'var(--ok)',
                                    fontSize: '0.72rem', fontWeight: 700, border: '1px solid var(--ok-border)'
                                  }}>
                                    🎁 OMAGGIO
                                  </span>
                                )}
                              </div>
                            </td>
                            <td style={{ padding: '10px 14px', textAlign: 'center', fontWeight: 700, color: isFreebie ? 'var(--ok)' : 'var(--accent-text)', fontFamily: 'var(--font-mono)', fontVariantNumeric: 'tabular-nums' }}>
                              {r.quantita}
                            </td>
                            <td style={{ padding: '10px 14px', textAlign: 'center', fontWeight: 700, color: 'var(--accent-text)' }}>
                              {r.uom}
                            </td>
                            <td style={{ padding: '10px 14px', textAlign: 'right', color: isFreebie ? 'var(--ok)' : 'var(--text-secondary)', fontFamily: 'var(--font-mono)', fontVariantNumeric: 'tabular-nums' }}>
                              {isFreebie ? <strong style={{ color: 'var(--ok)' }}>GRATIS</strong> : `€ ${r.prezzo_inserito.toFixed(2)}`}
                            </td>
                            <td style={{ padding: '10px 14px', textAlign: 'right', fontWeight: 700, color: isFreebie ? 'var(--ok)' : 'var(--text-primary)', fontFamily: 'var(--font-mono)', fontVariantNumeric: 'tabular-nums' }}>
                              {isFreebie ? <strong style={{ color: 'var(--ok)' }}>€ 0,00</strong> : `€ ${r.subtotale.toFixed(2)}`}
                            </td>
                          </tr>
                        );
                      })}
                    </tbody>
                  </table>
                </div>
              </div>

              {/* Formatted WhatsApp Message Preview */}
              {activeOrderDetail.whatsapp_message && (
                <div>
                  <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '8px' }}>
                    <span style={{ fontSize: '0.85rem', fontWeight: 700, color: 'var(--text-primary)' }}>
                      💬 Messaggio WhatsApp Generato
                    </span>
                    <button
                      type="button"
                      onClick={() => handleCopyMessage(activeOrderDetail.whatsapp_message || '')}
                      className="btn"
                      style={{
                        padding: '4px 10px',
                        fontSize: '0.75rem',
                        background: 'var(--bg-elevated)',
                        border: '1px solid var(--border-glass)',
                        display: 'flex',
                        alignItems: 'center',
                        gap: '6px'
                      }}
                    >
                      {copiedText ? <Check size={12} color="var(--ok)" /> : <Copy size={12} />}
                      <span>{copiedText ? 'Copiato!' : 'Copia Testo'}</span>
                    </button>
                  </div>
                  <pre style={{
                    padding: '14px',
                    borderRadius: 'var(--radius-md)',
                    background: 'var(--bg-inset)',
                    border: '1px solid var(--ok-border)',
                    color: 'var(--ok)',
                    fontSize: '0.8rem',
                    whiteSpace: 'pre-wrap',
                    fontFamily: 'var(--font-mono)',
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
              background: 'var(--bg-inset)'
            }}>
              {activeOrderDetail.whatsapp_message && (
                <a
                  href={`https://api.whatsapp.com/send?text=${encodeURIComponent(activeOrderDetail.whatsapp_message)}`}
                  target="_blank"
                  rel="noreferrer"
                  className="btn btn-primary"
                  style={{ background: 'var(--ok)', border: 'none', display: 'flex', alignItems: 'center', gap: '8px' }}
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
