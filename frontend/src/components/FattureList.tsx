import { useState, useEffect } from 'react';
import { Search, Filter, ChevronDown, ChevronUp, Tag, FileText, Calendar, Building2, Truck, Package, X } from 'lucide-react';
import { API_BASE } from '../api';

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
}

interface Fornitore { id: number; nome_azienda: string; }
interface Location { id: number; nome: string; }

const MARKERS = [
  { value: 'nessuno', label: 'Nessuno', color: '#6b7280', bg: 'rgba(107,114,128,0.15)' },
  { value: 'da_verificare', label: 'Da Verificare', color: '#f59e0b', bg: 'rgba(245,158,11,0.15)' },
  { value: 'verificata', label: 'Verificata', color: '#3b82f6', bg: 'rgba(59,130,246,0.15)' },
  { value: 'contestata', label: 'Contestata', color: '#ef4444', bg: 'rgba(239,68,68,0.15)' },
  { value: 'approvata', label: 'Approvata', color: '#10b981', bg: 'rgba(16,185,129,0.15)' },
  { value: 'sospesa', label: 'Sospesa', color: '#8b5cf6', bg: 'rgba(139,92,246,0.15)' },
];

function getMarker(value: string) {
  return MARKERS.find(m => m.value === value) || MARKERS[0];
}

