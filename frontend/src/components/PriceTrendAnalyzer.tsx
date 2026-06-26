import { useState, useEffect, useRef } from 'react'
import { Search, X, Calendar, Download, ArrowUpDown, Info, TrendingUp } from 'lucide-react'
import { fetchWithAuth } from '../api'

interface ProductSku {
  sku_interno: string
  nome_prodotto: string
  total_acquisti: number
}

interface SelectedProduct {
  sku: string
  label: string
  color: string
}

interface HistoryPoint {
  data: string
  prezzo_pagato: number
  quantita: number
  fornitore: string
  location: string
  prezzo_contratto: number | null
}

interface SkuTrend {
  sku_interno: string
  prodotto_nome: string
  prezzo_contratto_corrente: number | null
  history: HistoryPoint[]
}

interface TrendDataMap {
  [sku: string]: SkuTrend
}

interface Supplier {
  id: number
  nome_azienda: string
}

interface LocationItem {
  id: number
  nome_struttura: string
  piva_riferimento: string
}

// Preset list of distinct colors for multi-series charting
const CHART_COLORS = [
  '#3b82f6', // Bright Blue
  '#10b981', // Emerald Green
  '#f59e0b', // Amber/Yellow
  '#ef4444', // Red/Crimson
  '#a855f7', // Purple
  '#ec4899', // Pink
]

