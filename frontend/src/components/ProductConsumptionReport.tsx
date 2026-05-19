import { useState, useEffect } from 'react';
import { FileSpreadsheet, Search, RefreshCw, Download, BarChart2, Calendar, MapPin, Tag } from 'lucide-react';
import { API_BASE, getHeaders } from '../api';

interface ConsumptionItem {
  sku_interno: string;
  descrizione: string;
  quantita_totale: number;
  unita_misura: string;
  spesa_totale: number;
  prezzo_medio: number;
}

interface LocationItem {
  id: number;
  nome_struttura: string;
}

interface FornitoreItem {
  id: number;
  nome_azienda: string;
}

interface SKUDetail {
  sku_interno: string;
  consumo_per_location: Array<{
    location_nome: string;
    quantita_totale: number;
    spesa_totale: number;
  }>;
  consumo_per_mese: Array<{
    mese: string;
    quantita_totale: number;
    spesa_totale: number;
  }>;
}

export default function ProductConsumptionReport() {
  const [consumption, setConsumption] = useState<ConsumptionItem[]>([]);
  const [locations, setLocations] = useState<LocationItem[]>([]);
  const [fornitori, setFornitori] = useState<FornitoreItem[]>([]);
  
  // Filters
  const [selectedLocation, setSelectedLocation] = useState<string>('');
  const [selectedSupplier, setSelectedSupplier] = useState<string>('');
  const [dataDa, setDataDa] = useState<string>('');
  const [dataA, setDataA] = useState<string>('');
  const [searchQuery, setSearchQuery] = useState<string>('');

  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  
  // Detail Drawer States
  const [selectedSku, setSelectedSku] = useState<string | null>(null);
  const [selectedDesc, setSelectedDesc] = useState<string | null>(null);
  const [skuDetail, setSkuDetail] = useState<SKUDetail | null>(null);
  const [loadingDetail, setLoadingDetail] = useState(false);
  
  // Download State
  const [exporting, setExporting] = useState(false);

  const headers = getHeaders();

  // Load auxiliary lists (Locations and Suppliers)
  const loadFilters = async () => {
    try {
      const [locRes, fornRes] = await Promise.all([
        fetch(`${API_BASE}/location/`, { headers }),
        fetch(`${API_BASE}/fornitori/`, { headers })
      ]);
      if (locRes.ok) setLocations(await locRes.json());
      if (fornRes.ok) setFornitori(await fornRes.json());
    } catch (err) {
      console.error("Errore caricamento filtri consumi", err);
    }
  };

  // Load consumption aggregates based on filters
  const loadConsumption = async () => {
    setLoading(true);
    setError(null);
    try {
      const params = new URLSearchParams();
      if (selectedLocation) params.append('location_id', selectedLocation);
      if (selectedSupplier) params.append('fornitore_id', selectedSupplier);
      if (dataDa) params.append('data_da', dataDa);
      if (dataA) params.append('data_a', dataA);

      const res = await fetch(`${API_BASE}/intelligence/product-consumption?${params.toString()}`, { headers });
      if (!res.ok) throw new Error("Impossibile recuperare l'analisi dei consumi.");
      const data = await res.json();
      setConsumption(data);
    } catch (err: any) {
      setError(err.message || 'Errore di connessione al server.');
    } finally {
      setLoading(false);
    }
  };

  // Load SKU detailed splits
  const loadSkuDetail = async (sku: string) => {
    setLoadingDetail(true);
    setSkuDetail(null);
    try {
      const res = await fetch(`${API_BASE}/intelligence/product-consumption/${sku}`, { headers });
      if (!res.ok) throw new Error("Impossibile caricare il dettaglio dello SKU.");
      const data = await res.json();
      setSkuDetail(data);
    } catch (err) {
      console.error(err);
    } finally {
      setLoadingDetail(false);
    }
  };

  useEffect(() => {
    loadFilters();
  }, []);

  useEffect(() => {
    loadConsumption();
  }, [selectedLocation, selectedSupplier, dataDa, dataA]);

  const handleExcelExport = async () => {
    setExporting(true);
    try {
      const params = new URLSearchParams();
      if (selectedLocation) params.append('location_id', selectedLocation);
      if (selectedSupplier) params.append('fornitore_id', selectedSupplier);
      if (dataDa) params.append('data_da', dataDa);
      if (dataA) params.append('data_a', dataA);

      const res = await fetch(`${API_BASE}/intelligence/export-product-consumption-excel?${params.toString()}`, { headers });
      if (!res.ok) throw new Error("Esportazione Excel fallita");
      
      const blob = await res.blob();
      const url = window.URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = `Report_Consumi_Prodotti.xlsx`;
      document.body.appendChild(a);
      a.click();
      a.remove();
    } catch (err) {
      alert("Errore durante il download del report Excel");
    } finally {
      setExporting(false);
    }
  };

  const filteredItems = consumption.filter(item => 
    item.sku_interno.toLowerCase().includes(searchQuery.toLowerCase()) ||
    item.descrizione.toLowerCase().includes(searchQuery.toLowerCase())
  );

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: '24px' }}>
      
      {/* Filters & Control bar */}
      <div className="glass-panel" style={{ padding: '20px', display: 'flex', flexDirection: 'column', gap: '16px' }}>
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', flexWrap: 'wrap', gap: '12px' }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: '10px' }}>
            <BarChart2 color="var(--accent-blue)" size={22} />
            <h4 style={{ margin: 0, fontSize: '1.1rem', fontWeight: 600 }}>Filtri Analisi Consumi</h4>
          </div>
          <button
            onClick={handleExcelExport}
            className="btn btn-primary"
            disabled={exporting || loading}
            style={{ fontSize: '0.85rem', display: 'flex', alignItems: 'center', gap: '8px' }}
          >
            <Download size={15} />
            {exporting ? 'Generazione in corso...' : 'Esporta Report Excel'}
          </button>
        </div>

        {/* Filters Grid */}
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(200px, 1fr))', gap: '16px' }}>
          {/* Location filter */}
          <div style={{ display: 'flex', flexDirection: 'column', gap: '6px' }}>
            <label style={{ fontSize: '0.75rem', color: 'var(--text-secondary)', display: 'flex', alignItems: 'center', gap: '4px' }}>
              <MapPin size={12} /> Punto Vendita (Sede)
            </label>
            <select
              value={selectedLocation}
              onChange={e => setSelectedLocation(e.target.value)}
              style={{
                padding: '10px',
                borderRadius: '8px',
                background: 'rgba(255,255,255,0.03)',
                border: '1px solid var(--border-glass)',
                color: 'white',
                outline: 'none',
                fontSize: '0.85rem'
              }}
            >
              <option value="" style={{ background: '#13131c' }}>Tutte le sedi</option>
              {locations.map(l => (
                <option key={l.id} value={l.id} style={{ background: '#13131c' }}>{l.nome_struttura}</option>
              ))}
            </select>
          </div>

          {/* Supplier filter */}
          <div style={{ display: 'flex', flexDirection: 'column', gap: '6px' }}>
            <label style={{ fontSize: '0.75rem', color: 'var(--text-secondary)', display: 'flex', alignItems: 'center', gap: '4px' }}>
              <Tag size={12} /> Fornitore
            </label>
            <select
              value={selectedSupplier}
              onChange={e => setSelectedSupplier(e.target.value)}
              style={{
                padding: '10px',
                borderRadius: '8px',
                background: 'rgba(255,255,255,0.03)',
                border: '1px solid var(--border-glass)',
                color: 'white',
                outline: 'none',
                fontSize: '0.85rem'
              }}
            >
              <option value="" style={{ background: '#13131c' }}>Tutti i fornitori</option>
              {fornitori.map(f => (
                <option key={f.id} value={f.id} style={{ background: '#13131c' }}>{f.nome_azienda}</option>
              ))}
            </select>
          </div>

          {/* Start Date */}
          <div style={{ display: 'flex', flexDirection: 'column', gap: '6px' }}>
            <label style={{ fontSize: '0.75rem', color: 'var(--text-secondary)', display: 'flex', alignItems: 'center', gap: '4px' }}>
              <Calendar size={12} /> Data Da
            </label>
            <input
              type="date"
              value={dataDa}
              onChange={e => setDataDa(e.target.value)}
              style={{
                padding: '9px 10px',
                borderRadius: '8px',
                background: 'rgba(255,255,255,0.03)',
                border: '1px solid var(--border-glass)',
                color: 'white',
                outline: 'none',
                fontSize: '0.85rem'
              }}
            />
          </div>

          {/* End Date */}
          <div style={{ display: 'flex', flexDirection: 'column', gap: '6px' }}>
            <label style={{ fontSize: '0.75rem', color: 'var(--text-secondary)', display: 'flex', alignItems: 'center', gap: '4px' }}>
              <Calendar size={12} /> Data A
            </label>
            <input
              type="date"
              value={dataA}
              onChange={e => setDataA(e.target.value)}
              style={{
                padding: '9px 10px',
                borderRadius: '8px',
                background: 'rgba(255,255,255,0.03)',
                border: '1px solid var(--border-glass)',
                color: 'white',
                outline: 'none',
                fontSize: '0.85rem'
              }}
            />
          </div>
        </div>
      </div>

      {/* Main Content Pane */}
      <div style={{ display: 'flex', gap: '20px', flexWrap: 'wrap-reverse', alignItems: 'flex-start' }}>
        
        {/* Table list of products */}
        <div className="glass-panel" style={{ flex: '2', minWidth: '450px', padding: '24px', display: 'flex', flexDirection: 'column', gap: '20px' }}>
          
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', flexWrap: 'wrap', gap: '12px' }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
              <FileSpreadsheet size={18} color="var(--accent-blue)" />
              <h4 style={{ margin: 0, fontWeight: 600 }}>Elenco Consumo Articoli</h4>
            </div>
            <div style={{ position: 'relative', width: '100%', maxWidth: '260px' }}>
              <Search size={14} style={{ position: 'absolute', left: '10px', top: '50%', transform: 'translateY(-50%)', color: 'var(--text-secondary)' }} />
              <input
                type="text"
                placeholder="Cerca per prodotto..."
                value={searchQuery}
                onChange={e => setSearchQuery(e.target.value)}
                style={{
                  width: '100%',
                  boxSizing: 'border-box',
                  padding: '8px 10px 8px 32px',
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

          {loading ? (
            <div style={{ color: 'var(--text-secondary)', padding: '40px', display: 'flex', alignItems: 'center', justifyContent: 'center', gap: '10px' }}>
              <RefreshCw className="animate-spin" size={20} />
              <span>Analisi dei consumi in corso...</span>
            </div>
          ) : error ? (
            <div style={{ padding: '16px', borderRadius: '8px', background: 'var(--status-red-bg)', color: 'var(--status-red)', border: '1px solid rgba(239,68,68,0.2)' }}>
              {error}
            </div>
          ) : (
            <div style={{ overflowX: 'auto' }}>
              <table style={{ width: '100%', borderCollapse: 'collapse' }}>
                <thead>
                  <tr style={{ borderBottom: '1px solid rgba(255,255,255,0.05)', color: 'var(--text-secondary)', fontSize: '0.8rem', textAlign: 'left' }}>
                    <th style={{ padding: '12px' }}>Prodotto</th>
                    <th style={{ padding: '12px', textAlign: 'right' }}>Quantità</th>
                    <th style={{ padding: '12px', textAlign: 'center' }}>U.M.</th>
                    <th style={{ padding: '12px', textAlign: 'right' }}>P. Medio</th>
                    <th style={{ padding: '12px', textAlign: 'right' }}>Spesa Totale</th>
                  </tr>
                </thead>
                <tbody>
                  {filteredItems.length === 0 ? (
                    <tr>
                      <td colSpan={5} style={{ padding: '32px', textAlign: 'center', color: 'var(--text-secondary)' }}>
                        Nessun dato di consumo trovato con i filtri correnti.
                      </td>
                    </tr>
                  ) : (
                    filteredItems.map(item => (
                      <tr
                        key={item.sku_interno}
                        onClick={() => {
                          setSelectedSku(item.sku_interno);
                          setSelectedDesc(item.descrizione);
                          loadSkuDetail(item.sku_interno);
                        }}
                        style={{
                          borderBottom: '1px solid rgba(255,255,255,0.03)',
                          fontSize: '0.85rem',
                          cursor: 'pointer',
                          background: selectedSku === item.sku_interno ? 'rgba(59,130,246,0.08)' : 'transparent',
                          transition: 'var(--transition-smooth)'
                        }}
                        className="table-row-hover"
                      >
                        <td style={{ padding: '14px 12px', color: 'var(--text-primary)', fontWeight: 600, maxWidth: '240px', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{item.descrizione}</td>
                        <td style={{ padding: '14px 12px', textAlign: 'right', fontWeight: 600 }}>{item.quantita_totale.toLocaleString(undefined, { minimumFractionDigits: 1 })}</td>
                        <td style={{ padding: '14px 12px', textAlign: 'center', color: 'var(--text-secondary)' }}>{item.unita_misura}</td>
                        <td style={{ padding: '14px 12px', textAlign: 'right', color: '#10b981' }}>€ {item.prezzo_medio.toFixed(2)}</td>
                        <td style={{ padding: '14px 12px', textAlign: 'right', fontWeight: 600, color: 'white' }}>€ {item.spesa_totale.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}</td>
                      </tr>
                    ))
                  )}
                </tbody>
              </table>
            </div>
          )}
        </div>

        {/* Detailed Side Panel / Split view */}
        <div className="glass-panel" style={{ flex: '1', minWidth: '320px', padding: '24px', display: 'flex', flexDirection: 'column', gap: '20px' }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
            <BarChart2 size={18} color="var(--status-red)" />
            <h4 style={{ margin: 0, fontWeight: 600 }}>Dettaglio Split Articolo</h4>
          </div>

          {!selectedSku ? (
            <div style={{ padding: '40px 10px', textAlign: 'center', color: 'var(--text-secondary)', fontSize: '0.85rem', display: 'flex', flexDirection: 'column', gap: '12px' }}>
              <BarChart2 style={{ margin: '0 auto', opacity: 0.3 }} size={32} />
              <span>Seleziona un prodotto dalla lista a sinistra per visualizzare lo spaccato dei consumi mensili e per sede.</span>
            </div>
          ) : loadingDetail ? (
            <div style={{ color: 'var(--text-secondary)', padding: '40px', display: 'flex', alignItems: 'center', justifyContent: 'center', gap: '10px' }}>
              <RefreshCw className="animate-spin" size={18} />
              <span>Caricamento dettagli...</span>
            </div>
          ) : skuDetail ? (
            <div style={{ display: 'flex', flexDirection: 'column', gap: '24px' }}>
              <div>
                <h3 style={{ fontSize: '1.2rem', margin: '0 0 4px 0', color: 'white', lineHeight: '1.4' }}>{selectedDesc}</h3>
                <p style={{ fontSize: '0.8rem', color: 'var(--text-secondary)', margin: 0 }}>Distribuzione analitica dei volumi</p>
              </div>

              {/* Location split */}
              <div>
                <h5 style={{ margin: '0 0 12px 0', fontSize: '0.85rem', color: 'var(--text-primary)', borderBottom: '1px solid rgba(255,255,255,0.05)', paddingBottom: '6px' }}>Consumi per Sede (Punto Vendita)</h5>
                <div style={{ display: 'flex', flexDirection: 'column', gap: '12px' }}>
                  {skuDetail.consumo_per_location.map((loc, i) => (
                    <div key={i} style={{ display: 'flex', flexDirection: 'column', gap: '4px' }}>
                      <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: '0.8rem' }}>
                        <span style={{ fontWeight: 500, color: 'var(--text-secondary)' }}>{loc.location_nome}</span>
                        <span style={{ fontWeight: 600 }}>{loc.quantita_totale.toLocaleString()} unità</span>
                      </div>
                      <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: '0.75rem', color: 'var(--text-secondary)' }}>
                        <span>Spesa Complessiva:</span>
                        <span style={{ color: '#10b981', fontWeight: 500 }}>€ {loc.spesa_totale.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}</span>
                      </div>
                      {/* Progress bar effect */}
                      <div style={{ height: '4px', borderRadius: '2px', background: 'rgba(255,255,255,0.03)', overflow: 'hidden', marginTop: '2px' }}>
                        <div style={{
                          height: '100%',
                          background: 'linear-gradient(90deg, var(--accent-blue) 0%, #60a5fa 100%)',
                          width: `${Math.min(100, (loc.spesa_totale / (skuDetail.consumo_per_location[0]?.spesa_totale || 1)) * 100)}%`
                        }}></div>
                      </div>
                    </div>
                  ))}
                </div>
              </div>

              {/* Monthly series split */}
              <div>
                <h5 style={{ margin: '0 0 12px 0', fontSize: '0.85rem', color: 'var(--text-primary)', borderBottom: '1px solid rgba(255,255,255,0.05)', paddingBottom: '6px' }}>Andamento Storico Mensile</h5>
                <div style={{ display: 'flex', flexDirection: 'column', gap: '12px' }}>
                  {skuDetail.consumo_per_mese.map((mon, i) => (
                    <div key={i} style={{ display: 'flex', flexDirection: 'column', gap: '4px' }}>
                      <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: '0.8rem' }}>
                        <span style={{ fontWeight: 600, color: 'white' }}>{mon.mese}</span>
                        <span>{mon.quantita_totale.toLocaleString()} unità</span>
                      </div>
                      <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: '0.75rem', color: 'var(--text-secondary)' }}>
                        <span>Valore Speso:</span>
                        <span style={{ color: '#10b981', fontWeight: 500 }}>€ {mon.spesa_totale.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}</span>
                      </div>
                      <div style={{ height: '4px', borderRadius: '2px', background: 'rgba(255,255,255,0.03)', overflow: 'hidden', marginTop: '2px' }}>
                        <div style={{
                          height: '100%',
                          background: 'linear-gradient(90deg, var(--status-red) 0%, #f472b6 100%)',
                          width: `${Math.min(100, (mon.spesa_totale / (Math.max(...skuDetail.consumo_per_mese.map(m => m.spesa_totale)) || 1)) * 100)}%`
                        }}></div>
                      </div>
                    </div>
                  ))}
                </div>
              </div>

            </div>
          ) : (
            <div style={{ color: 'var(--text-secondary)', textAlign: 'center', padding: '20px' }}>
              Nessun dettaglio disponibile.
            </div>
          )}
        </div>

      </div>

    </div>
  );
}
