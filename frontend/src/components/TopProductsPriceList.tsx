import { useState, useEffect } from 'react';
import { FileSpreadsheet, TrendingUp, Coins, Package, ShoppingCart, Calendar, ArrowUpDown } from 'lucide-react';
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
  const [selectedSuppliers, setSelectedSuppliers] = useState<number[]>([]);
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
        if (selectedSuppliers.length > 0) params.append('fornitore_ids', selectedSuppliers.join(','));
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
  }, [limit, sortBy, selectedSuppliers, selectedLocations, dataDa, dataA]);

  // Excel export trigger
  const handleExportExcel = async () => {
    try {
      setExporting(true);
      const params = new URLSearchParams();
      params.append('limit', limit.toString());
      params.append('sort_by', sortBy);
      if (selectedSuppliers.length > 0) params.append('fornitore_ids', selectedSuppliers.join(','));
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
  const avgUnitPrice = totalVolume > 0 ? totalSpend / totalVolume : 0;

  const handleLocationToggle = (id: number) => {
    if (selectedLocations.includes(id)) {
      setSelectedLocations(selectedLocations.filter(locId => locId !== id));
    } else {
      setSelectedLocations([...selectedLocations, id]);
    }
  };

  const handleSupplierToggle = (id: number) => {
    if (selectedSuppliers.includes(id)) {
      setSelectedSuppliers(selectedSuppliers.filter(supId => supId !== id));
    } else {
      setSelectedSuppliers([...selectedSuppliers, id]);
    }
  };

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: '28px' }}>
      
      {/* KPI Overview Cards */}
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(220px, 1fr))', gap: '20px' }}>
        
        {/* Card 1: Articoli Rilevati */}
        <div className="glass-panel" style={{ padding: '20px', display: 'flex', alignItems: 'center', gap: '16px', borderLeft: '4px solid var(--accent)', position: 'relative', overflow: 'hidden' }}>
          <div style={{ padding: '12px', borderRadius: 'var(--radius-md)', background: 'var(--accent-bg)', color: 'var(--accent-text)' }}>
            <Package size={24} />
          </div>
          <div>
            <div style={{ fontSize: '0.8rem', color: 'var(--text-secondary)', textTransform: 'uppercase', letterSpacing: '0.5px' }}>Articoli Listino</div>
            <div style={{ fontSize: '1.6rem', fontWeight: 600, marginTop: '4px', fontFamily: 'var(--font-mono)', fontVariantNumeric: 'tabular-nums' }}>{products.length}</div>
          </div>
        </div>

        {/* Card 2: Spesa Totale Riferimento */}
        <div className="glass-panel" style={{ padding: '20px', display: 'flex', alignItems: 'center', gap: '16px', borderLeft: '4px solid var(--ok)', position: 'relative', overflow: 'hidden' }}>
          <div style={{ padding: '12px', borderRadius: 'var(--radius-md)', background: 'var(--ok-bg)', color: 'var(--ok)' }}>
            <Coins size={24} />
          </div>
          <div>
            <div style={{ fontSize: '0.8rem', color: 'var(--text-secondary)', textTransform: 'uppercase', letterSpacing: '0.5px' }}>Volume Spesa</div>
            <div style={{ fontSize: '1.6rem', fontWeight: 600, marginTop: '4px', fontFamily: 'var(--font-mono)', fontVariantNumeric: 'tabular-nums' }}>
              € {totalSpend.toLocaleString('it-IT', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}
            </div>
          </div>
        </div>

        {/* Card 3: Quantità Totale */}
        <div className="glass-panel" style={{ padding: '20px', display: 'flex', alignItems: 'center', gap: '16px', borderLeft: '4px solid var(--info)', position: 'relative', overflow: 'hidden' }}>
          <div style={{ padding: '12px', borderRadius: 'var(--radius-md)', background: 'var(--info-bg)', color: 'var(--info)' }}>
            <TrendingUp size={24} />
          </div>
          <div>
            <div style={{ fontSize: '0.8rem', color: 'var(--text-secondary)', textTransform: 'uppercase', letterSpacing: '0.5px' }}>Quantità Totale</div>
            <div style={{ fontSize: '1.6rem', fontWeight: 600, marginTop: '4px', fontFamily: 'var(--font-mono)', fontVariantNumeric: 'tabular-nums' }}>
              {totalVolume.toLocaleString('it-IT', { maximumFractionDigits: 0 })}
            </div>
          </div>
        </div>

        {/* Card 4: Prezzo Medio Ponderato */}
        <div className="glass-panel" style={{ padding: '20px', display: 'flex', alignItems: 'center', gap: '16px', borderLeft: '4px solid var(--warn)', position: 'relative', overflow: 'hidden' }}>
          <div style={{ padding: '12px', borderRadius: 'var(--radius-md)', background: 'var(--warn-bg)', color: 'var(--warn)' }}>
            <ShoppingCart size={24} />
          </div>
          <div>
            <div style={{ fontSize: '0.8rem', color: 'var(--text-secondary)', textTransform: 'uppercase', letterSpacing: '0.5px' }}>Costo Medio Unità</div>
            <div style={{ fontSize: '1.6rem', fontWeight: 600, marginTop: '4px', fontFamily: 'var(--font-mono)', fontVariantNumeric: 'tabular-nums' }}>
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
            <div style={{ display: 'flex', gap: '6px', background: 'var(--bg-inset)', padding: '4px', borderRadius: 'var(--radius-md)', border: '1px solid var(--line)' }}>
              {[10, 50, 100, 250, 500].map(val => (
                <button
                  key={val}
                  onClick={() => setLimit(val)}
                  style={{
                    padding: '6px 12px', borderRadius: '6px', border: 'none',
                    background: limit === val ? 'var(--accent)' : 'transparent',
                    color: limit === val ? 'var(--text-on-accent)' : 'var(--text-secondary)',
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
            <div style={{ display: 'flex', gap: '6px', background: 'var(--bg-inset)', padding: '4px', borderRadius: 'var(--radius-md)', border: '1px solid var(--line)' }}>
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
                    background: sortBy === opt.key ? 'var(--accent)' : 'transparent',
                    color: sortBy === opt.key ? 'var(--text-on-accent)' : 'var(--text-secondary)',
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

        {/* Row 2: Date Range */}
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(200px, 1fr))', gap: '16px' }}>
          
          {/* Date range - Da */}
          <div style={{ display: 'flex', flexDirection: 'column', gap: '6px' }}>
            <label style={{ fontSize: '0.8rem', color: 'var(--text-secondary)', fontWeight: 600 }}><Calendar size={12} style={{ display: 'inline', marginRight: '4px' }} />Data Inizio</label>
            <input
              type="date"
              value={dataDa}
              onChange={e => setDataDa(e.target.value)}
              style={{
                padding: '9px 10px', background: 'var(--bg-inset)', border: '1px solid var(--line)',
                borderRadius: 'var(--radius-sm)', color: 'var(--text-primary)', outline: 'none', fontSize: '0.9rem', width: '100%', boxSizing: 'border-box'
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
                padding: '9px 10px', background: 'var(--bg-inset)', border: '1px solid var(--line)',
                borderRadius: 'var(--radius-sm)', color: 'var(--text-primary)', outline: 'none', fontSize: '0.9rem', width: '100%', boxSizing: 'border-box'
              }}
            />
          </div>

        </div>

        {/* Row 3: Supplier pills multi-select */}
        <div style={{ display: 'flex', flexDirection: 'column', gap: '8px', borderTop: '1px solid var(--border-glass)', paddingTop: '16px' }}>
          <span style={{ fontSize: '0.8rem', color: 'var(--text-secondary)', fontWeight: 600 }}>Filtra per Fornitore (Seleziona per includere):</span>
          <div style={{ display: 'flex', flexWrap: 'wrap', gap: '8px' }}>
            <button
              onClick={() => setSelectedSuppliers([])}
              style={{
                padding: '6px 12px', borderRadius: '999px', fontSize: '0.8rem', cursor: 'pointer',
                border: '1px solid ' + (selectedSuppliers.length === 0 ? 'var(--accent-border)' : 'transparent'),
                background: selectedSuppliers.length === 0 ? 'var(--accent-bg)' : 'var(--bg-inset)',
                color: selectedSuppliers.length === 0 ? 'var(--text-primary)' : 'var(--text-secondary)',
                fontWeight: 600, transition: 'all 0.2s'
              }}
            >
              Tutti i Fornitori
            </button>
            {suppliers.map(s => {
              const isSelected = selectedSuppliers.includes(s.id);
              return (
                <button
                  key={s.id}
                  onClick={() => handleSupplierToggle(s.id)}
                  style={{
                    padding: '6px 12px', borderRadius: '999px', fontSize: '0.8rem', cursor: 'pointer',
                    border: '1px solid ' + (isSelected ? 'var(--accent-border)' : 'transparent'),
                    background: isSelected ? 'var(--accent-bg)' : 'var(--bg-inset)',
                    color: isSelected ? 'var(--text-primary)' : 'var(--text-secondary)',
                    fontWeight: 500, transition: 'all 0.2s'
                  }}
                >
                  {s.nome_azienda}
                </button>
              );
            })}
          </div>
        </div>

        {/* Row 3: Location pills multi-select */}
        <div style={{ display: 'flex', flexDirection: 'column', gap: '8px', borderTop: '1px solid var(--border-glass)', paddingTop: '16px' }}>
          <span style={{ fontSize: '0.8rem', color: 'var(--text-secondary)', fontWeight: 600 }}>Filtra per Sede (Seleziona per includere):</span>
          <div style={{ display: 'flex', flexWrap: 'wrap', gap: '8px' }}>
            <button
              onClick={() => setSelectedLocations([])}
              style={{
                padding: '6px 12px', borderRadius: '999px', fontSize: '0.8rem', cursor: 'pointer',
                border: '1px solid ' + (selectedLocations.length === 0 ? 'var(--accent-border)' : 'transparent'),
                background: selectedLocations.length === 0 ? 'var(--accent-bg)' : 'var(--bg-inset)',
                color: selectedLocations.length === 0 ? 'var(--text-primary)' : 'var(--text-secondary)',
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
                    padding: '6px 12px', borderRadius: '999px', fontSize: '0.8rem', cursor: 'pointer',
                    border: '1px solid ' + (isSelected ? 'var(--accent-border)' : 'transparent'),
                    background: isSelected ? 'var(--accent-bg)' : 'var(--bg-inset)',
                    color: isSelected ? 'var(--text-primary)' : 'var(--text-secondary)',
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
        <div style={{ overflowX: 'auto', borderRadius: 'var(--radius-md)', border: '1px solid var(--line)' }}>
          <table className="ds-table" style={{ width: '100%', borderCollapse: 'collapse' }}>
            <thead>
              <tr style={{ background: 'var(--bg-inset)', color: 'var(--text-secondary)', fontSize: '0.8rem', textAlign: 'left' }}>
                <th style={{ padding: '16px 12px', textAlign: 'center', width: '60px', borderBottom: '1px solid var(--line)' }}>Pos.</th>
                <th style={{ padding: '16px 12px', width: '120px', borderBottom: '1px solid var(--line)' }}>SKU Interno</th>
                <th style={{ padding: '16px 12px', borderBottom: '1px solid var(--line)' }}>Descrizione Prodotto</th>
                <th style={{ padding: '16px 12px', textAlign: 'center', width: '80px', borderBottom: '1px solid var(--line)' }}>U.M.</th>
                <th style={{ padding: '16px 12px', textAlign: 'right', width: '130px', borderBottom: '1px solid var(--line)' }}>Quantità Totale</th>
                <th style={{ padding: '16px 12px', textAlign: 'right', width: '110px', borderBottom: '1px solid var(--line)' }}>N. Acquisti</th>
                <th style={{ padding: '16px 12px', textAlign: 'right', width: '140px', color: 'var(--text-primary)', fontWeight: 600, borderBottom: '1px solid var(--line)' }}>Prezzo Medio</th>
                <th style={{ padding: '16px 12px', textAlign: 'right', width: '140px', borderBottom: '1px solid var(--line)' }}>Spesa Totale</th>
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
                        borderBottom: '1px solid var(--line)',
                        transition: 'background 0.2s',
                        cursor: 'default'
                      }}
                      onMouseEnter={e => e.currentTarget.style.background = 'var(--bg-elevated)'}
                      onMouseLeave={e => e.currentTarget.style.background = 'transparent'}
                    >
                      <td style={{ padding: '12px 10px', textAlign: 'center', fontWeight: 600, color: 'var(--text-primary)', fontFamily: 'var(--font-mono)', fontVariantNumeric: 'tabular-nums' }}>
                        {rankDisplay}
                      </td>
                      <td style={{ padding: '12px 10px' }}>
                        <span style={{ background: 'var(--accent-bg)', color: 'var(--accent-text)', padding: '4px 8px', borderRadius: 'var(--radius-sm)', fontSize: '0.85rem', fontWeight: 600, fontFamily: 'var(--font-mono)' }}>
                          {p.sku_interno}
                        </span>
                      </td>
                      <td style={{ padding: '12px 10px', fontWeight: 500, color: 'var(--text-primary)' }}>
                        {p.descrizione || 'N/A'}
                      </td>
                      <td style={{ padding: '12px 10px', textAlign: 'center', color: 'var(--text-secondary)', fontSize: '0.85rem' }}>
                        {p.unita_misura}
                      </td>
                      <td style={{ padding: '12px 10px', textAlign: 'right', fontWeight: 500, fontFamily: 'var(--font-mono)', fontVariantNumeric: 'tabular-nums' }}>
                        {p.quantita_totale.toLocaleString('it-IT', { minimumFractionDigits: 1, maximumFractionDigits: 1 })}
                      </td>
                      <td style={{ padding: '12px 10px', textAlign: 'right', color: 'var(--text-secondary)', fontFamily: 'var(--font-mono)', fontVariantNumeric: 'tabular-nums' }}>
                        {p.numero_acquisti}
                      </td>
                      <td style={{ padding: '12px 10px', textAlign: 'right', fontWeight: 700, color: 'var(--ok)', fontFamily: 'var(--font-mono)', fontVariantNumeric: 'tabular-nums' }}>
                        € {p.prezzo_medio.toLocaleString('it-IT', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}
                      </td>
                      <td style={{ padding: '12px 10px', textAlign: 'right', color: 'var(--text-primary)', fontWeight: 500, fontFamily: 'var(--font-mono)', fontVariantNumeric: 'tabular-nums' }}>
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