export default function PriceTrendAnalyzer() {
  const [allProducts, setAllProducts] = useState<ProductSku[]>([])
  const [selectedProducts, setSelectedProducts] = useState<SelectedProduct[]>([])
  const [searchQuery, setSearchQuery] = useState('')
  const [showSuggestions, setShowSuggestions] = useState(false)
  
  // Filters
  const [suppliers, setSuppliers] = useState<Supplier[]>([])
  const [locations, setLocations] = useState<LocationItem[]>([])
  const [selectedSupplier, setSelectedSupplier] = useState('')
  const [selectedLocation, setSelectedLocation] = useState('')
  const [startDate, setStartDate] = useState('')
  const [endDate, setEndDate] = useState('')

  // Loaded Trend Data
  const [trendData, setTrendData] = useState<TrendDataMap>({})
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  // Hover chart tracking state
  const [hoverData, setHoverData] = useState<{
    dateStr: string
    x: number
    y: number
    points: {
      sku: string
      label: string
      color: string
      price: number
      contractPrice: number | null
      supplier: string
      location: string
    }[]
  } | null>(null)

  // Table sorting & search state
  const [tableSearch, setTableSearch] = useState('')
  const [sortField, setSortField] = useState<string>('data')
  const [sortDirection, setSortDirection] = useState<'asc' | 'desc'>('desc')

  const containerRef = useRef<HTMLDivElement>(null)

  // 1. Initial Load: SKUs, Suppliers, Locations (Fetches in parallel to prevent cascading failures)
  useEffect(() => {
    // Load SKUs (Requires trailing slash in FastAPI router)
    fetchWithAuth('/sku/')
      .then(data => {
        setAllProducts(data)
      })
      .catch(err => {
        console.error('Error loading SKUs:', err)
      })

    // Load Suppliers
    fetchWithAuth('/fornitori/')
      .then(data => {
        setSuppliers(data)
      })
      .catch(err => {
        console.error('Error loading Suppliers:', err)
      })

    // Load Locations
    fetchWithAuth('/location/')
      .then(data => {
        setLocations(data)
      })
      .catch(err => {
        console.error('Error loading Locations:', err)
      })
  }, [])

  // 2. Fetch Trend Data whenever products or filters change
  useEffect(() => {
    if (selectedProducts.length === 0) {
      setTrendData({})
      setHoverData(null)
      return
    }

    async function fetchTrends() {
      setLoading(true)
      setError(null)
      
      const skusParam = selectedProducts.map(p => p.sku).join(',')
      let url = `/intelligence/price-trends?skus=${encodeURIComponent(skusParam)}`
      
      if (startDate) url += `&start_date=${encodeURIComponent(startDate)}`
      if (endDate) url += `&end_date=${encodeURIComponent(endDate)}`
      if (selectedSupplier) url += `&fornitore_ids=${encodeURIComponent(selectedSupplier)}`
      if (selectedLocation) url += `&location_ids=${encodeURIComponent(selectedLocation)}`

      try {
        const data = await fetchWithAuth(url)
        setTrendData(data)
      } catch (err: any) {
        setError(err.message || 'Errore di connessione.')
      } finally {
        setLoading(false)
      }
    }

    const timer = setTimeout(() => {
      fetchTrends()
    }, 300) // Debounce requests slightly

    return () => clearTimeout(timer)
  }, [selectedProducts, startDate, endDate, selectedSupplier, selectedLocation])

  // Click handler to close suggestions list
  useEffect(() => {
    function handleClickOutside(e: MouseEvent) {
      if (containerRef.current && !containerRef.current.contains(e.target as Node)) {
        setShowSuggestions(false)
      }
    }
    document.addEventListener('mousedown', handleClickOutside)
    return () => document.removeEventListener('mousedown', handleClickOutside)
  }, [])

  // 3. Product Selection Handlers
  const handleAddProduct = (product: ProductSku) => {
    if (selectedProducts.some(p => p.sku === product.sku_interno)) {
      setSearchQuery('')
      setShowSuggestions(false)
      return
    }

    // Assign the next available color from preset colors
    const color = CHART_COLORS[selectedProducts.length % CHART_COLORS.length]
    const label = product.nome_prodotto || product.sku_interno

    setSelectedProducts([...selectedProducts, { sku: product.sku_interno, label, color }])
    setSearchQuery('')
    setShowSuggestions(false)
  }

  const handleRemoveProduct = (sku: string) => {
    const updated = selectedProducts.filter(p => p.sku !== sku)
    // Re-assign colors to maintain consistent cycle
    const colorCorrected = updated.map((p, index) => ({
      ...p,
      color: CHART_COLORS[index % CHART_COLORS.length]
    }))
    setSelectedProducts(colorCorrected)
    setHoverData(null)
  }

  // Filter suggestions based on input query
  const suggestions = searchQuery.trim() === ''
    ? []
    : allProducts.filter(p =>
        p.sku_interno.toLowerCase().includes(searchQuery.toLowerCase()) ||
        (p.nome_prodotto && p.nome_prodotto.toLowerCase().includes(searchQuery.toLowerCase()))
      ).slice(0, 8)

  // 4. Custom SVG Chart Mathematics & Rendering
  const renderChart = () => {
    // Collect all valid points from loaded trend data
    const allSeriesPoints: { sku: string; timestamp: number; price: number; point: HistoryPoint; color: string; label: string }[] = []
    
    selectedProducts.forEach(p => {
      const data = trendData[p.sku]
      if (data && data.history) {
        data.history.forEach(h => {
          const timestamp = new Date(h.data).getTime()
          allSeriesPoints.push({
            sku: p.sku,
            timestamp,
            price: h.prezzo_pagato,
            point: h,
            color: p.color,
            label: p.label
          })
        })
      }
    })

    if (allSeriesPoints.length === 0) {
      return (
        <div style={{
          height: '300px',
          display: 'flex',
          flexDirection: 'column',
          alignItems: 'center',
          justifyContent: 'center',
          color: 'var(--text-secondary)',
          background: 'rgba(255,255,255,0.01)',
          borderRadius: '12px',
          border: '1px dashed var(--border-glass)'
        }}>
          <TrendingUp size={40} style={{ marginBottom: '12px', opacity: 0.4 }} />
          <span>Nessun dato storico di acquisto trovato per i filtri selezionati.</span>
        </div>
      )
    }

    // Determine Global Min/Max bounds for scaling
    const timestamps = allSeriesPoints.map(pt => pt.timestamp)
    const prices = allSeriesPoints.map(pt => pt.price)
    
    // Also include contract prices in the Y boundary check to prevent clipping of contract guide lines
    selectedProducts.forEach(p => {
      const data = trendData[p.sku]
      if (data && data.prezzo_contratto_corrente) {
        prices.push(data.prezzo_contratto_corrente)
      }
    })

    let minDate = Math.min(...timestamps)
    let maxDate = Math.max(...timestamps)
    let minPrice = Math.min(...prices)
    let maxPrice = Math.max(...prices)

    // Edge cases pads
    if (minDate === maxDate) {
      minDate -= 24 * 60 * 60 * 1000 // Sub 1 day
      maxDate += 24 * 60 * 60 * 1000 // Add 1 day
    }
    if (minPrice === maxPrice) {
      minPrice = Math.max(0, minPrice - 1)
      maxPrice += 1
    } else {
      // Add a small percentage pad to top and bottom of Y axis for aesthetics
      const delta = maxPrice - minPrice
      minPrice = Math.max(0, minPrice - delta * 0.08)
      maxPrice += delta * 0.08
    }

    // SVG Layout definitions
    const svgWidth = 850
    const svgHeight = 350
    const paddingX = 65
    const paddingY = 40
    const chartWidth = svgWidth - paddingX * 2
    const chartHeight = svgHeight - paddingY * 2

    // Coordinate conversion utilities
    const getX = (ts: number) => paddingX + ((ts - minDate) / (maxDate - minDate)) * chartWidth
    const getY = (pr: number) => paddingY + (1 - (pr - minPrice) / (maxPrice - minPrice)) * chartHeight

    // Generate Y-axis grid values
    const yGridLinesCount = 5
    const yGridValues: number[] = []
    for (let i = 0; i < yGridLinesCount; i++) {
      yGridValues.push(minPrice + (i / (yGridLinesCount - 1)) * (maxPrice - minPrice))
    }

    // Generate X-axis grid values (Time ticks)
    const xGridLinesCount = 4
    const xGridValues: number[] = []
    for (let i = 0; i < xGridLinesCount; i++) {
      xGridValues.push(minDate + (i / (xGridLinesCount - 1)) * (maxDate - minDate))
    }

    // Mouse interactive tracker event handlers
    const handleMouseMove = (e: React.MouseEvent<SVGSVGElement, MouseEvent>) => {
      const svg = e.currentTarget
      const rect = svg.getBoundingClientRect()
      const mouseX = ((e.clientX - rect.left) / rect.width) * svgWidth
      const mouseY = ((e.clientY - rect.top) / rect.height) * svgHeight

      if (mouseX < paddingX || mouseX > svgWidth - paddingX) {
        setHoverData(null)
        return
      }

      // Map mouseX back to timestamp
      const hoverTimestamp = minDate + ((mouseX - paddingX) / chartWidth) * (maxDate - minDate)

      // Find the closest overall transaction date in the data
      let closestTimestamp = timestamps[0]
      let minDiff = Math.abs(hoverTimestamp - closestTimestamp)

      timestamps.forEach(ts => {
        const diff = Math.abs(hoverTimestamp - ts)
        if (diff < minDiff) {
          minDiff = diff
          closestTimestamp = ts
        }
      })

      const closestDateStr = new Date(closestTimestamp).toISOString().split('T')[0]

      // Extract details for all selected products on this closest date
      const hoveredPoints: any[] = []
      selectedProducts.forEach(p => {
        const data = trendData[p.sku]
        if (data && data.history) {
          // Find the transaction closest to this date for this SKU, or on this exact date
          const skuPointsOnDate = data.history.filter(h => h.data === closestDateStr)
          if (skuPointsOnDate.length > 0) {
            skuPointsOnDate.forEach(sp => {
              hoveredPoints.push({
                sku: p.sku,
                label: p.label,
                color: p.color,
                price: sp.prezzo_pagato,
                contractPrice: data.prezzo_contratto_corrente,
                supplier: sp.fornitore,
                location: sp.location
              })
            })
          }
        }
      })

      if (hoveredPoints.length > 0) {
        setHoverData({
          dateStr: closestDateStr,
          x: getX(closestTimestamp),
          y: mouseY,
          points: hoveredPoints
        })
      } else {
        setHoverData(null)
      }
    }

    const handleMouseLeave = () => {
      setHoverData(null)
    }

    const formatDateStr = (isoString: string) => {
      const d = new Date(isoString)
      return d.toLocaleDateString('it-IT', { day: '2-digit', month: '2-digit', year: 'numeric' })
    }

    return (
      <div style={{ position: 'relative' }}>
        <svg
          viewBox={`0 0 ${svgWidth} ${svgHeight}`}
          width="100%"
          onMouseMove={handleMouseMove}
          onMouseLeave={handleMouseLeave}
          style={{
            background: 'var(--bg-secondary)',
            borderRadius: 'var(--border-radius-lg)',
            border: '1px solid var(--border-glass)',
            overflow: 'visible',
            cursor: 'crosshair',
            boxShadow: 'inset 0 0 20px rgba(0,0,0,0.3)'
          }}
        >
          {/* Horizontal Grid lines */}
          {yGridValues.map((val, idx) => {
            const yCoord = getY(val)
            return (
              <g key={`y-grid-${idx}`}>
                <line
                  x1={paddingX}
                  y1={yCoord}
                  x2={svgWidth - paddingX}
                  y2={yCoord}
                  stroke="var(--border-glass)"
                  strokeWidth="1"
                  strokeDasharray="4 4"
                />
                <text
                  x={paddingX - 10}
                  y={yCoord + 4}
                  textAnchor="end"
                  fill="var(--text-secondary)"
                  style={{ fontSize: '10px', fontFamily: 'inherit' }}
                >
                  {val.toFixed(2)} €
                </text>
              </g>
            )
          })}

          {/* Vertical Grid lines */}
          {xGridValues.map((val, idx) => {
            const xCoord = getX(val)
            return (
              <g key={`x-grid-${idx}`}>
                <line
                  x1={xCoord}
                  y1={paddingY}
                  x2={xCoord}
                  y2={svgHeight - paddingY}
                  stroke="var(--border-glass)"
                  strokeWidth="1"
                  strokeDasharray="4 4"
                />
                <text
                  x={xCoord}
                  y={svgHeight - paddingY + 18}
                  textAnchor="middle"
                  fill="var(--text-secondary)"
                  style={{ fontSize: '10px', fontFamily: 'inherit' }}
                >
                  {new Date(val).toLocaleDateString('it-IT', { month: 'short', year: '2-digit' })}
                </text>
              </g>
            )
          })}

          {/* Active Contract Benchmark Lines (Dashed, in SKU color) */}
          {selectedProducts.map(p => {
            const data = trendData[p.sku]
            if (data && data.prezzo_contratto_corrente !== null) {
              const contractY = getY(data.prezzo_contratto_corrente)
              if (contractY >= paddingY && contractY <= svgHeight - paddingY) {
                return (
                  <g key={`contract-guide-${p.sku}`}>
                    <line
                      x1={paddingX}
                      y1={contractY}
                      x2={svgWidth - paddingX}
                      y2={contractY}
                      stroke={p.color}
                      strokeWidth="1.2"
                      strokeDasharray="5 5"
                      opacity="0.45"
                    />
                    <text
                      x={svgWidth - paddingX - 4}
                      y={contractY - 4}
                      textAnchor="end"
                      fill={p.color}
                      opacity="0.8"
                      style={{ fontSize: '8.5px', fontWeight: 500 }}
                    >
                      Listino {p.sku}: {data.prezzo_contratto_corrente.toFixed(2)} €
                    </text>
                  </g>
                )
              }
            }
            return null
          })}

          {/* Price Trend Lines & Nodes */}
          {selectedProducts.map(p => {
            const data = trendData[p.sku]
            if (!data || !data.history || data.history.length === 0) return null

            // Map and sort historical coordinates chronologically
            const pts = data.history
              .map(h => ({
                x: getX(new Date(h.data).getTime()),
                y: getY(h.prezzo_pagato),
                price: h.prezzo_pagato,
                raw: h
              }))
              .sort((a, b) => a.x - b.x)

            // Build path string
            const pathD = pts.map((pt, i) => `${i === 0 ? 'M' : 'L'} ${pt.x} ${pt.y}`).join(' ')

            return (
              <g key={`trend-series-${p.sku}`}>
                {/* Neon Glow underlay line */}
                <path
                  d={pathD}
                  fill="none"
                  stroke={p.color}
                  strokeWidth="6"
                  opacity="0.15"
                  strokeLinecap="round"
                  strokeLinejoin="round"
                />
                {/* Main solid line */}
                <path
                  d={pathD}
                  fill="none"
                  stroke={p.color}
                  strokeWidth="2.5"
                  strokeLinecap="round"
                  strokeLinejoin="round"
                />
                {/* Interactive circles */}
                {pts.map((pt, index) => (
                  <circle
                    key={`dot-${p.sku}-${index}`}
                    cx={pt.x}
                    cy={pt.y}
                    r="4"
                    fill={p.color}
                    stroke="var(--bg-secondary)"
                    strokeWidth="1.5"
                    style={{ transition: 'r 0.15s ease' }}
                  />
                ))}
              </g>
            )
          })}

          {/* Active Hover vertical guide and highlighted circles */}
          {hoverData && (
            <g pointerEvents="none">
              {/* Vertical line tracker */}
              <line
                x1={hoverData.x}
                y1={paddingY}
                x2={hoverData.x}
                y2={svgHeight - paddingY}
                stroke="rgba(255, 255, 255, 0.3)"
                strokeWidth="1"
                strokeDasharray="3 3"
              />
              {/* Pulsing circles on intersection points */}
              {hoverData.points.map((pt, idx) => {
                const ptY = getY(pt.price)
                return (
                  <g key={`hover-pulse-${idx}`}>
                    <circle
                      cx={hoverData.x}
                      cy={ptY}
                      r="8"
                      fill={pt.color}
                      opacity="0.3"
                    />
                    <circle
                      cx={hoverData.x}
                      cy={ptY}
                      r="4.5"
                      fill={pt.color}
                      stroke="white"
                      strokeWidth="1.5"
                    />
                  </g>
                )
              })}
            </g>
          )}
        </svg>

        {/* Floating Custom HTML Tooltip (Glassmorphism) */}
        {hoverData && (
          <div
            className="glass-panel"
            style={{
              position: 'absolute',
              top: '20px',
              left: hoverData.x > svgWidth / 2 ? '30px' : 'auto',
              right: hoverData.x > svgWidth / 2 ? 'auto' : '30px',
              width: '300px',
              padding: '16px',
              borderRadius: 'var(--border-radius-md)',
              border: '1px solid rgba(255,255,255,0.1)',
              boxShadow: '0 12px 24px rgba(0,0,0,0.6)',
              zIndex: 10,
              pointerEvents: 'none',
              transition: 'all 0.1s ease-out'
            }}
          >
            <div style={{
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'space-between',
              marginBottom: '12px',
              borderBottom: '1px solid rgba(255,255,255,0.08)',
              paddingBottom: '6px'
            }}>
              <span style={{ fontSize: '0.75rem', color: 'var(--text-secondary)', fontWeight: 500 }}>
                Data Rilevazione
              </span>
              <span style={{ fontSize: '0.85rem', fontWeight: 600, color: 'white', display: 'flex', alignItems: 'center', gap: '4px' }}>
                <Calendar size={12} /> {formatDateStr(hoverData.dateStr)}
              </span>
            </div>
            <div style={{ display: 'flex', flexDirection: 'column', gap: '12px' }}>
              {hoverData.points.map((pt, idx) => {
                const deltaStr = pt.contractPrice
                  ? (((pt.price - pt.contractPrice) / pt.contractPrice) * 100).toFixed(1)
                  : null

                return (
                  <div key={`tooltip-pt-${idx}`} style={{ display: 'flex', flexDirection: 'column', gap: '3px' }}>
                    <div style={{ display: 'flex', alignItems: 'center', gap: '6px' }}>
                      <span style={{ width: '8px', height: '8px', borderRadius: '50%', backgroundColor: pt.color, display: 'inline-block' }}></span>
                      <span style={{ fontSize: '0.8rem', fontWeight: 600, color: '#fff', whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis', maxWidth: '240px' }}>
                        {pt.label}
                      </span>
                    </div>
                    <div style={{ paddingLeft: '14px', display: 'flex', flexDirection: 'column', gap: '1px' }}>
                      <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: '0.75rem' }}>
                        <span style={{ color: 'var(--text-secondary)' }}>Prezzo Pagato:</span>
                        <span style={{ fontWeight: 600, color: '#fff' }}>{pt.price.toFixed(2)} €</span>
                      </div>
                      {pt.contractPrice !== null && (
                        <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: '0.75rem' }}>
                          <span style={{ color: 'var(--text-secondary)' }}>Prezzo Contratto:</span>
                          <span style={{ color: 'var(--text-secondary)' }}>
                            {pt.contractPrice.toFixed(2)} € 
                            {deltaStr && (
                              <span style={{
                                marginLeft: '6px',
                                color: parseFloat(deltaStr) > 0 ? 'var(--status-red)' : 'var(--status-green)',
                                fontWeight: 600
                              }}>
                                {parseFloat(deltaStr) > 0 ? `+${deltaStr}%` : `${deltaStr}%`}
                              </span>
                            )}
                          </span>
                        </div>
                      )}
                      <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: '0.7rem', opacity: 0.7 }}>
                        <span style={{ color: 'var(--text-secondary)' }}>Fornitore:</span>
                        <span style={{ color: '#fff' }}>{pt.supplier}</span>
                      </div>
                      <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: '0.7rem', opacity: 0.7 }}>
                        <span style={{ color: 'var(--text-secondary)' }}>Sede:</span>
                        <span style={{ color: '#fff' }}>{pt.location}</span>
                      </div>
                    </div>
                  </div>
                )
              })}
            </div>
          </div>
        )}
      </div>
    )
  }

  // 5. Raw Transactions Table Construction
  const getTableData = () => {
    const rows: {
      sku: string
      label: string
      color: string
      data: string
      prezzo_pagato: number
      quantita: number
      fornitore: string
      location: string
      prezzo_contratto: number | null
    }[] = []

    selectedProducts.forEach(p => {
      const data = trendData[p.sku]
      if (data && data.history) {
        data.history.forEach(h => {
          rows.push({
            sku: p.sku,
            label: p.label,
            color: p.color,
            data: h.data,
            prezzo_pagato: h.prezzo_pagato,
            quantita: h.quantita,
            fornitore: h.fornitore,
            location: h.location,
            prezzo_contratto: h.prezzo_contratto
          })
        })
      }
    })

    // Filter by text search
    let filtered = rows
    if (tableSearch.trim() !== '') {
      const q = tableSearch.toLowerCase()
      filtered = rows.filter(r =>
        r.sku.toLowerCase().includes(q) ||
        r.label.toLowerCase().includes(q) ||
        r.fornitore.toLowerCase().includes(q) ||
        r.location.toLowerCase().includes(q)
      )
    }

    // Sort rows
    filtered.sort((a, b) => {
      let valA: any = a[sortField as keyof typeof a]
      let valB: any = b[sortField as keyof typeof b]

      if (sortField === 'delta') {
        const deltaA = a.prezzo_contratto ? (a.prezzo_pagato - a.prezzo_contratto) / a.prezzo_contratto : -9999
        const deltaB = b.prezzo_contratto ? (b.prezzo_pagato - b.prezzo_contratto) / b.prezzo_contratto : -9999
        valA = deltaA
        valB = deltaB
      }

      if (valA === null || valA === undefined) return 1
      if (valB === null || valB === undefined) return -1

      if (typeof valA === 'string') {
        return sortDirection === 'asc'
          ? valA.localeCompare(valB)
          : valB.localeCompare(valA)
      } else {
        return sortDirection === 'asc'
          ? (valA as number) - (valB as number)
          : (valB as number) - (valA as number)
      }
    })

    return filtered
  }

  const handleSort = (field: string) => {
    if (sortField === field) {
      setSortDirection(sortDirection === 'asc' ? 'desc' : 'asc')
    } else {
      setSortField(field)
      setSortDirection('desc')
    }
  }

  // 6. Export Table Data to CSV
  const handleExportCSV = () => {
    const rows = getTableData()
    if (rows.length === 0) return

    const headersList = ['Data', 'SKU', 'Prodotto', 'Fornitore', 'Sede', 'Quantita', 'Prezzo Pagato (€)', 'Prezzo Contratto (€)', 'Delta (%)']
    const csvRows = [headersList.join(';')]

    rows.forEach(r => {
      const delta = r.prezzo_contratto ? (((r.prezzo_pagato - r.prezzo_contratto) / r.prezzo_contratto) * 100).toFixed(2) : ''
      const rowData = [
        r.data,
        r.sku,
        `"${r.label.replace(/"/g, '""')}"`,
        `"${r.fornitore.replace(/"/g, '""')}"`,
        `"${r.location.replace(/"/g, '""')}"`,
        r.quantita,
        r.prezzo_pagato.toFixed(4),
        r.prezzo_contratto ? r.prezzo_contratto.toFixed(4) : '',
        delta
      ]
      csvRows.push(rowData.join(';'))
    })

    const csvContent = 'data:text/csv;charset=utf-8,\uFEFF' + encodeURIComponent(csvRows.join('\n'))
    const link = document.createElement('a')
    link.setAttribute('href', csvContent)
    link.setAttribute('download', `prezzi_sentinel_oscillazioni_${new Date().toISOString().split('T')[0]}.csv`)
    document.body.appendChild(link)
    link.click()
    document.body.removeChild(link)
  }

  const tableRows = getTableData()

  return (
    <div ref={containerRef} style={{ display: 'flex', flexDirection: 'column', gap: '24px' }}>
      
      {/* 1. Filter Grid Controls */}
      <div className="glass-panel" style={{ padding: '20px', display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(200px, 1fr))', gap: '16px' }}>
        <div style={{ display: 'flex', flexDirection: 'column', gap: '6px' }}>
          <label style={{ fontSize: '0.8rem', color: 'var(--text-secondary)', fontWeight: 500 }}>Fornitore</label>
          <select
            value={selectedSupplier}
            onChange={e => setSelectedSupplier(e.target.value)}
            style={{
              background: 'rgba(255,255,255,0.03)',
              border: '1px solid var(--border-glass)',
              borderRadius: '8px',
              padding: '10px 12px',
              color: 'white',
              outline: 'none',
              fontFamily: 'inherit',
              cursor: 'pointer'
            }}
          >
            <option value="" style={{ background: 'var(--bg-secondary)', color: 'white' }}>Tutti i fornitori</option>
            {suppliers.map(s => (
              <option key={s.id} value={s.id} style={{ background: 'var(--bg-secondary)', color: 'white' }}>
                {s.nome_azienda}
              </option>
            ))}
          </select>
        </div>

        <div style={{ display: 'flex', flexDirection: 'column', gap: '6px' }}>
          <label style={{ fontSize: '0.8rem', color: 'var(--text-secondary)', fontWeight: 500 }}>Sede (Location)</label>
          <select
            value={selectedLocation}
            onChange={e => setSelectedLocation(e.target.value)}
            style={{
              background: 'rgba(255,255,255,0.03)',
              border: '1px solid var(--border-glass)',
              borderRadius: '8px',
              padding: '10px 12px',
              color: 'white',
              outline: 'none',
              fontFamily: 'inherit',
              cursor: 'pointer'
            }}
          >
            <option value="" style={{ background: 'var(--bg-secondary)', color: 'white' }}>Tutte le sedi</option>
            {locations.map(l => (
              <option key={l.id} value={l.id} style={{ background: 'var(--bg-secondary)', color: 'white' }}>
                {l.nome_struttura}
              </option>
            ))}
          </select>
        </div>

        <div style={{ display: 'flex', flexDirection: 'column', gap: '6px' }}>
          <label style={{ fontSize: '0.8rem', color: 'var(--text-secondary)', fontWeight: 500 }}>Dal</label>
          <input
            type="date"
            value={startDate}
            onChange={e => setStartDate(e.target.value)}
            style={{
              background: 'rgba(255,255,255,0.03)',
              border: '1px solid var(--border-glass)',
              borderRadius: '8px',
              padding: '9px 12px',
              color: 'white',
              outline: 'none',
              fontFamily: 'inherit'
            }}
          />
        </div>

        <div style={{ display: 'flex', flexDirection: 'column', gap: '6px' }}>
          <label style={{ fontSize: '0.8rem', color: 'var(--text-secondary)', fontWeight: 500 }}>Al</label>
          <input
            type="date"
            value={endDate}
            onChange={e => setEndDate(e.target.value)}
            style={{
              background: 'rgba(255,255,255,0.03)',
              border: '1px solid var(--border-glass)',
              borderRadius: '8px',
              padding: '9px 12px',
              color: 'white',
              outline: 'none',
              fontFamily: 'inherit'
            }}
          />
        </div>
      </div>

      {/* 2. Product Search & Tags Section */}
      <div className="glass-panel" style={{ padding: '24px', display: 'flex', flexDirection: 'column', gap: '16px' }}>
        <h3 style={{ fontSize: '1.1rem', fontWeight: 600, display: 'flex', alignItems: 'center', gap: '8px' }}>
          <Search size={18} color="var(--accent-blue)" /> Seleziona Prodotti da Confrontare
        </h3>
        
        {/* Search Input Box */}
        <div style={{ position: 'relative', width: '100%' }}>
          <input
            type="text"
            placeholder="Cerca per SKU o descrizione prodotto..."
            value={searchQuery}
            onChange={e => { setSearchQuery(e.target.value); setShowSuggestions(true); }}
            onFocus={() => setShowSuggestions(true)}
            style={{
              width: '100%',
              background: 'rgba(255,255,255,0.02)',
              border: '1px solid var(--border-glass)',
              borderRadius: '10px',
              padding: '14px 16px',
              color: 'white',
              outline: 'none',
              fontSize: '0.95rem',
              transition: 'var(--transition-smooth)'
            }}
          />
          
          {/* Autocomplete Dropdown suggestions list */}
          {showSuggestions && suggestions.length > 0 && (
            <div className="glass-panel" style={{
              position: 'absolute',
              top: 'calc(100% + 8px)',
              left: 0,
              width: '100%',
              maxHeight: '300px',
              overflowY: 'auto',
              zIndex: 100,
              padding: '8px 0',
              boxShadow: '0 15px 30px rgba(0,0,0,0.5)',
              border: '1px solid rgba(255,255,255,0.08)'
            }}>
              {suggestions.map((p, idx) => (
                <div
                  key={`sug-${idx}`}
                  onClick={() => handleAddProduct(p)}
                  style={{
                    padding: '12px 20px',
                    cursor: 'pointer',
                    display: 'flex',
                    justifyContent: 'space-between',
                    alignItems: 'center',
                    transition: 'var(--transition-smooth)'
                  }}
                  className="suggestion-item"
                >
                  <div style={{ display: 'flex', flexDirection: 'column', gap: '2px' }}>
                    <span style={{ fontWeight: 600, fontSize: '0.9rem', color: 'white' }}>
                      {p.nome_prodotto || p.sku_interno}
                    </span>
                    <span style={{ fontSize: '0.75rem', color: 'var(--text-secondary)' }}>
                      SKU: {p.sku_interno}
                    </span>
                  </div>
                  <span className="badge badge-green" style={{ fontSize: '0.7rem' }}>
                    {p.total_acquisti} acquisti
                  </span>
                </div>
              ))}
            </div>
          )}
        </div>

        {/* Selected Product Color-Coded Pills */}
        {selectedProducts.length > 0 ? (
          <div style={{ display: 'flex', flexWrap: 'wrap', gap: '10px', marginTop: '4px' }}>
            {selectedProducts.map(p => (
              <div
                key={`tag-${p.sku}`}
                style={{
                  display: 'inline-flex',
                  alignItems: 'center',
                  gap: '8px',
                  background: 'rgba(255,255,255,0.03)',
                  border: `1px solid ${p.color}`,
                  borderRadius: '999px',
                  padding: '6px 14px',
                  fontSize: '0.85rem',
                  color: 'white',
                  boxShadow: `0 0 10px rgba(${p.color === '#3b82f6' ? '59,130,246' : p.color === '#10b981' ? '16,185,129' : p.color === '#f59e0b' ? '245,158,11' : '239,68,68'}, 0.15)`
                }}
              >
                <span style={{ width: '8px', height: '8px', borderRadius: '50%', backgroundColor: p.color }}></span>
                <span style={{ fontWeight: 500 }}>{p.label}</span>
                <button
                  onClick={() => handleRemoveProduct(p.sku)}
                  style={{
                    background: 'transparent',
                    border: 'none',
                    color: 'var(--text-secondary)',
                    cursor: 'pointer',
                    display: 'flex',
                    alignItems: 'center',
                    justifyContent: 'center',
                    padding: 0,
                    borderRadius: '50%'
                  }}
                  onMouseEnter={e => e.currentTarget.style.color = '#fff'}
                  onMouseLeave={e => e.currentTarget.style.color = 'var(--text-secondary)'}
                >
                  <X size={14} />
                </button>
              </div>
            ))}
          </div>
        ) : (
          <div style={{ display: 'flex', alignItems: 'center', gap: '8px', color: 'var(--text-secondary)', fontSize: '0.85rem', marginTop: '4px' }}>
            <Info size={14} />
            <span>Nessun prodotto selezionato. Cerca sopra per iniziare il confronto grafico.</span>
          </div>
        )}
      </div>

      {/* 3. Visualization Panel: Chart */}
      <div className="glass-panel" style={{ padding: '24px', display: 'flex', flexDirection: 'column', gap: '16px' }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
          <h3 style={{ fontSize: '1.2rem', fontWeight: 600 }}>Grafico Oscillazione Prezzi</h3>
          {selectedProducts.length > 0 && (
            <div style={{ fontSize: '0.8rem', color: 'var(--text-secondary)', display: 'flex', alignItems: 'center', gap: '6px' }}>
              <Info size={14} /> Passa il mouse sul grafico per i dettagli
            </div>
          )}
        </div>

        {error && (
          <div style={{
            padding: '12px 16px',
            borderRadius: '8px',
            background: 'var(--status-red-bg)',
            color: 'var(--status-red)',
            border: '1px solid rgba(239,68,68,0.2)',
            fontSize: '0.9rem'
          }}>
            {error}
          </div>
        )}

        {loading ? (
          <div style={{
            height: '300px',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            color: 'var(--text-secondary)'
          }}>
            <div className="spinner" style={{ marginRight: '10px' }}></div>
            Caricamento dati storici in corso...
          </div>
        ) : (
          renderChart()
        )}
      </div>

      {/* 4. Transactions Data Table */}
      {selectedProducts.length > 0 && !loading && (
        <div className="glass-panel" style={{ padding: '24px', display: 'flex', flexDirection: 'column', gap: '16px' }}>
          
          {/* Table Toolbar controls */}
          <div style={{ display: 'flex', flexWrap: 'wrap', justifyContent: 'space-between', alignItems: 'center', gap: '16px' }}>
            <h3 style={{ fontSize: '1.2rem', fontWeight: 600 }}>Dettaglio Righe Transazioni</h3>
            
            <div style={{ display: 'flex', alignItems: 'center', gap: '12px' }}>
              <input
                type="text"
                placeholder="Filtra tabella..."
                value={tableSearch}
                onChange={e => setTableSearch(e.target.value)}
                style={{
                  background: 'rgba(255,255,255,0.03)',
                  border: '1px solid var(--border-glass)',
                  borderRadius: '8px',
                  padding: '8px 12px',
                  color: 'white',
                  outline: 'none',
                  fontSize: '0.85rem',
                  width: '200px'
                }}
              />
              <button
                className="btn"
                onClick={handleExportCSV}
                disabled={tableRows.length === 0}
                style={{ padding: '8px 16px', fontSize: '0.85rem' }}
              >
                <Download size={14} /> Esporta CSV
              </button>
            </div>
          </div>

          {/* Raw Transactions Table */}
          <div style={{ overflowX: 'auto', width: '100%' }}>
            {tableRows.length > 0 ? (
              <table style={{ width: '100%', borderCollapse: 'collapse', textAlign: 'left', fontSize: '0.85rem' }}>
                <thead>
                  <tr style={{ borderBottom: '1px solid var(--border-glass)', color: 'var(--text-secondary)' }}>
                    <th style={{ padding: '12px 10px', cursor: 'pointer', fontWeight: 500 }} onClick={() => handleSort('data')}>
                      Data <ArrowUpDown size={12} style={{ marginLeft: '4px', verticalAlign: 'middle' }} />
                    </th>
                    <th style={{ padding: '12px 10px', cursor: 'pointer', fontWeight: 500 }} onClick={() => handleSort('sku')}>
                      SKU <ArrowUpDown size={12} style={{ marginLeft: '4px', verticalAlign: 'middle' }} />
                    </th>
                    <th style={{ padding: '12px 10px', cursor: 'pointer', fontWeight: 500 }} onClick={() => handleSort('label')}>
                      Prodotto <ArrowUpDown size={12} style={{ marginLeft: '4px', verticalAlign: 'middle' }} />
                    </th>
                    <th style={{ padding: '12px 10px', cursor: 'pointer', fontWeight: 500 }} onClick={() => handleSort('fornitore')}>
                      Fornitore <ArrowUpDown size={12} style={{ marginLeft: '4px', verticalAlign: 'middle' }} />
                    </th>
                    <th style={{ padding: '12px 10px', cursor: 'pointer', fontWeight: 500 }} onClick={() => handleSort('location')}>
                      Sede <ArrowUpDown size={12} style={{ marginLeft: '4px', verticalAlign: 'middle' }} />
                    </th>
                    <th style={{ padding: '12px 10px', fontWeight: 500 }}>Quantità</th>
                    <th style={{ padding: '12px 10px', cursor: 'pointer', fontWeight: 500 }} onClick={() => handleSort('prezzo_pagato')}>
                      Prezzo Pagato <ArrowUpDown size={12} style={{ marginLeft: '4px', verticalAlign: 'middle' }} />
                    </th>
                    <th style={{ padding: '12px 10px', cursor: 'pointer', fontWeight: 500 }} onClick={() => handleSort('prezzo_contratto')}>
                      Prezzo Contratto <ArrowUpDown size={12} style={{ marginLeft: '4px', verticalAlign: 'middle' }} />
                    </th>
                    <th style={{ padding: '12px 10px', cursor: 'pointer', fontWeight: 500 }} onClick={() => handleSort('delta')}>
                      Delta <ArrowUpDown size={12} style={{ marginLeft: '4px', verticalAlign: 'middle' }} />
                    </th>
                  </tr>
                </thead>
                <tbody>
                  {tableRows.map((r, idx) => {
                    const delta = r.prezzo_contratto ? ((r.prezzo_pagato - r.prezzo_contratto) / r.prezzo_contratto) * 100 : null
                    const parsedDate = new Date(r.data).toLocaleDateString('it-IT', { day: '2-digit', month: '2-digit', year: 'numeric' })
                    
                    return (
                      <tr key={`tr-${idx}`} style={{ borderBottom: '1px solid rgba(255,255,255,0.03)', transition: 'background 0.2s' }} className="table-row-hover">
                        <td style={{ padding: '12px 10px', fontWeight: 500 }}>{parsedDate}</td>
                        <td style={{ padding: '12px 10px', fontFamily: 'monospace', opacity: 0.8 }}>{r.sku}</td>
                        <td style={{ padding: '12px 10px', maxWidth: '180px', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                          <span style={{ display: 'inline-flex', alignItems: 'center', gap: '6px' }}>
                            <span style={{ width: '6px', height: '6px', borderRadius: '50%', backgroundColor: r.color }}></span>
                            {r.label}
                          </span>
                        </td>
                        <td style={{ padding: '12px 10px', color: 'var(--text-secondary)' }}>{r.fornitore}</td>
                        <td style={{ padding: '12px 10px', color: 'var(--text-secondary)' }}>{r.location}</td>
                        <td style={{ padding: '12px 10px' }}>{r.quantita}</td>
                        <td style={{ padding: '12px 10px', fontWeight: 600 }}>{r.prezzo_pagato.toFixed(4)} €</td>
                        <td style={{ padding: '12px 10px', opacity: r.prezzo_contratto ? 1 : 0.4 }}>
                          {r.prezzo_contratto ? `${r.prezzo_contratto.toFixed(4)} €` : '-'}
                        </td>
                        <td style={{ padding: '12px 10px' }}>
                          {delta !== null ? (
                            <span className={delta > 0 ? 'badge badge-red' : 'badge badge-green'}>
                              {delta > 0 ? `+${delta.toFixed(1)}%` : `${delta.toFixed(1)}%`}
                            </span>
                          ) : (
                            <span style={{ opacity: 0.4 }}>-</span>
                          )}
                        </td>
                      </tr>
                    )
                  })}
                </tbody>
              </table>
            ) : (
              <div style={{ padding: '20px 0', textAlign: 'center', color: 'var(--text-secondary)' }}>
                Nessun record corrispondente ai filtri di ricerca impostati.
              </div>
            )}
          </div>
        </div>
      )}
      
      {/* Dynamic CSS styles for hover effects and suggestions */}
      <style>{`
        .suggestion-item:hover {
          background: rgba(255, 255, 255, 0.05);
        }
        .table-row-hover:hover {
          background: rgba(255, 255, 255, 0.015);
        }
        .spinner {
          width: 18px;
          height: 18px;
          border: 2px solid rgba(255,255,255,0.1);
          border-radius: 50%;
          border-top-color: var(--accent-blue);
          animation: spin 0.8s linear infinite;
          display: inline-block;
        }
        @keyframes spin {
          to { transform: rotate(360deg); }
        }
      `}</style>

    </div>
  )
}
