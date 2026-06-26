import { useState, useEffect } from 'react';
import { FileSpreadsheet, TrendingUp, Coins, Package, ShoppingCart, Calendar, Filter, ArrowUpDown } from 'lucide-react';
import { API_BASE, getHeaders } from '../api';

interface ProductItem {
  sku_interno: string;
  descrizione: string;
  quantita_totale: number;
  quantita_omaggio: number;
  unita_misura: string;
  spesa_totale: number;
  numero_acquisti: number;
  prezzo_medio: number;
}

interface SupplierItem {
  id: number;
  nome_azienda: string;
}

interface LocationItem {
  id: number;
  nome_struttura: string;
}

export default function TopProductsPriceList() {
  // State for data
  const [products, setProducts] = useState<ProductItem[]>([]);
  const [suppliers, setSuppliers] = useState<SupplierItem[]>([]);
  const [locations, setLocations] = useState<LocationItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [exporting, setExporting] = useState(false);

  // Filters
  const [limit, setLimit] = useState<number>(50);
  const [sortBy, setSortBy] = useState<string>('quantita');
  const [selectedSupplier, setSelectedSupplier] = useState<string>('');
  const [selectedLocations, setSelectedLocations] = useState<number[]>([]);
  const [dataDa, setDataDa] = useState<string>('');
  const [dataA, setDataA] = useState<string>('');

  // Auxiliary data loading
  useEffect(() => {
    async function loadFilters() {
      try {
        const headers = getHeaders();
        const [supRes, locRes] = await Promise.all([
          fetch(`${API_BASE}/fornitori/`, { headers }),
          fetch(`${API_BASE}/location/`, { headers })
        ]);
        if (supRes.ok) setSuppliers(await supRes.json());
        if (locRes.ok) setLocations(await locRes.json());
      } catch (err) {
        console.error('Error loading filters data', err);
      }
    }
    loadFilters();
  }, []);

  // Main data loading
  useEffect(() => {
    async function loadData() {
      try {
        setLoading(true);
        const params = new URLSearchParams();
        params.append('limit', limit.toString());
        params.append('sort_by', sortBy);
        if (selectedSupplier) params.append('fornitore_id', selectedSupplier);
        if (selectedLocations.length > 0) params.append('location_ids', selectedLocations.join(','));
        if (dataDa) params.append('data_da', dataDa);
        if (dataA) params.append('data_a', dataA);

        const res = await fetch(`${API_BASE}/intelligence/top-purchased-products?${params.toString()}`, {
          headers: getHeaders()
        });
        if (res.ok) {
          setProducts(await res.json());
        }
      } catch (err) {
        console.error('Error fetching top products list', err);
      } finally {
        setLoading(false);
      }
    }
    loadData();
  }, [limit, sortBy, selectedSupplier, selectedLocations, dataDa, dataA]);

  // Excel export trigger
  const handleExportExcel = async () => {
    try {
      setExporting(true);
      const params = new URLSearchParams();
      params.append('limit', limit.toString());
      params.append('sort_by', sortBy);
      if (selectedSupplier) params.append('fornitore_id', selectedSupplier);
      if (selectedLocations.length > 0) params.append('location_ids', selectedLocations.join(','));
      if (dataDa) params.append('data_da', dataDa);
      if (dataA) params.append('data_a', dataA);

      const res = await fetch(`${API_BASE}/intelligence/export-top-purchased-excel?${params.toString()}`, {
        headers: getHeaders()
      });
      if (!res.ok) throw new Error('Excel export failed');

      const blob = await res.blob();
      const url = window.URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = `listino_top_${limit}_prodotti.xlsx`;
      document.body.appendChild(a);
      a.click();
      a.remove();
      window.URL.revokeObjectURL(url);
    } catch (err) {
      console.error('Error exporting Excel', err);
      alert('Impossibile scaricare il listino in Excel.');
    } finally {
      setExporting(false);
    }
  };

  // Helper calculation for KPI cards
  const totalSpend = products.reduce((sum, p) => sum + p.spesa_totale, 0);
  const totalVolume = products.reduce((sum, p) => sum + p.quantita_totale, 0);
  const totalOrders = products.reduce((sum, p) => sum + p.numero_acquisti, 0);
  const avgUnitPrice = totalVolume > 0 ? totalSpend / totalVolume : 0;

  const handleLocationToggle = (id: number) => {
    if (selectedLocations.includes(id)) {
      setSelectedLocations(selectedLocations.filter(locId => locId !== id));
    } else {
      setSelectedLocations([...selectedLocations, id]);
    }
  };

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: '28px' }}>
      
      {/* KPI Overview Cards */}
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(220px, 1fr))', gap: '20px' }}>
        
        {/* Card 1: Articoli Rilevati */}
        <div className="glass-panel" style={{ padding: '20px', display: 'flex', alignItems: 'center', gap: '16px', borderLeft: '4px solid var(--accent-blue)', position: 'relative', overflow: 'hidden' }}>
          <div style={{ padding: '12px', borderRadius: '12px', background: 'rgba(59, 130, 246, 0.1)', color: 'var(--accent-blue)' }}>
            <Package size={24} />
          </div>
          <div>
            <div style={{ fontSize: '0.8rem', color: 'var(--text-secondary)', textTransform: 'uppercase', letterSpacing: '0.5px' }}>Articoli Listino</div>
            <div style={{ fontSize: '1.6rem', fontWeight: 700, marginTop: '4px' }}>{products.length}</div>
          </div>
        </div>

        {/* Card 2: Spesa Totale Riferimento */}
        <div className="glass-panel" style={{ padding: '20px', display: 'flex', alignItems: 'center', gap: '16px', borderLeft: '4px solid var(--status-green)', position: 'relative', overflow: 'hidden' }}>
          <div style={{ padding: '12px', borderRadius: '12px', background: 'rgba(16, 185, 129, 0.1)', color: 'var(--status-green)' }}>
            <Coins size={24} />
          </div>
          <div>
            <div style={{ fontSize: '0.8rem', color: 'var(--text-secondary)', textTransform: 'uppercase', letterSpacing: '0.5px' }}>Volume Spesa</div>
            <div style={{ fontSize: '1.6rem', fontWeight: 700, marginTop: '4px' }}>
              € {totalSpend.toLocaleString('it-IT', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}
            </div>
          </div>
        </div>

        {/* Card 3: Quantità Totale */}
        <div className="glass-panel" style={{ padding: '20px', display: 'flex', alignItems: 'center', gap: '16px', borderLeft: '4px solid #8b5cf6', position: 'relative', overflow: 'hidden' }}>
          <div style={{ padding: '12px', borderRadius: '12px', background: 'rgba(139, 92, 246, 0.1)', color: '#8b5cf6' }}>
            <TrendingUp size={24} />
          </div>
          <div>
            <div style={{ fontSize: '0.8rem', color: 'var(--text-secondary)', textTransform: 'uppercase', letterSpacing: '0.5px' }}>Quantità Totale</div>
            <div style={{ fontSize: '1.6rem', fontWeight: 700, marginTop: '4px' }}>
              {totalVolume.toLocaleString('it-IT', { maximumFractionDigits: 0 })}
            </div>
          </div>
        </div>

        {/* Card 4: Prezzo Medio Ponderato */}
        <div className="glass-panel" style={{ padding: '20px', display: 'flex', alignItems: 'center', gap: '16px', borderLeft: '4px solid #f59e0b', position: 'relative', overflow: 'hidden' }}>
          <div style={{ padding: '12px', borderRadius: '12px', background: 'rgba(245, 158, 11, 0.1)', color: '#f59e0b' }}>
            <ShoppingCart size={24} />
          </div>
          <div>
            <div style={{ fontSize: '0.8rem', color: 'var(--text-secondary)', textTransform: 'uppercase', letterSpacing: '0.5px' }}>Costo Medio Unità</div>
            <div style={{ fontSize: '1.6rem', fontWeight: 700, marginTop: '4px' }}>
              € {avgUnitPrice.toLocaleString('it-IT', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}
            </div>
          </div>
        </div>

      </div>

      {/* Control Panel (Filters & Settings) */}
      <div className="glass-panel" style={{ padding: '24px', display: 'flex', flexDirection: 'column', gap: '20px' }}>
        
        {/* Row 1: Limit and Sorting Pills */}
        <div style={{ display: 'flex', flexWrap: 'wrap', justifyContent: 'space-between', alignItems: 'center', gap: '16px', borderBottom: '1px solid var(--border-glass)', paddingBottom: '16px' }}>
          
          {/* Limit selector */}
          <div style={{ display: 'flex', alignItems: 'center', gap: '12px' }}>
            <span style={{ fontSize: '0.9rem', color: 'var(--text-secondary)', fontWeight: 500 }}>Numero Prodotti (Top N):</span>
            <div style={{ display: 'flex', gap: '6px', background: 'rgba(255,255,255,0.02)', padding: '4px', borderRadius: '8px', border: '1px solid var(--border-glass)' }}>
              {[10, 50, 100, 250, 500].map(val => (
                <button
                  key={val}
                  onClick={() => setLimit(val)}
                  style={{
                    padding: '6px 12px', borderRadius: '6px', border: 'none',
                    background: limit === val ? 'var(--accent-blue)' : 'transparent',
                    color: limit === val ? 'white' : 'var(--text-secondary)',
                    fontWeight: 600, fontSize: '0.8rem', cursor: 'pointer', outline: 'none',
                    transition: 'all 0.2s'
                  }}
                >
                  {val}
                </button>
              ))}
            </div>
          </div>

          {/* Sorting Selector */}
          <div style={{ display: 'flex', alignItems: 'center', gap: '12px' }}>
            <span style={{ fontSize: '0.9rem', color: 'var(--text-secondary)', fontWeight: 500 }}><ArrowUpDown size={14} style={{ display: 'inline', marginRight: '4px', verticalAlign: 'middle' }} />Ordina per:</span>
            <div style={{ display: 'flex', gap: '6px', background: 'rgba(255,255,255,0.02)', padding: '4px', borderRadius: '8px', border: '1px solid var(--border-glass)' }}>
              {[
                { key: 'quantita', label: 'Volume' },
                { key: 'spesa', label: 'Spesa' },
                { key: 'acquisti', label: 'Frequenza' }
              ].map(opt => (
                <button
                  key={opt.key}
                  onClick={() => setSortBy(opt.key)}
                  style={{
                    padding: '6px 12px', borderRadius: '6px', border: 'none',
                    background: sortBy === opt.key ? 'var(--accent-blue)' : 'transparent',
                    color: sortBy === opt.key ? 'white' : 'var(--text-secondary)',
                    fontWeight: 600, fontSize: '0.8rem', cursor: 'pointer', outline: 'none',
                    transition: 'all 0.2s'
                  }}
                >
                  {opt.label}
                </button>
              ))}
            </div>
          </div>

        </div>

        {/* Row 2: Selectors & Date Range */}
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(200px, 1fr))', gap: '16px' }}>
          
          {/* Supplier filter */}
          <div style={{ display: 'flex', flexDirection: 'column', gap: '6px' }}>
            <label style={{ fontSize: '0.8rem', color: 'var(--text-secondary)', fontWeight: 600 }}><Filter size={12} style={{ display: 'inline', marginRight: '4px' }} />Fornitore</label>
            <select
              value={selectedSupplier}
              onChange={e => setSelectedSupplier(e.target.value)}
              style={{
                padding: '10px', background: 'var(--bg-secondary)', border: '1px solid var(--border-glass)',
                borderRadius: '8px', color: 'white', outline: 'none', fontSize: '0.9rem'
              }}
            >
              <option value="">Tutti i Fornitori</option>
              {suppliers.map(s => (
                <option key={s.id} value={s.id}>{s.nome_azienda}</option>
              ))}
            </select>
          </div>

          {/* Date range - Da */}
          <div style={{ display: 'flex', flexDirection: 'column', gap: '6px' }}>
            <label style={{ fontSize: '0.8rem', color: 'var(--text-secondary)', fontWeight: 600 }}><Calendar size={12} style={{ display: 'inline', marginRight: '4px' }} />Data Inizio</label>
            <input
              type="date"
              value={dataDa}
              onChange={e => setDataDa(e.target.value)}
              style={{
                padding: '9px 10px', background: 'var(--bg-secondary)', border: '1px solid var(--border-glass)',
                borderRadius: '8px', color: 'white', outline: 'none', fontSize: '0.9rem', width: '100%', boxSizing: 'border-box'
              }}
            />
          </div>

          {/* Date range - A */}
          <div style={{ display: 'flex', flexDirection: 'column', gap: '6px' }}>
            <label style={{ fontSize: '0.8rem', color: 'var(--text-secondary)', fontWeight: 600 }}><Calendar size={12} style={{ display: 'inline', marginRight: '4px' }} />Data Fine</label>
            <input
              type="date"
              value={dataA}
              onChange={e => setDataA(e.target.value)}
              style={{
                padding: '9px 10px', background: 'var(--bg-secondary)', border: '1px solid var(--border-glass)',
                borderRadius: '8px', color: 'white', outline: 'none', fontSize: '0.9rem', width: '100%', boxSizing: 'border-box'
              }}
            />
          </div>

        </div>

        {/* Row 3: Location pills multi-select */}
        <div style={{ display: 'flex', flexDirection: 'column', gap: '8px', borderTop: '1px solid var(--border-glass)', paddingTop: '16px' }}>
          <span style={{ fontSize: '0.8rem', color: 'var(--text-secondary)', fontWeight: 600 }}>Filtra per Sede (Seleziona per includere):</span>
          <div style={{ display: 'flex', flexWrap: 'wrap', gap: '8px' }}>
            <button
              onClick={() => setSelectedLocations([])}
              style={{
                padding: '6px 12px', borderRadius: '20px', fontSize: '0.8rem', cursor: 'pointer',
                border: '1px solid ' + (selectedLocations.length === 0 ? 'var(--accent-blue)' : 'transparent'),
                background: selectedLocations.length === 0 ? 'rgba(59,130,246,0.2)' : 'rgba(255,255,255,0.03)',
                color: selectedLocations.length === 0 ? 'white' : 'var(--text-secondary)',
                fontWeight: 600, transition: 'all 0.2s'
              }}
            >
              Tutte le Sedi
            </button>
            {locations.map(loc => {
              const isSelected = selectedLocations.includes(loc.id);
              return (
                <button
                  key={loc.id}
                  onClick={() => handleLocationToggle(loc.id)}
                  style={{
                    padding: '6px 12px', borderRadius: '20px', fontSize: '0.8rem', cursor: 'pointer',
                    border: '1px solid ' + (isSelected ? 'var(--accent-blue)' : 'transparent'),
                    background: isSelected ? 'rgba(59,130,246,0.2)' : 'rgba(255,255,255,0.03)',
                    color: isSelected ? 'white' : 'var(--text-secondary)',
                    fontWeight: 500, transition: 'all 0.2s'
                  }}
                >
                  {loc.nome_struttura}
                </button>
              );
            })}
          </div>
        </div>

      </div>

      {/* Main Results Panel */}
      <div className="glass-panel" style={{ padding: '24px', display: 'flex', flexDirection: 'column', gap: '20px' }}>
        
        {/* Table header area with Excel export button */}
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', flexWrap: 'wrap', gap: '12px' }}>
          <div>
            <h3 style={{ margin: 0, fontSize: '1.2rem', fontWeight: 600 }}>Elenco Benchmark Listino</h3>
            <p style={{ margin: '4px 0 0 0', fontSize: '0.85rem', color: 'var(--text-secondary)' }}>
              Mostra i prezzi medi storici dei {products.length} prodotti più acquistati in base ai filtri attivi.
            </p>
          </div>
          
          <button
            onClick={handleExportExcel}
            disabled={exporting || products.length === 0}
            className="btn btn-primary"
            style={{
              display: 'flex', alignItems: 'center', gap: '8px', padding: '10px 16px', fontSize: '0.85rem',
              opacity: (exporting || products.length === 0) ? 0.6 : 1, cursor: 'pointer'
            }}
          >
            <FileSpreadsheet size={16} />
            {exporting ? 'Generazione Excel...' : 'Esporta Listino Excel'}
          </button>
        </div>

        {/* Responsive Table */}
        <div style={{ overflowX: 'auto', borderRadius: '8px', border: '1px solid rgba(255,255,255,0.05)' }}>
          <table style={{ width: '100%', borderCollapse: 'collapse' }}>
            <thead>
              <tr style={{ background: 'rgba(255,255,255,0.02)', color: 'var(--text-secondary)', fontSize: '0.8rem', textAlign: 'left' }}>
                <th style={{ padding: '16px 12px', textAlign: 'center', width: '60px', borderBottom: '1px solid rgba(255,255,255,0.05)' }}>Pos.</th>
                <th style={{ padding: '16px 12px', width: '120px', borderBottom: '1px solid rgba(255,255,255,0.05)' }}>SKU Interno</th>
                <th style={{ padding: '16px 12px', borderBottom: '1px solid rgba(255,255,255,0.05)' }}>Descrizione Prodotto</th>
                <th style={{ padding: '16px 12px', textAlign: 'center', width: '80px', borderBottom: '1px solid rgba(255,255,255,0.05)' }}>U.M.</th>
                <th style={{ padding: '16px 12px', textAlign: 'right', width: '130px', borderBottom: '1px solid rgba(255,255,255,0.05)' }}>Quantità Totale</th>
                <th style={{ padding: '16px 12px', textAlign: 'right', width: '110px', borderBottom: '1px solid rgba(255,255,255,0.05)' }}>N. Acquisti</th>
                <th style={{ padding: '16px 12px', textAlign: 'right', width: '140px', color: 'white', fontWeight: 600, borderBottom: '1px solid rgba(255,255,255,0.05)' }}>Prezzo Medio</th>
                <th style={{ padding: '16px 12px', textAlign: 'right', width: '140px', borderBottom: '1px solid rgba(255,255,255,0.05)' }}>Spesa Totale</th>
              </tr>
            </thead>
            <tbody>
              {loading ? (
                <tr>
                  <td colSpan={8} style={{ padding: '40px', textAlign: 'center', color: 'var(--text-secondary)' }}>
                    Caricamento dati in corso...
                  </td>
                </tr>
              ) : products.length === 0 ? (
                <tr>
                  <td colSpan={8} style={{ padding: '40px', textAlign: 'center', color: 'var(--text-secondary)' }}>
                    Nessun prodotto trovato per i criteri di ricerca impostati.
                  </td>
                </tr>
              ) : (
                products.map((p, idx) => {
                  // Style first three positions with medals
                  const rank = idx + 1;
                  let rankDisplay: string | JSX.Element = `#${rank}`;
                  if (rank === 1) rankDisplay = <span style={{ fontSize: '1.25rem' }} title="1° Posto">🥇</span>;
                  else if (rank === 2) rankDisplay = <span style={{ fontSize: '1.25rem' }} title="2° Posto">🥈</span>;
                  else if (rank === 3) rankDisplay = <span style={{ fontSize: '1.25rem' }} title="3° Posto">🥉</span>;

                  return (
                    <tr
                      key={p.sku_interno}
                      style={{
                        borderBottom: '1px solid rgba(255,255,255,0.02)',
                        transition: 'background 0.2s',
                        cursor: 'default'
                      }}
                      onMouseEnter={e => e.currentTarget.style.background = 'rgba(255,255,255,0.01)'}
                      onMouseLeave={e => e.currentTarget.style.background = 'transparent'}
                    >
                      <td style={{ padding: '12px 10px', textAlign: 'center', fontWeight: 600, color: 'white' }}>
                        {rankDisplay}
                      </td>
                      <td style={{ padding: '12px 10px' }}>
                        <span style={{ background: 'rgba(59, 130, 246, 0.1)', color: 'var(--accent-blue)', padding: '4px 8px', borderRadius: '6px', fontSize: '0.85rem', fontWeight: 600 }}>
                          {p.sku_interno}
                        </span>
                      </td>
                      <td style={{ padding: '12px 10px', fontWeight: 500, color: 'rgba(255,255,255,0.9)' }}>
                        {p.descrizione || 'N/A'}
                      </td>
                      <td style={{ padding: '12px 10px', textAlign: 'center', color: 'var(--text-secondary)', fontSize: '0.85rem' }}>
                        {p.unita_misura}
                      </td>
                      <td style={{ padding: '12px 10px', textAlign: 'right', fontWeight: 500 }}>
                        {p.quantita_totale.toLocaleString('it-IT', { minimumFractionDigits: 1, maximumFractionDigits: 1 })}
                      </td>
                      <td style={{ padding: '12px 10px', textAlign: 'right', color: 'var(--text-secondary)' }}>
                        {p.numero_acquisti}
                      </td>
                      <td style={{ padding: '12px 10px', textAlign: 'right', fontWeight: 700, color: '#10b981' }}>
                        € {p.prezzo_medio.toLocaleString('it-IT', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}
                      </td>
                      <td style={{ padding: '12px 10px', textAlign: 'right', color: 'rgba(255,255,255,0.85)', fontWeight: 500 }}>
                        € {p.spesa_totale.toLocaleString('it-IT', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}
                      </td>
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
