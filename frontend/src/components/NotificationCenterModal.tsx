import { useState, useEffect, useMemo } from 'react';
import {
  Bell,
  X,
  ShoppingCart,
  ThumbsDown,
  User,
  Building2,
  Calendar,
  Eye,
  CheckCircle2,
  RefreshCw,
  ShieldAlert,
  ArrowRight
} from 'lucide-react';
import { API_BASE, getHeaders } from '../api';

interface OrderNotification {
  id: number;
  fornitore_id: number;
  fornitore_nome: string;
  location_id: number;
  location_nome: string;
  user_id?: number | null;
  user_nome: string;
  user_ruolo?: string | null;
  settore: string;
  data_ordine: string | null;
  data_consegna: string | null;
  spesa_totale: number;
  stato: string;
  stato_ricezione?: string | null;
  n_righe: number;
  totale_colli: number;
}

interface ProductFeedbackNotification {
  id: number;
  product_id: number;
  product_name: string;
  canonical_name: string;
  category?: string | null;
  sku_interno?: string | null;
  user_id: number;
  user_nome: string;
  motivo?: string | null;
  note?: string | null;
  rating?: number | null;
  created_at: string;
  stato: string;
}

interface NotificationCenterModalProps {
  isOpen: boolean;
  onClose: () => void;
  onViewOrder: (orderId: number) => void;
  onViewReviews: () => void;
  onViewReceipt: () => void;
  onRefreshCounts?: () => void;
}

