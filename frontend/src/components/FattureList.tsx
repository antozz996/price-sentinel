import { useState, useEffect } from 'react';
import { Search, Filter, ChevronDown, ChevronUp, Tag, FileText, Calendar, Building2, Truck, Package, X, AlertCircle } from 'lucide-react';
import { API_BASE, getHeaders } from '../api';
import Pagination from './Pagination';

interface FatturaItem {
  id: number;
  numero_documento: string;
  data_documento: string;
  data_ricezione_sdi: string;
  tipo_documento: string;
  totale_imponibile: number;
  marker: string;
  fornitore_id: number;
  location_id: number;
  fornitore_nome: string;
  location_nome: string;
  n_righe: number;
  n_anomalie: number;
}

interface RigaFattura {
  id: number;
  numero_linea: number;
  descrizione_fornitore_raw: string | null;
  codice_fornitore_raw: string | null;
  prezzo_unitario_fatturato: number;
  quantita: number;
  prezzo_netto_normalizzato: number;
  unita_misura_fattura: string | null;
  aliquota_iva: number | null;
  stato_matching: string;
  pfa_tipo?: string | null;
  pfa_valore?: number | null;
  netto_rientro?: number | null;
  anomalia_id?: number | null;
  anomalia_stato?: string | null;
  prezzo_listino_snapshot?: number | null;
  prezzo_fatturato_snapshot?: number | null;
  delta_prezzo?: number | null;
  delta_totale?: number | null;
}

interface Fornitore { id: number; nome_azienda: string; }
interface Location { id: number; nome_struttura: string; }

const MARKERS = [
  { value: 'nessuno', label: 'Nessuno', color: 'var(--text-muted)', bg: 'var(--bg-elevated)' },
  { value: 'da_verificare', label: 'Da Verificare', color: 'var(--warn)', bg: 'var(--warn-bg)' },
  { value: 'verificata', label: 'Verificata', color: 'var(--accent-text)', bg: 'var(--accent-bg)' },
  { value: 'contestata', label: 'Contestata', color: 'var(--crit)', bg: 'var(--crit-bg)' },
  { value: 'approvata', label: 'Approvata', color: 'var(--ok)', bg: 'var(--ok-bg)' },
  { value: 'sospesa', label: 'Sospesa', color: 'var(--info)', bg: 'var(--info-bg)' },
];

function getMarker(value: string) {
  return MARKERS.find(m => m.value === value) || MARKERS[0];
}

