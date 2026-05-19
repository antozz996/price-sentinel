import { useState, useEffect } from 'react';
import { ShoppingCart, Plus, Trash2, TrendingUp, AlertTriangle, ShieldCheck, CheckCircle2 } from 'lucide-react';
import { API_BASE, getHeaders } from '../api';

interface LocationItem {
  id: number;
  nome_struttura: string;
}

interface OrderItemInput {
  sku_interno: string;
  quantita: number;
  prezzo_inserito: number | '';
}

interface ConfrontoPrezzoItem {
  fornitore_id: number;
  fornitore_nome: string;
  prezzo: number;
}

interface RigaOttimizzata {
  sku_interno: string;
  descrizione: string;
  quantita: number;
  prezzo_inserito: number;
  prezzo_ottimale: number;
  tipo_regola: string; // concordato, spot_ottimale, sconosciuto
  fornitore_id: number;
  fornitore_nome: string;
  is_anomalia: boolean;
  dettaglio_anomalia?: string;
  confronto_prezzi: ConfrontoPrezzoItem[];
}

interface Sintesi {
  spesa_totale_blindata: number;
  risparmio_preventivo_stimato: number;
  numero_anomalie: number;
  avvisi_preventivi: string[];
}

interface OptimizationResult {
  righe_ottimizzate: RigaOttimizzata[];
  sintesi: Sintesi;
}

