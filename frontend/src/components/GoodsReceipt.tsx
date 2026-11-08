import { useState, useEffect, useMemo } from 'react';
import {
  PackageCheck,
  CheckCircle2,
  AlertTriangle,
  Search,
  RefreshCw,
  Calendar,
  Boxes,
  Clock,
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

interface OrderSummary {
  id: number;
  fornitore_id: number;
  fornitore_nome: string;
  location_id: number;
  location_nome: string;
  user_id?: number | null;
  user_nome?: string | null;
  user_ruolo?: string | null;
  settore: string;
  data_ordine: string | null;
  data_consegna: string | null;
  note: string | null;
  spesa_totale: number;
  stato: string;
  stato_ricezione: string;
  data_ricezione?: string | null;
  ricevuto_da_nome?: string | null;
  note_ricezione?: string | null;
  n_righe: number;
  totale_colli: number;
  totale_colli_ricevuti: number;
}

interface OrderLineItem {
  id: number;
  product_id?: number | null;
  sku_interno: string;
  descrizione: string;
  quantita: number;
  quantita_ricevuta: number;
  uom: string;
  prezzo_pattuito: number;
  prezzo_inserito: number;
  subtotale: number;
  stato_ottimizzazione: string;
  stato_riga: string; // conforme, parziale, mancante, danneggiato, in_attesa
  note_riga?: string | null;
}

interface OrderDetail extends OrderSummary {
  fornitore_piva?: string | null;
  fornitore_telefono?: string | null;
  fornitore_email?: string | null;
  whatsapp_message?: string | null;
  righe: OrderLineItem[];
}

export default function GoodsReceipt({ userProfile }: { userProfile?: UserProfile }) {
  void userProfile;
  const [orders, setOrders] = useState<OrderSummary[]>([]);
  const [loading, setLoading] = useState<boolean>(true);
  const [errorMsg, setErrorMsg] = useState<string | null>(null);

  // Filters
  const [searchQuery, setSearchQuery] = useState<string>('');
  const [selectedStatus, setSelectedStatus] = useState<string>('all');
  const [selectedSector, setSelectedSector] = useState<string>('all');
  const [selectedLocation, setSelectedLocation] = useState<string>('all');

  // Receipt Modal State
  const [activeOrder, setActiveOrder] = useState<OrderDetail | null>(null);
  const [loadingDetail, setLoadingDetail] = useState<boolean>(false);
  const [savingReceipt, setSavingReceipt] = useState<boolean>(false);
  const [receiptSuccessMsg, setReceiptSuccessMsg] = useState<string | null>(null);

  // Editable receipt state
  const [receiptLines, setReceiptLines] = useState<Record<number, { qty: number; status: string; note: string }>>({});
  const [globalReceiptStatus, setGlobalReceiptStatus] = useState<string>('ricevuto_conforme');
  const [globalReceiptNotes, setGlobalReceiptNotes] = useState<string>('');

  const headers = useMemo(() => getHeaders(), []);

  useEffect(() => {
    loadOrders();
  // Initial order bootstrap; receipt mutations invoke reload explicitly.
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  async function loadOrders() {
    setLoading(true);
    setErrorMsg(null);
    try {
      const res = await fetch(`${API_BASE}/ordini/`, { headers });
      if (!res.ok) throw new Error("Impossibile caricare il registro ordini.");
      const data = await res.json();
      setOrders(Array.isArray(data) ? data : []);
    } catch (err: any) {
      setErrorMsg(err.message || "Errore di connessione al server.");
    } finally {
      setLoading(false);
    }
  }

  async function openReceiptModal(orderId: number) {
    setLoadingDetail(true);
    setReceiptSuccessMsg(null);
    try {
      const res = await fetch(`${API_BASE}/ordini/${orderId}`, { headers });
      if (!res.ok) throw new Error("Impossibile caricare i dettagli dell'ordine.");
      const data: OrderDetail = await res.json();
      setActiveOrder(data);

      // Initialize line receipt states
      const linesState: Record<number, { qty: number; status: string; note: string }> = {};
      let hasDiscrepancy = false;

      data.righe.forEach(r => {
        const receivedQty = r.quantita_ricevuta !== undefined && r.quantita_ricevuta !== null
          ? r.quantita_ricevuta
          : r.quantita;
        
        let st = r.stato_riga || 'conforme';
        if (st === 'in_attesa') {
          st = receivedQty === r.quantita ? 'conforme' : (receivedQty === 0 ? 'mancante' : 'parziale');
        }
        if (st !== 'conforme') hasDiscrepancy = true;

        linesState[r.id] = {
          qty: receivedQty,
          status: st,
          note: r.note_riga || ''
        };
      });

      setReceiptLines(linesState);
      setGlobalReceiptStatus(
        data.stato_ricezione && data.stato_ricezione !== 'da_ricevere'
          ? data.stato_ricezione
          : (hasDiscrepancy ? 'ricevuto_con_riserva' : 'ricevuto_conforme')
      );
      setGlobalReceiptNotes(data.note_ricezione || '');
    } catch (err: any) {
      alert(err.message || "Errore apertura scarico merci.");
    } finally {
      setLoadingDetail(false);
    }
  }

  function handleSetAllConforme() {
    if (!activeOrder) return;
    const nextState: Record<number, { qty: number; status: string; note: string }> = {};
    activeOrder.righe.forEach(r => {
      nextState[r.id] = {
        qty: r.quantita,
        status: 'conforme',
        note: ''
      };
    });
    setReceiptLines(nextState);
    setGlobalReceiptStatus('ricevuto_conforme');
  }

  function handleLineQtyChange(rigaId: number, orderedQty: number, nextQty: number) {
    const safeQty = Math.max(0, Number(nextQty) || 0);
    setReceiptLines(prev => {
      const curr = prev[rigaId] || { qty: orderedQty, status: 'conforme', note: '' };
      let newStatus = curr.status;
      if (safeQty === orderedQty) newStatus = 'conforme';
      else if (safeQty === 0) newStatus = 'mancante';
      else if (safeQty < orderedQty) newStatus = 'parziale';
      else if (safeQty > orderedQty) newStatus = 'conforme';

      return {
        ...prev,
        [rigaId]: {
          ...curr,
          qty: safeQty,
          status: newStatus
        }
      };
    });
  }

  function handleLineStatusChange(rigaId: number, status: string) {
    setReceiptLines(prev => ({
      ...prev,
      [rigaId]: {
        ...prev[rigaId],
        status
      }
    }));
  }

  function handleLineNoteChange(rigaId: number, note: string) {
    setReceiptLines(prev => ({
      ...prev,
      [rigaId]: {
        ...prev[rigaId],
        note
      }
    }));
  }

  async function handleSaveReceipt() {
    if (!activeOrder) return;
    setSavingReceipt(true);
    try {
      const payload = {
        stato_ricezione: globalReceiptStatus,
        note_ricezione: globalReceiptNotes.trim() || null,
        righe: activeOrder.righe.map(r => {
          const l = receiptLines[r.id] || { qty: r.quantita, status: 'conforme', note: '' };
          return {
            riga_id: r.id,
            quantita_ricevuta: l.qty,
            stato_riga: l.status,
            note_riga: l.note.trim() || null
          };
        })
      };

      const res = await fetch(`${API_BASE}/ordini/${activeOrder.id}/ricezione`, {
        method: 'POST',
        headers: {
          ...headers,
          'Content-Type': 'application/json'
        },
        body: JSON.stringify(payload)
      });

      if (!res.ok) {
        const err = await res.json();
        throw new Error(err.detail || "Errore salvataggio ricezione merci.");
      }

      setReceiptSuccessMsg("✅ Scarico e ricezione merci registrati con successo!");
      loadOrders();
      setTimeout(() => {
        setActiveOrder(null);
      }, 1200);
    } catch (err: any) {
      alert(err.message || "Errore durante il salvataggio.");
    } finally {
      setSavingReceipt(false);
    }
  }

  // Filtered Orders
  const filteredOrders = useMemo(() => {
    return orders.filter(o => {
      const matchSearch = !searchQuery.trim()
        || String(o.id).includes(searchQuery.trim())
        || o.fornitore_nome.toLowerCase().includes(searchQuery.toLowerCase())
        || o.location_nome.toLowerCase().includes(searchQuery.toLowerCase())
        || (o.settore && o.settore.toLowerCase().includes(searchQuery.toLowerCase()));

      const matchStatus = selectedStatus === 'all'
        || (selectedStatus === 'da_ricevere' && (!o.stato_ricezione || o.stato_ricezione === 'da_ricevere'))
        || o.stato_ricezione === selectedStatus;

      const matchSector = selectedSector === 'all' || o.settore === selectedSector;
      const matchLocation = selectedLocation === 'all' || String(o.location_id) === selectedLocation;

      return matchSearch && matchStatus && matchSector && matchLocation;
    });
  }, [orders, searchQuery, selectedStatus, selectedSector, selectedLocation]);

  // Unique Sedi & Settori for dropdown filters
  const uniqueLocations = useMemo(() => {
    const map = new Map<number, string>();
    orders.forEach(o => map.set(o.location_id, o.location_nome));
    return Array.from(map.entries());
  }, [orders]);

  const uniqueSectors = useMemo(() => {
    const set = new Set<string>();
    orders.forEach(o => { if (o.settore) set.add(o.settore); });
    return Array.from(set);
  }, [orders]);

  // KPI calculations
  const kpiStats = useMemo(() => {
    const daRicevere = orders.filter(o => !o.stato_ricezione || o.stato_ricezione === 'da_ricevere').length;
    const conformi = orders.filter(o => o.stato_ricezione === 'ricevuto_conforme').length;
    const conRiserva = orders.filter(o => o.stato_ricezione === 'ricevuto_con_riserva' || o.stato_ricezione === 'ricevuto_parziale').length;
    const spesaTotale = orders.reduce((sum, o) => sum + o.spesa_totale, 0);
    return { daRicevere, conformi, conRiserva, spesaTotale };
  }, [orders]);

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: '20px' }}>
      {/* Header Banner */}
      <div className="glass-panel" style={{ padding: '24px', display: 'flex', justifyContent: 'space-between', alignItems: 'center', flexWrap: 'wrap', gap: '16px' }}>
        <div>
          <h2 style={{ margin: '0 0 6px 0', display: 'flex', alignItems: 'center', gap: '10px', color: 'var(--text-primary)' }}>
            <PackageCheck size={26} color="var(--primary-color)" /> Ricezione & Scarico Merci
          </h2>
          <p style={{ margin: 0, color: 'var(--text-secondary)', fontSize: '0.85rem' }}>
            Convalida e confronta quanto ordinato vs quanto effettivamente scaricato dai corrieri e fornitori per ciascuna sede.
          </p>
        </div>

        <button
          className="btn"
          onClick={loadOrders}
          disabled={loading || loadingDetail}
          style={{ background: 'var(--bg-elevated)', border: '1px solid var(--line)', display: 'flex', alignItems: 'center', gap: '6px' }}
        >
          <RefreshCw size={14} className={(loading || loadingDetail) ? 'spinner' : ''} /> Aggiorna
        </button>
      </div>

      {errorMsg && (
        <div style={{ padding: '12px 18px', borderRadius: 'var(--radius-md)', background: 'var(--crit-bg)', border: '1px solid var(--crit-border)', color: 'var(--crit)', fontWeight: 600, fontSize: '0.85rem' }}>
          {errorMsg}
        </div>
      )}

      {/* KPI Cards */}
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(220px, 1fr))', gap: '16px' }}>
        <div className="glass-panel" style={{ padding: '18px 20px', borderLeft: '4px solid var(--warn)' }}>
          <div style={{ fontSize: '0.75rem', color: 'var(--text-secondary)', fontWeight: 600, textTransform: 'uppercase' }}>
            In Attesa di Scarico
          </div>
          <div style={{ fontFamily: 'var(--font-mono)', fontVariantNumeric: 'tabular-nums', fontSize: '1.7rem', fontWeight: 600, color: 'var(--warn)', margin: '4px 0' }}>
            {kpiStats.daRicevere}
          </div>
          <div style={{ fontSize: '0.75rem', color: 'var(--text-secondary)' }}>Ordini da validare all'arrivo</div>
        </div>

        <div className="glass-panel" style={{ padding: '18px 20px', borderLeft: '4px solid var(--ok)' }}>
          <div style={{ fontSize: '0.75rem', color: 'var(--text-secondary)', fontWeight: 600, textTransform: 'uppercase' }}>
            Ricevuti Conformi
          </div>
          <div style={{ fontFamily: 'var(--font-mono)', fontVariantNumeric: 'tabular-nums', fontSize: '1.7rem', fontWeight: 600, color: 'var(--ok)', margin: '4px 0' }}>
            {kpiStats.conformi}
          </div>
          <div style={{ fontSize: '0.75rem', color: 'var(--text-secondary)' }}>Quantità e colli perfetti</div>
        </div>

        <div className="glass-panel" style={{ padding: '18px 20px', borderLeft: '4px solid var(--crit)' }}>
          <div style={{ fontSize: '0.75rem', color: 'var(--text-secondary)', fontWeight: 600, textTransform: 'uppercase' }}>
            Con Riserva / Parziali
          </div>
          <div style={{ fontFamily: 'var(--font-mono)', fontVariantNumeric: 'tabular-nums', fontSize: '1.7rem', fontWeight: 600, color: 'var(--crit)', margin: '4px 0' }}>
            {kpiStats.conRiserva}
          </div>
          <div style={{ fontSize: '0.75rem', color: 'var(--text-secondary)' }}>Colli mancanti o danneggiati</div>
        </div>

        <div className="glass-panel" style={{ padding: '18px 20px', borderLeft: '4px solid var(--accent-blue)' }}>
          <div style={{ fontSize: '0.75rem', color: 'var(--text-secondary)', fontWeight: 600, textTransform: 'uppercase' }}>
            Valore Totale Ordini
          </div>
          <div style={{ fontFamily: 'var(--font-mono)', fontVariantNumeric: 'tabular-nums', fontSize: '1.7rem', fontWeight: 600, color: 'var(--text-primary)', margin: '4px 0' }}>
            € {kpiStats.spesaTotale.toLocaleString('it-IT', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}
          </div>
          <div style={{ fontSize: '0.75rem', color: 'var(--text-secondary)' }}>Tutti i reparti gestiti</div>
        </div>
      </div>

      {/* Filter Toolbar */}
      <div className="glass-panel" style={{ padding: '16px 20px', display: 'flex', gap: '14px', flexWrap: 'wrap', alignItems: 'center' }}>
        <div style={{ flex: '1 1 240px', position: 'relative' }}>
          <Search size={16} color="var(--text-secondary)" style={{ position: 'absolute', left: '12px', top: '50%', transform: 'translateY(-50%)' }} />
          <input
            type="text"
            placeholder="Cerca per ID ordine, fornitore, sede..."
            value={searchQuery}
            onChange={e => setSearchQuery(e.target.value)}
            style={{ width: '100%', padding: '9px 12px 9px 36px', background: 'var(--bg-inset)', border: '1px solid var(--line)', borderRadius: 'var(--radius-sm)', color: 'var(--text-primary)', fontSize: '0.85rem' }}
          />
        </div>

        {/* Status Filter */}
        <select
          value={selectedStatus}
          onChange={e => setSelectedStatus(e.target.value)}
          style={{ padding: '9px 12px', background: 'var(--bg-inset)', border: '1px solid var(--line)', borderRadius: 'var(--radius-sm)', color: 'var(--text-primary)', fontSize: '0.85rem' }}
        >
          <option value="all">Tutti gli stati ricezione</option>
          <option value="da_ricevere">⏳ In attesa di scarico</option>
          <option value="ricevuto_conforme">✅ Ricevuto Conforme</option>
          <option value="ricevuto_parziale">⚠️ Ricevuto Parziale</option>
          <option value="ricevuto_con_riserva">🚨 Ricevuto con Riserva</option>
        </select>

        {/* Sector Filter */}
        <select
          value={selectedSector}
          onChange={e => setSelectedSector(e.target.value)}
          style={{ padding: '9px 12px', background: 'var(--bg-inset)', border: '1px solid var(--line)', borderRadius: 'var(--radius-sm)', color: 'var(--text-primary)', fontSize: '0.85rem' }}
        >
          <option value="all">Tutti i settori</option>
          {uniqueSectors.map(s => (
            <option key={s} value={s}>{s}</option>
          ))}
        </select>

        {/* Location Filter */}
        <select
          value={selectedLocation}
          onChange={e => setSelectedLocation(e.target.value)}
          style={{ padding: '9px 12px', background: 'var(--bg-inset)', border: '1px solid var(--line)', borderRadius: 'var(--radius-sm)', color: 'var(--text-primary)', fontSize: '0.85rem' }}
        >
          <option value="all">Tutte le sedi</option>
          {uniqueLocations.map(([id, name]) => (
            <option key={id} value={String(id)}>{name}</option>
          ))}
        </select>

        <div style={{ fontSize: '0.8rem', color: 'var(--text-secondary)', marginLeft: 'auto' }}>
          Trovati: <strong>{filteredOrders.length}</strong> ordini
        </div>
      </div>

      {/* Orders List Table */}
      <div className="glass-panel" style={{ padding: '0', overflow: 'hidden' }}>
        {loading ? (
          <div style={{ padding: '60px', textAlign: 'center', color: 'var(--text-secondary)' }}>
            <RefreshCw className="spinner" size={26} style={{ margin: '0 auto 10px' }} />
            <div>Caricamento registro ordini per ricezione...</div>
          </div>
        ) : filteredOrders.length === 0 ? (
          <div style={{ padding: '60px', textAlign: 'center', color: 'var(--text-secondary)' }}>
            <Boxes size={36} style={{ margin: '0 auto 10px', opacity: 0.4 }} />
            <h4 style={{ margin: '0 0 4px', color: 'var(--text-primary)' }}>Nessun ordine trovato</h4>
            <p style={{ margin: 0, fontSize: '0.85rem' }}>Nessun ordine corrisponde ai filtri di ricerca applicati.</p>
          </div>
        ) : (
          <div style={{ overflowX: 'auto' }}>
            <table className="ds-table" style={{ width: '100%', borderCollapse: 'collapse', textAlign: 'left', fontSize: '0.85rem' }}>
              <thead>
                <tr style={{ background: 'var(--bg-inset)', borderBottom: '1px solid var(--line)', color: 'var(--text-secondary)' }}>
                  <th style={{ padding: '14px 16px' }}>ID</th>
                  <th style={{ padding: '14px 16px' }}>Sede Destinazione</th>
                  <th style={{ padding: '14px 16px' }}>Fornitore</th>
                  <th style={{ padding: '14px 16px' }}>Settore</th>
                  <th style={{ padding: '14px 16px' }}>Data Consegna</th>
                  <th style={{ padding: '14px 16px' }}>Colli Ordinati / Ricevuti</th>
                  <th style={{ padding: '14px 16px' }}>Importo</th>
                  <th style={{ padding: '14px 16px' }}>Stato Scarico</th>
                  <th style={{ padding: '14px 16px', textAlign: 'right' }}>Azione</th>
                </tr>
              </thead>
              <tbody>
                {filteredOrders.map(o => {
                  const isDaRicevere = !o.stato_ricezione || o.stato_ricezione === 'da_ricevere';
                  const isConforme = o.stato_ricezione === 'ricevuto_conforme';
                  const isRiserva = o.stato_ricezione === 'ricevuto_con_riserva' || o.stato_ricezione === 'ricevuto_parziale';

                  return (
                    <tr
                      key={o.id}
                      style={{
                        borderBottom: '1px solid var(--line)',
                        transition: 'background 0.2s',
                        background: isRiserva ? 'var(--crit-bg)' : (isDaRicevere ? 'var(--warn-bg)' : 'transparent')
                      }}
                      className="table-row-hover"
                    >
                      <td style={{ padding: '14px 16px', fontWeight: 700, color: 'var(--accent-text)', fontFamily: 'var(--font-mono)' }}>
                        #{o.id}
                      </td>
                      <td style={{ padding: '14px 16px' }}>
                        <div style={{ fontWeight: 600, color: 'var(--text-primary)' }}>{o.location_nome}</div>
                        <div style={{ fontSize: '0.72rem', color: 'var(--text-secondary)' }}>Emesso da: {o.user_nome || 'Operatore'}</div>
                      </td>
                      <td style={{ padding: '14px 16px' }}>
                        <strong style={{ color: 'var(--text-primary)' }}>{o.fornitore_nome}</strong>
                      </td>
                      <td style={{ padding: '14px 16px' }}>
                        <span style={{
                          padding: '3px 8px',
                          borderRadius: '999px',
                          background: o.settore === 'Beverage' ? 'var(--accent-bg)' : (o.settore === 'Materiali di consumo' ? 'var(--ok-bg)' : 'var(--warn-bg)'),
                          color: o.settore === 'Beverage' ? 'var(--accent-text)' : (o.settore === 'Materiali di consumo' ? 'var(--ok)' : 'var(--warn)'),
                          fontSize: '0.75rem',
                          fontWeight: 700
                        }}>
                          {o.settore || 'Generico'}
                        </span>
                      </td>
                      <td style={{ padding: '14px 16px' }}>
                        <div style={{ color: 'var(--text-primary)', display: 'flex', alignItems: 'center', gap: '4px' }}>
                          <Calendar size={13} color="var(--text-secondary)" />
                          {o.data_consegna || 'N/D'}
                        </div>
                      </td>
                      <td style={{ padding: '14px 16px' }}>
                        <span style={{ fontWeight: 700, color: 'var(--text-primary)', fontFamily: 'var(--font-mono)', fontVariantNumeric: 'tabular-nums' }}>{o.totale_colli}</span> colli
                        {!isDaRicevere && (
                          <span style={{ color: isConforme ? 'var(--ok)' : 'var(--warn)', fontSize: '0.75rem', marginLeft: '6px', fontWeight: 600 }}>
                            (scaricati: {o.totale_colli_ricevuti})
                          </span>
                        )}
                      </td>
                      <td style={{ padding: '14px 16px', fontWeight: 700, color: 'var(--status-green)' }}>
                        € {o.spesa_totale.toFixed(2)}
                      </td>
                      <td style={{ padding: '14px 16px' }}>
                        {isDaRicevere ? (
                          <span style={{ padding: '3px 9px', borderRadius: '999px', background: 'var(--warn-bg)', color: 'var(--warn)', border: '1px solid var(--warn-border)', fontSize: '0.75rem', fontWeight: 700, display: 'inline-flex', alignItems: 'center', gap: '4px' }}>
                            <Clock size={11} /> Da Ricevere
                          </span>
                        ) : isConforme ? (
                          <span style={{ padding: '3px 9px', borderRadius: '999px', background: 'var(--ok-bg)', color: 'var(--ok)', border: '1px solid var(--ok-border)', fontSize: '0.75rem', fontWeight: 700, display: 'inline-flex', alignItems: 'center', gap: '4px' }}>
                            <CheckCircle2 size={11} /> Conforme
                          </span>
                        ) : (
                          <span style={{ padding: '3px 9px', borderRadius: '999px', background: 'var(--crit-bg)', color: 'var(--crit)', border: '1px solid var(--crit-border)', fontSize: '0.75rem', fontWeight: 700, display: 'inline-flex', alignItems: 'center', gap: '4px' }}>
                            <AlertTriangle size={11} /> Con Riserva
                          </span>
                        )}
                      </td>
                      <td style={{ padding: '14px 16px', textAlign: 'right' }}>
                        <button
                          onClick={() => openReceiptModal(o.id)}
                          className={isDaRicevere ? "btn btn-primary" : "btn"}
                          style={{
                            padding: '6px 14px',
                            fontSize: '0.8rem',
                            display: 'inline-flex',
                            alignItems: 'center',
                            gap: '6px',
                            background: isDaRicevere ? undefined : 'var(--bg-elevated)',
                            border: isDaRicevere ? undefined : '1px solid var(--line)'
                          }}
                        >
                          <PackageCheck size={14} />
                          {isDaRicevere ? 'Check Scarico Merci' : 'Dettagli / Modifica'}
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

      {/* Interactive Modal: Check Scarico Merci */}
      {activeOrder && (
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
          zIndex: 1000,
          padding: '20px'
        }}>
          <div className="glass-panel" style={{
            width: '100%',
            maxWidth: '900px',
            maxHeight: '90vh',
            background: 'var(--bg-card)',
            border: '1px solid var(--line-strong)',
            borderRadius: 'var(--radius-lg)',
            padding: '28px',
            display: 'flex',
            flexDirection: 'column',
            gap: '18px',
            overflowY: 'auto',
            boxShadow: 'var(--shadow-pop)'
          }}>
            {/* Modal Header */}
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', borderBottom: '1px solid var(--line)', paddingBottom: '14px' }}>
              <div>
                <div style={{ display: 'flex', alignItems: 'center', gap: '10px' }}>
                  <PackageCheck size={26} color="var(--primary-color)" />
                  <h3 style={{ margin: 0, color: 'var(--text-primary)', fontSize: '1.25rem' }}>
                    Check Scarico Merci — Ordine #{activeOrder.id}
                  </h3>
                  <span style={{ padding: '3px 8px', borderRadius: 'var(--radius-sm)', background: 'var(--accent-bg)', color: 'var(--accent-text)', fontSize: '0.75rem', fontWeight: 700, fontFamily: 'var(--font-mono)' }}>
                    {activeOrder.settore}
                  </span>
                </div>
                <div style={{ fontSize: '0.8rem', color: 'var(--text-secondary)', marginTop: '4px', display: 'flex', gap: '12px', flexWrap: 'wrap' }}>
                  <span>Sede: <strong style={{ color: 'var(--text-primary)' }}>{activeOrder.location_nome}</strong></span>
                  <span>• Fornitore: <strong style={{ color: 'var(--text-primary)' }}>{activeOrder.fornitore_nome}</strong></span>
                  {activeOrder.fornitore_telefono && <span>• 📞 {activeOrder.fornitore_telefono}</span>}
                  <span>• Consegna richiesta: <strong>{activeOrder.data_consegna || 'N/D'}</strong></span>
                </div>
              </div>

              <button
                type="button"
                onClick={() => setActiveOrder(null)}
                style={{ background: 'transparent', border: 'none', color: 'var(--text-secondary)', cursor: 'pointer', fontSize: '1.2rem', padding: '4px' }}
              >
                ✕
              </button>
            </div>

            {receiptSuccessMsg && (
              <div style={{ padding: '12px 16px', borderRadius: 'var(--radius-md)', background: 'var(--ok-bg)', border: '1px solid var(--ok-border)', color: 'var(--ok)', fontSize: '0.85rem', fontWeight: 600 }}>
                {receiptSuccessMsg}
              </div>
            )}

            {/* Quick Action Button: Tutto Conforme */}
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', background: 'var(--bg-inset)', padding: '12px 16px', borderRadius: 'var(--radius-md)', border: '1px solid var(--line)' }}>
              <div>
                <div style={{ fontWeight: 700, color: 'var(--text-primary)', fontSize: '0.88rem' }}>Controllo Veloce Scarico</div>
                <div style={{ fontSize: '0.75rem', color: 'var(--text-secondary)' }}>Se tutti i colli scaricati corrispondono esattamente alla bolla/ordine, valida con 1 click.</div>
              </div>
              <button
                type="button"
                onClick={handleSetAllConforme}
                className="btn btn-primary"
                style={{ display: 'flex', alignItems: 'center', gap: '6px', padding: '8px 16px', fontSize: '0.8rem', background: 'var(--ok)', borderColor: 'var(--ok)' }}
              >
                <CheckCircle2 size={15} /> Tutto Conforme al 100%
              </button>
            </div>

            {/* Order Lines Checklist */}
            <div style={{ display: 'flex', flexDirection: 'column', gap: '10px' }}>
              <div style={{ fontSize: '0.85rem', fontWeight: 700, color: 'var(--text-secondary)' }}>
                Articoli Ordinati & Quantità Effettivamente Ricevuta:
              </div>

              {activeOrder.righe.map(r => {
                const lineState = receiptLines[r.id] || { qty: r.quantita, status: 'conforme', note: '' };
                const isDiscrepant = lineState.qty !== r.quantita || lineState.status !== 'conforme';

                return (
                  <div
                    key={r.id}
                    style={{
                      padding: '14px 16px',
                      borderRadius: 'var(--radius-md)',
                      background: isDiscrepant ? 'var(--crit-bg)' : 'var(--bg-inset)',
                      border: isDiscrepant ? '1px solid var(--crit-border)' : '1px solid var(--line)',
                      display: 'flex',
                      flexDirection: 'column',
                      gap: '10px',
                      transition: 'all 0.2s'
                    }}
                  >
                    <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', flexWrap: 'wrap', gap: '10px' }}>
                      <div>
                        <div style={{ fontWeight: 700, color: 'var(--text-primary)', fontSize: '0.92rem', display: 'flex', alignItems: 'center', gap: '8px', flexWrap: 'wrap' }}>
                          <span>{r.descrizione}</span>
                          {(r.stato_ottimizzazione === 'omaggio' || r.prezzo_inserito === 0 || (r as any).is_omaggio) && (
                            <span style={{
                              padding: '2px 8px', borderRadius: 'var(--radius-sm)',
                              background: 'var(--ok-bg)', color: 'var(--ok)',
                              fontSize: '0.72rem', fontWeight: 700, border: '1px solid var(--ok-border)'
                            }}>
                              🎁 OMAGGIO (Promo 5+1)
                            </span>
                          )}
                        </div>
                        <div style={{ fontSize: '0.72rem', color: 'var(--text-secondary)', marginTop: '2px' }}>
                          SKU: <code>{r.sku_interno}</code> • Prezzo: {(r.stato_ottimizzazione === 'omaggio' || r.prezzo_inserito === 0 || (r as any).is_omaggio) ? 'GRATIS (€ 0,00)' : `€ ${r.prezzo_inserito.toFixed(2)}`} /{r.uom}
                        </div>
                      </div>

                      {/* Quantity Check Counter */}
                      <div style={{ display: 'flex', alignItems: 'center', gap: '14px' }}>
                        <div style={{ textAlign: 'right' }}>
                          <div style={{ fontSize: '0.72rem', color: 'var(--text-secondary)' }}>Ordinati</div>
                          <div style={{ fontWeight: 700, fontSize: '1rem', color: 'var(--text-primary)', fontFamily: 'var(--font-mono)', fontVariantNumeric: 'tabular-nums' }}>
                            {r.quantita} <span style={{ fontSize: '0.75rem', fontWeight: 500 }}>{r.uom}</span>
                          </div>
                        </div>

                        <div style={{ display: 'flex', alignItems: 'center', gap: '6px', background: 'var(--bg-inset)', padding: '4px 8px', borderRadius: 'var(--radius-sm)', border: '1px solid var(--line)' }}>
                          <span style={{ fontSize: '0.75rem', color: 'var(--text-secondary)', marginRight: '4px' }}>Scaricati:</span>
                          <button
                            type="button"
                            onClick={() => handleLineQtyChange(r.id, r.quantita, lineState.qty - 1)}
                            style={{ width: '26px', height: '26px', borderRadius: 'var(--radius-sm)', background: 'var(--bg-elevated)', border: 'none', color: 'var(--text-primary)', cursor: 'pointer', fontWeight: 700 }}
                          >
                            -
                          </button>
                          <input
                            type="number"
                            min="0"
                            step="any"
                            value={lineState.qty}
                            onChange={e => handleLineQtyChange(r.id, r.quantita, parseFloat(e.target.value) || 0)}
                            style={{ width: '55px', textAlign: 'center', background: 'transparent', border: 'none', color: isDiscrepant ? 'var(--crit)' : 'var(--ok)', fontWeight: 700, fontSize: '0.95rem', fontFamily: 'var(--font-mono)', fontVariantNumeric: 'tabular-nums', outline: 'none' }}
                          />
                          <span style={{ fontSize: '0.75rem', color: 'var(--text-secondary)', marginRight: '4px' }}>{r.uom}</span>
                          <button
                            type="button"
                            onClick={() => handleLineQtyChange(r.id, r.quantita, lineState.qty + 1)}
                            style={{ width: '26px', height: '26px', borderRadius: 'var(--radius-sm)', background: 'var(--bg-elevated)', border: 'none', color: 'var(--text-primary)', cursor: 'pointer', fontWeight: 700 }}
                          >
                            +
                          </button>
                        </div>
                      </div>
                    </div>

                    {/* Line Status Buttons & Notes */}
                    <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', flexWrap: 'wrap', gap: '10px', borderTop: '1px solid var(--line)', paddingTop: '8px' }}>
                      <div style={{ display: 'flex', gap: '6px', flexWrap: 'wrap' }}>
                        {[
                          { id: 'conforme', label: 'Conforme ✅', color: '#4cc38a' },
                          { id: 'parziale', label: 'Parziale ⚠️', color: '#e8b04a' },
                          { id: 'mancante', label: 'Mancante ❌', color: '#f0716a' },
                          { id: 'danneggiato', label: 'Danneggiato 📦💥', color: '#a48bf0' },
                        ].map(st => {
                          const active = lineState.status === st.id;
                          return (
                            <button
                              key={st.id}
                              type="button"
                              onClick={() => handleLineStatusChange(r.id, st.id)}
                              style={{
                                padding: '4px 10px',
                                borderRadius: 'var(--radius-sm)',
                                fontSize: '0.72rem',
                                fontWeight: active ? 700 : 500,
                                background: active ? `${st.color}22` : 'var(--bg-inset)',
                                border: active ? `1px solid ${st.color}` : '1px solid var(--line)',
                                color: active ? st.color : 'var(--text-secondary)',
                                cursor: 'pointer'
                              }}
                            >
                              {st.label}
                            </button>
                          );
                        })}
                      </div>

                      <input
                        type="text"
                        placeholder="Note riga (es. bottiglia sbeccata, collo bagnato)..."
                        value={lineState.note}
                        onChange={e => handleLineNoteChange(r.id, e.target.value)}
                        style={{ flex: '1 1 200px', padding: '5px 10px', background: 'var(--bg-inset)', border: '1px solid var(--line)', borderRadius: 'var(--radius-sm)', color: 'var(--text-primary)', fontSize: '0.75rem' }}
                      />
                    </div>
                  </div>
                );
              })}
            </div>

            {/* Global Receipt Outcome & Notes */}
            <div style={{ display: 'grid', gridTemplateColumns: '1fr 1.5fr', gap: '14px', background: 'var(--bg-inset)', padding: '16px', borderRadius: 'var(--radius-md)', border: '1px solid var(--line)' }}>
              <div>
                <label style={{ display: 'block', fontSize: '0.8rem', color: 'var(--text-secondary)', marginBottom: '6px', fontWeight: 600 }}>
                  Esito Globale Consegna
                </label>
                <select
                  value={globalReceiptStatus}
                  onChange={e => setGlobalReceiptStatus(e.target.value)}
                  style={{ width: '100%', padding: '10px 12px', background: 'var(--bg-inset)', border: '1px solid var(--line)', borderRadius: 'var(--radius-sm)', color: 'var(--text-primary)', fontSize: '0.85rem' }}
                >
                  <option value="ricevuto_conforme">✅ Ricevuto Conforme al 100%</option>
                  <option value="ricevuto_parziale">⚠️ Ricevuto Parziale (Mancano alcuni colli)</option>
                  <option value="ricevuto_con_riserva">🚨 Ricevuto con Riserva (Merce danneggiata/difforme)</option>
                </select>
              </div>

              <div>
                <label style={{ display: 'block', fontSize: '0.8rem', color: 'var(--text-secondary)', marginBottom: '6px', fontWeight: 600 }}>
                  Note Ricezione / Firma di Scarico
                </label>
                <input
                  type="text"
                  placeholder="Es. Consegnato da corriere Mario Rossi, riserva firmata su DDT cartaceo..."
                  value={globalReceiptNotes}
                  onChange={e => setGlobalReceiptNotes(e.target.value)}
                  style={{ width: '100%', padding: '10px 12px', background: 'var(--bg-inset)', border: '1px solid var(--line)', borderRadius: 'var(--radius-sm)', color: 'var(--text-primary)', fontSize: '0.85rem' }}
                />
              </div>
            </div>

            {/* Footer Buttons */}
            <div style={{ display: 'flex', justifyContent: 'flex-end', gap: '12px', marginTop: '6px' }}>
              <button
                type="button"
                onClick={() => setActiveOrder(null)}
                className="btn"
                style={{ background: 'transparent', border: '1px solid var(--line)' }}
              >
                Annulla
              </button>
              <button
                type="button"
                onClick={handleSaveReceipt}
                disabled={savingReceipt}
                className="btn btn-primary"
                style={{ display: 'flex', alignItems: 'center', gap: '8px', padding: '10px 24px', fontSize: '0.9rem' }}
              >
                <PackageCheck size={16} />
                {savingReceipt ? 'Salvataggio in corso...' : 'Conferma e Registra Scarico Merci'}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