export default function FattureList() {
  const [fatture, setFatture] = useState<FatturaItem[]>([]);
  const [fornitori, setFornitori] = useState<Fornitore[]>([]);
  const [locations, setLocations] = useState<Location[]>([]);
  const [loading, setLoading] = useState(true);
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
  const [searchQuery, setSearchQuery] = useState('');
  const [showFilters, setShowFilters] = useState(false);

  const token = localStorage.getItem('token');
  const headers = { 'Authorization': `Bearer ${token}`, 'bypass-tunnel-reminder': 'true' };

  useEffect(() => {
    loadFornitori();
    loadLocations();
  }, []);

  useEffect(() => {
    loadFatture();
  }, [filterFornitore, filterLocation, filterMarker, filterDataDa, filterDataA, searchQuery]);

  async function loadFornitori() {
    try {
      const res = await fetch(`${API_BASE}/fornitori/`, { headers });
      const data = await res.json();
      if (Array.isArray(data)) setFornitori(data);
    } catch (e) { console.error(e); }
  }

  async function loadLocations() {
    try {
      const res = await fetch(`${API_BASE}/location/`, { headers });
      const data = await res.json();
      if (Array.isArray(data)) setLocations(data);
    } catch (e) { console.error(e); }
  }

  async function loadFatture() {
    setLoading(true);
    try {
      const params = new URLSearchParams();
      if (filterFornitore) params.set('fornitore_id', filterFornitore);
      if (filterLocation) params.set('location_id', filterLocation);
      if (filterMarker) params.set('marker', filterMarker);
      if (filterDataDa) params.set('data_da', filterDataDa);
      if (filterDataA) params.set('data_a', filterDataA);
      if (searchQuery) params.set('search', searchQuery);
      params.set('limit', '100');

      const res = await fetch(`${API_BASE}/fatture/?${params}`, { headers });
      const data = await res.json();
      if (Array.isArray(data)) setFatture(data);
      else setFatture([]);
    } catch (e) {
      console.error(e);
      setFatture([]);
    } finally {
      setLoading(false);
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
    padding: '10px 12px', background: 'rgba(255,255,255,0.05)', border: '1px solid var(--border-glass)',
    borderRadius: '8px', color: 'white', fontSize: '0.85rem', outline: 'none', minWidth: '160px', flex: 1
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
            style={{ background: showFilters ? 'rgba(59,130,246,0.2)' : 'transparent', border: '1px solid var(--border-glass)', gap: '8px' }}
          >
            <Filter size={16} /> Filtri
            {hasActiveFilters && <span style={{ width: '8px', height: '8px', borderRadius: '50%', background: 'var(--accent-blue)', display: 'inline-block' }} />}
          </button>
          {hasActiveFilters && (
            <button className="btn" onClick={clearFilters} style={{ background: 'rgba(239,68,68,0.15)', border: 'none', color: '#ef4444', gap: '6px' }}>
              <X size={14} /> Reset
            </button>
          )}
        </div>

        {showFilters && (
          <div style={{ display: 'flex', flexWrap: 'wrap', gap: '12px', marginTop: '16px', paddingTop: '16px', borderTop: '1px solid var(--border-glass)' }}>
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
                {locations.map(l => <option key={l.id} value={l.id}>{l.nome}</option>)}
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
          <div style={{ fontSize: '1.5rem', fontWeight: 700 }}>{fatture.length}</div>
          <div style={{ fontSize: '0.75rem', color: 'var(--text-secondary)' }}>Fatture</div>
        </div>
        <div className="glass-panel" style={{ padding: '16px 24px', flex: 1, minWidth: '120px', textAlign: 'center' }}>
          <div style={{ fontSize: '1.5rem', fontWeight: 700, color: 'var(--status-red)' }}>{fatture.reduce((s, f) => s + f.n_anomalie, 0)}</div>
          <div style={{ fontSize: '0.75rem', color: 'var(--text-secondary)' }}>Anomalie</div>
        </div>
        <div className="glass-panel" style={{ padding: '16px 24px', flex: 1, minWidth: '120px', textAlign: 'center' }}>
          <div style={{ fontSize: '1.5rem', fontWeight: 700, color: 'var(--accent-blue)' }}>€{fatture.reduce((s, f) => s + f.totale_imponibile, 0).toLocaleString('it-IT', { minimumFractionDigits: 2 })}</div>
          <div style={{ fontSize: '0.75rem', color: 'var(--text-secondary)' }}>Totale</div>
        </div>
      </div>

      {/* Table */}
      <div className="glass-panel" style={{ padding: '0', overflow: 'hidden' }}>
        {loading ? (
          <div style={{ padding: '60px', textAlign: 'center', color: 'var(--text-secondary)' }}>Caricamento fatture...</div>
        ) : fatture.length === 0 ? (
          <div style={{ padding: '60px', textAlign: 'center', color: 'var(--text-secondary)' }}>
            <FileText size={48} style={{ marginBottom: '16px', opacity: 0.4 }} />
            <div>Nessuna fattura trovata</div>
            <div style={{ fontSize: '0.85rem', marginTop: '8px' }}>Carica fatture XML dalla sezione "Carica Fatture" o modifica i filtri.</div>
          </div>
        ) : (
          <div style={{ overflowX: 'auto' }}>
            <table style={{ width: '100%', borderCollapse: 'collapse' }}>
              <thead>
                <tr style={{ borderBottom: '1px solid var(--border-glass)', background: 'rgba(255,255,255,0.02)' }}>
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
                          borderBottom: '1px solid var(--border-glass)',
                          cursor: 'pointer',
                          background: isExpanded ? 'rgba(59,130,246,0.05)' : 'transparent',
                          transition: 'background 0.2s'
                        }}
                        onMouseEnter={e => (e.currentTarget.style.background = 'rgba(255,255,255,0.03)')}
                        onMouseLeave={e => (e.currentTarget.style.background = isExpanded ? 'rgba(59,130,246,0.05)' : 'transparent')}
                      >
                        <td style={tdStyle}>
                          <div style={{ position: 'relative' }}>
                            <button
                              onClick={e => { e.stopPropagation(); setMarkerDropdown(markerDropdown === f.id ? null : f.id); }}
                              style={{
                                background: m.bg, color: m.color, border: 'none', borderRadius: '20px',
                                padding: '4px 12px', fontSize: '0.75rem', fontWeight: 600, cursor: 'pointer',
                                whiteSpace: 'nowrap', transition: 'all 0.2s'
                              }}
                            >
                              {m.label}
                            </button>
                            {markerDropdown === f.id && (
                              <div style={{
                                position: 'absolute', top: '100%', left: 0, marginTop: '4px', zIndex: 100,
                                background: '#1e1e2e', border: '1px solid var(--border-glass)', borderRadius: '8px',
                                padding: '4px', minWidth: '150px', boxShadow: '0 8px 24px rgba(0,0,0,0.4)'
                              }}>
                                {MARKERS.map(mk => (
                                  <button
                                    key={mk.value}
                                    onClick={e => { e.stopPropagation(); updateMarker(f.id, mk.value); }}
                                    style={{
                                      display: 'block', width: '100%', padding: '8px 12px', border: 'none',
                                      background: f.marker === mk.value ? 'rgba(255,255,255,0.08)' : 'transparent',
                                      color: mk.color, textAlign: 'left', cursor: 'pointer', borderRadius: '4px',
                                      fontSize: '0.8rem', fontWeight: 500
                                    }}
                                    onMouseEnter={e => (e.currentTarget.style.background = 'rgba(255,255,255,0.06)')}
                                    onMouseLeave={e => (e.currentTarget.style.background = f.marker === mk.value ? 'rgba(255,255,255,0.08)' : 'transparent')}
                                  >
                                    ● {mk.label}
                                  </button>
                                ))}
                              </div>
                            )}
                          </div>
                        </td>
                        <td style={{ ...tdStyle, fontWeight: 600, fontFamily: 'monospace' }}>{f.numero_documento}</td>
                        <td style={tdStyle}>{new Date(f.data_documento).toLocaleDateString('it-IT')}</td>
                        <td style={tdStyle}>{f.fornitore_nome}</td>
                        <td style={tdStyle}>{f.location_nome}</td>
                        <td style={{ ...tdStyle, textAlign: 'right', fontWeight: 600 }}>€{f.totale_imponibile.toLocaleString('it-IT', { minimumFractionDigits: 2 })}</td>
                        <td style={{ ...tdStyle, textAlign: 'center' }}>{f.n_righe}</td>
                        <td style={{ ...tdStyle, textAlign: 'center' }}>
                          {f.n_anomalie > 0 ? (
                            <span style={{ background: 'rgba(239,68,68,0.15)', color: '#ef4444', padding: '2px 10px', borderRadius: '12px', fontSize: '0.8rem', fontWeight: 600 }}>
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
                          <td colSpan={9} style={{ padding: 0, background: 'rgba(0,0,0,0.15)' }}>
                            <div style={{ padding: '20px 24px' }}>
                              <h4 style={{ marginBottom: '12px', display: 'flex', alignItems: 'center', gap: '8px' }}>
                                <Package size={16} /> Dettaglio Prodotti
                              </h4>
                              {loadingRighe ? (
                                <div style={{ color: 'var(--text-secondary)', padding: '12px' }}>Caricamento righe...</div>
                              ) : righe.length === 0 ? (
                                <div style={{ color: 'var(--text-secondary)', padding: '12px' }}>Nessuna riga trovata.</div>
                              ) : (
                                <table style={{ width: '100%', borderCollapse: 'collapse' }}>
                                  <thead>
                                    <tr style={{ borderBottom: '1px solid var(--border-glass)' }}>
                                      <th style={{ ...thStyle, fontSize: '0.75rem' }}>#</th>
                                      <th style={{ ...thStyle, fontSize: '0.75rem' }}>Descrizione</th>
                                      <th style={{ ...thStyle, fontSize: '0.75rem' }}>Codice</th>
                                      <th style={{ ...thStyle, fontSize: '0.75rem', textAlign: 'right' }}>Prezzo Unit.</th>
                                      <th style={{ ...thStyle, fontSize: '0.75rem', textAlign: 'right' }}>Qtà</th>
                                      <th style={{ ...thStyle, fontSize: '0.75rem', textAlign: 'right' }}>Totale</th>
                                      <th style={{ ...thStyle, fontSize: '0.75rem', textAlign: 'center' }}>Matching</th>
                                    </tr>
                                  </thead>
                                  <tbody>
                                    {righe.map(r => (
                                      <tr key={r.id} style={{ borderBottom: '1px solid rgba(255,255,255,0.03)' }}>
                                        <td style={{ ...tdStyle, fontSize: '0.8rem', color: 'var(--text-secondary)' }}>{r.numero_linea}</td>
                                        <td style={{ ...tdStyle, fontSize: '0.85rem' }}>{r.descrizione_fornitore_raw || '—'}</td>
                                        <td style={{ ...tdStyle, fontSize: '0.8rem', fontFamily: 'monospace', color: 'var(--text-secondary)' }}>{r.codice_fornitore_raw || '—'}</td>
                                        <td style={{ ...tdStyle, fontSize: '0.85rem', textAlign: 'right' }}>€{Number(r.prezzo_unitario_fatturato).toFixed(2)}</td>
                                        <td style={{ ...tdStyle, fontSize: '0.85rem', textAlign: 'right' }}>{Number(r.quantita).toFixed(2)}</td>
                                        <td style={{ ...tdStyle, fontSize: '0.85rem', textAlign: 'right', fontWeight: 600 }}>€{Number(r.prezzo_netto_normalizzato * r.quantita).toFixed(2)}</td>
                                        <td style={{ ...tdStyle, textAlign: 'center' }}>
                                          <span style={{
                                            padding: '2px 8px', borderRadius: '12px', fontSize: '0.7rem', fontWeight: 600,
                                            background: r.stato_matching === 'matched' ? 'rgba(16,185,129,0.15)' : r.stato_matching === 'in_parking' ? 'rgba(245,158,11,0.15)' : 'rgba(107,114,128,0.15)',
                                            color: r.stato_matching === 'matched' ? '#10b981' : r.stato_matching === 'in_parking' ? '#f59e0b' : '#6b7280',
                                          }}>
                                            {r.stato_matching}
                                          </span>
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
