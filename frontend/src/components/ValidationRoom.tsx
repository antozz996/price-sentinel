import { useEffect, useState } from 'react';
import { Anomalia, API_BASE, getHeaders } from '../api';
import { AlertTriangle, MessageSquare, Download, Check, Save, Sparkles, RefreshCw, TrendingUp } from 'lucide-react';
import Pagination from './Pagination';

export default function ValidationRoom() {
  const [anomalie, setAnomalie] = useState<Anomalia[]>([]);
  const [loading, setLoading] = useState(true);
  const [skus, setSkus] = useState<{ sku_interno: string; descrizione_pattuita: string }[]>([]);
  const [selectedSkus, setSelectedSkus] = useState<{ [anomaliaId: number]: string }>({});
  const [conversionCoefficients, setConversionCoefficients] = useState<{ [anomaliaId: number]: string }>({});

  // Timeline analytics states
  const [expandedTrends, setExpandedTrends] = useState<{ [anomaliaId: number]: boolean }>({});
  const [trendData, setTrendData] = useState<{ [sku: string]: any }>({});
  const [loadingTrend, setLoadingTrend] = useState<{ [sku: string]: boolean }>({});

  // Pagination states
  const [limit, setLimit] = useState(25);
  const [offset, setOffset] = useState(0);
  const [total, setTotal] = useState(0);

  // Load all master list SKUs to allow manual override mapping
  const fetchSKUs = async () => {
    try {
      const res = await fetch(`${API_BASE}/listino/?limit=5000`, { headers: getHeaders() });
      if (res.ok) {
        const data = await res.json();
        setSkus(data);
      }
    } catch (err) {
      console.error("Error loading SKUs for manual matching", err);
    }
  };

  const fetchAnomalie = async (signal?: AbortSignal) => {
    try {
      setLoading(true);
      const params = new URLSearchParams();
      params.set('stato', 'da_verificare');
      params.set('limit', limit.toString());
      params.set('offset', offset.toString());

      const res = await fetch(`${API_BASE}/anomalie/?${params}`, { headers: getHeaders(), signal });
      if (!res.ok) {
        throw new Error(`Errore API: ${res.status}`);
      }

      const totalHeader = res.headers.get('X-Total-Count');
      if (totalHeader) {
        setTotal(parseInt(totalHeader, 10));
      } else {
        setTotal(0);
      }

      const data = await res.json();
      if (Array.isArray(data)) {
        setAnomalie(data);
      } else {
        setAnomalie([]);
      }
    } catch (err: any) {
      if (err.name !== 'AbortError') {
        console.error(err);
      }
    } finally {
      if (!signal?.aborted) {
        setLoading(false);
      }
    }
  };

  useEffect(() => {
    const controller = new AbortController();
    fetchAnomalie(controller.signal);
    fetchSKUs();
    return () => controller.abort();
  }, [limit, offset]);

  const handleAzione = async (id: number, azione: any, customNota?: string) => {
    try {
      const nota = customNota || (azione === 'accetta' ? 'Accettato via Dashboard' : 'Segnalato via Dashboard');
      const res = await fetch(`${API_BASE}/anomalie/${id}/azione`, {
        method: 'POST',
        headers: getHeaders(),
        body: JSON.stringify({ azione, nota })
      });
      if (!res.ok) throw new Error(`Errore: ${res.status}`);
      fetchAnomalie();
    } catch (err) {
      alert("Errore durante l'azione: " + err);
    }
  };

  // Create permanent dictionary alias mapping L1
  const handleSaveAlias = async (anomalia: Anomalia) => {
    const sku = selectedSkus[anomalia.id];
    if (!sku) {
      alert("Per favore, seleziona uno SKU interno prima di salvare.");
      return;
    }

    const scaleVal = conversionCoefficients[anomalia.id] ? parseFloat(conversionCoefficients[anomalia.id]) : 1.0;
    if (isNaN(scaleVal) || scaleVal <= 0) {
      alert("Fattore di conversione non valido. Inserire un numero positivo.");
      return;
    }

    try {
      const res = await fetch(`${API_BASE}/alias/`, {
        method: 'POST',
        headers: getHeaders(),
        body: JSON.stringify({
          fornitore_id: anomalia.fornitore_id || 1, // Fallback safely to first vendor if null
          codice_fornitore_originale: anomalia.codice_fornitore || 'RAW_CODE',
          sku_interno: sku,
          coefficiente_conversione: scaleVal
        })
      });

      if (res.ok) {
        alert(`💾 Associazione salvata permanentemente! Lo SKU ${sku} è ora associato a ${anomalia.codice_fornitore} con coefficiente ${scaleVal}`);
        // Automatica accettazione dopo mapping riuscito
        handleAzione(anomalia.id, 'accetta', `Autoregolato: Mappato alias permanentemente a SKU ${sku} (Coeff: ${scaleVal})`);
      } else {
        const errData = await res.json();
        alert(`Errore: ${errData.detail || 'Impossibile salvare alias'}`);
      }
    } catch (err) {
      alert("Errore durante il salvataggio dell'alias: " + err);
    }
  };

  // Toggle visual trend
  const toggleTrend = async (anomaliaId: number, sku: string) => {
    if (expandedTrends[anomaliaId]) {
      setExpandedTrends({ ...expandedTrends, [anomaliaId]: false });
      return;
    }

    setExpandedTrends({ ...expandedTrends, [anomaliaId]: true });

    if (trendData[sku]) return; // already loaded

    try {
      setLoadingTrend(prev => ({ ...prev, [sku]: true }));
      const res = await fetch(`${API_BASE}/intelligence/price-trend/${sku}`, { headers: getHeaders() });
      if (res.ok) {
        const data = await res.json();
        setTrendData(prev => ({ ...prev, [sku]: data }));
      }
    } catch (err) {
      console.error("Error loading trend data", err);
    } finally {
      setLoadingTrend(prev => ({ ...prev, [sku]: false }));
    }
  };

  // Generates 1-click WhatsApp preformatted message
  const handleWhatsAppDispute = (ano: Anomalia) => {
    const qtaStr = Number(ano.quantita || 1).toFixed(2);
    const listinoStr = Number(ano.prezzo_listino_snapshot).toFixed(2);
    const fatturaStr = Number(ano.prezzo_fatturato_snapshot).toFixed(2);
    const deltaStr = Number(ano.delta_totale).toFixed(2);
    
    const message = `Ciao, volevo segnalare un rincaro riscontrato sul vostro ultimo documento per il prodotto "${ano.descrizione_orig}". Il prezzo concordato da listino è di € ${listinoStr}, ma in fattura è stato addebitato € ${fatturaStr}. Su una quantità di ${qtaStr} unità, questo comporta una differenza da stornare pari a € ${deltaStr}.\nVi chiediamo cortesemente di emettere nota di credito correttiva. Grazie!`;
    
    const url = `https://api.whatsapp.com/send?text=${encodeURIComponent(message)}`;
    window.open(url, '_blank');
  };

  const handleExportExcel = () => {
    window.open(`${API_BASE}/intelligence/export-dispute-excel?soglia=5`, '_blank');
  };

  if (loading) return <div style={{ color: 'var(--text-secondary)', padding: '24px' }}>Caricamento anomalie...</div>;

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: '24px' }}>
      
      {/* Top Banner and Actions */}
      <div className="glass-panel" style={{ padding: '20px 24px', display: 'flex', justifyContent: 'space-between', alignItems: 'center', flexWrap: 'wrap', gap: '16px' }}>
        <div>
          <h3 style={{ margin: 0, fontWeight: 600 }}>Pannello Validazione Anomalie</h3>
          <span style={{ fontSize: '0.85rem', color: 'var(--text-secondary)' }}>
            Verifica gli scostamenti di prezzo e contesta o accetta le modifiche tariffarie
          </span>
        </div>
        <div style={{ display: 'flex', gap: '12px' }}>
          <button className="btn" onClick={handleExportExcel} style={{ display: 'flex', alignItems: 'center', gap: '8px', background: 'rgba(255,255,255,0.05)', borderColor: 'rgba(255,255,255,0.1)' }}>
            <Download size={16} /> Esporta Dossier Excel
          </button>
          <button className="btn btn-primary" onClick={() => fetchAnomalie()} style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
            <RefreshCw size={16} /> Refresh ({total})
          </button>
        </div>
      </div>

      {/* Anomalies List */}
      <div style={{ display: 'flex', flexDirection: 'column', gap: '16px' }}>
        {anomalie.length === 0 ? (
          <div className="glass-panel" style={{ padding: '48px', textAlign: 'center', color: 'var(--text-secondary)' }}>
            🎉 Ottimo lavoro! Nessuna anomalia pendente da verificare.
          </div>
        ) : (
          anomalie.map((ano) => {
            const rincaroPercentuale = ((Number(ano.prezzo_fatturato_snapshot) - Number(ano.prezzo_listino_snapshot)) / Number(ano.prezzo_listino_snapshot) * 100);
            const isTrendOpen = expandedTrends[ano.id] || false;
            const sku = ano.sku_interno || selectedSkus[ano.id] || "";
            const currentTrend = trendData[sku];
            const isTrendLoading = loadingTrend[sku] || false;

            return (
              <div key={ano.id} className="glass-panel" style={{ padding: '20px', display: 'flex', flexDirection: 'column', gap: '16px', borderLeft: '4px solid #ef4444' }}>
                
                {/* Header Row */}
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', flexWrap: 'wrap', gap: '12px' }}>
                  <div>
                    <span style={{ fontSize: '0.75rem', fontWeight: 600, color: 'var(--text-secondary)', background: 'rgba(255,255,255,0.05)', padding: '2px 8px', borderRadius: '4px', textTransform: 'uppercase' }}>
                      ID Anomalia #{ano.id}
                    </span>
                    <h4 style={{ margin: '8px 0 4px 0', fontWeight: 600 }}>{ano.descrizione_orig || `Riga #${ano.riga_fattura_id}`}</h4>
                    <span style={{ fontSize: '0.85rem', color: 'var(--text-secondary)' }}>
                      Fornitore: <strong>{ano.fornitore_nome || 'N/D'}</strong> | Codice: {ano.codice_fornitore || 'N/D'}
                    </span>
                  </div>
                  <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'flex-end' }}>
                    <span className="badge badge-red" style={{ fontSize: '1rem', padding: '6px 12px', borderRadius: '8px' }}>
                      + € {Number(ano.delta_totale).toFixed(2)} Totale
                    </span>
                    <span style={{ fontSize: '0.75rem', color: 'var(--text-secondary)', marginTop: '4px' }}>
                      Rincaro del {rincaroPercentuale.toFixed(1)}%
                    </span>
                  </div>
                </div>

                {/* Audit Grid Details */}
                <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(180px, 1fr))', gap: '16px', background: 'rgba(255,255,255,0.02)', padding: '16px', borderRadius: '8px' }}>
                  <div>
                    <span style={{ fontSize: '0.75rem', color: 'var(--text-secondary)' }}>Fatturato Netto</span>
                    <div style={{ fontSize: '1.2rem', fontWeight: 600, color: 'var(--text-primary)' }}>
                      € {Number(ano.prezzo_fatturato_snapshot).toFixed(2)} <span style={{ fontSize: '0.8rem', fontWeight: 400 }}>/ cad</span>
                    </div>
                  </div>
                  <div>
                    <span style={{ fontSize: '0.75rem', color: 'var(--text-secondary)' }}>Baseline Listino</span>
                    <div style={{ fontSize: '1.2rem', fontWeight: 600, color: '#10b981' }}>
                      € {Number(ano.prezzo_listino_snapshot).toFixed(2)} <span style={{ fontSize: '0.8rem', fontWeight: 400 }}>/ cad</span>
                    </div>
                  </div>
                  <div>
                    <span style={{ fontSize: '0.75rem', color: 'var(--text-secondary)' }}>Differenza Unitaria</span>
                    <div style={{ fontSize: '1.2rem', fontWeight: 600, color: '#ef4444' }}>
                      + € {Number(ano.delta_prezzo).toFixed(2)}
                    </div>
                  </div>
                  <div>
                    <span style={{ fontSize: '0.75rem', color: 'var(--text-secondary)' }}>Volume Acquistato</span>
                    <div style={{ fontSize: '1.2rem', fontWeight: 600 }}>
                      {Number(ano.quantita).toFixed(2)} unità
                    </div>
                  </div>
                </div>

                {/* Interactive Auto-Mapping bulb trigger */}
                <div style={{ display: 'flex', flexDirection: 'column', gap: '12px', background: 'rgba(245, 158, 11, 0.04)', border: '1px solid rgba(245, 158, 11, 0.1)', padding: '16px', borderRadius: '12px' }}>
                  <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                    <Sparkles size={16} color="#f59e0b" />
                    <span style={{ fontSize: '0.85rem', color: 'rgba(245, 158, 11, 0.95)', fontWeight: 600 }}>
                      💡 Suggerimento Auto-Mapping permanentemente:
                    </span>
                  </div>
                  
                  <div style={{ display: 'flex', alignItems: 'center', gap: '12px', flexWrap: 'wrap' }}>
                    <div style={{ flex: '2', minWidth: '240px', display: 'flex', flexDirection: 'column', gap: '4px' }}>
                      <span style={{ fontSize: '0.75rem', color: 'var(--text-secondary)' }}>Associa a Prodotto Listino</span>
                      <select 
                        value={selectedSkus[ano.id] || ''} 
                        onChange={(e) => setSelectedSkus({ ...selectedSkus, [ano.id]: e.target.value })}
                        style={{ background: 'rgba(0,0,0,0.2)', color: 'white', border: '1px solid rgba(255,255,255,0.1)', padding: '8px 12px', borderRadius: '8px', fontSize: '0.85rem', width: '100%' }}
                      >
                        <option value="">Seleziona lo SKU per agganciare l'Alias...</option>
                        {skus.map((s) => (
                          <option key={s.sku_interno} value={s.sku_interno}>
                            {s.sku_interno} - {s.descrizione_pattuita}
                          </option>
                        ))}
                      </select>
                    </div>

                    <div style={{ flex: '1', minWidth: '120px', display: 'flex', flexDirection: 'column', gap: '4px' }}>
                      <span style={{ fontSize: '0.75rem', color: 'var(--text-secondary)' }}>Fattore Conversione (e.g. 6.0)</span>
                      <input 
                        type="number" 
                        step="any"
                        placeholder="1.0"
                        value={conversionCoefficients[ano.id] || ''}
                        onChange={(e) => setConversionCoefficients({ ...conversionCoefficients, [ano.id]: e.target.value })}
                        style={{ background: 'rgba(0,0,0,0.2)', color: 'white', border: '1px solid rgba(255,255,255,0.1)', padding: '8px 12px', borderRadius: '8px', fontSize: '0.85rem', width: '100%' }}
                      />
                    </div>

                    <div style={{ display: 'flex', alignItems: 'flex-end', height: '100%', paddingTop: '18px' }}>
                      <button className="btn" onClick={() => handleSaveAlias(ano)} style={{ padding: '8px 16px', fontSize: '0.85rem', display: 'flex', alignItems: 'center', gap: '6px', background: 'rgba(245, 158, 11, 0.15)', borderColor: 'rgba(245, 158, 11, 0.2)', color: '#f59e0b', borderRadius: '8px', transition: 'all 0.2s' }}>
                        <Save size={14} /> Collega Alias
                      </button>
                    </div>
                  </div>
                </div>

                {/* Collapsible Chronological Historical Price Trend Visualizer */}
                {sku && (
                  <div style={{ borderTop: '1px solid rgba(255,255,255,0.05)', paddingTop: '12px' }}>
                    <button 
                      className="btn" 
                      onClick={() => toggleTrend(ano.id, sku)} 
                      style={{ padding: '6px 12px', fontSize: '0.8rem', display: 'flex', alignItems: 'center', gap: '6px', background: 'rgba(59, 130, 246, 0.1)', borderColor: 'rgba(59, 130, 246, 0.2)', color: '#3b82f6' }}
                    >
                      <TrendingUp size={14} /> {isTrendOpen ? "Nascondi Trend Storico" : "Visualizza Trend Storico"}
                    </button>

                    {isTrendOpen && (
                      <div className="glass-panel" style={{ marginTop: '12px', padding: '16px', background: 'rgba(0,0,0,0.3)', display: 'flex', flexDirection: 'column', gap: '16px' }}>
                        <h5 style={{ margin: 0, fontSize: '0.9rem', color: '#3b82f6', fontWeight: 600 }}>📈 Timeline Storico Prezzi (Acquisti & Listino)</h5>
                        
                        {isTrendLoading ? (
                          <div style={{ fontSize: '0.8rem', color: 'var(--text-secondary)', padding: '12px' }}>Caricamento dati analitici...</div>
                        ) : currentTrend && currentTrend.history && currentTrend.history.length > 0 ? (
                          (() => {
                            const history = currentTrend.history;
                            const prices = history.map((h: any) => h.prezzo_pagato);
                            const activeContract = currentTrend.prezzo_contratto_corrente;
                            
                            const allPrices = [...prices];
                            if (activeContract) allPrices.push(activeContract);
                            
                            const maxPrice = Math.max(...allPrices) * 1.15;
                            const minPrice = Math.min(...allPrices) * 0.85;
                            const priceRange = maxPrice - minPrice || 1;

                            return (
                              <div style={{ display: 'flex', flexDirection: 'column', gap: '20px' }}>
                                {/* The Graphic Visual Sparkline / Bar Chart */}
                                <div style={{ position: 'relative', height: '140px', borderBottom: '1px solid rgba(255,255,255,0.1)', display: 'flex', justifyContent: 'space-around', alignItems: 'flex-end', padding: '0 16px 8px 16px', marginTop: '10px' }}>
                                  
                                  {/* Baseline contract line */}
                                  {activeContract && (
                                    <div 
                                      style={{ 
                                        position: 'absolute', 
                                        left: 0, 
                                        right: 0, 
                                        bottom: `${((activeContract - minPrice) / priceRange) * 120}px`, 
                                        borderTop: '2px dashed #10b981', 
                                        zIndex: 1, 
                                        pointerEvents: 'none' 
                                      }}
                                    >
                                      <span style={{ position: 'absolute', right: '4px', top: '-18px', fontSize: '0.7rem', color: '#10b981', background: 'rgba(0,0,0,0.8)', padding: '2px 4px', borderRadius: '4px' }}>
                                        Contratto: € {activeContract.toFixed(2)}
                                      </span>
                                    </div>
                                  )}

                                  {/* Price Trend Points */}
                                  {history.map((pt: any, idx: number) => {
                                    const pointHeight = ((pt.prezzo_pagato - minPrice) / priceRange) * 120;
                                    const formattedDate = new Date(pt.data).toLocaleDateString('it-IT', { day: '2-digit', month: '2-digit' });
                                    const isOvercharge = activeContract && pt.prezzo_pagato > activeContract;

                                    return (
                                      <div 
                                        key={idx} 
                                        className="trend-bar-wrapper"
                                        style={{ 
                                          display: 'flex', 
                                          flexDirection: 'column', 
                                          alignItems: 'center', 
                                          position: 'relative', 
                                          height: '100%', 
                                          justifyContent: 'flex-end',
                                          width: '100%',
                                          zIndex: 2
                                        }}
                                      >
                                        {/* Dynamic Bar Element */}
                                        <div 
                                          style={{ 
                                            height: `${Math.max(pointHeight, 5)}px`, 
                                            width: '8px', 
                                            background: isOvercharge ? '#ef4444' : '#3b82f6', 
                                            borderRadius: '4px', 
                                            transition: 'all 0.3s', 
                                            opacity: 0.8,
                                            boxShadow: isOvercharge ? '0 0 8px rgba(239, 68, 68, 0.4)' : 'none'
                                          }}
                                        />

                                        {/* Hover Tooltip / Detail bubble */}
                                        <div className="trend-tooltip" style={{ fontSize: '0.75rem', color: '#fff', marginTop: '6px', textAlign: 'center' }}>
                                          <div style={{ fontWeight: 600 }}>€ {pt.prezzo_pagato.toFixed(2)}</div>
                                          <div style={{ fontSize: '0.65rem', color: 'var(--text-secondary)' }}>{formattedDate}</div>
                                        </div>
                                      </div>
                                    );
                                  })}
                                </div>

                                {/* Tabular Chronological List for high precision */}
                                <div style={{ display: 'flex', flexDirection: 'column', gap: '6px', maxHeight: '200px', overflowY: 'auto' }}>
                                  {history.map((pt: any, idx: number) => (
                                    <div key={idx} style={{ display: 'flex', justifyContent: 'space-between', padding: '6px 12px', background: 'rgba(255,255,255,0.02)', borderRadius: '6px', fontSize: '0.8rem' }}>
                                      <span style={{ color: 'var(--text-secondary)' }}>
                                        📅 {new Date(pt.data).toLocaleDateString('it-IT')}
                                      </span>
                                      <span>
                                        Fornitore: <strong>{pt.fornitore}</strong>
                                      </span>
                                      <span style={{ fontWeight: 600, color: activeContract && pt.prezzo_pagato > activeContract ? '#ef4444' : '#fff' }}>
                                        € {pt.prezzo_pagato.toFixed(2)} / cad (Qta: {pt.quantita})
                                      </span>
                                    </div>
                                  ))}
                                </div>
                              </div>
                            );
                          })()
                        ) : (
                          <div style={{ fontSize: '0.8rem', color: 'var(--text-secondary)', padding: '12px', textAlign: 'center' }}>
                            📭 Nessun dato storico di acquisto registrato per questo prodotto.
                          </div>
                        )}
                      </div>
                    )}
                  </div>
                )}

                {/* Action Controls Row */}
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', flexWrap: 'wrap', gap: '12px', borderTop: '1px solid rgba(255,255,255,0.05)', paddingTop: '16px' }}>
                  <div style={{ display: 'flex', gap: '10px' }}>
                    <button className="btn" onClick={() => handleWhatsAppDispute(ano)} style={{ display: 'flex', alignItems: 'center', gap: '8px', background: '#25D366', color: 'white', borderColor: '#25D366' }}>
                      <MessageSquare size={16} /> 💬 Contesta su WhatsApp
                    </button>
                  </div>
                  <div style={{ display: 'flex', gap: '12px' }}>
                    <button className="btn btn-primary" onClick={() => handleAzione(ano.id, 'accetta')} style={{ display: 'flex', alignItems: 'center', gap: '8px', background: 'var(--status-green)', borderColor: 'var(--status-green)' }}>
                      <Check size={16} /> Accetta Variazione
                    </button>
                    <button className="btn" onClick={() => handleAzione(ano.id, 'segnala')} style={{ display: 'flex', alignItems: 'center', gap: '8px', color: 'var(--status-red)', background: 'var(--status-red-bg)', borderColor: 'rgba(239, 68, 68, 0.2)' }}>
                      <AlertTriangle size={16} /> Segnala & Escala
                    </button>
                  </div>
                </div>

              </div>
            );
          })
        )}
      </div>

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
  );
}