export default function OrderOptimizer() {
  const [locations, setLocations] = useState<LocationItem[]>([]);
  const [availableSkus, setAvailableSkus] = useState<string[]>([]);
  const [selectedLocation, setSelectedLocation] = useState<number | ''>('');
  
  // Cart state
  const [basket, setBasket] = useState<OrderItemInput[]>([
    { sku_interno: '', quantita: 1, prezzo_inserito: '' }
  ]);

  // Result states
  const [loadingOpt, setLoadingOpt] = useState(false);
  const [optResult, setOptResult] = useState<OptimizationResult | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [successMsg, setSuccessMsg] = useState<string | null>(null);
  const [submittingOrder, setSubmittingOrder] = useState(false);

  const headers = getHeaders();

  useEffect(() => {
    async function loadInitialData() {
      try {
        const [locRes, matrixRes] = await Promise.all([
          fetch(`${API_BASE}/location/`, { headers }),
          fetch(`${API_BASE}/intelligence/cross-location`, { headers })
        ]);

        if (locRes.ok) {
          const locData = await locRes.json();
          if (Array.isArray(locData)) {
            setLocations(locData);
            if (locData.length > 0) setSelectedLocation(locData[0].id);
          }
        }

        if (matrixRes.ok) {
          const matrixData = await matrixRes.json();
          if (matrixData) {
            setAvailableSkus(Object.keys(matrixData));
            // Default first basket item
            if (Object.keys(matrixData).length > 0) {
              setBasket([{ sku_interno: Object.keys(matrixData)[0], quantita: 1, prezzo_inserito: '' }]);
            }
          }
        }
      } catch (err) {
        console.error(err);
      }
    }
    loadInitialData();
  }, []);

  const handleAddRow = () => {
    const defaultSku = availableSkus.length > 0 ? availableSkus[0] : '';
    setBasket([...basket, { sku_interno: defaultSku, quantita: 1, prezzo_inserito: '' }]);
  };

  const handleRemoveRow = (index: number) => {
    const newBasket = [...basket];
    newBasket.splice(index, 1);
    setBasket(newBasket);
  };

  const handleChangeRow = (index: number, field: keyof OrderItemInput, value: any) => {
    const newBasket = [...basket];
    newBasket[index] = { ...newBasket[index], [field]: value };
    setBasket(newBasket);
  };

  const handleOptimize = async () => {
    setError(null);
    setSuccessMsg(null);
    setLoadingOpt(true);
    try {
      // Filter out rows with no SKU
      const validItems = basket.filter(item => item.sku_interno !== '');
      if (validItems.length === 0) {
        throw new Error("Aggiungi almeno un articolo valido al carrello.");
      }

      const formattedItems = validItems.map(item => ({
        sku_interno: item.sku_interno,
        quantita: Number(item.quantita) || 1,
        prezzo_inserito: item.prezzo_inserito !== '' ? Number(item.prezzo_inserito) : null
      }));

      const res = await fetch(`${API_BASE}/ordini/ottimizza`, {
        method: 'POST',
        headers: {
          ...headers,
          'Content-Type': 'application/json'
        },
        body: JSON.stringify(formattedItems)
      });

      if (!res.ok) {
        throw new Error(`Errore di ottimizzazione: ${res.status}`);
      }

      const data = await res.json();
      setOptResult(data);
    } catch (err: any) {
      setError(err.message || "Errore durante l'ottimizzazione dell'ordine.");
    } finally {
      setLoadingOpt(false);
    }
  };

  const handleCheckout = async () => {
    if (!selectedLocation) {
      alert("Seleziona la sede emittente dell'ordine.");
      return;
    }

    setError(null);
    setSuccessMsg(null);
    setSubmittingOrder(true);

    try {
      const validItems = basket.filter(item => item.sku_interno !== '');
      const formattedItems = validItems.map(item => ({
        sku_interno: item.sku_interno,
        quantita: Number(item.quantita) || 1,
        prezzo_inserito: item.prezzo_inserito !== '' ? Number(item.prezzo_inserito) : null
      }));

      const res = await fetch(`${API_BASE}/ordini/crea`, {
        method: 'POST',
        headers: {
          ...headers,
          'Content-Type': 'application/json'
        },
        body: JSON.stringify({
          location_id: Number(selectedLocation),
          items: formattedItems
        })
      });

      if (!res.ok) {
        throw new Error("Errore durante la creazione dell'ordine.");
      }

      const orderIds = await res.json();
      setSuccessMsg(
        `Ordini d'acquisto emessi ed inviati correttamente! Generati ${orderIds.length} documenti d'ordine suddivisi per fornitore.`
      );
      // Reset basket
      const defaultSku = availableSkus.length > 0 ? availableSkus[0] : '';
      setBasket([{ sku_interno: defaultSku, quantita: 1, prezzo_inserito: '' }]);
      setOptResult(null);
    } catch (err: any) {
      setError(err.message || "Errore durante la finalizzazione degli ordini.");
    } finally {
      setSubmittingOrder(false);
    }
  };

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: '24px' }}>
      
      {/* Configuration Header Card */}
      <div className="glass-panel" style={{ padding: '20px', display: 'flex', flexWrap: 'wrap', gap: '20px', alignItems: 'center', justifyContent: 'space-between' }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: '10px' }}>
          <ShoppingCart color="var(--accent-blue)" size={22} />
          <div>
            <h4 style={{ margin: 0, fontWeight: 600 }}>Ottimizzatore Preventivo Ordini d'Acquisto</h4>
            <p style={{ margin: 0, fontSize: '0.75rem', color: 'var(--text-secondary)' }}>
              Componi l'ordine per verificare i contratti ed ottimizzare il routing fornitori prima dell'invio.
            </p>
          </div>
        </div>

        <div style={{ display: 'flex', alignItems: 'center', gap: '12px' }}>
          <label style={{ fontSize: '0.85rem', color: 'var(--text-secondary)', fontWeight: 500 }}>Sede Emittente:</label>
          <select
            value={selectedLocation}
            onChange={e => setSelectedLocation(Number(e.target.value) || '')}
            style={{
              padding: '8px 12px',
              borderRadius: '8px',
              background: 'rgba(255,255,255,0.03)',
              border: '1px solid var(--border-glass)',
              color: 'white',
              outline: 'none',
              fontSize: '0.85rem'
            }}
          >
            {locations.map(loc => (
              <option key={loc.id} value={loc.id} style={{ background: '#13131c' }}>
                {loc.nome_struttura}
              </option>
            ))}
          </select>
        </div>
      </div>

      {/* Main Order Construction Row */}
      <div style={{ display: 'grid', gridTemplateColumns: '1fr', gap: '20px' }}>
        
        {/* Cart panel */}
        <div className="glass-panel" style={{ padding: '24px', display: 'flex', flexDirection: 'column', gap: '20px' }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
            <h3 style={{ margin: 0, fontSize: '1.1rem', fontWeight: 600 }}>Carrello Articoli</h3>
            <button
              onClick={handleAddRow}
              className="btn"
              style={{ display: 'flex', alignItems: 'center', gap: '6px', fontSize: '0.8rem', padding: '6px 12px', background: 'rgba(255,255,255,0.05)', border: 'none' }}
            >
              <Plus size={14} /> Aggiungi Articolo
            </button>
          </div>

          <table style={{ width: '100%', borderCollapse: 'collapse' }}>
            <thead>
              <tr style={{ borderBottom: '1px solid rgba(255,255,255,0.05)', color: 'var(--text-secondary)', fontSize: '0.8rem', textAlign: 'left' }}>
                <th style={{ padding: '12px' }}>Seleziona SKU Prodotto</th>
                <th style={{ padding: '12px', width: '120px' }}>Quantità</th>
                <th style={{ padding: '12px', width: '180px' }}>Prezzo Manuale (Opzionale)</th>
                <th style={{ padding: '12px', width: '60px', textAlign: 'center' }}>Rimuovi</th>
              </tr>
            </thead>
            <tbody>
              {basket.map((row, index) => (
                <tr key={index} style={{ borderBottom: '1px solid rgba(255,255,255,0.02)' }}>
                  <td style={{ padding: '10px 6px' }}>
                    <select
                      value={row.sku_interno}
                      onChange={e => handleChangeRow(index, 'sku_interno', e.target.value)}
                      style={{
                        width: '100%',
                        padding: '10px',
                        borderRadius: '8px',
                        background: 'rgba(255,255,255,0.03)',
                        border: '1px solid var(--border-glass)',
                        color: 'white',
                        outline: 'none',
                        fontSize: '0.85rem'
                      }}
                    >
                      <option value="" style={{ background: '#13131c' }}>Scegli Prodotto...</option>
                      {availableSkus.map(sku => (
                        <option key={sku} value={sku} style={{ background: '#13131c' }}>
                          {sku}
                        </option>
                      ))}
                    </select>
                  </td>
                  <td style={{ padding: '10px 6px' }}>
                    <input
                      type="number"
                      min="0.1"
                      step="any"
                      value={row.quantita}
                      onChange={e => handleChangeRow(index, 'quantita', Number(e.target.value) || '')}
                      style={{
                        width: '100%',
                        boxSizing: 'border-box',
                        padding: '10px',
                        background: 'rgba(255,255,255,0.03)',
                        border: '1px solid var(--border-glass)',
                        borderRadius: '8px',
                        color: 'white',
                        outline: 'none',
                        fontSize: '0.85rem',
                        textAlign: 'center'
                      }}
                    />
                  </td>
                  <td style={{ padding: '10px 6px' }}>
                    <input
                      type="number"
                      placeholder="Spot o Contratto..."
                      min="0"
                      step="any"
                      value={row.prezzo_inserito}
                      onChange={e => handleChangeRow(index, 'prezzo_inserito', e.target.value !== '' ? Number(e.target.value) : '')}
                      style={{
                        width: '100%',
                        boxSizing: 'border-box',
                        padding: '10px',
                        background: 'rgba(255,255,255,0.03)',
                        border: '1px solid var(--border-glass)',
                        borderRadius: '8px',
                        color: 'white',
                        outline: 'none',
                        fontSize: '0.85rem',
                        textAlign: 'right'
                      }}
                    />
                  </td>
                  <td style={{ padding: '10px 6px', textAlign: 'center' }}>
                    <button
                      onClick={() => handleRemoveRow(index)}
                      disabled={basket.length <= 1}
                      style={{ background: 'transparent', border: 'none', color: '#ef4444', cursor: 'pointer', padding: '6px' }}
                    >
                      <Trash2 size={16} />
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>

          <div style={{ display: 'flex', justifyContent: 'flex-end', marginTop: '10px' }}>
            <button
              onClick={handleOptimize}
              disabled={loadingOpt}
              className="btn btn-primary"
              style={{ display: 'flex', alignItems: 'center', gap: '8px' }}
            >
              <TrendingUp size={16} />
              {loadingOpt ? 'Ottimizzazione in corso...' : 'Analizza e Ottimizza Spesa'}
            </button>
          </div>
        </div>

      </div>

      {/* Success or Error banners */}
      {error && (
        <div style={{ padding: '16px', borderRadius: '8px', background: 'var(--status-red-bg)', color: 'var(--status-red)', border: '1px solid rgba(239,68,68,0.2)' }}>
          {error}
        </div>
      )}

      {successMsg && (
        <div style={{ padding: '16px', borderRadius: '8px', background: 'rgba(16,185,129,0.1)', color: '#10b981', border: '1px solid rgba(16,185,129,0.2)', display: 'flex', alignItems: 'center', gap: '8px' }}>
          <CheckCircle2 size={18} />
          {successMsg}
        </div>
      )}

      {/* Optimization Results Panels */}
      {optResult && (
        <div style={{ display: 'flex', flexDirection: 'column', gap: '24px' }}>
          
          {/* Rule C: Summary Cards */}
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(260px, 1fr))', gap: '20px' }}>
            <div className="glass-panel" style={{ padding: '20px', display: 'flex', flexDirection: 'column', gap: '6px' }}>
              <span style={{ fontSize: '0.75rem', color: 'var(--text-secondary)' }}>Spesa Totale Blindata (Prezzi Concordati)</span>
              <span style={{ fontSize: '1.5rem', fontWeight: 700, color: '#10b981' }}>
                € {optResult.sintesi.spesa_totale_blindata.toLocaleString('it-IT', { minimumFractionDigits: 2 })}
              </span>
            </div>
            
            <div className="glass-panel" style={{ padding: '20px', display: 'flex', flexDirection: 'column', gap: '6px' }}>
              <span style={{ fontSize: '0.75rem', color: 'var(--text-secondary)' }}>Risparmio Spot Ottenuto</span>
              <span style={{ fontSize: '1.5rem', fontWeight: 700, color: 'var(--accent-blue)', display: 'flex', alignItems: 'center', gap: '8px' }}>
                +€ {optResult.sintesi.risparmio_preventivo_stimato.toLocaleString('it-IT', { minimumFractionDigits: 2 })}
                <CheckCircle2 size={20} color="#10b981" />
              </span>
            </div>

            <div className="glass-panel" style={{ padding: '20px', display: 'flex', flexDirection: 'column', gap: '6px' }}>
              <span style={{ fontSize: '0.75rem', color: 'var(--text-secondary)' }}>Anomalie Preventive Rilevate</span>
              <span style={{ fontSize: '1.5rem', fontWeight: 700, color: optResult.sintesi.numero_anomalie > 0 ? '#ef4444' : 'var(--text-primary)' }}>
                {optResult.sintesi.numero_anomalie}
              </span>
            </div>
          </div>

          {/* Rule C: Preventive Warnings Block */}
          {optResult.sintesi.numero_anomalie > 0 && (
            <div style={{
              padding: '16px',
              borderRadius: '8px',
              background: 'rgba(239,68,68,0.06)',
              border: '1px solid rgba(239,68,68,0.2)',
              display: 'flex',
              flexDirection: 'column',
              gap: '10px'
            }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: '8px', color: '#ef4444', fontWeight: 600, fontSize: '0.9rem' }}>
                <AlertTriangle size={18} />
                <span>ATTENZIONE: Rilevate {optResult.sintesi.numero_anomalie} anomalie di prezzo preventive!</span>
              </div>
              <ul style={{ margin: 0, paddingLeft: '20px', fontSize: '0.8rem', color: 'var(--text-secondary)', display: 'flex', flexDirection: 'column', gap: '4px' }}>
                {optResult.sintesi.avvisi_preventivi.map((avviso, aIdx) => (
                  <li key={aIdx}>{avviso}</li>
                ))}
              </ul>
              <p style={{ margin: 0, fontSize: '0.75rem', color: '#f59e0b', fontWeight: 500, marginTop: '4px' }}>
                * Nota: L'invio dell'ordine registrerà queste discrepanze preventive a database per il successivo auditing.
              </p>
            </div>
          )}

          {/* Optimized Items Table */}
          <div className="glass-panel" style={{ padding: '24px', display: 'flex', flexDirection: 'column', gap: '20px' }}>
            <h4 style={{ margin: 0, fontSize: '1rem', fontWeight: 600, display: 'flex', alignItems: 'center', gap: '8px' }}>
              <ShieldCheck color="var(--accent-blue)" size={18} />
              Analisi e Routing Consigliato dei Prodotti
            </h4>

            <div style={{ overflowX: 'auto' }}>
              <table style={{ width: '100%', borderCollapse: 'collapse' }}>
                <thead>
                  <tr style={{ borderBottom: '1px solid rgba(255,255,255,0.05)', color: 'var(--text-secondary)', fontSize: '0.8rem', textAlign: 'left' }}>
                    <th style={{ padding: '12px' }}>Prodotto</th>
                    <th style={{ padding: '12px', textAlign: 'center' }}>Q.tà</th>
                    <th style={{ padding: '12px' }}>Fornitore Consigliato</th>
                    <th style={{ padding: '12px', textAlign: 'right' }}>Prezzo Consigliato</th>
                    <th style={{ padding: '12px', textAlign: 'right' }}>Prezzo Inserito</th>
                    <th style={{ padding: '12px', textAlign: 'center' }}>Routing Status</th>
                  </tr>
                </thead>
                <tbody>
                  {optResult.righe_ottimizzate.map((riga, idx) => (
                    <tr key={idx} style={{ borderBottom: '1px solid rgba(255,255,255,0.03)', fontSize: '0.85rem' }}>
                      <td style={{ padding: '12px' }}>
                        <div style={{ display: 'flex', flexDirection: 'column', gap: '2px' }}>
                          <span style={{ fontWeight: 600 }}>{riga.sku_interno}</span>
                          <span style={{ fontSize: '0.7rem', color: 'var(--text-secondary)' }}>{riga.descrizione}</span>
                        </div>
                      </td>
                      <td style={{ padding: '12px', textAlign: 'center' }}>{riga.quantita}</td>
                      <td style={{ padding: '12px' }}>
                        <div style={{ display: 'flex', flexDirection: 'column', gap: '2px' }}>
                          <span style={{ fontWeight: 500 }}>{riga.fornitore_nome}</span>
                          {riga.confronto_prezzi.length > 1 && (
                            <span style={{ fontSize: '0.7rem', color: 'var(--text-secondary)' }}>
                              Altri listini spot: {riga.confronto_prezzi.map(c => `${c.fornitore_nome} (€ ${c.prezzo.toFixed(2)})`).join(', ')}
                            </span>
                          )}
                        </div>
                      </td>
                      <td style={{ padding: '12px', textAlign: 'right', fontWeight: 600, color: '#10b981' }}>
                        € {riga.prezzo_ottimale.toFixed(2)}
                      </td>
                      <td style={{ padding: '12px', textAlign: 'right', color: riga.is_anomalia ? '#ef4444' : 'var(--text-primary)' }}>
                        € {riga.prezzo_inserito.toFixed(2)}
                      </td>
                      <td style={{ padding: '12px', textAlign: 'center' }}>
                        {riga.tipo_regola === 'concordato' ? (
                          <span style={{ 
                            fontSize: '0.7rem', 
                            color: '#10b981', 
                            background: 'rgba(16,185,129,0.1)', 
                            padding: '4px 8px', 
                            borderRadius: '12px', 
                            fontWeight: 600 
                          }}>
                            CONTRATTO BLINDATO
                          </span>
                        ) : riga.tipo_regola === 'spot_ottimale' ? (
                          <span style={{ 
                            fontSize: '0.7rem', 
                            color: 'var(--accent-blue)', 
                            background: 'rgba(59,130,246,0.1)', 
                            padding: '4px 8px', 
                            borderRadius: '12px', 
                            fontWeight: 600 
                          }}>
                            MIGLIOR PREZZO SPOT
                          </span>
                        ) : (
                          <span style={{ 
                            fontSize: '0.7rem', 
                            color: 'var(--text-secondary)', 
                            background: 'rgba(255,255,255,0.05)', 
                            padding: '4px 8px', 
                            borderRadius: '12px', 
                            fontWeight: 600 
                          }}>
                            SPOT FUORI LISTINO
                          </span>
                        )}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>

            <div style={{ display: 'flex', justifyContent: 'flex-end', marginTop: '10px' }}>
              <button
                onClick={handleCheckout}
                disabled={submittingOrder}
                className="btn btn-primary"
                style={{ display: 'flex', alignItems: 'center', gap: '8px', background: '#10b981', borderColor: '#10b981' }}
              >
                <CheckCircle2 size={16} />
                {submittingOrder ? 'Emissione ordini...' : 'Conferma e Invia Ordini Ottimizzati'}
              </button>
            </div>
          </div>

        </div>
      )}

    </div>
  );
}
