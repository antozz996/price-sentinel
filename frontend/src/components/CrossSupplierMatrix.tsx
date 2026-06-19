import { useState, useEffect } from 'react';
import { Grid, Search, CheckCircle, RefreshCw, Info, AlertTriangle, Filter } from 'lucide-react';
import { API_BASE, getHeaders } from '../api';

interface FornitoreItem {
  id: number;
  nome_azienda: string;
  p_iva: string;
}

interface PrezzoDettaglio {
  prezzo: number;
  tipo: 'concordato' | 'spot';
}

interface SkuMatrixRow {
  sku_interno: string;
  descrizione: string;
  prezzi: Record<string, PrezzoDettaglio>;
}

export default function CrossSupplierMatrix() {
  const [matrix, setMatrix] = useState<Record<string, SkuMatrixRow> | null>(null);
  const [fornitori, setFornitori] = useState<FornitoreItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [searchQuery, setSearchQuery] = useState('');
  const [onlyComparable, setOnlyComparable] = useState(false);
  const [dataDa, setDataDa] = useState<string>('');
  const [dataA, setDataA] = useState<string>('');
  const [selectedSupplierIds, setSelectedSupplierIds] = useState<number[]>([]);
  const [showFilterDropdown, setShowFilterDropdown] = useState(false);

  const headers = getHeaders();

  const loadData = async (signal?: AbortSignal) => {
    setLoading(true);
    setError(null);
    try {
      let matrixUrl = `${API_BASE}/intelligence/cross-supplier`;
      const queryParams = new URLSearchParams();
      if (dataDa) queryParams.append("data_da", dataDa);
      if (dataA) queryParams.append("data_a", dataA);
      const queryString = queryParams.toString();
      if (queryString) {
        matrixUrl += `?${queryString}`;
      }

      const [fornitoriRes, matrixRes] = await Promise.all([
        fetch(`${API_BASE}/fornitori/`, { headers, signal }),
        fetch(matrixUrl, { headers, signal })
      ]);

      if (!fornitoriRes.ok || !matrixRes.ok) {
        throw new Error("Errore nel caricamento dei dati di comparazione fornitori.");
      }

      const fornitoriData = await fornitoriRes.json();
      const matrixData = await matrixRes.json();

      if (Array.isArray(fornitoriData)) {
        // Mostriamo solo i fornitori che hanno almeno un prezzo inserito nella matrice per evitare colonne vuote inutili
        const activeSupplierIds = new Set<string>();
        if (matrixData) {
          Object.values(matrixData).forEach((row: any) => {
            Object.keys(row.prezzi).forEach(fid => activeSupplierIds.add(fid));
          });
        }
        const filteredFornitori = fornitoriData.filter(f => activeSupplierIds.has(String(f.id)));
        setFornitori(filteredFornitori);

        const stored = localStorage.getItem('ps_selected_supplier_ids');
        if (stored) {
          try {
            const parsed = JSON.parse(stored) as number[];
            const activeIds = filteredFornitori.map(f => f.id);
            const storedActiveIds = parsed.filter(id => activeIds.includes(id));
            
            const newlyAdded = activeIds.filter(id => !parsed.includes(id));
            if (newlyAdded.length > 0) {
              const merged = [...storedActiveIds, ...newlyAdded];
              setSelectedSupplierIds(merged);
              localStorage.setItem('ps_selected_supplier_ids', JSON.stringify(merged));
            } else {
              setSelectedSupplierIds(storedActiveIds);
            }
          } catch (e) {
            setSelectedSupplierIds(filteredFornitori.map(f => f.id));
          }
        } else {
          setSelectedSupplierIds(filteredFornitori.map(f => f.id));
        }
      }
      
      if (matrixData) {
        setMatrix(matrixData);
      }
    } catch (err: any) {
      if (err.name !== 'AbortError') {
        setError(err.message || "Impossibile caricare i dati.");
      }
    } finally {
      setLoading(false);
    }
  };

  const handleSupplierToggle = (id: number) => {
    let updated: number[];
    if (selectedSupplierIds.includes(id)) {
      updated = selectedSupplierIds.filter(x => x !== id);
    } else {
      updated = [...selectedSupplierIds, id];
    }
    setSelectedSupplierIds(updated);
    localStorage.setItem('ps_selected_supplier_ids', JSON.stringify(updated));
  };

  const handleToggleAllSuppliers = (selectAll: boolean) => {
    const updated = selectAll ? fornitori.map(f => f.id) : [];
    setSelectedSupplierIds(updated);
    localStorage.setItem('ps_selected_supplier_ids', JSON.stringify(updated));
  };

  useEffect(() => {
    const controller = new AbortController();
    loadData(controller.signal);
    return () => controller.abort();
  }, [dataDa, dataA]);

  if (loading) {
    return (
      <div style={{ color: 'var(--text-secondary)', padding: '40px', display: 'flex', alignItems: 'center', justifyContent: 'center', gap: '12px' }}>
        <RefreshCw className="animate-spin" size={24} color="var(--accent-blue)" />
        <span style={{ fontSize: '1rem', fontWeight: 500 }}>Caricamento Analisi Comparativa Fornitori...</span>
      </div>
    );
  }

  if (error) {
    return (
      <div style={{ padding: '24px' }}>
        <div className="glass-panel" style={{ padding: '20px', background: 'var(--status-red-bg)', color: 'var(--status-red)', border: '1px solid rgba(239, 68, 68, 0.2)' }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: '10px', fontWeight: 600 }}>
            <AlertTriangle size={20} />
            <span>Errore di Caricamento</span>
          </div>
          <p style={{ margin: '8px 0 0 0', fontSize: '0.9rem', color: 'rgba(255, 255, 255, 0.7)' }}>{error}</p>
        </div>
      </div>
    );
  }

  // Filtriamo gli SKU in base alla ricerca e al toggle comparabile (almeno 2 prezzi presenti)
  const allSkus = matrix ? Object.keys(matrix) : [];
  
  const filteredSkus = allSkus.filter(sku => {
    const row = matrix![sku];
    
    // Filtro di ricerca per SKU o Descrizione
    const matchQuery = 
      sku.toLowerCase().includes(searchQuery.toLowerCase()) || 
      row.descrizione.toLowerCase().includes(searchQuery.toLowerCase());
    
    if (!matchQuery) return false;

    // Filtro prodotti comparabili (almeno 2 fornitori con prezzo)
    if (onlyComparable) {
      const numPrices = Object.keys(row.prezzi).length;
      return numPrices >= 2;
    }

    return true;
  });

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: '24px' }}>
      
      {/* Guida e Legenda */}
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(320px, 1fr))', gap: '20px' }}>
        
        {/* Info Box */}
        <div className="glass-panel" style={{ padding: '20px', display: 'flex', flexDirection: 'column', gap: '10px' }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: '10px' }}>
            <Grid color="var(--accent-blue)" size={20} />
            <h4 style={{ margin: 0, fontWeight: 600 }}>Cos'è la Matrice Fornitori?</h4>
          </div>
          <p style={{ fontSize: '0.8rem', color: 'var(--text-secondary)', margin: 0, lineHeight: 1.5 }}>
            Questa vista incrocia l'intero assortimento merci con i prezzi di tutti i fornitori. 
            Il sistema analizza sia i listini contrattualizzati sia la cronologia delle fatture storiche, evidenziando in modo predittivo dove acquistare per risparmiare.
          </p>
        </div>

        {/* Legenda Colori */}
        <div className="glass-panel" style={{ padding: '20px', display: 'flex', flexDirection: 'column', gap: '10px' }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: '10px' }}>
            <Info color="var(--accent-blue)" size={20} />
            <h4 style={{ margin: 0, fontWeight: 600 }}>Legenda e Badge</h4>
          </div>
          <div style={{ display: 'flex', flexDirection: 'column', gap: '8px', fontSize: '0.8rem' }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
              <span style={{ display: 'inline-block', width: '12px', height: '12px', borderRadius: '3px', background: 'rgba(16, 185, 129, 0.15)', border: '1px solid #10b981' }}></span>
              <span style={{ color: 'var(--text-secondary)' }}>
                <strong style={{ color: '#10b981' }}>Miglior Prezzo (Bordo Verde)</strong>: La tariffa più bassa rilevata per lo SKU corrente.
              </span>
            </div>
            <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
              <span style={{ display: 'inline-block', width: '12px', height: '12px', borderRadius: '3px', background: 'rgba(245, 158, 11, 0.1)', border: '1px solid #f59e0b' }}></span>
              <span style={{ color: 'var(--text-secondary)' }}>
                <strong style={{ color: '#f59e0b' }}>Prezzo con Delta (Arancio)</strong>: Quotazioni più costose rispetto alla miglior scelta (mostra lo spreco unitario ed in %).
              </span>
            </div>
            <div style={{ display: 'flex', alignItems: 'center', gap: '12px' }}>
              <span style={{ fontSize: '0.65rem', background: 'rgba(59,130,246,0.1)', color: 'var(--accent-blue)', padding: '2px 6px', borderRadius: '4px', fontWeight: 600 }}>Concordato</span>
              <span style={{ color: 'var(--text-secondary)' }}>Prezzo fisso bloccato da Listino Master.</span>
            </div>
            <div style={{ display: 'flex', alignItems: 'center', gap: '12px' }}>
              <span style={{ fontSize: '0.65rem', background: 'rgba(255,255,255,0.06)', color: 'var(--text-secondary)', padding: '2px 6px', borderRadius: '4px', fontWeight: 600 }}>Spot</span>
              <span style={{ color: 'var(--text-secondary)' }}>Prezzo minimo d'acquisto registrato in fattura.</span>
            </div>
          </div>
        </div>

      </div>

      {/* Pannello Matrice Principale */}
      <div className="glass-panel" style={{ padding: '24px', display: 'flex', flexDirection: 'column', gap: '20px' }}>
        
        {/* Toolbar Interattiva */}
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', flexWrap: 'wrap', gap: '16px' }}>
          
          {/* Toggle Interruttore Comparabilità */}
          <div style={{ display: 'flex', alignItems: 'center', gap: '12px' }}>
            <label style={{ position: 'relative', display: 'inline-flex', alignItems: 'center', cursor: 'pointer' }}>
              <input
                type="checkbox"
                checked={onlyComparable}
                onChange={e => setOnlyComparable(e.target.checked)}
                style={{
                  width: '38px',
                  height: '20px',
                  appearance: 'none',
                  background: onlyComparable ? 'var(--accent-blue)' : 'rgba(255,255,255,0.1)',
                  borderRadius: '10px',
                  position: 'relative',
                  outline: 'none',
                  cursor: 'pointer',
                  transition: 'background 0.3s'
                }}
              />
              <span style={{
                width: '16px',
                height: '16px',
                background: 'white',
                borderRadius: '50%',
                position: 'absolute',
                left: onlyComparable ? '20px' : '2px',
                top: '2px',
                transition: 'left 0.3s',
                boxShadow: '0 2px 4px rgba(0,0,0,0.3)'
              }} />
              <span style={{ marginLeft: '10px', fontSize: '0.85rem', fontWeight: 600, color: 'var(--text-primary)' }}>
                Mostra solo prodotti comparabili (2+ fornitori)
              </span>
            </label>
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

          {/* Supplier Columns Selector */}
          <div style={{ position: 'relative' }}>
            <button
              onClick={() => setShowFilterDropdown(!showFilterDropdown)}
              className="btn"
              style={{
                display: 'flex',
                alignItems: 'center',
                gap: '8px',
                background: 'rgba(255,255,255,0.03)',
                border: '1px solid var(--border-glass)',
                color: 'white',
                padding: '8px 16px',
                borderRadius: '8px',
                fontSize: '0.85rem',
                cursor: 'pointer',
                height: '38px'
              }}
            >
              <Filter size={14} color="var(--accent-blue)" />
              <span>Fornitori ({selectedSupplierIds.length}/{fornitori.length})</span>
            </button>
            
            {showFilterDropdown && (
              <>
                <div 
                  onClick={() => setShowFilterDropdown(false)} 
                  style={{ position: 'fixed', top: 0, left: 0, right: 0, bottom: 0, zIndex: 999 }}
                />
                <div 
                  className="glass-panel" 
                  style={{
                    position: 'absolute',
                    top: '45px',
                    left: 0,
                    zIndex: 1000,
                    minWidth: '260px',
                    maxHeight: '300px',
                    overflowY: 'auto',
                    padding: '16px',
                    display: 'flex',
                    flexDirection: 'column',
                    gap: '12px',
                    boxShadow: '0 10px 25px rgba(0,0,0,0.5)',
                    border: '1px solid var(--border-glass)',
                    borderRadius: '8px'
                  }}
                >
                  <div style={{ display: 'flex', justifyContent: 'space-between', borderBottom: '1px solid rgba(255,255,255,0.08)', paddingBottom: '8px', marginBottom: '4px' }}>
                    <button 
                      onClick={() => handleToggleAllSuppliers(true)}
                      style={{ background: 'none', border: 'none', color: 'var(--accent-blue)', fontSize: '0.75rem', cursor: 'pointer', fontWeight: 600 }}
                    >
                      Tutti
                    </button>
                    <button 
                      onClick={() => handleToggleAllSuppliers(false)}
                      style={{ background: 'none', border: 'none', color: '#fca5a5', fontSize: '0.75rem', cursor: 'pointer', fontWeight: 600 }}
                    >
                      Deseleziona
                    </button>
                  </div>
                  <div style={{ display: 'flex', flexDirection: 'column', gap: '8px' }}>
                    {fornitori.map(f => {
                      const isChecked = selectedSupplierIds.includes(f.id);
                      return (
                        <label key={f.id} style={{ display: 'flex', alignItems: 'center', gap: '10px', cursor: 'pointer', fontSize: '0.85rem', color: 'var(--text-primary)' }}>
                          <input
                            type="checkbox"
                            checked={isChecked}
                            onChange={() => handleSupplierToggle(f.id)}
                            style={{ cursor: 'pointer', accentColor: 'var(--accent-blue)' }}
                          />
                          <span>{f.nome_azienda}</span>
                        </label>
                      );
                    })}
                  </div>
                </div>
              </>
            )}
          </div>

          {/* Input di Ricerca */}
          <div style={{ position: 'relative', width: '100%', maxWidth: '320px' }}>
            <Search size={16} style={{ position: 'absolute', left: '12px', top: '50%', transform: 'translateY(-50%)', color: 'var(--text-secondary)' }} />
            <input
              type="text"
              placeholder="Cerca SKU o nome prodotto..."
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

        {/* Tabella Matrice */}
        <div style={{ overflowX: 'auto', borderRadius: '8px', border: '1px solid var(--border-glass)' }}>
          <table style={{ width: '100%', borderCollapse: 'collapse' }}>
            <thead>
              <tr style={{ borderBottom: '1px solid var(--border-glass)', color: 'var(--text-secondary)', fontSize: '0.8rem', textAlign: 'left', background: 'rgba(255,255,255,0.01)' }}>
                <th style={{ padding: '16px 12px', minWidth: '180px' }}>Descrizione / SKU Interno</th>
                {fornitori.filter(f => selectedSupplierIds.includes(f.id)).map(f => (
                  <th key={f.id} style={{ padding: '16px 12px', textAlign: 'right', minWidth: '150px' }}>
                    <div style={{ display: 'flex', flexDirection: 'column', gap: '2px', alignItems: 'flex-end' }}>
                      <span style={{ fontWeight: 600, color: 'white', fontSize: '0.85rem' }}>{f.nome_azienda}</span>
                      <span style={{ fontSize: '0.65rem', color: 'var(--text-secondary)' }}>P.IVA {f.p_iva}</span>
                    </div>
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {filteredSkus.length === 0 ? (
                <tr>
                  <td colSpan={fornitori.filter(f => selectedSupplierIds.includes(f.id)).length + 1} style={{ padding: '40px', textAlign: 'center', color: 'var(--text-secondary)' }}>
                    Nessun prodotto corrisponde ai criteri impostati. Prova a cambiare la ricerca o disattivare il toggle.
                  </td>
                </tr>
              ) : (
                filteredSkus.map(sku => {
                  const row = matrix![sku];
                  const visiblePricesList = Object.entries(row.prezzi)
                    .filter(([fid]) => selectedSupplierIds.includes(Number(fid)))
                    .map(([_, p]) => p.prezzo);
                  const minPrice = visiblePricesList.length > 0 ? Math.min(...visiblePricesList) : null;

                  return (
                    <tr key={sku} style={{ borderBottom: '1px solid rgba(255,255,255,0.03)', fontSize: '0.85rem', transition: 'background-color 0.15s' }} className="table-row-hover">
                      
                      {/* Cella SKU / Dettaglio */}
                      <td style={{ padding: '14px 12px', verticalAlign: 'middle' }}>
                        <div style={{ display: 'flex', flexDirection: 'column', gap: '2px' }}>
                          <span style={{ fontWeight: 700, color: 'white' }}>{row.descrizione}</span>
                          <span style={{ fontSize: '0.75rem', color: 'var(--text-secondary)' }}>{sku}</span>
                        </div>
                      </td>

                      {/* Celle Fornitori */}
                      {fornitori.filter(f => selectedSupplierIds.includes(f.id)).map(f => {
                        const priceInfo = row.prezzi[f.id];
                        if (!priceInfo) {
                          return (
                            <td key={f.id} style={{ padding: '14px 12px', textAlign: 'right', color: 'rgba(255,255,255,0.15)', verticalAlign: 'middle' }}>
                              -
                            </td>
                          );
                        }

                        const price = priceInfo.prezzo;
                        const isMin = minPrice !== null && (price - minPrice) <= 0.0101;
                        const deltaUnitario = minPrice !== null ? price - minPrice : 0;
                        const deltaPercent = minPrice !== null && minPrice > 0 ? (deltaUnitario / minPrice) * 100 : 0;

                        return (
                          <td 
                            key={f.id}
                            style={{ 
                              padding: '12px',
                              textAlign: 'right',
                              verticalAlign: 'middle',
                              background: isMin ? 'rgba(16, 185, 129, 0.04)' : 'transparent',
                              border: isMin ? '1px solid rgba(16, 185, 129, 0.25)' : '1px solid transparent',
                              transition: 'background 0.2s',
                              borderRadius: isMin ? '6px' : '0'
                            }}
                          >
                            <div style={{ display: 'flex', flexDirection: 'column', gap: '4px', alignItems: 'flex-end' }}>
                              
                              {/* Prezzo e badge tipologia */}
                              <div style={{ display: 'flex', alignItems: 'center', gap: '6px' }}>
                                <span style={{ 
                                  fontSize: '0.6rem', 
                                  background: priceInfo.tipo === 'concordato' ? 'rgba(59,130,246,0.12)' : 'rgba(255,255,255,0.06)', 
                                  color: priceInfo.tipo === 'concordato' ? 'var(--accent-blue)' : 'var(--text-secondary)', 
                                  padding: '2px 5px', 
                                  borderRadius: '4px', 
                                  fontWeight: 600,
                                  textTransform: 'uppercase'
                                }}>
                                  {priceInfo.tipo}
                                </span>
                                <span style={{ fontWeight: 700, color: isMin ? '#10b981' : '#f59e0b', fontSize: '0.9rem' }}>
                                  € {price.toFixed(2)}
                                </span>
                              </div>

                              {/* Indicazione Delta o Badge di Miglior Prezzo */}
                              {isMin ? (
                                <div style={{ display: 'flex', alignItems: 'center', gap: '3px', color: '#10b981', fontSize: '0.7rem', fontWeight: 600 }}>
                                  <CheckCircle size={10} />
                                  <span>Miglior Prezzo</span>
                                </div>
                              ) : (
                                <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'flex-end', gap: '1px' }}>
                                  <span style={{ fontSize: '0.7rem', color: '#ef4444', fontWeight: 700 }}>
                                    +€ {deltaUnitario.toFixed(2)}
                                  </span>
                                  <span style={{ fontSize: '0.65rem', color: 'rgba(255, 255, 255, 0.45)', fontWeight: 500 }}>
                                    (+{deltaPercent.toFixed(0)}%)
                                  </span>
                                </div>
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
