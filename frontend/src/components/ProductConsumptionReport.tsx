import { useState, useEffect } from 'react';
import { FileSpreadsheet, Search, RefreshCw, Download, BarChart2, Calendar, MapPin, Tag, FileText, X } from 'lucide-react';
import { API_BASE, getHeaders } from '../api';

interface ConsumptionItem {
  sku_interno: string;
  descrizione: string;
  quantita_totale: number;
  quantita_omaggio: number;
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
  prezzo_minimo?: number;
  prezzo_massimo?: number;
  prezzo_medio?: number;
}

const cleanText = (str: string) => {
  if (!str) return '';
  return str
    .replace(/&amp;/g, '&')
    .replace(/&lt;/g, '<')
    .replace(/&gt;/g, '>')
    .replace(/&quot;/g, '"')
    .replace(/&apos;/g, "'")
    .replace(/&#39;/g, "'");
};

export default function ProductConsumptionReport() {
  const [consumption, setConsumption] = useState<ConsumptionItem[]>([]);
  const [locations, setLocations] = useState<LocationItem[]>([]);
  const [fornitori, setFornitori] = useState<FornitoreItem[]>([]);
  
  // Filters
  const [selectedLocations, setSelectedLocations] = useState<number[]>([]);
  const [selectedSupplier, setSelectedSupplier] = useState<string>('');
  const [dataDa, setDataDa] = useState<string>('');
  const [dataA, setDataA] = useState<string>('');
  const [searchQuery, setSearchQuery] = useState<string>('');

  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  
  // Detail Drawer States
  const [selectedSkus, setSelectedSkus] = useState<string[]>([]);
  const [skuDetail, setSkuDetail] = useState<SKUDetail | null>(null);
  const [loadingDetail, setLoadingDetail] = useState(false);
  
  // Download State
  const [exporting, setExporting] = useState(false);

  // Invoices Modal States
  const [showInvoicesModal, setShowInvoicesModal] = useState(false);
  const [invoicesList, setInvoicesList] = useState<any[]>([]);
  const [loadingInvoices, setLoadingInvoices] = useState(false);

  const headers = getHeaders();

  const formatMese = (meseStr: string) => {
    if (!meseStr || !meseStr.includes('-')) return meseStr;
    const [year, month] = meseStr.split('-');
    const monthsMap: { [key: string]: string } = {
      '01': 'Gen',
      '02': 'Feb',
      '03': 'Mar',
      '04': 'Apr',
      '05': 'Mag',
      '06': 'Giu',
      '07': 'Lug',
      '08': 'Ago',
      '09': 'Set',
      '10': 'Ott',
      '11': 'Nov',
      '12': 'Dic'
    };
    const monAbbr = monthsMap[month];
    return monAbbr ? `${monAbbr}-${year}` : meseStr;
  };

  const formatData = (dateStr: string) => {
    if (!dateStr) return '';
    const parts = dateStr.split('-');
    if (parts.length === 3) {
      return `${parts[2]}/${parts[1]}/${parts[0]}`; // YYYY-MM-DD -> DD/MM/YYYY
    }
    return dateStr;
  };

  const handleOpenInvoices = async () => {
    setShowInvoicesModal(true);
    setLoadingInvoices(true);
    try {
      const params = new URLSearchParams();
      if (selectedLocations.length > 0) {
        params.append('location_ids', selectedLocations.join(','));
      }
      if (selectedSupplier) params.append('fornitore_id', selectedSupplier);
      if (dataDa) params.append('data_da', dataDa);
      if (dataA) params.append('data_a', dataA);

      const queryString = params.toString() ? `?${params.toString()}` : '';
      const skuParam = encodeURIComponent(selectedSkus.join(','));

      const res = await fetch(`${API_BASE}/intelligence/product-consumption/${skuParam}/invoices${queryString}`, { headers });
      if (!res.ok) throw new Error("Errore caricamento fatture.");
      const data = await res.json();
      setInvoicesList(data);
    } catch (err) {
      console.error(err);
    } finally {
      setLoadingInvoices(false);
    }
  };

  const handlePDFExport = async () => {
    setLoadingInvoices(true);
    try {
      const params = new URLSearchParams();
      if (selectedLocations.length > 0) {
        params.append('location_ids', selectedLocations.join(','));
      }
      if (selectedSupplier) params.append('fornitore_id', selectedSupplier);
      if (dataDa) params.append('data_da', dataDa);
      if (dataA) params.append('data_a', dataA);

      const queryString = params.toString() ? `?${params.toString()}` : '';
      const skuParam = encodeURIComponent(selectedSkus.join(','));

      const res = await fetch(`${API_BASE}/intelligence/product-consumption/${skuParam}/invoices-pdf${queryString}`, { headers });
      if (!res.ok) throw new Error("Esportazione PDF fallita");
      
      const blob = await res.blob();
      const url = window.URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = `Riepilogo_Fatture_Consumo.pdf`;
      document.body.appendChild(a);
      a.click();
      a.remove();
    } catch {
      alert("Errore durante il download del report PDF");
    } finally {
      setLoadingInvoices(false);
    }
  };

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
      if (selectedLocations.length > 0) {
        params.append('location_ids', selectedLocations.join(','));
      }
      if (selectedSupplier) params.append('fornitore_id', selectedSupplier);
      if (dataDa) params.append('data_da', dataDa);
      if (dataA) params.append('data_a', dataA);

      const res = await fetch(`${API_BASE}/intelligence/product-consumption?${params.toString()}`, { headers });
      if (!res.ok) throw new Error("Impossibile recuperare l'analisi dei consumi.");
      const data = await res.json();
      const sanitizedData = data.map((item: ConsumptionItem) => ({
        ...item,
        descrizione: cleanText(item.descrizione)
      }));
      setConsumption(sanitizedData);
    } catch (err: any) {
      setError(err.message || 'Errore di connessione al server.');
    } finally {
      setLoading(false);
    }
  };

  // Load and aggregate SKU detailed splits
  const loadSkusDetail = async (skus: string[]) => {
    if (skus.length === 0) {
      setSkuDetail(null);
      return;
    }
    setLoadingDetail(true);
    try {
      const params = new URLSearchParams();
      if (selectedLocations.length > 0) {
        params.append('location_ids', selectedLocations.join(','));
      }
      if (selectedSupplier) params.append('fornitore_id', selectedSupplier);
      if (dataDa) params.append('data_da', dataDa);
      if (dataA) params.append('data_a', dataA);

      const queryString = params.toString() ? `?${params.toString()}` : '';
      const skuParam = encodeURIComponent(skus.join(','));

      const res = await fetch(`${API_BASE}/intelligence/product-consumption/${skuParam}${queryString}`, { headers });
      if (!res.ok) throw new Error("Errore caricamento dettagli dei consumi consolidati.");
      const data: SKUDetail = await res.json();

      // Ordina gli output per spesa decrescente e andamento mensile decrescente
      const byLocation = [...data.consumo_per_location].sort((a, b) => b.spesa_totale - a.spesa_totale);
      const byMonth = [...data.consumo_per_mese].sort((a, b) => b.mese.localeCompare(a.mese));

      setSkuDetail({
        sku_interno: skus.length === 1 ? skus[0] : `${skus.length} Articoli`,
        consumo_per_location: byLocation,
        consumo_per_mese: byMonth,
        prezzo_minimo: data.prezzo_minimo,
        prezzo_massimo: data.prezzo_massimo,
        prezzo_medio: data.prezzo_medio
      });
    } catch (err) {
      console.error(err);
    } finally {
      setLoadingDetail(false);
    }
  };

  useEffect(() => {
    loadFilters();
  // Initial filter bootstrap.
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    loadConsumption();
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selectedLocations, selectedSupplier, dataDa, dataA]);

  useEffect(() => {
    loadSkusDetail(selectedSkus);
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selectedSkus, selectedLocations, selectedSupplier, dataDa, dataA]);

  const handleExcelExport = async () => {
    setExporting(true);
    try {
      const params = new URLSearchParams();
      if (selectedLocations.length > 0) {
        params.append('location_ids', selectedLocations.join(','));
      }
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
    } catch {
      alert("Errore durante il download del report Excel");
    } finally {
      setExporting(false);
    }
  };

  const filteredItems = consumption.filter(item => 
    item.sku_interno.toLowerCase().includes(searchQuery.toLowerCase()) ||
    item.descrizione.toLowerCase().includes(searchQuery.toLowerCase())
  );

  const detailTitle = selectedSkus.length === 0
    ? ''
    : selectedSkus.length === 1
      ? (consumption.find(item => item.sku_interno === selectedSkus[0])?.descrizione || selectedSkus[0])
      : `Consumo Consolidato (${selectedSkus.length} Prodotti)`;

  const totalUnits = skuDetail 
    ? skuDetail.consumo_per_location.reduce((sum, loc) => sum + loc.quantita_totale, 0)
    : 0;
  const totalSpend = skuDetail
    ? skuDetail.consumo_per_location.reduce((sum, loc) => sum + loc.spesa_totale, 0)
    : 0;
  const prezzoMinimo = skuDetail?.prezzo_minimo || 0;
  const prezzoMassimo = skuDetail?.prezzo_massimo || 0;
  const prezzoMedio = skuDetail?.prezzo_medio || 0;

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
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(220px, 1fr))', gap: '16px', alignItems: 'end' }}>
          {/* Location filter (Multi-select Glass pills) */}
          <div style={{ display: 'flex', flexDirection: 'column', gap: '8px' }}>
            <label style={{ fontSize: '0.75rem', color: 'var(--text-secondary)', display: 'flex', alignItems: 'center', gap: '4px' }}>
              <MapPin size={12} /> Punto Vendita (Sedi Multiple)
            </label>
            <div style={{ 
              display: 'flex', 
              flexWrap: 'wrap', 
              gap: '6px', 
              padding: '6px 10px', 
              borderRadius: '8px', 
              border: '1px solid var(--line)', 
              background: 'var(--bg-inset)', 
              minHeight: '38px', 
              alignItems: 'center',
              boxSizing: 'border-box'
            }}>
              <button
                onClick={() => setSelectedLocations([])}
                style={{
                  padding: '4px 10px',
                  borderRadius: '999px',
                  fontSize: '0.75rem',
                  fontWeight: 500,
                  cursor: 'pointer',
                  border: '1px solid ' + (selectedLocations.length === 0 ? 'var(--accent-blue)' : 'transparent'),
                  background: selectedLocations.length === 0 ? 'var(--accent-bg)' : 'var(--bg-inset)',
                  color: selectedLocations.length === 0 ? 'var(--text-primary)' : 'var(--text-secondary)',
                  transition: 'all 0.2s ease-in-out',
                  outline: 'none'
                }}
              >
                Tutte
              </button>
              {locations.map(l => {
                const isSelected = selectedLocations.includes(l.id);
                return (
                  <button
                    key={l.id}
                    onClick={() => {
                      if (isSelected) {
                        setSelectedLocations(selectedLocations.filter(id => id !== l.id));
                      } else {
                        setSelectedLocations([...selectedLocations, l.id]);
                      }
                    }}
                    style={{
                      padding: '4px 10px',
                      borderRadius: '999px',
                      fontSize: '0.75rem',
                      fontWeight: 500,
                      cursor: 'pointer',
                      border: '1px solid ' + (isSelected ? 'var(--accent-blue)' : 'transparent'),
                      background: isSelected ? 'var(--accent-bg)' : 'var(--bg-inset)',
                      color: isSelected ? 'var(--text-primary)' : 'var(--text-secondary)',
                      transition: 'all 0.2s ease-in-out',
                      outline: 'none'
                    }}
                  >
                    {l.nome_struttura}
                  </button>
                );
              })}
            </div>
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
                borderRadius: 'var(--radius-sm)',
                background: 'var(--bg-inset)',
                border: '1px solid var(--line)',
                color: 'var(--text-primary)',
                outline: 'none',
                fontSize: '0.85rem',
                height: '38px',
                boxSizing: 'border-box'
              }}
            >
              <option value="" style={{ background: 'var(--bg-card)' }}>Tutti i fornitori</option>
              {fornitori.map(f => (
                <option key={f.id} value={f.id} style={{ background: 'var(--bg-card)' }}>{f.nome_azienda}</option>
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
                borderRadius: 'var(--radius-sm)',
                background: 'var(--bg-inset)',
                border: '1px solid var(--line)',
                color: 'var(--text-primary)',
                outline: 'none',
                fontSize: '0.85rem',
                height: '38px',
                boxSizing: 'border-box'
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
                borderRadius: 'var(--radius-sm)',
                background: 'var(--bg-inset)',
                border: '1px solid var(--line)',
                color: 'var(--text-primary)',
                outline: 'none',
                fontSize: '0.85rem',
                height: '38px',
                boxSizing: 'border-box'
              }}
            />
          </div>
        </div>
      </div>

      {/* Main Content Pane */}
      <div 
        id="consumption-report-container" 
        style={{ 
          display: 'flex', 
          flexDirection: 'column',
          gap: '24px',
          width: '100%'
        }}
      >
        
        {/* Table list of products */}
        <div 
          className="glass-panel" 
          style={{ 
            width: '100%', 
            padding: '24px', 
            display: 'flex', 
            flexDirection: 'column', 
            gap: '20px'
          }}
        >
          
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
                  background: 'var(--bg-inset)',
                  border: '1px solid var(--line)',
                  borderRadius: 'var(--radius-sm)',
                  color: 'var(--text-primary)',
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
            <div style={{ padding: '16px', borderRadius: '8px', background: 'var(--status-red-bg)', color: 'var(--status-red)', border: '1px solid var(--crit-border)' }}>
              {error}
            </div>
          ) : (
            <div style={{ overflowX: 'auto' }}>
              <table className="ds-table" style={{ width: '100%', borderCollapse: 'collapse' }}>
                <thead>
                  <tr style={{ borderBottom: '1px solid var(--line)', color: 'var(--text-secondary)', fontSize: '0.8rem', textAlign: 'left' }}>
                    <th style={{ padding: '12px', width: '40px', textAlign: 'center' }}>
                      <input 
                        type="checkbox" 
                        checked={filteredItems.length > 0 && selectedSkus.length === filteredItems.length}
                        onChange={(e) => {
                          if (e.target.checked) {
                            setSelectedSkus(filteredItems.map(item => item.sku_interno));
                          } else {
                            setSelectedSkus([]);
                          }
                        }}
                        style={{ cursor: 'pointer' }}
                      />
                    </th>
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
                      <td colSpan={6} style={{ padding: '32px', textAlign: 'center', color: 'var(--text-secondary)' }}>
                        Nessun dato di consumo trovato con i filtri correnti.
                      </td>
                    </tr>
                  ) : (
                    filteredItems.map(item => {
                      const isSelected = selectedSkus.includes(item.sku_interno);
                      return (
                        <tr
                          key={item.sku_interno}
                          onClick={() => {
                            const sku = item.sku_interno;
                            if (isSelected) {
                              setSelectedSkus(selectedSkus.filter(s => s !== sku));
                            } else {
                              setSelectedSkus([...selectedSkus, sku]);
                            }
                          }}
                          style={{
                            borderBottom: '1px solid var(--line)',
                            fontSize: '0.85rem',
                            cursor: 'pointer',
                            background: isSelected ? 'var(--accent-bg)' : 'transparent',
                            transition: 'var(--transition-smooth)'
                          }}
                          className="table-row-hover"
                        >
                          <td style={{ padding: '14px 12px', textAlign: 'center' }} onClick={(e) => e.stopPropagation()}>
                            <input 
                              type="checkbox" 
                              checked={isSelected}
                              onChange={(e) => {
                                const sku = item.sku_interno;
                                if (e.target.checked) {
                                  setSelectedSkus([...selectedSkus, sku]);
                                } else {
                                  setSelectedSkus(selectedSkus.filter(s => s !== sku));
                                }
                              }}
                              style={{ cursor: 'pointer' }}
                            />
                          </td>
                          <td style={{ padding: '14px 12px', color: 'var(--text-primary)', fontWeight: 600, maxWidth: '240px', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{item.descrizione}</td>
                          <td style={{ padding: '14px 12px', textAlign: 'right', fontWeight: 600, fontFamily: 'var(--font-mono)', fontVariantNumeric: 'tabular-nums' }}>
                            {item.quantita_omaggio > 0 ? (
                              <span style={{ display: 'inline-flex', flexDirection: 'column', alignItems: 'flex-end', gap: '2px' }}>
                                <span>{item.quantita_totale.toLocaleString(undefined, { minimumFractionDigits: 1 })}</span>
                                <span 
                                  style={{ 
                                    fontSize: '0.73rem', 
                                    color: 'var(--ok)', 
                                    whiteSpace: 'nowrap',
                                    background: 'var(--ok-bg)',
                                    padding: '1px 6px',
                                    borderRadius: '4px',
                                    border: '1px solid var(--ok-border)',
                                    fontWeight: 500
                                  }} 
                                  title={`${item.quantita_omaggio.toLocaleString(undefined, { minimumFractionDigits: 1 })} unità in omaggio`}
                                >
                                  di cui {item.quantita_omaggio.toLocaleString(undefined, { minimumFractionDigits: 1 })} omaggi
                                </span>
                              </span>
                            ) : (
                              item.quantita_totale.toLocaleString(undefined, { minimumFractionDigits: 1 })
                            )}
                          </td>
                          <td style={{ padding: '14px 12px', textAlign: 'center', color: 'var(--text-secondary)' }}>{item.unita_misura}</td>
                          <td style={{ padding: '14px 12px', textAlign: 'right', color: 'var(--ok)', fontFamily: 'var(--font-mono)', fontVariantNumeric: 'tabular-nums' }}>€ {item.prezzo_medio.toFixed(2)}</td>
                          <td style={{ padding: '14px 12px', textAlign: 'right', fontWeight: 600, color: 'var(--text-primary)', fontFamily: 'var(--font-mono)', fontVariantNumeric: 'tabular-nums' }}>€ {item.spesa_totale.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}</td>
                        </tr>
                      );
                    })
                  )}
                </tbody>
              </table>
            </div>
          )}
        </div>

        {/* Detailed Side Panel / Split view */}
        {selectedSkus.length > 0 && (
          <div 
            className="glass-panel" 
            style={{ 
              width: '100%',
              padding: '24px', 
              display: 'flex', 
              flexDirection: 'column', 
              gap: '20px'
            }}
          >
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', flexWrap: 'wrap', gap: '12px' }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                <BarChart2 size={18} color="var(--status-red)" />
                <h4 style={{ margin: 0, fontWeight: 600 }}>Dettaglio Consumo</h4>
              </div>
              <div style={{ display: 'flex', gap: '10px' }}>
                <button
                  onClick={handleOpenInvoices}
                  className="btn"
                  style={{
                    fontSize: '0.8rem',
                    display: 'flex',
                    alignItems: 'center',
                    gap: '6px',
                    background: 'var(--bg-elevated)',
                    color: 'var(--text-primary)',
                    border: '1px solid var(--line)',
                    padding: '6px 12px',
                    borderRadius: '6px',
                    cursor: 'pointer',
                    transition: 'all 0.2s'
                  }}
                  onMouseOver={(e) => e.currentTarget.style.background = 'var(--bg-elevated)'}
                  onMouseOut={(e) => e.currentTarget.style.background = 'var(--bg-elevated)'}
                >
                  <FileText size={14} color="var(--accent-blue)" />
                  Vedi Storico
                </button>
                <button
                  onClick={handlePDFExport}
                  className="btn"
                  style={{
                    fontSize: '0.8rem',
                    display: 'flex',
                    alignItems: 'center',
                    gap: '6px',
                    background: 'var(--crit-bg)',
                    color: 'var(--status-red)',
                    border: '1px solid var(--crit-border)',
                    padding: '6px 12px',
                    borderRadius: '6px',
                    cursor: 'pointer',
                    transition: 'all 0.2s'
                  }}
                  onMouseOver={(e) => e.currentTarget.style.background = 'var(--crit-bg)'}
                  onMouseOut={(e) => e.currentTarget.style.background = 'var(--crit-bg)'}
                >
                  <Download size={14} />
                  Scarica PDF
                </button>
              </div>
            </div>

            {loadingDetail ? (
              <div style={{ color: 'var(--text-secondary)', padding: '40px', display: 'flex', alignItems: 'center', justifyContent: 'center', gap: '10px' }}>
                <RefreshCw className="animate-spin" size={18} />
                <span>Calcolo aggregato dettagli...</span>
              </div>
            ) : skuDetail ? (
              <div style={{ display: 'flex', flexDirection: 'column', gap: '24px' }}>
                <div>
                  <h3 style={{ fontSize: '1.2rem', margin: '0 0 4px 0', color: 'var(--text-primary)', lineHeight: '1.4' }}>{detailTitle}</h3>
                  <p style={{ fontSize: '0.8rem', color: 'var(--text-secondary)', margin: 0 }}>Analisi dei volumi e spesa consolidata</p>
                </div>

                {/* Grand Total Summary Box */}
                <div style={{ display: 'flex', flexDirection: 'column', gap: '12px' }}>
                  {/* Row 1: Volume & Spesa */}
                  <div className="detail-kpi-row-1" style={{
                    display: 'grid',
                    gridTemplateColumns: '1fr 1fr',
                    gap: '12px'
                  }}>
                    {/* Volume Card */}
                    <div style={{
                      background: 'var(--bg-inset)',
                      border: '1px solid var(--line)',
                      borderRadius: '12px',
                      padding: '14px',
                      display: 'flex',
                      flexDirection: 'column',
                      gap: '4px',
                      boxShadow: 'none'
                    }}>
                      <span style={{ fontSize: '0.7rem', color: 'var(--text-secondary)', textTransform: 'uppercase', letterSpacing: '0.5px', fontWeight: 500 }}>
                        Volume Totale Consolidato
                      </span>
                      <span style={{ fontSize: '1.3rem', fontWeight: 600, color: 'var(--text-primary)', fontFamily: 'var(--font-mono)', fontVariantNumeric: 'tabular-nums', display: 'flex', alignItems: 'baseline', gap: '4px' }}>
                        {totalUnits.toLocaleString()}
                        <span style={{ fontSize: '0.75rem', color: 'var(--text-secondary)', fontWeight: 400 }}>unità</span>
                      </span>
                    </div>

                    {/* Spend Card */}
                    <div style={{
                      background: 'var(--ok-bg)',
                      border: '1px solid var(--ok-border)',
                      borderRadius: '12px',
                      padding: '14px',
                      display: 'flex',
                      flexDirection: 'column',
                      gap: '4px',
                      boxShadow: 'none'
                    }}>
                      <span style={{ fontSize: '0.7rem', color: 'var(--ok)', textTransform: 'uppercase', letterSpacing: '0.5px', fontWeight: 600 }}>
                        Spesa Totale Consolidata
                      </span>
                      <span style={{ fontSize: '1.3rem', fontWeight: 600, color: 'var(--ok)', fontFamily: 'var(--font-mono)', fontVariantNumeric: 'tabular-nums' }}>
                        € {totalSpend.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}
                      </span>
                    </div>
                  </div>

                  {/* Row 2: Min, Medio, Max Prices */}
                  <div className="detail-kpi-row-2" style={{
                    display: 'grid',
                    gridTemplateColumns: 'repeat(auto-fit, minmax(100px, 1fr))',
                    gap: '12px'
                  }}>
                    {/* Min Price Card */}
                    <div style={{
                      background: 'var(--accent-bg)',
                      border: '1px solid var(--accent-border)',
                      borderRadius: '12px',
                      padding: '12px',
                      display: 'flex',
                      flexDirection: 'column',
                      gap: '4px'
                    }}>
                      <span style={{ fontSize: '0.65rem', color: 'var(--accent-text)', textTransform: 'uppercase', letterSpacing: '0.5px', fontWeight: 600 }}>
                        Prezzo Minimo
                      </span>
                      <span style={{ fontSize: '1.15rem', fontWeight: 600, color: 'var(--accent-text)', fontFamily: 'var(--font-mono)', fontVariantNumeric: 'tabular-nums' }}>
                        € {prezzoMinimo.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}
                      </span>
                    </div>

                    {/* Avg Price Card */}
                    <div style={{
                      background: 'var(--info-bg)',
                      border: '1px solid var(--info-border)',
                      borderRadius: '12px',
                      padding: '12px',
                      display: 'flex',
                      flexDirection: 'column',
                      gap: '4px'
                    }}>
                      <span style={{ fontSize: '0.65rem', color: 'var(--info)', textTransform: 'uppercase', letterSpacing: '0.5px', fontWeight: 600 }}>
                        Prezzo Medio
                      </span>
                      <span style={{ fontSize: '1.15rem', fontWeight: 600, color: 'var(--info)', fontFamily: 'var(--font-mono)', fontVariantNumeric: 'tabular-nums' }}>
                        € {prezzoMedio.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}
                      </span>
                    </div>

                    {/* Max Price Card */}
                    <div style={{
                      background: 'var(--warn-bg)',
                      border: '1px solid var(--warn-border)',
                      borderRadius: '12px',
                      padding: '12px',
                      display: 'flex',
                      flexDirection: 'column',
                      gap: '4px'
                    }}>
                      <span style={{ fontSize: '0.65rem', color: 'var(--warn)', textTransform: 'uppercase', letterSpacing: '0.5px', fontWeight: 600 }}>
                        Prezzo Massimo
                      </span>
                      <span style={{ fontSize: '1.15rem', fontWeight: 600, color: 'var(--warn)', fontFamily: 'var(--font-mono)', fontVariantNumeric: 'tabular-nums' }}>
                        € {prezzoMassimo.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}
                      </span>
                    </div>
                  </div>
                </div>

                <div className="detail-split-grid" style={{
                  display: 'grid',
                  gridTemplateColumns: 'repeat(auto-fit, minmax(300px, 1fr))',
                  gap: '32px',
                  alignItems: 'start'
                }}>
                  {/* Location split */}
                  <div>
                    <h5 style={{ margin: '0 0 12px 0', fontSize: '0.85rem', color: 'var(--text-primary)', borderBottom: '1px solid var(--line)', paddingBottom: '6px' }}>Consumi per Sede (Punto Vendita)</h5>
                    {skuDetail.consumo_per_location.length === 0 ? (
                      <div style={{ fontSize: '0.8rem', color: 'var(--text-secondary)', fontStyle: 'italic' }}>Nessun dato per punto vendita</div>
                    ) : (
                      <div style={{ display: 'flex', flexDirection: 'column', gap: '12px' }}>
                        {skuDetail.consumo_per_location.map((loc, i) => (
                          <div key={i} style={{ display: 'flex', flexDirection: 'column', gap: '4px' }}>
                            <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: '0.8rem' }}>
                              <span style={{ fontWeight: 500, color: 'var(--text-secondary)' }}>{loc.location_nome}</span>
                              <span style={{ fontWeight: 600, fontFamily: 'var(--font-mono)', fontVariantNumeric: 'tabular-nums' }}>{loc.quantita_totale.toLocaleString()} unità</span>
                            </div>
                            <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: '0.75rem', color: 'var(--text-secondary)' }}>
                              <span>Spesa Complessiva:</span>
                              <span style={{ color: 'var(--ok)', fontWeight: 500, fontFamily: 'var(--font-mono)', fontVariantNumeric: 'tabular-nums' }}>€ {loc.spesa_totale.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}</span>
                            </div>
                            {/* Progress bar effect */}
                            <div style={{ height: '4px', borderRadius: '2px', background: 'var(--bg-inset)', overflow: 'hidden', marginTop: '2px' }}>
                              <div style={{
                                height: '100%',
                                background: 'var(--accent)',
                                width: `${Math.min(100, (loc.spesa_totale / (skuDetail.consumo_per_location[0]?.spesa_totale || 1)) * 100)}%`
                              }}></div>
                            </div>
                          </div>
                        ))}
                      </div>
                    )}
                  </div>

                  {/* Monthly series split */}
                  <div>
                    <h5 style={{ margin: '0 0 12px 0', fontSize: '0.85rem', color: 'var(--text-primary)', borderBottom: '1px solid var(--line)', paddingBottom: '6px' }}>Andamento Storico Mensile</h5>
                    {skuDetail.consumo_per_mese.length === 0 ? (
                      <div style={{ fontSize: '0.8rem', color: 'var(--text-secondary)', fontStyle: 'italic' }}>Nessun dato storico</div>
                    ) : (
                      <div style={{ display: 'flex', flexDirection: 'column', gap: '12px' }}>
                        {skuDetail.consumo_per_mese.map((mon, i) => (
                          <div key={i} style={{ display: 'flex', flexDirection: 'column', gap: '4px' }}>
                            <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: '0.8rem' }}>
                              <span style={{ fontWeight: 600, color: 'var(--text-primary)' }}>{formatMese(mon.mese)}</span>
                              <span style={{ fontFamily: 'var(--font-mono)', fontVariantNumeric: 'tabular-nums' }}>{mon.quantita_totale.toLocaleString()} unità</span>
                            </div>
                            <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: '0.75rem', color: 'var(--text-secondary)' }}>
                              <span>Valore Speso:</span>
                              <span style={{ color: 'var(--ok)', fontWeight: 500, fontFamily: 'var(--font-mono)', fontVariantNumeric: 'tabular-nums' }}>€ {mon.spesa_totale.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}</span>
                            </div>
                            <div style={{ height: '4px', borderRadius: '2px', background: 'var(--bg-inset)', overflow: 'hidden', marginTop: '2px' }}>
                              <div style={{
                                height: '100%',
                                background: 'var(--crit)',
                                width: `${Math.min(100, (mon.spesa_totale / (Math.max(...skuDetail.consumo_per_mese.map(m => m.spesa_totale)) || 1)) * 100)}%`
                              }}></div>
                            </div>
                          </div>
                        ))}
                      </div>
                    )}
                  </div>
                </div>

              </div>
            ) : (
              <div style={{ color: 'var(--text-secondary)', textAlign: 'center', padding: '20px' }}>
                Nessun dettaglio disponibile.
              </div>
            )}
          </div>
        )}

      </div>

      {/* Riepilogo Fatture Modal */}
      {showInvoicesModal && (
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
          zIndex: 9999,
          padding: '20px',
          boxSizing: 'border-box'
        }}>
          <div className="glass-panel invoices-modal-content" style={{
            width: '100%',
            maxWidth: '1000px',
            maxHeight: '85vh',
            display: 'flex',
            flexDirection: 'column',
            padding: '24px',
            background: 'var(--bg-card)',
            boxShadow: 'var(--shadow-pop)',
            border: '1px solid var(--line)',
            borderRadius: 'var(--radius-lg)',
            overflow: 'hidden'
          }}>
            {/* Header */}
            <div className="modal-header-container" style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', borderBottom: '1px solid var(--line)', paddingBottom: '16px', marginBottom: '20px' }}>
              <div>
                <h4 style={{ margin: 0, fontSize: '1.2rem', fontWeight: 600, color: 'var(--text-primary)', display: 'flex', alignItems: 'center', gap: '8px' }}>
                  <FileText size={20} color="var(--accent-blue)" />
                  Storico Fatture di Consumo
                </h4>
                <p style={{ margin: '4px 0 0 0', fontSize: '0.8rem', color: 'var(--text-secondary)' }}>
                  {detailTitle}
                </p>
              </div>
              <div style={{ display: 'flex', alignItems: 'center', gap: '12px' }}>
                <button
                  onClick={handlePDFExport}
                  className="btn"
                  style={{
                    fontSize: '0.8rem',
                    display: 'flex',
                    alignItems: 'center',
                    gap: '6px',
                    background: 'var(--crit-bg)',
                    color: 'var(--status-red)',
                    border: '1px solid var(--crit-border)',
                    padding: '6px 14px',
                    borderRadius: '6px',
                    cursor: 'pointer',
                    fontWeight: 500,
                    transition: 'all 0.2s'
                  }}
                  onMouseOver={(e) => e.currentTarget.style.background = 'var(--crit-bg)'}
                  onMouseOut={(e) => e.currentTarget.style.background = 'var(--crit-bg)'}
                >
                  <Download size={14} />
                  Esporta PDF
                </button>
                <button
                  onClick={() => setShowInvoicesModal(false)}
                  style={{
                    background: 'transparent',
                    border: 'none',
                    color: 'var(--text-secondary)',
                    cursor: 'pointer',
                    padding: '4px',
                    display: 'flex',
                    alignItems: 'center',
                    justifyContent: 'center',
                    borderRadius: '50%',
                    transition: 'all 0.2s'
                  }}
                  onMouseOver={(e) => e.currentTarget.style.background = 'var(--bg-elevated)'}
                  onMouseOut={(e) => e.currentTarget.style.background = 'transparent'}
                >
                  <X size={20} />
                </button>
              </div>
            </div>

            {/* Table / Content */}
            {loadingInvoices ? (
              <div style={{ flex: 1, display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center', gap: '12px', padding: '60px 0', color: 'var(--text-secondary)' }}>
                <RefreshCw className="animate-spin" size={24} color="var(--accent-blue)" />
                <span>Caricamento riepilogo fatture...</span>
              </div>
            ) : invoicesList.length === 0 ? (
              <div style={{ flex: 1, display: 'flex', alignItems: 'center', justifyContent: 'center', padding: '60px 0', color: 'var(--text-secondary)', fontStyle: 'italic' }}>
                Nessuna fattura trovata per i criteri selezionati.
              </div>
            ) : (
              <div style={{ flex: 1, overflowY: 'auto', overflowX: 'auto', marginRight: '-8px', paddingRight: '8px' }}>
                <table className="ds-table" style={{ width: '100%', borderCollapse: 'collapse', fontSize: '0.85rem' }}>
                  <thead>
                    <tr style={{ borderBottom: '1px solid var(--line)', color: 'var(--text-secondary)', textAlign: 'left' }}>
                      <th style={{ padding: '10px' }}>Data</th>
                      <th style={{ padding: '10px' }}>N. Documento</th>
                      <th style={{ padding: '10px' }}>Sede</th>
                      <th style={{ padding: '10px' }}>Fornitore</th>
                      <th style={{ padding: '10px' }}>Descrizione XML</th>
                      <th style={{ padding: '10px', textAlign: 'right' }}>Quantità</th>
                      <th style={{ padding: '10px', textAlign: 'right' }}>Prezzo Unit.</th>
                      <th style={{ padding: '10px', textAlign: 'right' }}>Spesa Totale</th>
                    </tr>
                  </thead>
                  <tbody>
                    {invoicesList.map((inv, idx) => (
                      <tr 
                        key={idx} 
                        style={{ borderBottom: '1px solid var(--line)', transition: 'background 0.2s' }}
                        className="table-row-hover"
                      >
                        <td style={{ padding: '12px 10px', whiteSpace: 'nowrap', fontFamily: 'var(--font-mono)', fontVariantNumeric: 'tabular-nums' }}>{formatData(inv.data_documento)}</td>
                        <td style={{ padding: '12px 10px' }}>
                          <span
                            onClick={() => {
                              const token = localStorage.getItem('token');
                              window.open(`${API_BASE}/fatture/${inv.fattura_id}/html?token=${token}`, '_blank');
                            }}
                            style={{
                              fontWeight: 600,
                              color: 'var(--accent-text)',
                              cursor: 'pointer',
                              textDecoration: 'none',
                              transition: 'all 0.2s'
                            }}
                            onMouseOver={(e) => {
                              e.currentTarget.style.color = 'var(--accent-text)';
                              e.currentTarget.style.textDecoration = 'underline';
                            }}
                            onMouseOut={(e) => {
                              e.currentTarget.style.color = 'var(--accent-text)';
                              e.currentTarget.style.textDecoration = 'none';
                            }}
                            title="Visualizza anteprima fattura originale"
                          >
                            {inv.numero_documento}
                          </span>
                        </td>
                        <td style={{ padding: '12px 10px', color: 'var(--text-secondary)' }}>{inv.location_nome}</td>
                        <td style={{ padding: '12px 10px', color: 'var(--text-secondary)' }}>{inv.fornitore_nome}</td>
                        <td style={{ padding: '12px 10px', maxWidth: '200px', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }} title={inv.prodotto_descrizione}>
                          {inv.prodotto_descrizione}
                        </td>
                        <td style={{ padding: '12px 10px', textAlign: 'right', fontWeight: 600, fontFamily: 'var(--font-mono)', fontVariantNumeric: 'tabular-nums' }}>
                          {inv.is_omaggio || inv.unita_misura === 'OMAGGIO' ? (
                            <span style={{ display: 'inline-flex', alignItems: 'center', gap: '6px' }}>
                              <span>
                                {inv.quantita.toLocaleString(undefined, { minimumFractionDigits: 1 })}{' '}
                                {inv.unita_misura === 'OMAGGIO' 
                                  ? (consumption.find(c => c.sku_interno === inv.sku_interno)?.unita_misura || 'Pz') 
                                  : inv.unita_misura
                                }
                              </span>
                              <span 
                                style={{ 
                                  fontSize: '0.7rem', 
                                  color: 'var(--ok)', 
                                  fontWeight: 700,
                                  background: 'var(--ok-bg)',
                                  padding: '1px 5px',
                                  borderRadius: '3px',
                                  border: '1px solid var(--ok-border)'
                                }}
                              >
                                OMAGGIO
                              </span>
                            </span>
                          ) : (
                            `${inv.quantita.toLocaleString(undefined, { minimumFractionDigits: 1 })} ${inv.unita_misura}`
                          )}
                        </td>
                        <td style={{ padding: '12px 10px', textAlign: 'right', color: 'var(--ok)', fontFamily: 'var(--font-mono)', fontVariantNumeric: 'tabular-nums' }}>
                          € {inv.prezzo_unitario.toFixed(2)}
                        </td>
                        <td style={{ padding: '12px 10px', textAlign: 'right', fontWeight: 600, color: 'var(--text-primary)', fontFamily: 'var(--font-mono)', fontVariantNumeric: 'tabular-nums' }}>
                          € {inv.spesa_totale.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}

            {/* Footer Summary / Stats */}
            {!loadingInvoices && invoicesList.length > 0 && (
              <div style={{
                display: 'flex',
                justifyContent: 'flex-end',
                gap: '40px',
                borderTop: '1px solid var(--line)',
                paddingTop: '16px',
                marginTop: '16px',
                fontSize: '0.9rem'
              }}>
                <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                  <span style={{ color: 'var(--text-secondary)' }}>Quantità Totale:</span>
                  <span style={{ fontWeight: 600, color: 'var(--text-primary)', fontFamily: 'var(--font-mono)', fontVariantNumeric: 'tabular-nums' }}>
                    {invoicesList.reduce((acc, curr) => acc + curr.quantita, 0).toLocaleString(undefined, { minimumFractionDigits: 1 })} unità
                  </span>
                </div>
                <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                  <span style={{ color: 'var(--text-secondary)' }}>Spesa Totale:</span>
                  <span style={{ fontWeight: 600, color: 'var(--ok)', fontFamily: 'var(--font-mono)', fontVariantNumeric: 'tabular-nums' }}>
                    € {invoicesList.reduce((acc, curr) => acc + curr.spesa_totale, 0).toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}
                  </span>
                </div>
              </div>
            )}
          </div>
        </div>
      )}

    </div>
  );
}