export default function NotificationCenterModal({
  isOpen,
  onClose,
  onViewOrder,
  onViewReviews,
  onViewReceipt: _onViewReceipt,
  onRefreshCounts
}: NotificationCenterModalProps) {
  const [activeTab, setActiveTab] = useState<'orders' | 'feedbacks'>('orders');
  const [orders, setOrders] = useState<OrderNotification[]>([]);
  const [feedbacks, setFeedbacks] = useState<ProductFeedbackNotification[]>([]);
  const [loading, setLoading] = useState<boolean>(true);
  const [resolvingId, setResolvingId] = useState<number | null>(null);

  const headers = useMemo(() => getHeaders(), []);

  useEffect(() => {
    if (isOpen) {
      loadAllNotifications();
    }
  }, [isOpen]);

  async function loadAllNotifications() {
    setLoading(true);
    try {
      const [ordRes, feedRes] = await Promise.all([
        fetch(`${API_BASE}/ordini/notifications/feed`, { headers }),
        fetch(`${API_BASE}/feedbacks/pending`, { headers })
      ]);

      if (ordRes.ok) {
        const ordData = await ordRes.json();
        setOrders(ordData.notifications || []);
      }

      if (feedRes.ok) {
        const feedData = await feedRes.json();
        setFeedbacks(Array.isArray(feedData) ? feedData : []);
      }
    } catch (e) {
      console.error(e);
    } finally {
      setLoading(false);
    }
  }

  async function handleResolveFeedback(feedbackId: number, action: 'escluso' | 'archiviato', disattiva: boolean = false) {
    setResolvingId(feedbackId);
    try {
      const res = await fetch(`${API_BASE}/feedbacks/${feedbackId}/risolvi`, {
        method: 'PATCH',
        headers: { ...headers, 'Content-Type': 'application/json' },
        body: JSON.stringify({
          action,
          disattiva_prodotto: disattiva,
          admin_notes: `Gestito dal centro notifiche (${action})`
        })
      });

      if (res.ok) {
        setFeedbacks(prev => prev.filter(f => f.id !== feedbackId));
        if (onRefreshCounts) onRefreshCounts();
      }
    } catch (e) {
      console.error(e);
    } finally {
      setResolvingId(null);
    }
  }

  if (!isOpen) return null;

  return (
    <div style={{
      position: 'fixed',
      top: 0,
      left: 0,
      right: 0,
      bottom: 0,
      background: 'rgba(0, 0, 0, 0.82)',
      backdropFilter: 'blur(8px)',
      display: 'flex',
      alignItems: 'center',
      justifyContent: 'center',
      zIndex: 9999,
      padding: '20px'
    }}>
      <div className="glass-panel" style={{
        width: '100%',
        maxWidth: '820px',
        maxHeight: '90vh',
        background: '#13131c',
        border: '1px solid rgba(255, 255, 255, 0.12)',
        borderRadius: '16px',
        display: 'flex',
        flexDirection: 'column',
        overflow: 'hidden',
        boxShadow: '0 25px 60px rgba(0, 0, 0, 0.9)'
      }}>
        {/* Modal Header */}
        <div style={{
          padding: '20px 24px',
          borderBottom: '1px solid rgba(255, 255, 255, 0.08)',
          display: 'flex',
          justifyContent: 'space-between',
          alignItems: 'center',
          background: 'rgba(255, 255, 255, 0.02)'
        }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: '12px' }}>
            <div style={{
              width: '40px',
              height: '40px',
              borderRadius: '10px',
              background: 'rgba(59, 130, 246, 0.15)',
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
              color: 'var(--accent-blue)'
            }}>
              <Bell size={20} />
            </div>
            <div>
              <h3 style={{ margin: 0, color: 'white', fontSize: '1.2rem' }}>Centro Notifiche & Attività</h3>
              <p style={{ margin: 0, color: 'var(--text-secondary)', fontSize: '0.8rem' }}>
                Monitora in tempo reale gli ordini effettuati e le segnalazioni dei responsabili di settore
              </p>
            </div>
          </div>

          <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
            <button
              type="button"
              onClick={loadAllNotifications}
              disabled={loading}
              className="btn"
              style={{ padding: '6px 12px', fontSize: '0.78rem', background: 'rgba(255,255,255,0.05)', border: '1px solid var(--border-glass)', display: 'flex', alignItems: 'center', gap: '4px' }}
            >
              <RefreshCw size={13} className={loading ? 'spinner' : ''} /> Aggiorna
            </button>
            <button
              type="button"
              onClick={onClose}
              style={{ background: 'transparent', border: 'none', color: 'var(--text-secondary)', cursor: 'pointer', padding: '6px' }}
            >
              <X size={20} />
            </button>
          </div>
        </div>

        {/* Tab Navigation */}
        <div style={{ display: 'flex', borderBottom: '1px solid rgba(255,255,255,0.08)', padding: '0 24px', background: 'rgba(0,0,0,0.2)' }}>
          <button
            type="button"
            onClick={() => setActiveTab('orders')}
            style={{
              padding: '14px 20px',
              background: 'transparent',
              border: 'none',
              borderBottom: activeTab === 'orders' ? '2px solid var(--accent-blue)' : '2px solid transparent',
              color: activeTab === 'orders' ? 'white' : 'var(--text-secondary)',
              fontWeight: activeTab === 'orders' ? 700 : 500,
              fontSize: '0.9rem',
              cursor: 'pointer',
              display: 'flex',
              alignItems: 'center',
              gap: '8px'
            }}
          >
            <ShoppingCart size={16} />
            <span>Nuovi Ordini Emessi</span>
            <span style={{
              padding: '2px 7px',
              borderRadius: '10px',
              background: 'rgba(59, 130, 246, 0.2)',
              color: '#60a5fa',
              fontSize: '0.72rem',
              fontWeight: 800
            }}>
              {orders.length}
            </span>
          </button>

          <button
            type="button"
            onClick={() => setActiveTab('feedbacks')}
            style={{
              padding: '14px 20px',
              background: 'transparent',
              border: 'none',
              borderBottom: activeTab === 'feedbacks' ? '2px solid #ef4444' : '2px solid transparent',
              color: activeTab === 'feedbacks' ? 'white' : 'var(--text-secondary)',
              fontWeight: activeTab === 'feedbacks' ? 700 : 500,
              fontSize: '0.9rem',
              cursor: 'pointer',
              display: 'flex',
              alignItems: 'center',
              gap: '8px'
            }}
          >
            <ThumbsDown size={16} />
            <span>Segnalazioni Prodotti (Voto NO)</span>
            {feedbacks.length > 0 && (
              <span style={{
                padding: '2px 7px',
                borderRadius: '10px',
                background: '#ef4444',
                color: 'white',
                fontSize: '0.72rem',
                fontWeight: 800
              }}>
                {feedbacks.length}
              </span>
            )}
          </button>
        </div>

        {/* Tab Content Body */}
        <div style={{ padding: '20px 24px', overflowY: 'auto', flex: 1, display: 'flex', flexDirection: 'column', gap: '12px' }}>
          {loading ? (
            <div style={{ padding: '50px', textAlign: 'center', color: 'var(--text-secondary)' }}>
              <RefreshCw className="spinner" size={24} style={{ margin: '0 auto 10px' }} />
              <div>Caricamento feed notifiche...</div>
            </div>
          ) : activeTab === 'orders' ? (
            orders.length === 0 ? (
              <div style={{ padding: '50px', textAlign: 'center', color: 'var(--text-secondary)' }}>
                <CheckCircle2 size={36} style={{ margin: '0 auto 10px', opacity: 0.4, color: '#10b981' }} />
                <h4 style={{ margin: '0 0 4px', color: 'white' }}>Nessun ordine recente</h4>
                <p style={{ margin: 0, fontSize: '0.85rem' }}>Non ci sono ordini registrati nelle ultime ore.</p>
              </div>
            ) : (
              orders.map(o => (
                <div
                  key={o.id}
                  style={{
                    padding: '16px 18px',
                    borderRadius: '12px',
                    background: 'rgba(255, 255, 255, 0.02)',
                    border: '1px solid var(--border-glass)',
                    display: 'flex',
                    flexDirection: 'column',
                    gap: '10px',
                    transition: 'all 0.2s'
                  }}
                  className="table-row-hover"
                >
                  <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', flexWrap: 'wrap', gap: '10px' }}>
                    <div>
                      <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                        <span style={{ fontWeight: 800, color: 'var(--primary-color)', fontSize: '1rem' }}>
                          Ordine #{o.id}
                        </span>
                        <span style={{
                          padding: '2px 8px',
                          borderRadius: '6px',
                          background: o.settore === 'Beverage' ? 'rgba(59, 130, 246, 0.15)' : 'rgba(16, 185, 129, 0.15)',
                          color: o.settore === 'Beverage' ? '#60a5fa' : '#34d399',
                          fontSize: '0.72rem',
                          fontWeight: 700
                        }}>
                          {o.settore}
                        </span>
                        <span style={{ color: 'var(--text-secondary)', fontSize: '0.8rem' }}>➔</span>
                        <strong style={{ color: 'white', fontSize: '0.95rem' }}>{o.fornitore_nome}</strong>
                      </div>

                      {/* Explicit Author & Location details */}
                      <div style={{ display: 'flex', gap: '12px', alignItems: 'center', flexWrap: 'wrap', marginTop: '6px', fontSize: '0.8rem' }}>
                        <div style={{ display: 'flex', alignItems: 'center', gap: '5px', color: '#93c5fa' }}>
                          <User size={13} />
                          <span>Emesso da: <strong style={{ color: 'white' }}>{o.user_nome}</strong></span>
                        </div>
                        <div style={{ display: 'flex', alignItems: 'center', gap: '5px', color: 'var(--text-secondary)' }}>
                          <Building2 size={13} />
                          <span>Sede: <strong style={{ color: 'white' }}>{o.location_nome}</strong></span>
                        </div>
                        <div style={{ display: 'flex', alignItems: 'center', gap: '5px', color: 'var(--text-secondary)' }}>
                          <Calendar size={13} />
                          <span>{o.data_ordine ? new Date(o.data_ordine).toLocaleString('it-IT', { day: '2-digit', month: '2-digit', hour: '2-digit', minute: '2-digit' }) : 'N/D'}</span>
                        </div>
                      </div>
                    </div>

                    {/* Right side: Amount and Direct Order View Redirect */}
                    <div style={{ textAlign: 'right', display: 'flex', flexDirection: 'column', alignItems: 'flex-end', gap: '8px' }}>
                      <div>
                        <div style={{ fontSize: '0.72rem', color: 'var(--text-secondary)' }}>Importo Totale</div>
                        <div style={{ fontWeight: 800, fontSize: '1.1rem', color: 'var(--status-green)' }}>
                          € {o.spesa_totale.toFixed(2)}
                        </div>
                      </div>

                      <button
                        type="button"
                        onClick={() => {
                          onClose();
                          onViewOrder(o.id);
                        }}
                        className="btn btn-primary"
                        style={{ padding: '6px 14px', fontSize: '0.78rem', display: 'flex', alignItems: 'center', gap: '6px' }}
                      >
                        <Eye size={13} /> Visualizza Ordine #{o.id}
                      </button>
                    </div>
                  </div>
                </div>
              ))
            )
          ) : (
            feedbacks.length === 0 ? (
              <div style={{ padding: '50px', textAlign: 'center', color: 'var(--text-secondary)' }}>
                <CheckCircle2 size={36} style={{ margin: '0 auto 10px', opacity: 0.4, color: '#10b981' }} />
                <h4 style={{ margin: '0 0 4px', color: 'white' }}>Nessuna segnalazione critica</h4>
                <p style={{ margin: 0, fontSize: '0.85rem' }}>Tutti i prodotti del listino hanno gradimento positivo.</p>
              </div>
            ) : (
              feedbacks.map(f => (
                <div
                  key={f.id}
                  style={{
                    padding: '16px',
                    borderRadius: '12px',
                    background: 'rgba(239, 68, 68, 0.04)',
                    border: '1px solid rgba(239, 68, 68, 0.25)',
                    display: 'flex',
                    flexDirection: 'column',
                    gap: '10px'
                  }}
                >
                  <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', flexWrap: 'wrap', gap: '10px' }}>
                    <div>
                      <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                        <span style={{ padding: '2px 8px', borderRadius: '6px', background: 'rgba(239, 68, 68, 0.2)', color: '#f87171', fontSize: '0.75rem', fontWeight: 800 }}>
                          👎 SEGNALATO DA ESCLUDERE
                        </span>
                        <h4 style={{ margin: 0, color: 'white', fontSize: '1rem' }}>{f.product_name}</h4>
                      </div>
                      <div style={{ fontSize: '0.75rem', color: 'var(--text-secondary)', marginTop: '4px' }}>
                        SKU: <code>{f.sku_interno || 'N/D'}</code> • Settore: {f.category || 'Generico'} • Segnalato da: <strong style={{ color: 'white' }}>{f.user_nome}</strong>
                      </div>
                    </div>

                    <span style={{ fontSize: '0.72rem', color: 'var(--text-secondary)' }}>
                      {f.created_at ? new Date(f.created_at).toLocaleDateString('it-IT') : ''}
                    </span>
                  </div>

                  {f.motivo && (
                    <div style={{ padding: '8px 12px', borderRadius: '6px', background: 'rgba(0,0,0,0.2)', color: '#fca5a5', fontSize: '0.8rem', fontWeight: 600 }}>
                      Motivo: {f.motivo}
                    </div>
                  )}

                  {f.note && (
                    <div style={{ fontSize: '0.8rem', color: 'var(--text-secondary)', fontStyle: 'italic' }}>
                      "{f.note}"
                    </div>
                  )}

                  <div style={{ display: 'flex', justifyContent: 'flex-end', gap: '8px', borderTop: '1px solid rgba(255,255,255,0.05)', paddingTop: '10px', marginTop: '4px' }}>
                    <button
                      type="button"
                      disabled={resolvingId === f.id}
                      onClick={() => handleResolveFeedback(f.id, 'archiviato', false)}
                      className="btn"
                      style={{ padding: '6px 12px', fontSize: '0.75rem', background: 'transparent', border: '1px solid var(--border-glass)' }}
                    >
                      Archivia Segnalazione
                    </button>

                    <button
                      type="button"
                      disabled={resolvingId === f.id}
                      onClick={() => handleResolveFeedback(f.id, 'escluso', true)}
                      className="btn"
                      style={{ padding: '6px 14px', fontSize: '0.75rem', background: '#ef4444', color: 'white', border: 'none', display: 'flex', alignItems: 'center', gap: '4px' }}
                    >
                      <ShieldAlert size={13} /> Disattiva dal Listino
                    </button>
                  </div>
                </div>
              ))
            )
          )}
        </div>

        {/* Modal Footer */}
        <div style={{ padding: '14px 24px', borderTop: '1px solid rgba(255, 255, 255, 0.08)', display: 'flex', justifyContent: 'space-between', alignItems: 'center', background: 'rgba(0,0,0,0.3)' }}>
          <button
            type="button"
            onClick={() => {
              onClose();
              onViewReviews();
            }}
            className="btn"
            style={{ fontSize: '0.8rem', background: 'transparent', border: '1px solid var(--border-glass)', display: 'flex', alignItems: 'center', gap: '6px' }}
          >
            Vai alla Pagina Recensioni Prodotti <ArrowRight size={13} />
          </button>

          <button
            type="button"
            onClick={onClose}
            className="btn"
            style={{ fontSize: '0.8rem', background: 'rgba(255,255,255,0.05)', border: '1px solid var(--border-glass)' }}
          >
            Chiudi
          </button>
        </div>
      </div>
    </div>
  );
}
