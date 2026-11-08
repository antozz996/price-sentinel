import { useState, useEffect } from 'react';
import { AlertTriangle, CheckCircle2, Trash2, X, RefreshCw, MessageSquare } from 'lucide-react';
import { API_BASE, getHeaders } from '../api';

interface FeedbackItem {
  id: number;
  product_id: number;
  canonical_name: string;
  order_name: string | null;
  sku_interno: string | null;
  category: string | null;
  is_active: boolean;
  user_id: number;
  user_email: string;
  user_nome: string;
  user_ruolo: string;
  feedback: string;
  motivo: string | null;
  note: string | null;
  stato: string;
  created_at: string;
}

interface ProductFeedbackReviewModalProps {
  isOpen: boolean;
  onClose: () => void;
  onFeedbackResolved?: () => void;
}

export default function ProductFeedbackReviewModal({ isOpen, onClose, onFeedbackResolved }: ProductFeedbackReviewModalProps) {
  const [feedbacks, setFeedbacks] = useState<FeedbackItem[]>([]);
  const [loading, setLoading] = useState(false);
  const [resolvingId, setResolvingId] = useState<number | null>(null);
  const [actionMessage, setActionMessage] = useState<string | null>(null);

  const headers = getHeaders();

  useEffect(() => {
    if (isOpen) {
      loadPendingFeedbacks();
    }
  // Opening the modal is the intended refresh trigger.
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [isOpen]);

  const loadPendingFeedbacks = async () => {
    setLoading(true);
    setActionMessage(null);
    try {
      const res = await fetch(`${API_BASE}/products/feedbacks/pending`, { headers });
      if (res.ok) {
        const data = await res.json();
        setFeedbacks(data.feedbacks || []);
      }
    } catch (e) {
      console.error(e);
    } finally {
      setLoading(false);
    }
  };

  const handleResolve = async (feedbackId: number, action: 'escludi_prodotto' | 'archivia', productName: string) => {
    const confirmMsg = action === 'escludi_prodotto'
      ? `Confermi di voler DISATTIVARE ed ESCLUDERE il prodotto "${productName}" dal catalogo ordini?`
      : `Confermi di voler archiviare la segnalazione mantenendo il prodotto "${productName}" attivo?`;

    if (!window.confirm(confirmMsg)) return;

    setResolvingId(feedbackId);
    try {
      const res = await fetch(`${API_BASE}/products/feedbacks/${feedbackId}/resolve`, {
        method: 'POST',
        headers: {
          ...headers,
          'Content-Type': 'application/json'
        },
        body: JSON.stringify({ action })
      });

      if (res.ok) {
        const data = await res.json();
        setActionMessage(data.message);
        setFeedbacks(prev => prev.filter(f => f.id !== feedbackId));
        if (onFeedbackResolved) onFeedbackResolved();
      }
    } catch (e) {
      console.error(e);
    } finally {
      setResolvingId(null);
    }
  };

  if (!isOpen) return null;

  return (
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
        maxWidth: '850px',
        maxHeight: '90vh',
        display: 'flex',
        flexDirection: 'column',
        borderRadius: 'var(--radius-lg)',
        border: '1px solid var(--border-glass)',
        boxShadow: 'var(--shadow-pop)',
        overflow: 'hidden'
      }}>
        {/* Modal Header */}
        <div style={{
          padding: '20px 24px',
          borderBottom: '1px solid var(--border-glass)',
          display: 'flex',
          justifyContent: 'space-between',
          alignItems: 'center',
          background: 'var(--bg-inset)'
        }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: '12px' }}>
            <div style={{
              width: '38px',
              height: '38px',
              borderRadius: 'var(--radius-md)',
              background: 'var(--crit-bg)',
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
              color: 'var(--crit)'
            }}>
              <AlertTriangle size={20} />
            </div>
            <div>
              <h3 style={{ margin: 0, fontSize: '1.2rem', color: 'var(--text-primary)' }}>
                Segnalazioni & Feedback Prodotti dai Responsabili
              </h3>
              <p style={{ margin: 0, fontSize: '0.8rem', color: 'var(--text-secondary)' }}>
                Valuta le segnalazioni negative (NO) degli operatori di settore ed escludi i prodotti non graditi.
              </p>
            </div>
          </div>

          <button
            onClick={onClose}
            style={{
              background: 'transparent',
              border: 'none',
              color: 'var(--text-secondary)',
              cursor: 'pointer',
              padding: '6px',
              borderRadius: 'var(--radius-md)'
            }}
          >
            <X size={20} />
          </button>
        </div>

        {/* Action Flash Message */}
        {actionMessage && (
          <div style={{
            padding: '12px 24px',
            background: 'var(--ok-bg)',
            borderBottom: '1px solid var(--ok-border)',
            color: 'var(--ok)',
            fontSize: '0.85rem',
            display: 'flex',
            alignItems: 'center',
            gap: '8px'
          }}>
            <CheckCircle2 size={16} />
            <span>{actionMessage}</span>
          </div>
        )}

        {/* Modal Body */}
        <div style={{ padding: '20px 24px', overflowY: 'auto', flex: 1, display: 'flex', flexDirection: 'column', gap: '14px' }}>
          {loading ? (
            <div style={{ padding: '50px', textAlign: 'center', color: 'var(--text-secondary)' }}>
              <RefreshCw className="spinner" size={26} style={{ margin: '0 auto 10px' }} />
              <div>Caricamento segnalazioni in corso...</div>
            </div>
          ) : feedbacks.length === 0 ? (
            <div style={{ padding: '50px 20px', textAlign: 'center', color: 'var(--text-secondary)' }}>
              <CheckCircle2 size={42} color="var(--ok)" style={{ margin: '0 auto 12px', opacity: 0.8 }} />
              <h4 style={{ margin: '0 0 6px', color: 'var(--text-primary)' }}>Nessuna segnalazione pendente</h4>
              <p style={{ fontSize: '0.85rem', margin: 0 }}>
                I responsabili di settore non hanno inviato nuovi feedback negativi sui prodotti in catalogo.
              </p>
            </div>
          ) : (
            feedbacks.map(item => (
              <div
                key={item.id}
                style={{
                  padding: '16px 20px',
                  borderRadius: 'var(--radius-lg)',
                  background: 'var(--bg-inset)',
                  border: '1px solid var(--crit-border)',
                  display: 'flex',
                  justifyContent: 'space-between',
                  alignItems: 'flex-start',
                  gap: '16px',
                  flexWrap: 'wrap'
                }}
              >
                <div style={{ flex: 1, minWidth: '260px' }}>
                  <div style={{ display: 'flex', alignItems: 'center', gap: '8px', flexWrap: 'wrap' }}>
                    <strong style={{ fontSize: '1rem', color: 'var(--text-primary)' }}>
                      {item.order_name || item.canonical_name}
                    </strong>
                    <span style={{
                      padding: '2px 8px',
                      borderRadius: 'var(--radius-sm)',
                      background: 'var(--crit-bg)',
                      color: 'var(--crit)',
                      fontWeight: 700,
                      fontSize: '0.72rem'
                    }}>
                      👎 FEEDBACK NO
                    </span>
                    {item.category && (
                      <span style={{
                        padding: '2px 8px',
                        borderRadius: 'var(--radius-sm)',
                        background: 'var(--accent-bg)',
                        color: 'var(--accent-text)',
                        fontSize: '0.72rem',
                        fontWeight: 600
                      }}>
                        {item.category}
                      </span>
                    )}
                  </div>

                  {item.order_name && item.canonical_name !== item.order_name && (
                    <div style={{ fontSize: '0.78rem', color: 'var(--text-secondary)', marginTop: '2px' }}>
                      {item.canonical_name}
                    </div>
                  )}

                  <div style={{ display: 'flex', alignItems: 'center', gap: '10px', marginTop: '6px', fontSize: '0.75rem', color: 'var(--text-secondary)' }}>
                    <span>SKU: <code>{item.sku_interno || 'N/D'}</code></span>
                    <span>•</span>
                    <span>Segnalato da: <strong style={{ color: 'var(--text-primary)' }}>{item.user_nome}</strong> ({item.user_ruolo})</span>
                    <span>•</span>
                    <span>{new Date(item.created_at).toLocaleDateString('it-IT', { day: '2-digit', month: '2-digit', year: 'numeric', hour: '2-digit', minute: '2-digit' })}</span>
                  </div>

                  {/* Motivazione & Note */}
                  <div style={{
                    marginTop: '10px',
                    padding: '10px 12px',
                    borderRadius: 'var(--radius-md)',
                    background: 'var(--bg-inset)',
                    border: '1px solid var(--line)',
                    fontSize: '0.85rem'
                  }}>
                    <div style={{ display: 'flex', alignItems: 'center', gap: '6px', color: 'var(--crit)', fontWeight: 700 }}>
                      <MessageSquare size={13} />
                      Motivo: {item.motivo || 'Nessun motivo specificato'}
                    </div>
                    {item.note && (
                      <div style={{ marginTop: '4px', color: 'var(--text-secondary)', fontSize: '0.8rem' }}>
                        "{item.note}"
                      </div>
                    )}
                  </div>
                </div>

                {/* Action Buttons for Admin */}
                <div style={{ display: 'flex', flexDirection: 'column', gap: '8px', minWidth: '170px' }}>
                  <button
                    type="button"
                    disabled={resolvingId === item.id}
                    onClick={() => handleResolve(item.id, 'escludi_prodotto', item.order_name || item.canonical_name)}
                    className="btn"
                    style={{
                      background: 'var(--crit-bg)',
                      border: '1px solid var(--crit-border)',
                      color: 'var(--crit)',
                      padding: '8px 12px',
                      fontSize: '0.82rem',
                      fontWeight: 700,
                      display: 'flex',
                      alignItems: 'center',
                      justifyContent: 'center',
                      gap: '6px'
                    }}
                  >
                    <Trash2 size={14} /> Escludi Prodotto
                  </button>

                  <button
                    type="button"
                    disabled={resolvingId === item.id}
                    onClick={() => handleResolve(item.id, 'archivia', item.order_name || item.canonical_name)}
                    className="btn"
                    style={{
                      background: 'var(--bg-elevated)',
                      border: '1px solid var(--border-glass)',
                      color: 'var(--text-primary)',
                      padding: '8px 12px',
                      fontSize: '0.82rem',
                      display: 'flex',
                      alignItems: 'center',
                      justifyContent: 'center',
                      gap: '6px'
                    }}
                  >
                    <CheckCircle2 size={14} /> Mantieni & Archivia
                  </button>
                </div>
              </div>
            ))
          )}
        </div>

        {/* Modal Footer */}
        <div style={{
          padding: '16px 24px',
          borderTop: '1px solid var(--border-glass)',
          display: 'flex',
          justifyContent: 'space-between',
          alignItems: 'center',
          background: 'var(--bg-inset)'
        }}>
          <button
            onClick={loadPendingFeedbacks}
            className="btn"
            style={{ background: 'transparent', border: '1px solid var(--border-glass)', fontSize: '0.82rem', display: 'flex', alignItems: 'center', gap: '6px' }}
          >
            <RefreshCw size={14} /> Aggiorna Lista
          </button>

          <button
            onClick={onClose}
            className="btn btn-primary"
            style={{ padding: '8px 20px', fontSize: '0.85rem' }}
          >
            Chiudi
          </button>
        </div>
      </div>
    </div>
  );
}
