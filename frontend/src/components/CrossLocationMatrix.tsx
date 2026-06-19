import { useState, useEffect } from 'react';
import { Grid, Download, FileText, Search, ShieldAlert, CheckCircle, RefreshCw, HelpCircle } from 'lucide-react';
import { API_BASE, getHeaders } from '../api';

interface LocationItem {
  id: number;
  nome_struttura: string;
  p_iva: string;
}

interface FornitoreItem {
  id: number;
  nome_azienda: string;
  p_iva: string;
}

export default function CrossLocationMatrix() {
  const [matrix, setMatrix] = useState<Record<string, Record<string, { prezzo: number; fattura_id: number; quantita?: number }>> | null>(null);
  const [locations, setLocations] = useState<LocationItem[]>([]);
  const [fornitori, setFornitori] = useState<FornitoreItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [searchQuery, setSearchQuery] = useState('');
  const [selectedSupplier, setSelectedSupplier] = useState<number | ''>('');
  const [downloading, setDownloading] = useState(false);
  const [dataDa, setDataDa] = useState<string>('');
  const [dataA, setDataA] = useState<string>('');

  const headers = getHeaders();

  const loadData = async (signal?: AbortSignal) => {
    setLoading(true);
    setError(null);
    try {
      let matrixUrl = `${API_BASE}/intelligence/cross-location`;
      const queryParams = new URLSearchParams();
      if (dataDa) queryParams.append("data_da", dataDa);
      if (dataA) queryParams.append("data_a", dataA);
      const queryString = queryParams.toString();
      if (queryString) {
        matrixUrl += `?${queryString}`;
      }

      const [locationsRes, fornitoriRes, matrixRes] = await Promise.all([
        fetch(`${API_BASE}/location/`, { headers, signal }),
        fetch(`${API_BASE}/fornitori/`, { headers, signal }),
        fetch(matrixUrl, { headers, signal })
      ]);

      if (!locationsRes.ok || !fornitoriRes.ok || !matrixRes.ok) {
        throw new Error('Errore nel recupero delle informazioni di Intelligence');
      }

      const locationsData = await locationsRes.json();
      const fornitoriData = await fornitoriRes.json();
      const matrixData = await matrixRes.json();

      if (Array.isArray(locationsData)) setLocations(locationsData);
      if (Array.isArray(fornitoriData)) setFornitori(fornitoriData);
      if (matrixData) setMatrix(matrixData);
    } catch (err: any) {
      if (err.name !== 'AbortError') {
        setError(err.message || 'Impossibile connettersi al server.');
      }
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    const controller = new AbortController();
    loadData(controller.signal);
    return () => controller.abort();
  }, [dataDa, dataA]);

  const handleDownloadPassport = async () => {
    if (!selectedSupplier) return;
    setDownloading(true);
    try {
      const supplier = fornitori.find(f => f.id === selectedSupplier);
      const supplierName = supplier ? supplier.nome_azienda : `Fornitore_${selectedSupplier}`;
      
      const res = await fetch(`${API_BASE}/intelligence/export-vendor-passport/${selectedSupplier}`, {
        headers
      });

      if (!res.ok) {
        throw new Error("Impossibile scaricare il passaporto");
      }

      const blob = await res.blob();
      const url = window.URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = `Vendor_Passport_${supplierName.replace(/\s+/g, '_')}.pdf`;
      document.body.appendChild(a);
      a.click();
      a.remove();
    } catch (err) {
      alert("Errore durante il download del passaporto del fornitore");
    } finally {
      setDownloading(false);
    }
  };

  if (loading) {
    return (
      <div style={{ color: 'var(--text-secondary)', padding: '24px', display: 'flex', alignItems: 'center', gap: '10px' }}>
        <RefreshCw className="animate-spin" size={18} />
        <span>Caricamento dell'Analisi Incrociata Sedi...</span>
      </div>
    );
  }

  if (error) {
    return (
      <div style={{ padding: '24px' }}>
        <div style={{ padding: '16px', borderRadius: '8px', background: 'var(--status-red-bg)', color: 'var(--status-red)', border: '1px solid rgba(239,68,68,0.2)' }}>
          {error}
        </div>
      </div>
    );
  }

  // Filter matrix keys by search query
  const filteredSkus = matrix
    ? Object.keys(matrix).filter(sku => 
        sku.toLowerCase().includes(searchQuery.toLowerCase())
      )
    : [];

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: '24px' }}>
      
      {/* Exporter & Legend Grid */}
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(320px, 1fr))', gap: '20px' }}>
        
        {/* Vendor Passport Panel */}
        <div className="glass-panel" style={{ padding: '20px', display: 'flex', flexDirection: 'column', gap: '16px' }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: '10px' }}>
            <FileText color="var(--accent-blue)" size={20} />
            <h4 style={{ margin: 0, fontWeight: 600 }}>Download Vendor Passport (PDF)</h4>
          </div>
          <p style={{ fontSize: '0.8rem', color: 'var(--text-secondary)', margin: 0 }}>
            Genera un fascicolo PDF di Business Intelligence consolidato contenente l'assortimento, i volumi storici e l'efficienza commerciale del fornitore.
          </p>
          <div style={{ display: 'flex', gap: '12px', alignItems: 'center' }}>
            <select
              value={selectedSupplier}
              onChange={e => setSelectedSupplier(Number(e.target.value) || '')}
              style={{
                flex: 1,
                padding: '10px',
                borderRadius: '8px',
                background: 'rgba(255,255,255,0.03)',
                border: '1px solid var(--border-glass)',
                color: 'white',
                outline: 'none',
                fontSize: '0.85rem'
              }}
            >
              <option value="" style={{ background: '#13131c' }}>Seleziona Fornitore Whitelist...</option>
              {fornitori.map(f => (
                <option key={f.id} value={f.id} style={{ background: '#13131c' }}>
                  {f.nome_azienda} (P.IVA {f.p_iva})
                </option>
              ))}
            </select>
            <button
              onClick={handleDownloadPassport}
              className="btn btn-primary"
              disabled={!selectedSupplier || downloading}
              style={{ height: '38px', padding: '0 16px', fontSize: '0.85rem', display: 'flex', alignItems: 'center', gap: '6px' }}
            >
              <Download size={14} />
              {downloading ? 'Generazione...' : 'Scarica'}
            </button>
          </div>
        </div>

        {/* Legend / Info Panel */}
        <div className="glass-panel" style={{ padding: '20px', display: 'flex', flexDirection: 'column', gap: '12px' }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: '10px' }}>
            <ShieldAlert color="var(--primary-color)" size={20} />
            <h4 style={{ margin: 0, fontWeight: 600 }}>Guida agli Indicatori di Prezzo</h4>
          </div>
          <div style={{ display: 'flex', flexDirection: 'column', gap: '8px', fontSize: '0.8rem' }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
              <CheckCircle size={14} color="#10b981" />
              <span style={{ color: 'var(--text-secondary)' }}>
                <strong style={{ color: '#10b981' }}>Prezzo Ottimale (Verde)</strong>: Il prezzo d'acquisto minimo assoluto ottenuto all'interno del gruppo per quel prodotto.
              </span>
            </div>
            <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
              <ShieldAlert size={14} color="#f59e0b" />
              <span style={{ color: 'var(--text-secondary)' }}>
                <strong style={{ color: '#f59e0b' }}>Prezzo con Varianza (Arancione)</strong>: Prezzi superiori alla tariffa minima di acquisto della holding (leakage potenziale).
              </span>
            </div>
            <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
              <HelpCircle size={14} color="var(--text-secondary)" />
              <span style={{ color: 'var(--text-secondary)' }}>
                <strong style={{ color: 'white' }}>Trattino (-)</strong>: Nessun acquisto per questo SKU effettuato dal locale selezionato.
              </span>
            </div>
          </div>
        </div>

      </div>

      {/* Main Grid Panel */}
      <div className="glass-panel" style={{ padding: '24px', display: 'flex', flexDirection: 'column', gap: '20px' }}>
        
        {/* Table Toolbar */}
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', flexWrap: 'wrap', gap: '20px' }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: '10px' }}>
            <Grid color="var(--accent-blue)" size={20} />
            <h3 style={{ margin: 0, fontSize: '1.25rem', fontWeight: 600 }}>Griglia Comparativa delle Sedi</h3>
          </div>

          {/* Date Filters */}
          <div style={{ display: 'flex', alignItems: 'center', gap: '12px', flexWrap: 'wrap' }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: '6px' }}>
              <span style={{ fontSize: '0.8rem', color: 'var(--text-secondary)' }}>Da:</span>
              <input
                type="date"
                value={dataDa}
                onChange={e => setDataDa(e.target.value)}
                style={{
                  padding: '8px 12px',
                  background: 'rgba(255,255,255,0.03)',
                  border: '1px solid var(--border-glass)',
                  borderRadius: '8px',
                  color: 'white',
                  outline: 'none',
                  fontSize: '0.85rem'
                }}
              />
            </div>
            <div style={{ display: 'flex', alignItems: 'center', gap: '6px' }}>
              <span style={{ fontSize: '0.8rem', color: 'var(--text-secondary)' }}>A:</span>
              <input
                type="date"
                value={dataA}
                onChange={e => setDataA(e.target.value)}
                style={{
                  padding: '8px 12px',
                  background: 'rgba(255,255,255,0.03)',
                  border: '1px solid var(--border-glass)',
                  borderRadius: '8px',
                  color: 'white',
                  outline: 'none',
                  fontSize: '0.85rem'
                }}
              />
            </div>
            {(dataDa || dataA) && (
              <button
                onClick={() => { setDataDa(''); setDataA(''); }}
                style={{
                  padding: '8px 12px',
                  background: 'rgba(239, 68, 68, 0.1)',
                  border: '1px solid rgba(239, 68, 68, 0.2)',
                  borderRadius: '8px',
                  color: '#fca5a5',
                  cursor: 'pointer',
                  fontSize: '0.85rem'
                }}
              >
                Resetta
              </button>
            )}
          </div>

          <div style={{ position: 'relative', width: '100%', maxWidth: '300px' }}>
            <Search size={16} style={{ position: 'absolute', left: '12px', top: '50%', transform: 'translateY(-50%)', color: 'var(--text-secondary)' }} />
            <input
              type="text"
              placeholder="Cerca SKU interno prodotto..."
              value={searchQuery}
              onChange={e => setSearchQuery(e.target.value)}
              style={{
                width: '100%',
                boxSizing: 'border-box',
                padding: '10px 12px 10px 36px',
                background: 'rgba(255,255,255,0.03)',
                border: '1px solid var(--border-glass)',
                borderRadius: '8px',
                color: 'white',
                outline: 'none',
                fontSize: '0.85rem'
              }}
            />
          </div>
        </div>

        {/* Matrix Table */}
        <div style={{ overflowX: 'auto' }}>
          <table style={{ width: '100%', borderCollapse: 'collapse' }}>
            <thead>
              <tr style={{ borderBottom: '1px solid rgba(255,255,255,0.05)', color: 'var(--text-secondary)', fontSize: '0.8rem', textAlign: 'left' }}>
                <th style={{ padding: '12px' }}>Nome Prodotto</th>
                {locations.map(loc => (
                  <th key={loc.id} style={{ padding: '12px', textAlign: 'right' }}>
                    {loc.nome_struttura}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {filteredSkus.length === 0 ? (
                <tr>
                  <td colSpan={locations.length + 1} style={{ padding: '32px', textAlign: 'center', color: 'var(--text-secondary)' }}>
                    Nessun dato corrispondente trovato nella matrice d'acquisto.
                  </td>
                </tr>
              ) : (
                filteredSkus.map(sku => {
                  const locationPrices = matrix ? matrix[sku] : {};
                  const pricesList = Object.values(locationPrices).filter(p => p !== undefined && p !== null);
                  const numericPricesList = pricesList.map((p: any) => p.prezzo);
                  const minPrice = numericPricesList.length > 0 ? Math.min(...numericPricesList) : null;

                  return (
                    <tr key={sku} style={{ borderBottom: '1px solid rgba(255,255,255,0.03)', fontSize: '0.9rem' }}>
                      <td style={{ padding: '16px 12px', fontWeight: 600, color: 'var(--text-primary)' }}>
                        {sku.split(' (')[0]}
                      </td>
                      {locations.map(loc => {
                        const cellData = locationPrices[loc.id];
                        if (cellData === undefined || cellData === null) {
                          return (
                            <td key={loc.id} style={{ padding: '16px 12px', textAlign: 'right', color: 'rgba(255,255,255,0.2)' }}>
                              -
                            </td>
                          );
                        }

                        const price = cellData.prezzo;
                        const fatturaId = cellData.fattura_id;
                        const quantita = cellData.quantita || 0;
                        const isMin = minPrice !== null && (price - minPrice) <= 0.0101;
                        const delta = minPrice !== null && minPrice > 0 ? ((price - minPrice) / minPrice) * 100 : 0;
                        const deltaUnitario = minPrice !== null && price > minPrice ? price - minPrice : 0;
                        const deltaTotaleEconomico = deltaUnitario * quantita;

                        return (
                          <td 
                            key={loc.id} 
                            style={{ 
                              padding: '16px 12px', 
                              textAlign: 'right',
                              cursor: 'pointer',
                              transition: 'background-color 0.2s',
                              position: 'relative'
                            }}
                            title="Visualizza fattura originale"
                            onClick={() => {
                              const token = localStorage.getItem('token');
                              window.open(`${API_BASE}/fatture/${fatturaId}/html?token=${token}`, '_blank');
                            }}
                            onMouseEnter={(e) => {
                              e.currentTarget.style.backgroundColor = 'rgba(255, 255, 255, 0.05)';
                            }}
                            onMouseLeave={(e) => {
                              e.currentTarget.style.backgroundColor = 'transparent';
                            }}
                          >
                            <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'flex-end', gap: '3px' }}>
                              <span style={{ 
                                fontWeight: 600,
                                color: isMin ? '#10b981' : '#f59e0b',
                                display: 'inline-flex',
                                alignItems: 'center',
                                gap: '4px'
                              }}>
                                € {price.toFixed(2)}
                              </span>
                              {!isMin && delta > 0 && deltaTotaleEconomico > 0 && (
                                <span style={{ 
                                  fontSize: '0.75rem', 
                                  color: '#ef4444', 
                                  fontWeight: 700,
                                  marginTop: '1px'
                                }}>
                                  Spreco: € {deltaTotaleEconomico.toFixed(2)} ({quantita.toFixed(0)} BT)
                                </span>
                              )}
                              {!isMin && delta > 0 && (
                                <span style={{ 
                                  fontSize: '0.65rem', 
                                  color: 'rgba(255, 255, 255, 0.45)', 
                                  fontWeight: 500
                                }}>
                                  +{delta.toFixed(0)}% delta
                                </span>
                              )}
                              {isMin && pricesList.length > 1 && (
                                <span style={{ 
                                  fontSize: '0.7rem', 
                                  color: '#10b981', 
                                  background: 'rgba(16,185,129,0.1)', 
                                  padding: '1px 6px', 
                                  borderRadius: '4px',
                                  fontWeight: 500
                                }}>
                                  Best Price
                                </span>
                              )}
                            </div>
                          </td>
                        );
                      })}
                    </tr>
                  );
                })
              )}
            </tbody>
          </table>
        </div>

      </div>

    </div>
  );
}
