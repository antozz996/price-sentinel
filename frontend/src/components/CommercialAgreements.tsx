import { useState, useEffect } from 'react';
import { Search, Percent, TrendingDown, Truck, Building2, Calendar, Award, DollarSign, BarChart2 } from 'lucide-react';
import { API_BASE, getHeaders } from '../api';

interface PFAScaglioneInfo {
  id: number;
  soglia_da: number;
  soglia_a: number | null;
  valore_percentuale: number;
}

interface AgreementItem {
  listino_id: number;
  sku_interno: string;
  descrizione: string;
  fornitore_id: number;
  fornitore_nome: string;
  unita_misura: string;
  prezzo_pattuito: number;
  pfa_tipo: string;
  pfa_valore: number | null;
  pfa_scaglioni: PFAScaglioneInfo[];
  netto_rientro_contratto: number | null;
  quantita_acquistata: number;
  totale_fatturato: number;
  rientro_accumulato: number;
  netto_rientro_medio: number;
}

interface Fornitore { id: number; nome_azienda: string; }
interface Location { id: number; nome_struttura: string; }

export default function CommercialAgreements() {
  const [agreements, setAgreements] = useState<AgreementItem[]>([]);
  const [fornitori, setFornitori] = useState<Fornitore[]>([]);
  const [locations, setLocations] = useState<Location[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  // Filters
  const [filterFornitore, setFilterFornitore] = useState('');
  const [filterLocation, setFilterLocation] = useState('');
  const [filterDataDa, setFilterDataDa] = useState('');
  const [filterDataA, setFilterDataA] = useState('');
  const [searchQuery, setSearchQuery] = useState('');

  const headers = getHeaders();

  useEffect(() => {
    const controller = new AbortController();
    loadFornitori(controller.signal);
    loadLocations(controller.signal);
    return () => controller.abort();
  }, []);

  useEffect(() => {
    const controller = new AbortController();
    loadAgreements(controller.signal);
    return () => controller.abort();
  }, [filterFornitore, filterLocation, filterDataDa, filterDataA]);

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

  async function loadAgreements(signal?: AbortSignal) {
    setLoading(true);
    setError(null);
    try {
      const params = new URLSearchParams();
      if (filterFornitore) params.set('fornitore_id', filterFornitore);
      if (filterLocation) params.set('location_id', filterLocation);
      if (filterDataDa) params.set('data_da', filterDataDa);
      if (filterDataA) params.set('data_a', filterDataA);

      const res = await fetch(`${API_BASE}/accordi/?${params}`, { headers, signal });
      if (!res.ok) throw new Error(`Errore API: ${res.status}`);
      const data = await res.json();
      if (Array.isArray(data)) {
        setAgreements(data);
      } else {
        setAgreements([]);
      }
    } catch (e: any) {
      if (e.name !== 'AbortError') {
        console.error(e);
        setError("Impossibile caricare gli accordi commerciali.");
      }
    } finally {
      if (!signal?.aborted) setLoading(false);
    }
  }

  const filteredAgreements = agreements.filter(ag => {
    if (!searchQuery) return true;
    const q = searchQuery.toLowerCase();
    return (
      ag.sku_interno.toLowerCase().includes(q) ||
      ag.descrizione.toLowerCase().includes(q) ||
      ag.fornitore_nome.toLowerCase().includes(q)
    );
  });

  // Calculate aggregated stats
  const totalVolume = filteredAgreements.reduce((sum, ag) => sum + ag.quantita_acquistata, 0);
  const totalSpent = filteredAgreements.reduce((sum, ag) => sum + ag.totale_fatturato, 0);
  const totalRebate = filteredAgreements.reduce((sum, ag) => sum + ag.rientro_accumulato, 0);
  const averageDiscountPct = totalSpent > 0 ? (totalRebate / totalSpent) * 100 : 0;

  const selectStyle: React.CSSProperties = {
    padding: '10px 12px', background: 'rgba(255,255,255,0.05)', border: '1px solid var(--border-glass)',
    borderRadius: '8px', color: 'white', fontSize: '0.85rem', outline: 'none', minWidth: '160px', flex: 1
  };

  const inputStyle: React.CSSProperties = {
    ...selectStyle, minWidth: '130px'
  };

  const thStyle: React.CSSProperties = {
    padding: '14px 16px', textAlign: 'left', fontSize: '0.8rem',
    color: 'var(--text-secondary)', fontWeight: 600, textTransform: 'uppercase',
    letterSpacing: '0.5px', whiteSpace: 'nowrap'
  };

  const tdStyle: React.CSSProperties = {
    padding: '12px 16px', fontSize: '0.9rem', whiteSpace: 'nowrap'
  };

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: '24px' }}>
      
      {/* Search and Filters Bar */}
      <div className="glass-panel" style={{ padding: '20px' }}>
        <div style={{ display: 'flex', flexWrap: 'wrap', gap: '16px', alignItems: 'flex-end' }}>
          
          <div style={{ display: 'flex', flexDirection: 'column', gap: '6px', flex: 2, minWidth: '240px' }}>
            <label style={{ fontSize: '0.75rem', color: 'var(--text-secondary)', display: 'flex', alignItems: 'center', gap: '6px' }}>
              <Search size={12} /> Cerca SKU o Descrizione
            </label>
            <input
              type="text"
              placeholder="Cerca per SKU, descrizione o fornitore..."
              value={searchQuery}
              onChange={e => setSearchQuery(e.target.value)}
              style={{ ...inputStyle, width: '100%' }}
            />
          </div>

          <div style={{ display: 'flex', flexDirection: 'column', gap: '6px', flex: 1, minWidth: '150px' }}>
            <label style={{ fontSize: '0.75rem', color: 'var(--text-secondary)', display: 'flex', alignItems: 'center', gap: '6px' }}>
              <Truck size={12} /> Fornitore
            </label>
            <select value={filterFornitore} onChange={e => setFilterFornitore(e.target.value)} style={selectStyle}>
              <option value="">Tutti i fornitori</option>
              {fornitori.map(f => <option key={f.id} value={f.id}>{f.nome_azienda}</option>)}
            </select>
          </div>

          <div style={{ display: 'flex', flexDirection: 'column', gap: '6px', flex: 1, minWidth: '150px' }}>
            <label style={{ fontSize: '0.75rem', color: 'var(--text-secondary)', display: 'flex', alignItems: 'center', gap: '6px' }}>
              <Building2 size={12} /> Sede (Location)
            </label>
            <select value={filterLocation} onChange={e => setFilterLocation(e.target.value)} style={selectStyle}>
              <option value="">Tutte le sedi</option>
              {locations.map(l => <option key={l.id} value={l.id}>{l.nome_struttura}</option>)}
            </select>
          </div>

          <div style={{ display: 'flex', flexDirection: 'column', gap: '6px', minWidth: '130px' }}>
            <label style={{ fontSize: '0.75rem', color: 'var(--text-secondary)', display: 'flex', alignItems: 'center', gap: '6px' }}>
              <Calendar size={12} /> Da
            </label>
            <input type="date" value={filterDataDa} onChange={e => setFilterDataDa(e.target.value)} style={inputStyle} />
          </div>

          <div style={{ display: 'flex', flexDirection: 'column', gap: '6px', minWidth: '130px' }}>
            <label style={{ fontSize: '0.75rem', color: 'var(--text-secondary)', display: 'flex', alignItems: 'center', gap: '6px' }}>
              <Calendar size={12} /> A
            </label>
            <input type="date" value={filterDataA} onChange={e => setFilterDataA(e.target.value)} style={inputStyle} />
          </div>

        </div>
      </div>

      {/* KPI Cards Grid */}
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(220px, 1fr))', gap: '16px' }}>
        
        <div className="glass-panel" style={{ padding: '24px', display: 'flex', alignItems: 'center', gap: '20px' }}>
          <div style={{ padding: '14px', borderRadius: '12px', background: 'rgba(59, 130, 246, 0.1)', color: '#3b82f6' }}>
            <DollarSign size={24} />
          </div>
          <div>
            <div style={{ fontSize: '1.75rem', fontWeight: 700 }}>
              € {totalSpent.toLocaleString('it-IT', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}
            </div>
            <div style={{ fontSize: '0.8rem', color: 'var(--text-secondary)', marginTop: '4px' }}>Fatturato Sotto Accordo</div>
          </div>
        </div>

        <div className="glass-panel" style={{ padding: '24px', display: 'flex', alignItems: 'center', gap: '20px' }}>
          <div style={{ padding: '14px', borderRadius: '12px', background: 'rgba(16, 185, 129, 0.1)', color: '#10b981' }}>
            <TrendingDown size={24} />
          </div>
          <div>
            <div style={{ fontSize: '1.75rem', fontWeight: 700, color: '#10b981' }}>
              € {totalRebate.toLocaleString('it-IT', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}
            </div>
            <div style={{ fontSize: '0.8rem', color: 'var(--text-secondary)', marginTop: '4px' }}>Rientro Maturato Stimato</div>
          </div>
        </div>

        <div className="glass-panel" style={{ padding: '24px', display: 'flex', alignItems: 'center', gap: '20px' }}>
          <div style={{ padding: '14px', borderRadius: '12px', background: 'rgba(139, 92, 246, 0.1)', color: '#8b5cf6' }}>
            <BarChart2 size={24} />
          </div>
          <div>
            <div style={{ fontSize: '1.75rem', fontWeight: 700 }}>
              {totalVolume.toLocaleString('it-IT', { maximumFractionDigits: 2 })}
            </div>
            <div style={{ fontSize: '0.8rem', color: 'var(--text-secondary)', marginTop: '4px' }}>Volume Acquistato Totale</div>
          </div>
        </div>

        <div className="glass-panel" style={{ padding: '24px', display: 'flex', alignItems: 'center', gap: '20px' }}>
          <div style={{ padding: '14px', borderRadius: '12px', background: 'rgba(245, 158, 11, 0.1)', color: '#f59e0b' }}>
            <Percent size={24} />
          </div>
          <div>
            <div style={{ fontSize: '1.75rem', fontWeight: 700, color: '#f59e0b' }}>
              {averageDiscountPct.toFixed(2)} %
            </div>
            <div style={{ fontSize: '0.8rem', color: 'var(--text-secondary)', marginTop: '4px' }}>Risparmio Medio (PFA)</div>
          </div>
        </div>

      </div>

      {/* Main Table Panel */}
      <div className="glass-panel" style={{ padding: '0', overflow: 'hidden' }}>
        <div style={{ padding: '20px', borderBottom: '1px solid var(--border-glass)', display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
          <h3 style={{ margin: 0, fontSize: '1.1rem', fontWeight: 600, display: 'flex', alignItems: 'center', gap: '8px' }}>
            <Award size={18} color="var(--accent-blue)" /> Accordi Commerciali Attivi
          </h3>
          <span style={{ fontSize: '0.8rem', color: 'var(--text-secondary)', background: 'rgba(255,255,255,0.05)', padding: '4px 10px', borderRadius: '12px' }}>
            {filteredAgreements.length} Accordi
          </span>
        </div>

        {loading ? (
          <div style={{ padding: '60px', textAlign: 'center', color: 'var(--text-secondary)' }}>Caricamento accordi commerciali...</div>
        ) : error ? (
          <div style={{ padding: '60px', textAlign: 'center', color: 'var(--status-red)' }}>{error}</div>
        ) : filteredAgreements.length === 0 ? (
          <div style={{ padding: '60px', textAlign: 'center', color: 'var(--text-secondary)' }}>Nessun accordo commerciale trovato con i filtri selezionati.</div>
        ) : (
          <div style={{ overflowX: 'auto' }}>
            <table style={{ width: '100%', borderCollapse: 'collapse' }}>
              <thead>
                <tr style={{ borderBottom: '1px solid var(--border-glass)', background: 'rgba(255,255,255,0.02)' }}>
                  <th style={thStyle}>Fornitore</th>
                  <th style={thStyle}>Prodotto / SKU</th>
                  <th style={{ ...thStyle, textAlign: 'right' }}>Prezzo Pattuito</th>
                  <th style={thStyle}>Accordo (PFA)</th>
                  <th style={{ ...thStyle, textAlign: 'right' }}>Prezzo Netto Contr.</th>
                  <th style={{ ...thStyle, textAlign: 'right' }}>Volume Acq.</th>
                  <th style={{ ...thStyle, textAlign: 'right' }}>Tot. Fatturato</th>
                  <th style={{ ...thStyle, textAlign: 'right' }}>Rientro Maturato</th>
                  <th style={{ ...thStyle, textAlign: 'right' }}>Netto Medio Real.</th>
                </tr>
              </thead>
              <tbody>
                {filteredAgreements.map(ag => {
                  let pfaLabel = '';
                  let pfaBadgeBg = 'rgba(255,255,255,0.05)';
                  let pfaBadgeColor = 'white';

                  if (ag.pfa_tipo === 'fisso') {
                    pfaLabel = `-${Number(ag.pfa_valore).toFixed(2)} € / ${ag.unita_misura}`;
                    pfaBadgeBg = 'rgba(16, 185, 129, 0.1)';
                    pfaBadgeColor = '#10b981';
                  } else if (ag.pfa_tipo === 'percentuale') {
                    pfaLabel = `-${(Number(ag.pfa_valore) * 100).toFixed(1)}% PFA`;
                    pfaBadgeBg = 'rgba(59, 130, 246, 0.1)';
                    pfaBadgeColor = '#3b82f6';
                  } else if (ag.pfa_tipo === 'scaglioni') {
                    pfaLabel = 'Scaglioni';
                    pfaBadgeBg = 'rgba(245, 158, 11, 0.1)';
                    pfaBadgeColor = '#f59e0b';
                  }

                  return (
                    <tr key={ag.listino_id} style={{ borderBottom: '1px solid var(--border-glass)', transition: 'background 0.2s' }} onMouseEnter={e => e.currentTarget.style.background = 'rgba(255,255,255,0.01)'} onMouseLeave={e => e.currentTarget.style.background = 'transparent'}>
                      <td style={{ ...tdStyle, fontWeight: 500 }}>{ag.fornitore_nome}</td>
                      <td style={tdStyle}>
                        <div style={{ fontWeight: 600 }}>{ag.descrizione}</div>
                        <div style={{ fontSize: '0.75rem', color: 'var(--text-secondary)', fontFamily: 'monospace', marginTop: '2px' }}>{ag.sku_interno}</div>
                      </td>
                      <td style={{ ...tdStyle, textAlign: 'right', fontWeight: 500 }}>€ {Number(ag.prezzo_pattuito).toFixed(2)}</td>
                      <td style={tdStyle}>
                        <div style={{ display: 'inline-flex', flexDirection: 'column', gap: '4px' }}>
                          <span style={{
                            padding: '4px 10px', borderRadius: '12px', fontSize: '0.75rem', fontWeight: 600,
                            background: pfaBadgeBg, color: pfaBadgeColor, textAlign: 'center', display: 'inline-block'
                          }}>
                            {pfaLabel}
                          </span>
                          
                          {/* If scaglioni, show thresholds tooltip/list on hover */}
                          {ag.pfa_tipo === 'scaglioni' && ag.pfa_scaglioni.length > 0 && (
                            <div style={{ fontSize: '0.7rem', color: 'var(--text-secondary)', display: 'flex', flexDirection: 'column', gap: '2px', padding: '4px 8px', background: 'rgba(0,0,0,0.2)', borderRadius: '6px', border: '1px solid rgba(255,255,255,0.03)', marginTop: '4px' }}>
                              {ag.pfa_scaglioni.map(sc => (
                                <div key={sc.id} style={{ display: 'flex', justifyContent: 'space-between', gap: '8px' }}>
                                  <span>&gt; €{sc.soglia_da.toLocaleString('it-IT')}:</span>
                                  <span style={{ color: '#f59e0b', fontWeight: 600 }}>{(sc.valore_percentuale * 100).toFixed(1)}%</span>
                                </div>
                              ))}
                            </div>
                          )}
                        </div>
                      </td>
                      <td style={{ ...tdStyle, textAlign: 'right', fontWeight: 600, color: '#10b981' }}>
                        € {ag.netto_rientro_contratto !== null ? Number(ag.netto_rientro_contratto).toFixed(2) : '—'}
                      </td>
                      <td style={{ ...tdStyle, textAlign: 'right' }}>
                        {Number(ag.quantita_acquistata).toFixed(1)} <span style={{ fontSize: '0.8rem', color: 'var(--text-secondary)' }}>{ag.unita_misura}</span>
                      </td>
                      <td style={{ ...tdStyle, textAlign: 'right' }}>€ {Number(ag.totale_fatturato).toFixed(2)}</td>
                      <td style={{ ...tdStyle, textAlign: 'right', fontWeight: 500, color: '#10b981' }}>
                        € {Number(ag.rientro_accumulato).toFixed(2)}
                      </td>
                      <td style={{ ...tdStyle, textAlign: 'right', fontWeight: 600, color: 'var(--accent-blue)' }}>
                        € {Number(ag.netto_rientro_medio).toFixed(2)}
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
