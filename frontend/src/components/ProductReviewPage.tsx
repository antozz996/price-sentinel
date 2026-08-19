import { useState, useEffect, useMemo } from 'react';
import {
  Star,
  ThumbsUp,
  ThumbsDown,
  Search,
  RefreshCw,
  Boxes,
  CheckCircle2,
  ShieldAlert,
  Send,
} from 'lucide-react';
import { API_BASE, getHeaders } from '../api';

interface UserProfile {
  id: number;
  email: string;
  nome_completo?: string | null;
  ruolo: string;
  ruolo_dettagliato?: string | null;
  settore_abilitato?: string | null;
  location_id?: number | null;
}

interface FeedbackItem {
  id: number;
  user_id: number;
  user_nome: string;
  user_email: string;
  user_ruolo?: string | null;
  feedback: string;
  rating?: number | null;
  motivo?: string | null;
  note?: string | null;
  stato: string;
  created_at: string;
  admin_action?: string | null;
  admin_notes?: string | null;
}

interface ProductReviewItem {
  product_id: number;
  sku_interno?: string | null;
  canonical_name: string;
  order_name?: string | null;
  category?: string | null;
  subcategory?: string | null;
  brand?: string | null;
  comparison_unit?: string | null;
  prezzo_riferimento?: number | null;
  fornitore_abituale?: string | null;
  totale_feedback: number;
  positivi_si: number;
  negativi_no: number;
  rating_medio?: number | null;
  mio_feedback?: FeedbackItem | null;
  recensioni_recenti: FeedbackItem[];
}

const MOTIVI_POSITIVI = [
  'Alta qualità / Resa eccellente',
  'Packaging perfetto',
  'Molto richiesto dai clienti',
  'Prezzo conveniente',
  'Facile conservazione',
  'Consigliato'
];

const MOTIVI_NEGATIVI = [
  'Scarsa resa / Bassa qualità',
  'Packaging difettoso / Gocciola',
  'Scadenza troppo breve',
  'Troppo caro / Fuori mercato',
  'Poco gradito dai clienti',
  'Problemi di conservazione',
  'Da sostituire o escludere'
];

const SECTORS = [
  { id: 'all', label: 'Tutti i Settori', icon: '🌟' },
  { id: 'Beverage', label: 'Beverage', icon: '🍹' },
  { id: 'Materiali di consumo', label: 'Materiali di consumo', icon: '📦' },
  { id: 'Food', label: 'Food', icon: '🍽️' },
];

