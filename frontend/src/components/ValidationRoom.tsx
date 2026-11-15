import { useEffect, useState } from 'react';
import { Anomalia, API_BASE, getHeaders } from '../api';
import { PriceTrendSeries, downloadWithAuth, formatEuro, isLinePoint, pointPriceLabel } from '../priceTrend';
import { AlertTriangle, MessageSquare, Download, Check, Save, Sparkles, RefreshCw, TrendingUp } from 'lucide-react';
import Pagination from './Pagination';

// Snapshot prices are per comparison unit; the invoice quantity is per invoice unit.
const comparisonQuantity = (ano: Anomalia): number => Number(ano.quantita_confronto ?? ano.quantita ?? 0);
const unitLabel = (ano: Anomalia): string => ano.comparison_unit || 'unità di listino';
const trendKey = (sku: string, fornitoreId?: number | null) => `${sku}|${fornitoreId ?? ''}`;

export default function ValidationRoom() {
  const [anomalie, setAnomalie] = useState<Anomalia[]>([]);
  const [loading, setLoading] = useState(true);
  const [products, setProducts] = useState<{ sku_interno: string | null; canonical_name: string; order_name?: string | null }[]>([]);
  const [selectedSkus, setSelectedSkus] = useState<{ [anomaliaId: number]: string }>({});
  const [productQueries, setProductQueries] = useState<{ [anomaliaId: number]: string }>({});
  const [conversionCoefficients, setConversionCoefficients] = useState<{ [anomaliaId: number]: string }>({});

  // Timeline analytics states
  const [expandedTrends, setExpandedTrends] = useState<{ [anomaliaId: number]: boolean }>({});
  // Keyed by sku|supplier: the trend of an anomaly shows only its own supplier.
  const [trendData, setTrendData] = useState<{ [key: string]: PriceTrendSeries | null }>({});
  const [loadingTrend, setLoadingTrend] = useState<{ [key: string]: boolean }>({});
  const [exporting, setExporting] = useState(false);

  // Pagination states
  const [limit, setLimit] = useState(25);
  const [offset, setOffset] = useState(0);
  const [total, setTotal] = useState(0);

  // Load canonical products so operators can search by a human name instead of
  // memorising internal SKU codes.
  const fetchProducts = async () => {
    try {
      const res = await fetch(`${API_BASE}/products`, { headers: getHeaders() });
      if (res.ok) {
        const data = await res.json();
        setProducts(Array.isArray(data) ? data.filter(product => product.sku_interno) : []);
      }
    } catch (err) {
      console.error("Error loading products for manual matching", err);
    }
  };

  const productLabel = (product: { sku_interno: string | null; canonical_name: string; order_name?: string | null }) =>
    `${product.order_name ? `${product.order_name} · ` : ''}${product.canonical_name} — ${product.sku_interno}`;

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
    fetchProducts();
    return () => controller.abort();
  // Pagination is the intended anomaly reload trigger; SKU lookup is static.
  // eslint-disable-next-line react-hooks/exhaustive-deps
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
      alert("Cerca e seleziona un prodotto prima di salvare.");
      return;
    }
    if (!anomalia.fornitore_id) {
      alert("Il fornitore della riga non è identificato: impossibile creare un collegamento sicuro.");
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
          fornitore_id: anomalia.fornitore_id,
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
  const toggleTrend = async (anomaliaId: number, sku: string, fornitoreId?: number | null) => {
    if (expandedTrends[anomaliaId]) {
      setExpandedTrends({ ...expandedTrends, [anomaliaId]: false });
      return;
    }

    setExpandedTrends({ ...expandedTrends, [anomaliaId]: true });

    const key = trendKey(sku, fornitoreId);
    if (trendData[key]) return; // already loaded

    try {
      setLoadingTrend(prev => ({ ...prev, [key]: true }));
      const params = new URLSearchParams({ skus: sku });
      if (fornitoreId) params.set('fornitore_ids', String(fornitoreId));
      const res = await fetch(`${API_BASE}/intelligence/price-trends?${params}`, { headers: getHeaders() });
      if (res.ok) {
        const data = await res.json();
        setTrendData(prev => ({ ...prev, [key]: data?.[sku] ?? null }));
      }
    } catch (err) {
      console.error("Error loading trend data", err);
    } finally {
      setLoadingTrend(prev => ({ ...prev, [key]: false }));
    }
  };

  // Generates 1-click WhatsApp preformatted message
  const handleWhatsAppDispute = (ano: Anomalia) => {
    // Quantity in the same unit as the two prices, so price difference x quantity = total.
    const unit = unitLabel(ano);
    const qtaStr = comparisonQuantity(ano).toLocaleString('it-IT', { maximumFractionDigits: 2 });
    const invoiceQty = Number(ano.quantita ?? 0);
    const invoiceQtyStr = invoiceQty !== comparisonQuantity(ano) && ano.unita_fattura
      ? ` (${invoiceQty.toLocaleString('it-IT', { maximumFractionDigits: 2 })} ${ano.unita_fattura} in fattura)`
      : '';
    const listinoStr = formatEuro(Number(ano.prezzo_listino_snapshot));
    const fatturaStr = formatEuro(Number(ano.prezzo_fatturato_snapshot));
    const deltaStr = formatEuro(Number(ano.delta_totale));

    const message = `Ciao, volevo segnalare un rincaro riscontrato sul vostro ultimo documento per il prodotto "${ano.descrizione_orig}". Il prezzo concordato da listino è di ${listinoStr} / ${unit}, ma in fattura è stato addebitato ${fatturaStr} / ${unit}. Su una quantità di ${qtaStr} ${unit}${invoiceQtyStr}, questo comporta una differenza da stornare pari a ${deltaStr}.\nVi chiediamo cortesemente di emettere nota di credito correttiva. Grazie!`;

    const url = `https://api.whatsapp.com/send?text=${encodeURIComponent(message)}`;
    window.open(url, '_blank');
  };

  // The dossier lists exactly the anomalies of this panel (same filters as the list).
  const handleExportExcel = async () => {
    setExporting(true);
    try {
      await downloadWithAuth('/intelligence/export-dispute-excel', 'dossier_contestazione_rincari.xlsx');
    } catch (err) {
      alert(`Impossibile scaricare il dossier Excel: ${err instanceof Error ? err.message : err}`);
    } finally {
      setExporting(false);
    }
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
          <button className="btn" onClick={handleExportExcel} disabled={exporting} title="Le anomalie di questo pannello, una riga ciascuna: il totale è la somma dei sovrapprezzi" style={{ display: 'flex', alignItems: 'center', gap: '8px', background: 'var(--bg-elevated)', borderColor: 'var(--line-strong)' }}>
            <Download size={16} /> {exporting ? 'Preparazione…' : 'Esporta Dossier Excel'}
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
            const currentTrend = trendData[trendKey(sku, ano.fornitore_id)];
            const isTrendLoading = loadingTrend[trendKey(sku, ano.fornitore_id)] || false;
            const unit = unitLabel(ano);
            const qtyConfronto = comparisonQuantity(ano);

            return (
              <div key={ano.id} className="glass-panel" style={{ padding: '20px', display: 'flex', flexDirection: 'column', gap: '16px', borderLeft: '4px solid var(--crit)' }}>
                
                {/* Header Row */}
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', flexWrap: 'wrap', gap: '12px' }}>
                  <div>
                    <span style={{ fontSize: '0.75rem', fontWeight: 600, color: 'var(--text-secondary)', background: 'var(--bg-elevated)', padding: '2px 8px', borderRadius: 'var(--radius-sm)', textTransform: 'uppercase' }}>
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
                <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(180px, 1fr))', gap: '16px', background: 'var(--bg-inset)', padding: '16px', borderRadius: 'var(--radius-md)' }}>
                  <div>
                    <span style={{ fontSize: '0.75rem', color: 'var(--text-secondary)' }}>Fatturato Netto</span>
                    <div style={{ fontSize: '1.2rem', fontWeight: 600, color: 'var(--text-primary)', fontFamily: 'var(--font-mono)', fontVariantNumeric: 'tabular-nums' }}>
                      {formatEuro(Number(ano.prezzo_fatturato_snapshot))} <span style={{ fontSize: '0.8rem', fontWeight: 400 }}>/ {unit}</span>
                    </div>
                  </div>
                  <div>
                    <span style={{ fontSize: '0.75rem', color: 'var(--text-secondary)' }}>Baseline Listino</span>
                    <div style={{ fontSize: '1.2rem', fontWeight: 600, color: 'var(--ok)', fontFamily: 'var(--font-mono)', fontVariantNumeric: 'tabular-nums' }}>
                      {formatEuro(Number(ano.prezzo_listino_snapshot))} <span style={{ fontSize: '0.8rem', fontWeight: 400 }}>/ {unit}</span>
                    </div>
                  </div>
                  <div>
                    <span style={{ fontSize: '0.75rem', color: 'var(--text-secondary)' }}>Differenza Unitaria</span>
                    <div style={{ fontSize: '1.2rem', fontWeight: 600, color: 'var(--crit)', fontFamily: 'var(--font-mono)', fontVariantNumeric: 'tabular-nums' }}>
                      + € {Number(ano.delta_prezzo).toLocaleString('it-IT', { minimumFractionDigits: 2, maximumFractionDigits: 4 })} <span style={{ fontSize: '0.8rem', fontWeight: 400 }}>/ {unit}</span>
                    </div>
                  </div>
                  <div>
                    <span style={{ fontSize: '0.75rem', color: 'var(--text-secondary)' }}>Volume Acquistato</span>
                    <div style={{ fontSize: '1.2rem', fontWeight: 600, fontFamily: 'var(--font-mono)', fontVariantNumeric: 'tabular-nums' }}>
                      {qtyConfronto.toLocaleString('it-IT', { maximumFractionDigits: 2 })} {unit}
                    </div>
                    {Number(ano.quantita ?? 0) !== qtyConfronto && (
                      <span style={{ fontSize: '0.75rem', color: 'var(--text-secondary)', display: 'block' }}>
                        ({Number(ano.quantita ?? 0).toLocaleString('it-IT', { maximumFractionDigits: 2 })} {ano.unita_fattura || ''} in fattura)
                      </span>
                    )}
                  </div>
                </div>

                {/* Mapping is shown only when ingestion has not already linked the invoice line. */}
                {ano.sku_interno ? (
                  <div style={{ display: 'flex', alignItems: 'center', gap: '10px', background: 'var(--ok-bg)', border: '1px solid var(--ok-border)', padding: '14px 16px', borderRadius: 'var(--radius-lg)', color: 'var(--ok)' }}>
                    <Check size={18} />
                    <div>
                      <strong>Prodotto già associato</strong>
                      <div style={{ fontSize: '0.8rem', marginTop: '2px' }}>
                        SKU {ano.sku_interno}. L’associazione eseguita nel flusso fatture viene riutilizzata automaticamente.
                      </div>
                    </div>
                  </div>
                ) : (
                <div style={{ display: 'flex', flexDirection: 'column', gap: '12px', background: 'var(--warn-bg)', border: '1px solid var(--warn-border)', padding: '16px', borderRadius: 'var(--radius-lg)' }}>
                  <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                    <Sparkles size={16} color="var(--warn)" />
                    <span style={{ fontSize: '0.85rem', color: 'var(--warn)', fontWeight: 600 }}>
                      Associazione mancante: collega questa voce una sola volta
                    </span>
                  </div>
                  
                  <div style={{ display: 'flex', alignItems: 'center', gap: '12px', flexWrap: 'wrap' }}>
                    <div style={{ flex: '2', minWidth: '240px', display: 'flex', flexDirection: 'column', gap: '4px' }}>
                      <span style={{ fontSize: '0.75rem', color: 'var(--text-secondary)' }}>Cerca prodotto per nome, nome informale o SKU</span>
                      <input
                        list={`products-${ano.id}`}
                        value={productQueries[ano.id] || ''}
                        placeholder="Scrivi ad esempio Moët Ice Imperial…"
                        onChange={(e) => {
                          const query = e.target.value;
                          const match = products.find(product => productLabel(product) === query || product.sku_interno === query);
                          setProductQueries(prev => ({ ...prev, [ano.id]: query }));
                          setSelectedSkus(prev => ({ ...prev, [ano.id]: match?.sku_interno || '' }));
                        }}
                        style={{ background: 'var(--bg-inset)', color: 'var(--text-primary)', border: '1px solid var(--line)', padding: '8px 12px', borderRadius: 'var(--radius-sm)', fontSize: '0.85rem', width: '100%' }}
                      />
                      <datalist id={`products-${ano.id}`}>
                        {products.map(product => (
                          <option key={product.sku_interno!} value={productLabel(product)} />
                        ))}
                      </datalist>
                    </div>

                    <div style={{ flex: '1', minWidth: '120px', display: 'flex', flexDirection: 'column', gap: '4px' }}>
                      <span style={{ fontSize: '0.75rem', color: 'var(--text-secondary)' }}>Fattore Conversione (e.g. 6.0)</span>
                      <input 
                        type="number" 
                        step="any"
                        placeholder="1.0"
                        value={conversionCoefficients[ano.id] || ''}
                        onChange={(e) => setConversionCoefficients({ ...conversionCoefficients, [ano.id]: e.target.value })}
                        style={{ background: 'var(--bg-inset)', color: 'var(--text-primary)', border: '1px solid var(--line)', padding: '8px 12px', borderRadius: 'var(--radius-sm)', fontSize: '0.85rem', width: '100%' }}
                      />
                    </div>

                    <div style={{ display: 'flex', alignItems: 'flex-end', height: '100%', paddingTop: '18px' }}>
                      <button className="btn" onClick={() => handleSaveAlias(ano)} style={{ padding: '8px 16px', fontSize: '0.85rem', display: 'flex', alignItems: 'center', gap: '6px', background: 'var(--warn-bg)', borderColor: 'var(--warn-border)', color: 'var(--warn)', borderRadius: 'var(--radius-sm)', transition: 'all 0.2s' }}>
                        <Save size={14} /> Collega Alias
                      </button>
                    </div>
                  </div>
                </div>
                )}

                {/* Collapsible Chronological Historical Price Trend Visualizer */}
                {sku && (
                  <div style={{ borderTop: '1px solid var(--line)', paddingTop: '12px' }}>
                    <button 
                      className="btn" 
                      onClick={() => toggleTrend(ano.id, sku, ano.fornitore_id)}
                      style={{ padding: '6px 12px', fontSize: '0.8rem', display: 'flex', alignItems: 'center', gap: '6px', background: 'var(--accent-bg)', borderColor: 'var(--accent-border)', color: 'var(--accent-text)' }}
                    >
                      <TrendingUp size={14} /> {isTrendOpen ? "Nascondi Trend Storico" : "Visualizza Trend Storico"}
                    </button>

                    {isTrendOpen && (
                      <div className="glass-panel" style={{ marginTop: '12px', padding: '16px', background: 'var(--bg-inset)', display: 'flex', flexDirection: 'column', gap: '16px' }}>
                        <h5 style={{ margin: 0, fontSize: '0.9rem', color: 'var(--accent-text)', fontWeight: 600 }}>📈 Timeline Storico Prezzi (Acquisti & Listino)</h5>
                        
                        {isTrendLoading ? (
                          <div style={{ fontSize: '0.8rem', color: 'var(--text-secondary)', padding: '12px' }}>Caricamento dati analitici...</div>
                        ) : currentTrend && currentTrend.history && currentTrend.history.length > 0 ? (
                          (() => {
                            // Only this supplier's lines, converted to its price-list unit; returns
                            // and lines that cannot be converted stay in the list below, not on the chart.
                            const allPoints = currentTrend.history;
                            const history = allPoints.filter(isLinePoint);
                            const prices = history.map(h => h.prezzo_pagato as number);
                            const activeContract = currentTrend.prezzo_contratto_corrente;
                            const chartUnit = currentTrend.unita_contratto_corrente || history[0]?.unita_confronto || '';

                            const allPrices = [...prices, ...history.map(h => h.prezzo_contratto).filter((v): v is number => v !== null)];
                            if (activeContract) allPrices.push(activeContract);

                            const maxPrice = allPrices.length ? Math.max(...allPrices) * 1.15 : 1;
                            const minPrice = allPrices.length ? Math.min(...allPrices) * 0.85 : 0;
                            const priceRange = maxPrice - minPrice || 1;

                            return (
                              <div style={{ display: 'flex', flexDirection: 'column', gap: '20px' }}>
                                {/* The Graphic Visual Sparkline / Bar Chart */}
                                <div style={{ position: 'relative', height: '140px', borderBottom: '1px solid var(--line-strong)', display: 'flex', justifyContent: 'space-around', alignItems: 'flex-end', padding: '0 16px 8px 16px', marginTop: '10px' }}>
                                  
                                  {/* Baseline contract line */}
                                  {activeContract && (
                                    <div 
                                      style={{ 
                                        position: 'absolute', 
                                        left: 0, 
                                        right: 0, 
                                        bottom: `${((activeContract - minPrice) / priceRange) * 120}px`, 
                                        borderTop: '2px dashed var(--ok)',
                                        zIndex: 1, 
                                        pointerEvents: 'none' 
                                      }}
                                    >
                                      <span style={{ position: 'absolute', right: '4px', top: '-18px', fontSize: '0.7rem', color: 'var(--ok)', background: 'var(--bg-card)', padding: '2px 4px', borderRadius: 'var(--radius-sm)', fontFamily: 'var(--font-mono)', fontVariantNumeric: 'tabular-nums' }}>
                                        Contratto attuale: {formatEuro(activeContract)} / {chartUnit}
                                      </span>
                                    </div>
                                  )}

                                  {history.length === 0 && (
                                    <div style={{ alignSelf: 'center', fontSize: '0.8rem', color: 'var(--text-secondary)' }}>
                                      Nessun acquisto convertibile nell'unità del listino: vedi l'elenco qui sotto.
                                    </div>
                                  )}

                                  {/* Price Trend Points */}
                                  {history.map((pt, idx) => {
                                    const price = pt.prezzo_pagato as number;
                                    const pointHeight = ((price - minPrice) / priceRange) * 120;
                                    const formattedDate = new Date(pt.data).toLocaleDateString('it-IT', { day: '2-digit', month: '2-digit' });
                                    // Red only against the price list valid on that invoice's date.
                                    const isOvercharge = pt.prezzo_contratto !== null && price > pt.prezzo_contratto;

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
                                            background: isOvercharge ? 'var(--crit)' : 'var(--accent)',
                                            borderRadius: '4px',
                                            transition: 'all 0.3s',
                                            opacity: 0.8,
                                            boxShadow: 'none'
                                          }}
                                        />

                                        {/* Hover Tooltip / Detail bubble */}
                                        <div className="trend-tooltip" style={{ fontSize: '0.75rem', color: 'var(--text-primary)', marginTop: '6px', textAlign: 'center' }}>
                                          <div style={{ fontWeight: 600, fontFamily: 'var(--font-mono)', fontVariantNumeric: 'tabular-nums' }}>{formatEuro(price)}</div>
                                          <div style={{ fontSize: '0.65rem', color: 'var(--text-secondary)' }}>{formattedDate}</div>
                                        </div>
                                      </div>
                                    );
                                  })}
                                </div>

                                {/* Tabular Chronological List for high precision */}
                                <div style={{ display: 'flex', flexDirection: 'column', gap: '6px', maxHeight: '200px', overflowY: 'auto' }}>
                                  {allPoints.map((pt, idx) => {
                                    const over = isLinePoint(pt) && pt.prezzo_contratto !== null && (pt.prezzo_pagato as number) > pt.prezzo_contratto;
                                    return (
                                      <div key={idx} style={{ display: 'flex', justifyContent: 'space-between', gap: '12px', flexWrap: 'wrap', padding: '6px 12px', background: 'var(--bg-inset)', borderRadius: 'var(--radius-sm)', fontSize: '0.8rem', opacity: isLinePoint(pt) ? 1 : 0.75 }}>
                                        <span style={{ color: 'var(--text-secondary)' }}>
                                          📅 {new Date(pt.data).toLocaleDateString('it-IT')}
                                          {pt.is_reso && <strong style={{ marginLeft: '6px', color: 'var(--warn)' }}>RESO (nota di credito)</strong>}
                                        </span>
                                        <span>
                                          Fornitore: <strong>{pt.fornitore}</strong>
                                        </span>
                                        <span style={{ fontWeight: 600, color: over ? 'var(--crit)' : 'var(--text-primary)', fontFamily: 'var(--font-mono)', fontVariantNumeric: 'tabular-nums' }}>
                                          {pointPriceLabel(pt)}
                                          {pt.confrontabile && pt.unita_fattura !== pt.unita_confronto && ` (fatt. ${formatEuro(pt.prezzo_fattura)} / ${pt.unita_fattura})`}
                                          {` · Qta ${pt.quantita.toLocaleString('it-IT')} ${pt.unita_fattura}`}
                                          {pt.prezzo_contratto !== null && pt.confrontabile && ` · listino ${formatEuro(pt.prezzo_contratto)}`}
                                        </span>
                                      </div>
                                    );
                                  })}
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
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', flexWrap: 'wrap', gap: '12px', borderTop: '1px solid var(--line)', paddingTop: '16px' }}>
                  <div style={{ display: 'flex', gap: '10px' }}>
                    <button className="btn" onClick={() => handleWhatsAppDispute(ano)} style={{ display: 'flex', alignItems: 'center', gap: '8px', background: '#25D366', color: 'white', borderColor: '#25D366' }}>
                      <MessageSquare size={16} /> 💬 Contesta su WhatsApp
                    </button>
                  </div>
                  <div style={{ display: 'flex', gap: '12px' }}>
                    <button className="btn btn-primary" onClick={() => handleAzione(ano.id, 'accetta')} style={{ display: 'flex', alignItems: 'center', gap: '8px', background: 'var(--status-green)', borderColor: 'var(--status-green)' }}>
                      <Check size={16} /> Accetta Variazione
                    </button>
                    <button className="btn" onClick={() => handleAzione(ano.id, 'segnala')} style={{ display: 'flex', alignItems: 'center', gap: '8px', color: 'var(--crit)', background: 'var(--crit-bg)', borderColor: 'var(--crit-border)' }}>
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