// focus: opened from another page (e.g. Analisi prezzi) to show one invoice with its lines.
export default function FattureList({ focus }: { focus?: { id: number; numero: string } | null } = {}) {
  const [fatture, setFatture] = useState<FatturaItem[]>([]);
  const [fornitori, setFornitori] = useState<Fornitore[]>([]);
  const [locations, setLocations] = useState<Location[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [expandedId, setExpandedId] = useState<number | null>(null);
  const [righe, setRighe] = useState<RigaFattura[]>([]);
  const [loadingRighe, setLoadingRighe] = useState(false);
  const [markerDropdown, setMarkerDropdown] = useState<number | null>(null);

  // Filters
  const [filterFornitore, setFilterFornitore] = useState('');
  const [filterLocation, setFilterLocation] = useState('');
  const [filterMarker, setFilterMarker] = useState('');
  const [filterDataDa, setFilterDataDa] = useState('');
  const [filterDataA, setFilterDataA] = useState('');
  const [searchQuery, setSearchQuery] = useState(focus?.numero || '');
  // Debounced copy used for fetching, so typing doesn't send one request per keystroke.
  const [debouncedSearch, setDebouncedSearch] = useState(focus?.numero || '');
  const [showFilters, setShowFilters] = useState(false);

  useEffect(() => {
    const t = setTimeout(() => setDebouncedSearch(searchQuery), 350);
    return () => clearTimeout(t);
  }, [searchQuery]);

  // Pagination states
  const [limit, setLimit] = useState(25);
  const [offset, setOffset] = useState(0);
  const [total, setTotal] = useState(0);
  const [totalAmount, setTotalAmount] = useState<number | null>(null);
  const [totalAnomalies, setTotalAnomalies] = useState<number | null>(null);

  const headers = getHeaders();

  useEffect(() => {
    const controller = new AbortController();
    loadFornitori(controller.signal);
    loadLocations(controller.signal);
    return () => controller.abort();
  // Initial filter bootstrap; the abort controller owns this request lifecycle.
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    if (focus?.id) {
      setExpandedId(focus.id);
      loadRighe(focus.id);
    }
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [focus?.id]);

  // Reset offset to 0 when filters or page size changes
  useEffect(() => {
    setOffset(0);
  }, [filterFornitore, filterLocation, filterMarker, filterDataDa, filterDataA, debouncedSearch, limit]);

  useEffect(() => {
    const controller = new AbortController();
    loadFatture(controller.signal);
    return () => controller.abort();
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [filterFornitore, filterLocation, filterMarker, filterDataDa, filterDataA, debouncedSearch, limit, offset]);

  async function loadFornitori(signal?: AbortSignal) {
    try {
      const res = await fetch(`${API_BASE}/fornitori/`, { headers, signal });
      const data = await res.json();
      if (Array.isArray(data)) setFornitori(data);
    } catch (e: any) {
      if (e.name !== 'AbortError') console.error(e);
    }
  }

  async function loadLocations(signal?: AbortSignal) {
    try {
      const res = await fetch(`${API_BASE}/location/`, { headers, signal });
      const data = await res.json();
      if (Array.isArray(data)) setLocations(data);
    } catch (e: any) {
      if (e.name !== 'AbortError') console.error(e);
    }
  }

  async function loadFatture(signal?: AbortSignal) {
    setLoading(true);
    setError(null);
    try {
      const params = new URLSearchParams();
      if (filterFornitore) params.set('fornitore_id', filterFornitore);
      if (filterLocation) params.set('location_id', filterLocation);
      if (filterMarker) params.set('marker', filterMarker);
      if (filterDataDa) params.set('data_da', filterDataDa);
      if (filterDataA) params.set('data_a', filterDataA);
      if (debouncedSearch) params.set('search', debouncedSearch);
      params.set('limit', limit.toString());
      params.set('offset', offset.toString());

      const res = await fetch(`${API_BASE}/fatture/?${params}`, { headers, signal });
      
      if (!res.ok) {
        throw new Error(`Errore API: ${res.status}`);
      }

      // Read X-Total-Count header
      const totalHeader = res.headers.get('X-Total-Count');
      if (totalHeader) {
        setTotal(parseInt(totalHeader, 10));
      } else {
        setTotal(0);
      }
      const amountHeader = res.headers.get('X-Total-Amount');
      setTotalAmount(amountHeader === null ? null : Number(amountHeader));
      const anomaliesHeader = res.headers.get('X-Total-Anomalies');
      setTotalAnomalies(anomaliesHeader === null ? null : Number(anomaliesHeader));

      const data = await res.json();
      if (Array.isArray(data)) setFatture(data);
      else setFatture([]);
    } catch (e: any) {
      if (e.name !== 'AbortError') {
        console.error(e);
        setError("Impossibile caricare le fatture. Verifica la connessione o riprova più tardi.");
        setFatture([]);
      }
    } finally {
      if (!signal?.aborted) {
        setLoading(false);
      }
    }
  }

  async function loadRighe(fatturaId: number) {
    setLoadingRighe(true);
    try {
      const res = await fetch(`${API_BASE}/fatture/${fatturaId}/righe`, { headers });
      const data = await res.json();
      if (Array.isArray(data)) setRighe(data);
    } catch (e) { console.error(e); }
    finally { setLoadingRighe(false); }
  }

  async function updateMarker(fatturaId: number, marker: string) {
    try {
      await fetch(`${API_BASE}/fatture/${fatturaId}/marker?marker=${marker}`, {
        method: 'PATCH',
        headers,
      });
      setFatture(prev => prev.map(f => f.id === fatturaId ? { ...f, marker } : f));
      setMarkerDropdown(null);
    } catch (e) { console.error(e); }
  }

  function toggleExpand(id: number) {
    if (expandedId === id) {
      setExpandedId(null);
      setRighe([]);
    } else {
      setExpandedId(id);
      loadRighe(id);
    }
  }

  function clearFilters() {
    setFilterFornitore('');
    setFilterLocation('');
    setFilterMarker('');
    setFilterDataDa('');
    setFilterDataA('');
    setSearchQuery('');
  }

  const hasActiveFilters = filterFornitore || filterLocation || filterMarker || filterDataDa || filterDataA || searchQuery;

  const selectStyle: React.CSSProperties = {
    padding: '10px 12px', background: 'var(--bg-inset)', border: '1px solid var(--line)',
    borderRadius: 'var(--radius-sm)', color: 'var(--text-primary)', fontSize: '0.85rem', outline: 'none', minWidth: '160px', flex: 1
  };

  const inputStyle: React.CSSProperties = {
    ...selectStyle, minWidth: '130px'
  };

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: '20px' }}>

      {/* Search + Filter Bar */}
      <div className="glass-panel" style={{ padding: '20px' }}>
        <div style={{ display: 'flex', gap: '12px', alignItems: 'center' }}>
          <div style={{ flex: 1, position: 'relative' }}>
            <Search size={18} style={{ position: 'absolute', left: '12px', top: '50%', transform: 'translateY(-50%)', color: 'var(--text-secondary)' }} />
            <input
              type="text"
              placeholder="Cerca per numero documento..."
              value={searchQuery}
              onChange={e => setSearchQuery(e.target.value)}
              style={{ ...inputStyle, width: '100%', paddingLeft: '40px', minWidth: 'unset' }}
            />
          </div>
          <button
            className="btn"
            onClick={() => setShowFilters(!showFilters)}
            style={{ background: showFilters ? 'var(--accent-bg)' : 'transparent', border: '1px solid var(--line)', gap: '8px' }}
          >
            <Filter size={16} /> Filtri
            {hasActiveFilters && <span style={{ width: '8px', height: '8px', borderRadius: '50%', background: 'var(--accent)', display: 'inline-block' }} />}
          </button>
          {hasActiveFilters && (
            <button className="btn" onClick={clearFilters} style={{ background: 'var(--crit-bg)', border: 'none', color: 'var(--crit)', gap: '6px' }}>
              <X size={14} /> Reset
            </button>
          )}
        </div>

        {showFilters && (
          <div style={{ display: 'flex', flexWrap: 'wrap', gap: '12px', marginTop: '16px', paddingTop: '16px', borderTop: '1px solid var(--line)' }}>
            <div style={{ display: 'flex', flexDirection: 'column', gap: '4px', flex: 1, minWidth: '150px' }}>
              <label style={{ fontSize: '0.75rem', color: 'var(--text-secondary)', display: 'flex', alignItems: 'center', gap: '6px' }}><Truck size={12} /> Fornitore</label>
              <select value={filterFornitore} onChange={e => setFilterFornitore(e.target.value)} style={selectStyle}>
                <option value="">Tutti</option>
                {fornitori.map(f => <option key={f.id} value={f.id}>{f.nome_azienda}</option>)}
              </select>
            </div>
            <div style={{ display: 'flex', flexDirection: 'column', gap: '4px', flex: 1, minWidth: '150px' }}>
              <label style={{ fontSize: '0.75rem', color: 'var(--text-secondary)', display: 'flex', alignItems: 'center', gap: '6px' }}><Building2 size={12} /> Azienda</label>
              <select value={filterLocation} onChange={e => setFilterLocation(e.target.value)} style={selectStyle}>
                <option value="">Tutte</option>
                {locations.map(l => <option key={l.id} value={l.id}>{l.nome_struttura}</option>)}
              </select>
            </div>
            <div style={{ display: 'flex', flexDirection: 'column', gap: '4px', flex: 1, minWidth: '150px' }}>
              <label style={{ fontSize: '0.75rem', color: 'var(--text-secondary)', display: 'flex', alignItems: 'center', gap: '6px' }}><Tag size={12} /> Marker</label>
              <select value={filterMarker} onChange={e => setFilterMarker(e.target.value)} style={selectStyle}>
                <option value="">Tutti</option>
                {MARKERS.filter(m => m.value !== 'nessuno').map(m => <option key={m.value} value={m.value}>{m.label}</option>)}
              </select>
            </div>
            <div style={{ display: 'flex', flexDirection: 'column', gap: '4px', minWidth: '130px' }}>
              <label style={{ fontSize: '0.75rem', color: 'var(--text-secondary)', display: 'flex', alignItems: 'center', gap: '6px' }}><Calendar size={12} /> Da</label>
              <input type="date" value={filterDataDa} onChange={e => setFilterDataDa(e.target.value)} style={inputStyle} />
            </div>
            <div style={{ display: 'flex', flexDirection: 'column', gap: '4px', minWidth: '130px' }}>
              <label style={{ fontSize: '0.75rem', color: 'var(--text-secondary)', display: 'flex', alignItems: 'center', gap: '6px' }}><Calendar size={12} /> A</label>
              <input type="date" value={filterDataA} onChange={e => setFilterDataA(e.target.value)} style={inputStyle} />
            </div>
          </div>
        )}
      </div>

      {/* Stats */}
      <div style={{ display: 'flex', gap: '12px', flexWrap: 'wrap' }}>
        <div className="glass-panel" style={{ padding: '16px 24px', flex: 1, minWidth: '120px', textAlign: 'center' }}>
          <div style={{ fontSize: '1.5rem', fontWeight: 600, fontFamily: 'var(--font-mono)', fontVariantNumeric: 'tabular-nums' }}>{total.toLocaleString('it-IT')}</div>
          <div style={{ fontSize: '0.75rem', color: 'var(--text-secondary)' }}>Fatture</div>
        </div>
        <div className="glass-panel" style={{ padding: '16px 24px', flex: 1, minWidth: '120px', textAlign: 'center' }}>
          <div style={{ fontSize: '1.5rem', fontWeight: 600, color: 'var(--crit)', fontFamily: 'var(--font-mono)', fontVariantNumeric: 'tabular-nums' }}>{totalAnomalies === null ? '—' : totalAnomalies.toLocaleString('it-IT')}</div>
          <div style={{ fontSize: '0.75rem', color: 'var(--text-secondary)' }}>Anomalie</div>
        </div>
        <div className="glass-panel" style={{ padding: '16px 24px', flex: 1, minWidth: '120px', textAlign: 'center' }}>
          <div style={{ fontSize: '1.5rem', fontWeight: 600, color: 'var(--accent-text)', fontFamily: 'var(--font-mono)', fontVariantNumeric: 'tabular-nums' }}>{totalAmount === null ? '—' : `€${totalAmount.toLocaleString('it-IT', { minimumFractionDigits: 2 })}`}</div>
          <div style={{ fontSize: '0.75rem', color: 'var(--text-secondary)' }}>Totale</div>
        </div>
      </div>

      {/* Table */}
      <div className="glass-panel" style={{ padding: '0', overflow: 'hidden' }}>
        {loading ? (
          <div style={{ padding: '60px', textAlign: 'center', color: 'var(--text-secondary)' }}>Caricamento fatture...</div>
        ) : error ? (
          <div style={{ padding: '60px', textAlign: 'center', color: 'var(--status-red)' }}>
            <AlertCircle size={48} style={{ marginBottom: '16px', opacity: 0.4 }} />
            <div>{error}</div>
            <button className="btn btn-primary" onClick={() => loadFatture()} style={{ marginTop: '16px' }}>Riprova</button>
          </div>
        ) : fatture.length === 0 ? (
          <div style={{ padding: '60px', textAlign: 'center', color: 'var(--text-secondary)' }}>
            <FileText size={48} style={{ marginBottom: '16px', opacity: 0.4 }} />
            <div>Nessuna fattura trovata</div>
            <div style={{ fontSize: '0.85rem', marginTop: '8px' }}>Carica fatture XML dalla sezione "Carica Fatture" o modifica i filtri.</div>
          </div>
        ) : (
          <>
            <div style={{ overflowX: 'auto' }}>
            <table className="ds-table" style={{ width: '100%', borderCollapse: 'collapse' }}>
              <thead>
                <tr style={{ borderBottom: '1px solid var(--line)', background: 'var(--bg-inset)' }}>
                  <th style={thStyle}>Marker</th>
                  <th style={thStyle}>N° Documento</th>
                  <th style={thStyle}>Data</th>
                  <th style={thStyle}>Fornitore</th>
                  <th style={thStyle}>Azienda</th>
                  <th style={{ ...thStyle, textAlign: 'right' }}>Importo</th>
                  <th style={{ ...thStyle, textAlign: 'center' }}>Righe</th>
                  <th style={{ ...thStyle, textAlign: 'center' }}>Anomalie</th>
                  <th style={{ ...thStyle, width: '40px' }}></th>
                </tr>
              </thead>
              <tbody>
                {fatture.map(f => {
                  const m = getMarker(f.marker);
                  const isExpanded = expandedId === f.id;
                  return (
                    <>
                      <tr
                        key={f.id}
                        onClick={() => toggleExpand(f.id)}
                        style={{
                          borderBottom: '1px solid var(--line)',
                          cursor: 'pointer',
                          background: isExpanded ? 'var(--accent-bg)' : 'transparent',
                          transition: 'background 0.2s'
                        }}
                        onMouseEnter={e => (e.currentTarget.style.background = 'var(--bg-elevated)')}
                        onMouseLeave={e => (e.currentTarget.style.background = isExpanded ? 'var(--accent-bg)' : 'transparent')}
                      >
                        <td style={tdStyle}>
                          <div style={{ position: 'relative' }}>
                            <button
                              onClick={e => { e.stopPropagation(); setMarkerDropdown(markerDropdown === f.id ? null : f.id); }}
                              style={{
                                background: m.bg, color: m.color, border: 'none', borderRadius: '999px',
                                padding: '4px 12px', fontSize: '0.75rem', fontWeight: 600, cursor: 'pointer',
                                whiteSpace: 'nowrap', transition: 'all 0.2s'
                              }}
                            >
                              {m.label}
                            </button>
                            {markerDropdown === f.id && (
                              <div style={{
                                position: 'absolute', top: '100%', left: 0, marginTop: '4px', zIndex: 100,
                                background: 'var(--bg-card)', border: '1px solid var(--line-strong)', borderRadius: 'var(--radius-md)',
                                padding: '4px', minWidth: '150px', boxShadow: 'var(--shadow-pop)'
                              }}>
                                {MARKERS.map(mk => (
                                  <button
                                    key={mk.value}
                                    onClick={e => { e.stopPropagation(); updateMarker(f.id, mk.value); }}
                                    style={{
                                      display: 'block', width: '100%', padding: '8px 12px', border: 'none',
                                      background: f.marker === mk.value ? 'var(--bg-elevated)' : 'transparent',
                                      color: mk.color, textAlign: 'left', cursor: 'pointer', borderRadius: '4px',
                                      fontSize: '0.8rem', fontWeight: 500
                                    }}
                                    onMouseEnter={e => (e.currentTarget.style.background = 'var(--bg-elevated)')}
                                    onMouseLeave={e => (e.currentTarget.style.background = f.marker === mk.value ? 'var(--bg-elevated)' : 'transparent')}
                                  >
                                    ● {mk.label}
                                  </button>
                                ))}
                              </div>
                            )}
                          </div>
                        </td>
                        <td style={{ ...tdStyle, fontWeight: 600, fontFamily: 'var(--font-mono)' }}>{f.numero_documento}</td>
                        <td style={tdStyle}>{new Date(f.data_documento).toLocaleDateString('it-IT')}</td>
                        <td style={tdStyle}>{f.fornitore_nome}</td>
                        <td style={tdStyle}>{f.location_nome}</td>
                        <td style={{ ...tdStyle, textAlign: 'right', fontWeight: 600, fontFamily: 'var(--font-mono)', fontVariantNumeric: 'tabular-nums' }}>€{f.totale_imponibile.toLocaleString('it-IT', { minimumFractionDigits: 2 })}</td>
                        <td style={{ ...tdStyle, textAlign: 'center', fontFamily: 'var(--font-mono)', fontVariantNumeric: 'tabular-nums' }}>{f.n_righe}</td>
                        <td style={{ ...tdStyle, textAlign: 'center' }}>
                          {f.n_anomalie > 0 ? (
                            <span style={{ background: 'var(--crit-bg)', color: 'var(--crit)', padding: '2px 10px', borderRadius: '999px', fontSize: '0.8rem', fontWeight: 600, fontFamily: 'var(--font-mono)', fontVariantNumeric: 'tabular-nums' }}>
                              {f.n_anomalie}
                            </span>
                          ) : (
                            <span style={{ color: 'var(--text-secondary)' }}>—</span>
                          )}
                        </td>
                        <td style={tdStyle}>
                          {isExpanded ? <ChevronUp size={16} /> : <ChevronDown size={16} />}
                        </td>
                      </tr>
                      {isExpanded && (
                        <tr key={`${f.id}-detail`}>
                          <td colSpan={9} style={{ padding: 0, background: 'var(--bg-inset)' }}>
                            <div style={{ padding: '20px 24px' }}>
                              <h4 style={{ marginBottom: '12px', display: 'flex', alignItems: 'center', gap: '8px' }}>
                                <Package size={16} /> Dettaglio Prodotti
                              </h4>
                              {loadingRighe ? (
                                <div style={{ color: 'var(--text-secondary)', padding: '12px' }}>Caricamento righe...</div>
                              ) : righe.length === 0 ? (
                                <div style={{ color: 'var(--text-secondary)', padding: '12px' }}>Nessuna riga trovata.</div>
                              ) : (
                                <table className="ds-table" style={{ width: '100%', borderCollapse: 'collapse' }}>
                                  <thead>
                                    <tr style={{ borderBottom: '1px solid var(--line)' }}>
                                      <th style={{ ...thStyle, fontSize: '0.75rem' }}>#</th>
                                      <th style={{ ...thStyle, fontSize: '0.75rem' }}>Descrizione</th>
                                      <th style={{ ...thStyle, fontSize: '0.75rem' }}>Codice</th>
                                      <th style={{ ...thStyle, fontSize: '0.75rem', textAlign: 'right' }}>Prezzo Unit.</th>
                                      <th style={{ ...thStyle, fontSize: '0.75rem', textAlign: 'right' }}>Qtà</th>
                                      <th style={{ ...thStyle, fontSize: '0.75rem', textAlign: 'right' }}>Totale</th>
                                      <th style={{ ...thStyle, fontSize: '0.75rem', textAlign: 'center' }}>Matching</th>
                                      <th style={{ ...thStyle, fontSize: '0.75rem', textAlign: 'center' }}>Anomalia prezzo</th>
                                    </tr>
                                  </thead>
                                  <tbody>
                                    {righe.map(r => (
                                      <tr key={r.id} style={{ borderBottom: '1px solid var(--line)', background: r.anomalia_id ? 'var(--crit-bg)' : 'transparent' }}>
                                        <td style={{ ...tdStyle, fontSize: '0.8rem', color: 'var(--text-secondary)' }}>{r.numero_linea}</td>
                                        <td style={{ ...tdStyle, fontSize: '0.85rem' }}>{r.descrizione_fornitore_raw || '—'}</td>
                                        <td style={{ ...tdStyle, fontSize: '0.8rem', fontFamily: 'var(--font-mono)', color: 'var(--text-secondary)' }}>{r.codice_fornitore_raw || '—'}</td>
                                        <td style={{ ...tdStyle, fontSize: '0.85rem', textAlign: 'right', fontFamily: 'var(--font-mono)', fontVariantNumeric: 'tabular-nums' }}>
                                          <div>€{Number(r.prezzo_netto_normalizzato).toFixed(2)}</div>
                                          {r.netto_rientro !== undefined && r.netto_rientro !== null && Number(r.netto_rientro) !== Number(r.prezzo_netto_normalizzato) && (
                                            <div style={{
                                              fontSize: '0.72rem', color: 'var(--ok)', fontWeight: 600, marginTop: '2px',
                                              display: 'flex', alignItems: 'center', justifyContent: 'flex-end', gap: '3px'
                                            }}>
                                              <span>Net: €{Number(r.netto_rientro).toFixed(2)}</span>
                                              <span style={{ fontSize: '0.65rem', background: 'var(--ok-bg)', padding: '1px 5px', borderRadius: '999px' }}>
                                                {r.pfa_tipo === 'fisso' ? `-${Number(r.pfa_valore).toFixed(2)}€` : `-${(Number(r.pfa_valore)*100).toFixed(0)}%`}
                                              </span>
                                            </div>
                                          )}
                                        </td>
                                        <td style={{ ...tdStyle, fontSize: '0.85rem', textAlign: 'right', fontFamily: 'var(--font-mono)', fontVariantNumeric: 'tabular-nums' }}>{Number(r.quantita).toFixed(2)}</td>
                                        <td style={{ ...tdStyle, fontSize: '0.85rem', textAlign: 'right', fontWeight: 600, fontFamily: 'var(--font-mono)', fontVariantNumeric: 'tabular-nums' }}>€{Number(r.prezzo_netto_normalizzato * r.quantita).toFixed(2)}</td>
                                        <td style={{ ...tdStyle, textAlign: 'center' }}>
                                          <span style={{
                                            padding: '2px 8px', borderRadius: '999px', fontSize: '0.7rem', fontWeight: 600,
                                            background: r.stato_matching === 'matched' ? 'var(--ok-bg)' : r.stato_matching === 'in_parking' ? 'var(--warn-bg)' : 'var(--bg-elevated)',
                                            color: r.stato_matching === 'matched' ? 'var(--ok)' : r.stato_matching === 'in_parking' ? 'var(--warn)' : 'var(--text-muted)',
                                          }}>
                                            {r.stato_matching}
                                          </span>
                                        </td>
                                        <td style={{ ...tdStyle, textAlign: 'center', minWidth: '190px' }}>
                                          {r.anomalia_id ? (
                                            <div style={{ color: 'var(--crit)', fontSize: '0.75rem', lineHeight: 1.45, fontFamily: 'var(--font-mono)', fontVariantNumeric: 'tabular-nums' }}>
                                              <div style={{ fontWeight: 700, color: 'var(--crit)' }}>Scostamento €{Number(r.delta_totale || 0).toFixed(2)}</div>
                                              <div>Pattuito €{Number(r.prezzo_listino_snapshot || 0).toFixed(2)} · Fatturato €{Number(r.prezzo_fatturato_snapshot || 0).toFixed(2)}</div>
                                              <div>+€{Number(r.delta_prezzo || 0).toFixed(2)} per unità</div>
                                            </div>
                                          ) : (
                                            <span style={{ color: 'var(--text-secondary)' }}>—</span>
                                          )}
                                        </td>
                                      </tr>
                                    ))}
                                  </tbody>
                                </table>
                              )}
                            </div>
                          </td>
                        </tr>
                      )}
                    </>
                  );
                })}
              </tbody>
            </table>
          </div>
          <div style={{ padding: '0 24px 24px 24px' }}>
            <Pagination
              limit={limit}
              offset={offset}
              total={total}
              onChange={(l: number, o: number) => {
                setLimit(l);
                setOffset(o);
              }}
            />
          </div>
          </>
        )}
      </div>
    </div>
  );
}

const thStyle: React.CSSProperties = {
  padding: '14px 16px', textAlign: 'left', fontSize: '0.8rem',
  color: 'var(--text-secondary)', fontWeight: 600, textTransform: 'uppercase',
  letterSpacing: '0.5px', whiteSpace: 'nowrap'
};

const tdStyle: React.CSSProperties = {
  padding: '12px 16px', fontSize: '0.9rem', whiteSpace: 'nowrap'
};