export default function ProductReviewPage({ userProfile }: { userProfile?: UserProfile }) {
  const [products, setProducts] = useState<ProductReviewItem[]>([]);
  const [loading, setLoading] = useState<boolean>(true);
  const [errorMsg, setErrorMsg] = useState<string | null>(null);

  // Filters
  const [searchTerm, setSearchTerm] = useState<string>('');
  const [selectedSector, setSelectedSector] = useState<string>('all');
  const [reviewFilter, setReviewFilter] = useState<string>('tutti'); // tutti, da_recensire, recensiti, segnalati_no

  // Draft review states per product_id
  const [draftFeedback, setDraftFeedback] = useState<Record<number, string>>({}); // 'SI' | 'NO'
  const [draftRating, setDraftRating] = useState<Record<number, number>>({});
  const [draftMotivo, setDraftMotivo] = useState<Record<number, string>>({});
  const [draftNote, setDraftNote] = useState<Record<number, string>>({});
  const [savingId, setSavingId] = useState<number | null>(null);
  const [successToast, setSuccessToast] = useState<string | null>(null);

  const headers = useMemo(() => getHeaders(), []);

  // Check allowed sectors for user
  const allowedSectors = useMemo(() => {
    if (!userProfile?.settore_abilitato || userProfile.settore_abilitato === 'all') {
      return ['Beverage', 'Materiali di consumo', 'Food'];
    }
    return userProfile.settore_abilitato.split(',').map(s => s.trim()).filter(Boolean);
  }, [userProfile]);

  useEffect(() => {
    loadProducts();
  }, [selectedSector, reviewFilter]);

  async function loadProducts() {
    setLoading(true);
    setErrorMsg(null);
    try {
      const params = new URLSearchParams();
      if (selectedSector !== 'all') params.append('category', selectedSector);
      if (reviewFilter !== 'tutti') params.append('filtro_recensione', reviewFilter);

      const res = await fetch(`${API_BASE}/feedbacks/prodotti?${params.toString()}`, { headers });
      if (!res.ok) throw new Error("Impossibile caricare l'elenco dei prodotti per recensione.");
      const data = await res.json();
      setProducts(Array.isArray(data) ? data : []);

      // Prepopulate drafts with user's existing reviews
      const nextFb: Record<number, string> = {};
      const nextRating: Record<number, number> = {};
      const nextMotivo: Record<number, string> = {};
      const nextNote: Record<number, string> = {};

      data.forEach((p: ProductReviewItem) => {
        if (p.mio_feedback) {
          nextFb[p.product_id] = p.mio_feedback.feedback;
          if (p.mio_feedback.rating) nextRating[p.product_id] = p.mio_feedback.rating;
          if (p.mio_feedback.motivo) nextMotivo[p.product_id] = p.mio_feedback.motivo;
          if (p.mio_feedback.note) nextNote[p.product_id] = p.mio_feedback.note;
        }
      });

      setDraftFeedback(nextFb);
      setDraftRating(nextRating);
      setDraftMotivo(nextMotivo);
      setDraftNote(nextNote);
    } catch (err: any) {
      setErrorMsg(err.message || "Errore di connessione.");
    } finally {
      setLoading(false);
    }
  }

  async function handleSaveReview(productId: number) {
    const fb = draftFeedback[productId] || 'SI';
    const rating = draftRating[productId] || (fb === 'SI' ? 5 : 2);
    const motivo = draftMotivo[productId] || '';
    const note = draftNote[productId] || '';

    setSavingId(productId);
    try {
      const res = await fetch(`${API_BASE}/feedbacks/`, {
        method: 'POST',
        headers: {
          ...headers,
          'Content-Type': 'application/json'
        },
        body: JSON.stringify({
          product_id: productId,
          feedback: fb,
          rating,
          motivo: motivo.trim() || null,
          note: note.trim() || null
        })
      });

      if (!res.ok) {
        const err = await res.json();
        throw new Error(err.detail || "Errore salvataggio recensione.");
      }

      setSuccessToast(`Recensione salvata con successo per l'articolo!`);
      setTimeout(() => setSuccessToast(null), 3000);
      loadProducts();
    } catch (err: any) {
      alert(err.message || "Errore salvataggio.");
    } finally {
      setSavingId(null);
    }
  }

  async function handleAdminDeactivateProduct(_productId: number, feedbackId?: number) {
    if (!window.confirm("Disattivare ed escludere questo prodotto dal catalogo e listino acquisti?")) {
      return;
    }

    try {
      if (feedbackId) {
        await fetch(`${API_BASE}/feedbacks/${feedbackId}/risolvi`, {
          method: 'PATCH',
          headers: { ...headers, 'Content-Type': 'application/json' },
          body: JSON.stringify({ action: 'escluso', disattiva_prodotto: true, admin_notes: 'Escluso da pannello recensioni' })
        });
      }
      setSuccessToast("Prodotto escluso dal catalogo con successo.");
      loadProducts();
    } catch (err: any) {
      alert("Errore durante l'esclusione del prodotto.");
    }
  }

  // Filtered Products by search term
  const filteredProducts = useMemo(() => {
    return products.filter(p => {
      const search = searchTerm.toLowerCase().trim();
      if (!search) return true;
      return p.canonical_name.toLowerCase().includes(search)
        || (p.order_name && p.order_name.toLowerCase().includes(search))
        || (p.sku_interno && p.sku_interno.toLowerCase().includes(search))
        || (p.brand && p.brand.toLowerCase().includes(search));
    });
  }, [products, searchTerm]);

  // Overall KPIs
  const kpis = useMemo(() => {
    const tot = products.length;
    const recensitiDaMe = products.filter(p => p.mio_feedback !== null).length;
    const totaleSi = products.reduce((acc, p) => acc + p.positivi_si, 0);
    const totaleNo = products.reduce((acc, p) => acc + p.negativi_no, 0);
    return { tot, recensitiDaMe, totaleSi, totaleNo };
  }, [products]);

  const isAdmin = userProfile?.ruolo === 'admin' || userProfile?.ruolo_dettagliato === 'admin';

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: '20px' }}>
      {/* Header Banner */}
      <div className="glass-panel" style={{ padding: '24px', display: 'flex', justifyContent: 'space-between', alignItems: 'center', flexWrap: 'wrap', gap: '16px' }}>
        <div>
          <h2 style={{ margin: '0 0 6px 0', display: 'flex', alignItems: 'center', gap: '10px', color: 'white' }}>
            <Star size={26} color="#facc15" fill="#facc15" /> Recensioni & Qualità Prodotti
          </h2>
          <p style={{ margin: 0, color: 'var(--text-secondary)', fontSize: '0.85rem' }}>
            Valuta i prodotti ricevuti e segnala articoli con scarsa resa o difetti di packaging per ottimizzare le decisioni di acquisto del gruppo.
          </p>
        </div>

        <button
          className="btn"
          onClick={loadProducts}
          disabled={loading}
          style={{ background: 'rgba(255, 255, 255, 0.05)', border: '1px solid var(--border-glass)', display: 'flex', alignItems: 'center', gap: '6px' }}
        >
          <RefreshCw size={14} className={loading ? 'spinner' : ''} /> Aggiorna
        </button>
      </div>

      {/* Toast Notification */}
      {errorMsg && (
        <div style={{ padding: '12px 18px', borderRadius: '10px', background: 'rgba(239, 68, 68, 0.15)', border: '1px solid rgba(239, 68, 68, 0.3)', color: '#f87171', fontWeight: 600, fontSize: '0.85rem' }}>
          {errorMsg}
        </div>
      )}

      {/* Toast Notification */}
      {successToast && (
        <div style={{ padding: '12px 18px', borderRadius: '10px', background: 'rgba(16, 185, 129, 0.15)', border: '1px solid rgba(16, 185, 129, 0.3)', color: '#34d399', fontWeight: 600, fontSize: '0.85rem', display: 'flex', alignItems: 'center', gap: '8px' }}>
          <CheckCircle2 size={16} /> {successToast}
        </div>
      )}

      {/* KPI Cards */}
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(220px, 1fr))', gap: '16px' }}>
        <div className="glass-panel" style={{ padding: '18px 20px', borderLeft: '4px solid var(--accent-blue)' }}>
          <div style={{ fontSize: '0.75rem', color: 'var(--text-secondary)', fontWeight: 600, textTransform: 'uppercase' }}>
            Prodotti a Catalogo
          </div>
          <div style={{ fontSize: '1.7rem', fontWeight: 800, color: 'white', margin: '4px 0' }}>
            {kpis.tot}
          </div>
          <div style={{ fontSize: '0.75rem', color: 'var(--text-secondary)' }}>Reparti assegnati</div>
        </div>

        <div className="glass-panel" style={{ padding: '18px 20px', borderLeft: '4px solid #10b981' }}>
          <div style={{ fontSize: '0.75rem', color: 'var(--text-secondary)', fontWeight: 600, textTransform: 'uppercase' }}>
            Apprezzati (Voto SI)
          </div>
          <div style={{ fontSize: '1.7rem', fontWeight: 800, color: '#10b981', margin: '4px 0' }}>
            {kpis.totaleSi}
          </div>
          <div style={{ fontSize: '0.75rem', color: 'var(--text-secondary)' }}>Gradimento positivo confermato</div>
        </div>

        <div className="glass-panel" style={{ padding: '18px 20px', borderLeft: '4px solid #ef4444' }}>
          <div style={{ fontSize: '0.75rem', color: 'var(--text-secondary)', fontWeight: 600, textTransform: 'uppercase' }}>
            Segnalazioni Critiche (NO)
          </div>
          <div style={{ fontSize: '1.7rem', fontWeight: 800, color: '#ef4444', margin: '4px 0' }}>
            {kpis.totaleNo}
          </div>
          <div style={{ fontSize: '0.75rem', color: 'var(--text-secondary)' }}>Articoli da escludere / sostituire</div>
        </div>

        <div className="glass-panel" style={{ padding: '18px 20px', borderLeft: '4px solid #facc15' }}>
          <div style={{ fontSize: '0.75rem', color: 'var(--text-secondary)', fontWeight: 600, textTransform: 'uppercase' }}>
            Le Mie Recensioni
          </div>
          <div style={{ fontSize: '1.7rem', fontWeight: 800, color: '#facc15', margin: '4px 0' }}>
            {kpis.recensitiDaMe} / {kpis.tot}
          </div>
          <div style={{ fontSize: '0.75rem', color: 'var(--text-secondary)' }}>Prodotti valutati dal tuo account</div>
        </div>
      </div>

      {/* Sector Tabs Bar */}
      <div style={{ display: 'flex', gap: '10px', flexWrap: 'wrap', alignItems: 'center' }}>
        {SECTORS
          .filter(sec => sec.id === 'all' ? (allowedSectors.length > 1) : allowedSectors.includes(sec.id))
          .map(sec => {
            const isSelected = selectedSector === sec.id;
            return (
              <button
                key={sec.id}
                type="button"
                onClick={() => setSelectedSector(sec.id)}
                style={{
                  padding: '9px 18px',
                  borderRadius: '30px',
                  border: isSelected ? '2px solid var(--accent-blue)' : '1px solid var(--border-glass)',
                  background: isSelected ? 'rgba(59, 130, 246, 0.15)' : 'rgba(255, 255, 255, 0.02)',
                  color: isSelected ? 'white' : 'var(--text-secondary)',
                  fontWeight: isSelected ? 700 : 500,
                  fontSize: '0.9rem',
                  cursor: 'pointer',
                  display: 'flex',
                  alignItems: 'center',
                  gap: '8px',
                  transition: 'all 0.2s'
                }}
              >
                <span>{sec.icon}</span>
                <span>{sec.label}</span>
              </button>
            );
          })}
      </div>

      {/* Search & Review Status Filter Bar */}
      <div className="glass-panel" style={{ padding: '16px 20px', display: 'flex', gap: '14px', flexWrap: 'wrap', alignItems: 'center' }}>
        <div style={{ flex: '1 1 260px', position: 'relative' }}>
          <Search size={16} color="var(--text-secondary)" style={{ position: 'absolute', left: '12px', top: '50%', transform: 'translateY(-50%)' }} />
          <input
            type="text"
            placeholder="Cerca prodotto, marca o codice SKU..."
            value={searchTerm}
            onChange={e => setSearchTerm(e.target.value)}
            style={{ width: '100%', padding: '9px 12px 9px 36px', background: 'rgba(0,0,0,0.25)', border: '1px solid var(--border-glass)', borderRadius: '8px', color: 'white', fontSize: '0.85rem' }}
          />
        </div>

        {/* Filter State */}
        <select
          value={reviewFilter}
          onChange={e => setReviewFilter(e.target.value)}
          style={{ padding: '9px 14px', background: '#13131c', border: '1px solid var(--border-glass)', borderRadius: '8px', color: 'white', fontSize: '0.85rem' }}
        >
          <option value="tutti">Tutti i prodotti</option>
          <option value="da_recensire">⏳ Da recensire da me</option>
          <option value="recensiti">✅ Già recensiti</option>
          <option value="segnalati_no">👎 Segnalati con voto NO</option>
        </select>

        <div style={{ fontSize: '0.8rem', color: 'var(--text-secondary)', marginLeft: 'auto' }}>
          Mostrati: <strong>{filteredProducts.length}</strong> prodotti
        </div>
      </div>

      {/* Product Review Cards Grid */}
      {loading ? (
        <div style={{ padding: '60px', textAlign: 'center', color: 'var(--text-secondary)' }}>
          <RefreshCw className="spinner" size={26} style={{ margin: '0 auto 10px' }} />
          <div>Caricamento catalogo recensioni...</div>
        </div>
      ) : filteredProducts.length === 0 ? (
        <div className="glass-panel" style={{ padding: '60px 20px', textAlign: 'center', color: 'var(--text-secondary)' }}>
          <Boxes size={40} style={{ margin: '0 auto 12px', opacity: 0.4 }} />
          <h3 style={{ margin: '0 0 6px', color: 'white' }}>Nessun prodotto trovato</h3>
          <p style={{ fontSize: '0.85rem', margin: 0 }}>Modifica i filtri o la ricerca per visualizzare altri articoli.</p>
        </div>
      ) : (
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(360px, 1fr))', gap: '16px' }}>
          {filteredProducts.map(prod => {
            const currentFb = draftFeedback[prod.product_id] || (prod.mio_feedback?.feedback || 'SI');
            const currentRating = draftRating[prod.product_id] || (prod.mio_feedback?.rating || (currentFb === 'SI' ? 5 : 2));
            const currentMotivo = draftMotivo[prod.product_id] || (prod.mio_feedback?.motivo || '');
            const currentNote = draftNote[prod.product_id] || (prod.mio_feedback?.note || '');
            const isSaving = savingId === prod.product_id;
            const hasMyReview = prod.mio_feedback !== null && prod.mio_feedback !== undefined;

            return (
              <div
                key={prod.product_id}
                className="glass-panel"
                style={{
                  padding: '20px',
                  display: 'flex',
                  flexDirection: 'column',
                  justifyContent: 'space-between',
                  gap: '16px',
                  border: hasMyReview ? '1px solid rgba(250, 204, 21, 0.3)' : '1px solid var(--border-glass)',
                  background: hasMyReview ? 'rgba(250, 204, 21, 0.02)' : 'rgba(255, 255, 255, 0.02)',
                  transition: 'all 0.2s'
                }}
              >
                {/* Top Info */}
                <div>
                  <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', gap: '10px' }}>
                    <div>
                      <div style={{ fontWeight: 800, fontSize: '1rem', color: 'white', lineHeight: '1.3' }}>
                        {prod.order_name || prod.canonical_name}
                      </div>
                      {prod.order_name && prod.canonical_name !== prod.order_name && (
                        <div style={{ color: 'var(--text-secondary)', fontSize: '0.75rem', marginTop: '2px' }}>
                          {prod.canonical_name}
                        </div>
                      )}
                    </div>

                    {/* Overall Stats Pill */}
                    <div style={{ textAlign: 'right', flexShrink: 0 }}>
                      <div style={{ display: 'flex', gap: '6px', alignItems: 'center' }}>
                        <span style={{ padding: '2px 6px', borderRadius: '4px', background: 'rgba(16, 185, 129, 0.15)', color: '#34d399', fontSize: '0.72rem', fontWeight: 800 }}>
                          👍 {prod.positivi_si}
                        </span>
                        <span style={{ padding: '2px 6px', borderRadius: '4px', background: 'rgba(239, 68, 68, 0.15)', color: '#f87171', fontSize: '0.72rem', fontWeight: 800 }}>
                          👎 {prod.negativi_no}
                        </span>
                      </div>
                      {prod.rating_medio && (
                        <div style={{ fontSize: '0.75rem', color: '#facc15', fontWeight: 700, marginTop: '2px' }}>
                          ⭐ {prod.rating_medio} / 5
                        </div>
                      )}
                    </div>
                  </div>

                  <div style={{ display: 'flex', gap: '8px', alignItems: 'center', flexWrap: 'wrap', marginTop: '8px', fontSize: '0.75rem' }}>
                    <span style={{ color: 'var(--text-secondary)' }}>
                      SKU: <code>{prod.sku_interno || 'N/D'}</code>
                    </span>
                    {prod.category && (
                      <>
                        <span style={{ color: 'rgba(255,255,255,0.2)' }}>•</span>
                        <span style={{ color: '#93c5fd' }}>{prod.category}</span>
                      </>
                    )}
                    {prod.fornitore_abituale && (
                      <>
                        <span style={{ color: 'rgba(255,255,255,0.2)' }}>•</span>
                        <span style={{ color: 'var(--text-secondary)' }}>Fornitore: <strong style={{ color: 'white' }}>{prod.fornitore_abituale}</strong></span>
                      </>
                    )}
                  </div>
                </div>

                {/* Rating Input Box */}
                <div style={{ background: 'rgba(0, 0, 0, 0.3)', padding: '14px', borderRadius: '10px', border: '1px solid rgba(255,255,255,0.06)', display: 'flex', flexDirection: 'column', gap: '10px' }}>
                  <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                    <span style={{ fontSize: '0.8rem', fontWeight: 700, color: 'white' }}>Il tuo Gradimento:</span>

                    {/* SI / NO Big Toggle */}
                    <div style={{ display: 'flex', gap: '8px' }}>
                      <button
                        type="button"
                        onClick={() => {
                          setDraftFeedback(prev => ({ ...prev, [prod.product_id]: 'SI' }));
                          setDraftRating(prev => ({ ...prev, [prod.product_id]: 5 }));
                        }}
                        style={{
                          padding: '6px 14px',
                          borderRadius: '8px',
                          border: currentFb === 'SI' ? '2px solid #10b981' : '1px solid rgba(255,255,255,0.1)',
                          background: currentFb === 'SI' ? 'rgba(16, 185, 129, 0.2)' : 'rgba(255,255,255,0.02)',
                          color: currentFb === 'SI' ? '#34d399' : 'var(--text-secondary)',
                          fontWeight: 800,
                          fontSize: '0.82rem',
                          cursor: 'pointer',
                          display: 'flex',
                          alignItems: 'center',
                          gap: '6px'
                        }}
                      >
                        <ThumbsUp size={14} /> SI (OK)
                      </button>

                      <button
                        type="button"
                        onClick={() => {
                          setDraftFeedback(prev => ({ ...prev, [prod.product_id]: 'NO' }));
                          setDraftRating(prev => ({ ...prev, [prod.product_id]: 2 }));
                        }}
                        style={{
                          padding: '6px 14px',
                          borderRadius: '8px',
                          border: currentFb === 'NO' ? '2px solid #ef4444' : '1px solid rgba(255,255,255,0.1)',
                          background: currentFb === 'NO' ? 'rgba(239, 68, 68, 0.2)' : 'rgba(255,255,255,0.02)',
                          color: currentFb === 'NO' ? '#f87171' : 'var(--text-secondary)',
                          fontWeight: 800,
                          fontSize: '0.82rem',
                          cursor: 'pointer',
                          display: 'flex',
                          alignItems: 'center',
                          gap: '6px'
                        }}
                      >
                        <ThumbsDown size={14} /> NO (Critico)
                      </button>
                    </div>
                  </div>

                  {/* Stars Rating Selector */}
                  <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                    <span style={{ fontSize: '0.75rem', color: 'var(--text-secondary)' }}>Voto (1-5):</span>
                    <div style={{ display: 'flex', gap: '4px' }}>
                      {[1, 2, 3, 4, 5].map(star => (
                        <button
                          key={star}
                          type="button"
                          onClick={() => setDraftRating(prev => ({ ...prev, [prod.product_id]: star }))}
                          style={{ background: 'transparent', border: 'none', cursor: 'pointer', padding: '2px' }}
                        >
                          <Star
                            size={18}
                            color={star <= currentRating ? '#facc15' : 'rgba(255,255,255,0.2)'}
                            fill={star <= currentRating ? '#facc15' : 'transparent'}
                          />
                        </button>
                      ))}
                    </div>
                  </div>

                  {/* Motivations Tags */}
                  <div>
                    <span style={{ fontSize: '0.72rem', color: 'var(--text-secondary)', display: 'block', marginBottom: '4px' }}>
                      Motivazione veloce:
                    </span>
                    <div style={{ display: 'flex', gap: '6px', flexWrap: 'wrap' }}>
                      {(currentFb === 'SI' ? MOTIVI_POSITIVI : MOTIVI_NEGATIVI).map(m => {
                        const isSelected = currentMotivo === m;
                        return (
                          <button
                            key={m}
                            type="button"
                            onClick={() => setDraftMotivo(prev => ({ ...prev, [prod.product_id]: isSelected ? '' : m }))}
                            style={{
                              padding: '3px 8px',
                              borderRadius: '6px',
                              fontSize: '0.7rem',
                              fontWeight: isSelected ? 700 : 500,
                              background: isSelected ? (currentFb === 'SI' ? 'rgba(16, 185, 129, 0.25)' : 'rgba(239, 68, 68, 0.25)') : 'rgba(255,255,255,0.04)',
                              border: isSelected ? `1px solid ${currentFb === 'SI' ? '#10b981' : '#ef4444'}` : '1px solid rgba(255,255,255,0.06)',
                              color: isSelected ? 'white' : 'var(--text-secondary)',
                              cursor: 'pointer'
                            }}
                          >
                            {m}
                          </button>
                        );
                      })}
                    </div>
                  </div>

                  {/* Notes Textarea */}
                  <textarea
                    placeholder="Note operative e dettagli qualitativi (es. resa in miscelazione, sapore, tenuta scatola)..."
                    value={currentNote}
                    onChange={e => setDraftNote(prev => ({ ...prev, [prod.product_id]: e.target.value }))}
                    rows={2}
                    style={{ width: '100%', padding: '8px 10px', background: 'rgba(0,0,0,0.2)', border: '1px solid var(--border-glass)', borderRadius: '6px', color: 'white', fontSize: '0.78rem', resize: 'vertical' }}
                  />

                  {/* Save Button */}
                  <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginTop: '4px' }}>
                    {hasMyReview ? (
                      <span style={{ fontSize: '0.72rem', color: '#facc15', fontWeight: 600 }}>
                        ⭐ Hai già recensito questo articolo
                      </span>
                    ) : (
                      <span style={{ fontSize: '0.72rem', color: 'var(--text-secondary)' }}>
                        Nessuna recensione inserita
                      </span>
                    )}

                    <button
                      type="button"
                      onClick={() => handleSaveReview(prod.product_id)}
                      disabled={isSaving}
                      className="btn btn-primary"
                      style={{ padding: '6px 14px', fontSize: '0.78rem', display: 'flex', alignItems: 'center', gap: '6px' }}
                    >
                      <Send size={12} />
                      {isSaving ? 'Salvataggio...' : (hasMyReview ? 'Aggiorna Recensione' : 'Invia Recensione')}
                    </button>
                  </div>
                </div>

                {/* Recent Reviews from colleagues / Admin Actions */}
                {prod.recensioni_recenti.length > 0 && (
                  <div style={{ borderTop: '1px solid rgba(255,255,255,0.05)', paddingTop: '10px' }}>
                    <div style={{ fontSize: '0.72rem', color: 'var(--text-secondary)', fontWeight: 700, marginBottom: '6px' }}>
                      Ultime recensioni del team ({prod.recensioni_recenti.length}):
                    </div>
                    <div style={{ display: 'flex', flexDirection: 'column', gap: '6px', maxHeight: '110px', overflowY: 'auto' }}>
                      {prod.recensioni_recenti.map(r => (
                        <div key={r.id} style={{ background: 'rgba(255,255,255,0.02)', padding: '6px 8px', borderRadius: '6px', fontSize: '0.72rem', display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start' }}>
                          <div>
                            <div style={{ fontWeight: 600, color: 'white' }}>
                              {r.feedback === 'SI' ? '👍' : '👎'} {r.user_nome}
                              {r.rating && <span style={{ color: '#facc15', marginLeft: '6px' }}>⭐ {r.rating}/5</span>}
                            </div>
                            {r.motivo && <div style={{ color: r.feedback === 'SI' ? '#34d399' : '#f87171', fontWeight: 600 }}>{r.motivo}</div>}
                            {r.note && <div style={{ color: 'var(--text-secondary)', fontStyle: 'italic', marginTop: '2px' }}>"{r.note}"</div>}
                          </div>
                          <span style={{ fontSize: '0.65rem', color: 'var(--text-secondary)' }}>
                            {new Date(r.created_at).toLocaleDateString()}
                          </span>
                        </div>
                      ))}
                    </div>
                  </div>
                )}

                {/* Admin Quick Deactivation Action */}
                {isAdmin && prod.negativi_no > 0 && (
                  <div style={{ borderTop: '1px solid rgba(239, 68, 68, 0.2)', paddingTop: '10px', display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                    <span style={{ fontSize: '0.72rem', color: '#f87171' }}>
                      Segnalato con {prod.negativi_no} voti negativi
                    </span>
                    <button
                      type="button"
                      onClick={() => handleAdminDeactivateProduct(prod.product_id, prod.recensioni_recenti.find(r => r.feedback === 'NO')?.id)}
                      className="btn"
                      style={{ background: 'rgba(239,68,68,0.15)', border: '1px solid rgba(239,68,68,0.3)', color: '#ef4444', padding: '4px 10px', fontSize: '0.75rem', display: 'flex', alignItems: 'center', gap: '4px' }}
                    >
                      <ShieldAlert size={13} /> Disattiva dal Listino
                    </button>
                  </div>
                )}
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}
