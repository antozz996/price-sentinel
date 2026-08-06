import { useEffect, useMemo, useState } from 'react'
import { AlertTriangle, Building2, Check, ClipboardPaste, History, Pencil, Plus, RefreshCw, RotateCcw, Save, Search, Settings2, Table2, Trash2 } from 'lucide-react'
import { fetchWithAuth } from '../api'

type Supplier = { id: number; name: string; vat: string }
type Product = { id: number; sku_interno?: string | null; canonical_name: string; order_name?: string | null }
type Offer = {
  supplier_id: number
  supplier_name: string
  price: string
  uom?: string | null
  source_type: 'contratto' | 'spot'
  eligible: boolean
  exclusion_reasons: string[]
  assessment: { status: string; quality_score: number }
  is_absolute_cheapest: boolean
  is_recommended: boolean
  is_selected: boolean
}
type MatrixRow = {
  product_id: number
  sku_interno?: string | null
  canonical_name: string
  order_name?: string | null
  category?: string | null
  comparison_unit: string
  offers: Record<string, Offer>
  eligible_supplier_ids: number[]
  absolute_cheapest_supplier_id?: number | null
  recommended_supplier_id?: number | null
  selected_supplier_id?: number | null
  recommendation_reason: string
  requires_manual_selection: boolean
}
type MatrixResponse = {
  total: number
  limit: number
  offset: number
  suppliers: Supplier[]
  rows: MatrixRow[]
}
type Preview = {
  preview_token: string
  status: string
  expires_at: string
  can_commit: boolean
  counts: { create: number; update: number; unchanged: number; errors: number }
  changes: Array<{
    row: number
    product_name: string
    supplier_name: string
    old_price?: string | null
    new_price: string
    uom: string
    action: 'create' | 'update' | 'unchanged'
  }>
  errors: Array<{ type: string; row?: number; header?: string; reference?: string; message: string; supplier_id?: number; category?: string | null }>
  supplier_mapping: Array<{ header: string; supplier_id?: number | null; supplier_name?: string | null; method: string }>
  product_mapping: Array<{ reference: string; product_id?: number | null; canonical_name?: string | null; method: string }>
  order_name_changes?: Array<{ product_id: number; canonical_name: string; old_order_name?: string | null; new_order_name: string }>
}
type SectorMode = 'auto' | 'enabled' | 'disabled'
type SupplierSectorResponse = {
  categories: string[]
  suppliers: Array<{
    id: number
    name: string
    sectors: Array<{ category: string; mode: SectorMode; inferred: boolean; effective_enabled: boolean }>
  }>
}

const panel: React.CSSProperties = { padding: 20, display: 'flex', flexDirection: 'column', gap: 16 }
const input: React.CSSProperties = { padding: '10px 12px', background: 'rgba(255,255,255,.035)', color: 'white', border: '1px solid var(--border-glass)', borderRadius: 8 }
const tabs = [
  { id: 'matrix', label: 'Matrice', icon: Table2 },
  { id: 'paste', label: 'Foglio prezzi', icon: ClipboardPaste },
  { id: 'sectors', label: 'Settori fornitori', icon: Building2 },
  { id: 'rules', label: 'Qualità e regole', icon: Settings2 },
  { id: 'history', label: 'Storico e audit', icon: History },
] as const

function money(value?: string | null) {
  return value ? `€ ${Number(value).toFixed(2)}` : '—'
}

function errorMessage(error: unknown) {
  return error instanceof Error ? error.message : 'Operazione non riuscita'
}

const MIN_SHEET_ROWS = 18
const MIN_SHEET_COLUMNS = 6

function blankSheet(rows = MIN_SHEET_ROWS, columns = MIN_SHEET_COLUMNS): string[][] {
  return Array.from({ length: rows }, (_, rowIndex) =>
    Array.from({ length: columns }, (_, columnIndex) =>
      rowIndex === 0 && columnIndex === 0
        ? 'Nome rapido ordine (facoltativo)'
        : rowIndex === 0 && columnIndex === 1 ? 'Prodotto reale' : '',
    ),
  )
}

function sheetFromMatrix(matrix: MatrixResponse): string[][] {
  const suppliers = matrix.suppliers
  const rows = [
    ['Nome rapido ordine (facoltativo)', 'Prodotto reale', ...suppliers.map(supplier => supplier.name)],
    ...matrix.rows.map(row => [
      row.order_name || '',
      row.canonical_name,
      ...suppliers.map(supplier => row.offers[String(supplier.id)]?.price || ''),
    ]),
  ]
  const rowCount = Math.max(MIN_SHEET_ROWS, rows.length)
  const columnCount = Math.max(MIN_SHEET_COLUMNS, suppliers.length + 2)
  return Array.from({ length: rowCount }, (_, rowIndex) =>
    Array.from({ length: columnCount }, (_, columnIndex) => rows[rowIndex]?.[columnIndex] || ''),
  )
}

function sheetText(sheet: string[][]): string {
  let lastRow = sheet.length - 1
  while (lastRow > 0 && sheet[lastRow].every(cell => !cell.trim())) lastRow -= 1
  let lastColumn = 0
  for (let rowIndex = 0; rowIndex <= lastRow; rowIndex += 1) {
    sheet[rowIndex].forEach((cell, columnIndex) => {
      if (cell.trim()) lastColumn = Math.max(lastColumn, columnIndex)
    })
  }
  return sheet
    .slice(0, lastRow + 1)
    .map(row => Array.from({ length: lastColumn + 1 }, (_, columnIndex) => row[columnIndex] || '').join('\t'))
    .join('\n')
}

function columnLabel(index: number): string {
  let value = index + 1
  let label = ''
  while (value > 0) {
    value -= 1
    label = String.fromCharCode(65 + (value % 26)) + label
    value = Math.floor(value / 26)
  }
  return label
}

export default function SmartPriceSheet({ isAdmin }: { isAdmin: boolean }) {
  const [activeTab, setActiveTab] = useState<(typeof tabs)[number]['id']>('matrix')
  const [matrix, setMatrix] = useState<MatrixResponse | null>(null)
  const [sheetCatalog, setSheetCatalog] = useState<MatrixResponse | null>(null)
  const [products, setProducts] = useState<Product[]>([])
  const [search, setSearch] = useState('')
  const [offset, setOffset] = useState(0)
  const [selectedSupplierIds, setSelectedSupplierIds] = useState<number[]>([])
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [notice, setNotice] = useState<string | null>(null)

  const [sheet, setSheet] = useState<string[][]>(() => blankSheet())
  const [sheetInitialized, setSheetInitialized] = useState(false)
  const [effectiveDate, setEffectiveDate] = useState(new Date().toISOString().slice(0, 10))
  const [defaultUom, setDefaultUom] = useState('piece')
  const [supplierMapping, setSupplierMapping] = useState<Record<string, number>>({})
  const [productMapping, setProductMapping] = useState<Record<string, number>>({})
  const [preview, setPreview] = useState<Preview | null>(null)
  const [sectorData, setSectorData] = useState<SupplierSectorResponse | null>(null)
  const [sectorSupplierId, setSectorSupplierId] = useState<number | ''>('')
  const [sectorSaving, setSectorSaving] = useState<string | null>(null)

  const [editing, setEditing] = useState<{ product: MatrixRow; supplier: Supplier; price: string; uom: string } | null>(null)
  const [ruleProductId, setRuleProductId] = useState<number | ''>('')
  const [ruleSupplierId, setRuleSupplierId] = useState<number | ''>('')
  const [assessmentStatus, setAssessmentStatus] = useState('approved')
  const [quality, setQuality] = useState(3)
  const [reason, setReason] = useState('')
  const [selectionMode, setSelectionMode] = useState('best_eligible_price')
  const [preferredSupplierId, setPreferredSupplierId] = useState<number | ''>('')
  const [minimumQuality, setMinimumQuality] = useState(1)
  const [premiumPercent, setPremiumPercent] = useState('0')
  const [premiumAbsolute, setPremiumAbsolute] = useState('0')
  const [allowSpot, setAllowSpot] = useState(true)
  const [assessments, setAssessments] = useState<any[]>([])
  const [policies, setPolicies] = useState<any[]>([])
  const [historyRows, setHistoryRows] = useState<any[]>([])
  const [auditRows, setAuditRows] = useState<any[]>([])
  const [deviations, setDeviations] = useState<any[]>([])

  async function loadMatrix() {
    setLoading(true)
    setError(null)
    try {
      const query = new URLSearchParams({ limit: '50', offset: String(offset) })
      if (search.trim()) query.set('search', search.trim())
      const data = await fetchWithAuth(`/smart-price-sheet/matrix?${query}`) as MatrixResponse
      setMatrix(data)
      setSelectedSupplierIds(current => {
        const valid = current.filter(id => data.suppliers.some(item => item.id === id))
        if (valid.length) return valid
        const used = data.suppliers.filter(supplier => data.rows.some(row => row.offers[String(supplier.id)])).slice(0, 8)
        return (used.length ? used : data.suppliers.slice(0, 8)).map(item => item.id)
      })
    } catch (err) {
      setError(errorMessage(err))
    } finally {
      setLoading(false)
    }
  }

  async function loadProducts() {
    if (products.length) return
    try {
      const data = await fetchWithAuth('/products') as Product[]
      setProducts(data.filter(item => item.sku_interno))
    } catch (err) {
      setError(errorMessage(err))
    }
  }

  async function loadFullPriceSheet() {
    setLoading(true); setError(null)
    try {
      const data = await fetchWithAuth('/smart-price-sheet/matrix?limit=500&offset=0') as MatrixResponse
      setSheetCatalog(data)
      setSheet(sheetFromMatrix(data))
      setSheetInitialized(true)
      setNotice(`Foglio caricato: ${data.total} prodotti, solo fornitori pertinenti per settore.`)
    } catch (err) {
      setError(errorMessage(err))
    } finally {
      setLoading(false)
    }
  }

  async function loadRules() {
    try {
      const [assessmentData, policyData] = await Promise.all([
        fetchWithAuth('/smart-price-sheet/assessments'),
        fetchWithAuth('/smart-price-sheet/policies'),
      ])
      setAssessments(assessmentData as any[])
      setPolicies(policyData as any[])
    } catch (err) {
      setError(errorMessage(err))
    }
  }

  async function loadSupplierSectors(preferredSupplierId?: number) {
    setLoading(true); setError(null)
    try {
      const data = await fetchWithAuth('/smart-price-sheet/supplier-sectors') as SupplierSectorResponse
      setSectorData(data)
      setSectorSupplierId(current => {
        const requested = preferredSupplierId || current
        return requested && data.suppliers.some(item => item.id === requested)
          ? requested
          : data.suppliers[0]?.id || ''
      })
    } catch (err) {
      setError(errorMessage(err))
    } finally {
      setLoading(false)
    }
  }

  async function saveSupplierSector(category: string, mode: SectorMode) {
    if (!sectorSupplierId) return
    const key = `${sectorSupplierId}:${category}`
    setSectorSaving(key); setError(null); setNotice(null)
    try {
      await fetchWithAuth('/smart-price-sheet/supplier-sectors', {
        method: 'PUT',
        body: JSON.stringify({ supplier_id: sectorSupplierId, category, mode }),
      })
      await loadSupplierSectors(Number(sectorSupplierId))
      setSheetInitialized(false)
      await loadMatrix()
      setNotice(mode === 'auto'
        ? `Settore “${category}” nuovamente gestito in automatico.`
        : `Settore “${category}” ${mode === 'enabled' ? 'abilitato' : 'escluso'} per il fornitore.`)
    } catch (err) {
      setError(errorMessage(err))
    } finally {
      setSectorSaving(null)
    }
  }

  async function loadHistory() {
    try {
      if (!isAdmin) {
        const deviationData = await fetchWithAuth('/smart-price-sheet/deviations?limit=200')
        setHistoryRows([]); setAuditRows([]); setDeviations(deviationData as any[])
        return
      }
      const [prices, audits, deviationData] = await Promise.all([
        fetchWithAuth('/smart-price-sheet/history?limit=200'),
        fetchWithAuth('/smart-price-sheet/audit?limit=200'),
        fetchWithAuth('/smart-price-sheet/deviations?limit=200'),
      ])
      setHistoryRows(prices as any[])
      setAuditRows(audits as any[])
      setDeviations(deviationData as any[])
    } catch (err) {
      setError(errorMessage(err))
    }
  }

  // Reload is intentionally driven by pagination; search runs on Enter/button.
  // eslint-disable-next-line react-hooks/exhaustive-deps
  useEffect(() => { void loadMatrix() }, [offset])
  useEffect(() => {
    if (activeTab === 'paste' || activeTab === 'rules') void loadProducts()
    if (activeTab === 'sectors') void loadSupplierSectors()
    if (activeTab === 'rules') void loadRules()
    if (activeTab === 'history') void loadHistory()
  // Tab activation is the only trigger; loaders handle their own cached state.
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [activeTab])

  useEffect(() => {
    if (activeTab === 'paste' && matrix && !sheetInitialized) void loadFullPriceSheet()
  // Opening the tab or invalidating the committed sheet is the only trigger.
  }, [activeTab, matrix, sheetInitialized])

  const visibleSuppliers = useMemo(
    () => (matrix?.suppliers || []).filter(item => selectedSupplierIds.includes(item.id)),
    [matrix, selectedSupplierIds],
  )

  async function createPastePreview() {
    setLoading(true); setError(null); setNotice(null)
    try {
      const data = await fetchWithAuth('/smart-price-sheet/preview', {
        method: 'POST',
        body: JSON.stringify({ text: sheetText(sheet), supplier_mapping: supplierMapping, product_mapping: productMapping, effective_date: effectiveDate, default_uom: defaultUom }),
      }) as Preview
      setPreview(data)
    } catch (err) {
      setError(errorMessage(err))
    } finally { setLoading(false) }
  }

  async function createCellPreview() {
    if (!editing) return
    setLoading(true); setError(null)
    try {
      const data = await fetchWithAuth('/smart-price-sheet/cell-preview', {
        method: 'POST',
        body: JSON.stringify({ product_id: editing.product.product_id, supplier_id: editing.supplier.id, price: editing.price, uom: editing.uom, effective_date: effectiveDate }),
      }) as Preview
      setPreview(data); setEditing(null)
    } catch (err) { setError(errorMessage(err)) } finally { setLoading(false) }
  }

  async function commitPreview() {
    if (!preview) return
    setLoading(true); setError(null)
    try {
      const result = await fetchWithAuth('/smart-price-sheet/commit', {
        method: 'POST', body: JSON.stringify({ preview_token: preview.preview_token, confirm: true }),
      }) as any
      setNotice(`Aggiornamento completato: ${result.result.created} prezzi nuovi, ${result.result.updated} storicizzati, ${result.result.order_names_updated || 0} nomi rapidi, ${result.result.aliases_created || 0} descrizioni riconosciute per il futuro.`)
      setPreview(null); setSheetInitialized(false); await loadMatrix()
    } catch (err) { setError(errorMessage(err)) } finally { setLoading(false) }
  }

  function updateSheetCell(rowIndex: number, columnIndex: number, value: string) {
    setSheet(current => current.map((row, currentRow) =>
      currentRow === rowIndex
        ? row.map((cell, currentColumn) => currentColumn === columnIndex ? value : cell)
        : row,
    ))
    setPreview(null)
  }

  function pasteIntoSheet(event: React.ClipboardEvent<HTMLInputElement>, startRow: number, startColumn: number) {
    const clipboard = event.clipboardData.getData('text/plain')
    if (!clipboard) return
    event.preventDefault()
    const pastedRows = clipboard.replace(/\r/g, '').split('\n')
      .filter((row, index, rows) => index < rows.length - 1 || row.length > 0)
      .map(row => row.split('\t'))
    if (!pastedRows.length) return
    const requiredRows = Math.max(sheet.length, startRow + pastedRows.length)
    const pastedWidth = Math.max(...pastedRows.map(row => row.length))
    const requiredColumns = Math.max(sheet[0]?.length || 0, startColumn + pastedWidth)
    const next = Array.from({ length: requiredRows }, (_, rowIndex) =>
      Array.from({ length: requiredColumns }, (_, columnIndex) => sheet[rowIndex]?.[columnIndex] || ''),
    )
    let skipped = 0
    pastedRows.forEach((row, rowOffset) => row.forEach((cell, columnOffset) => {
      const targetRow = startRow + rowOffset
      const targetColumn = startColumn + columnOffset
      const value = cell.trim()
      if (value && !isSheetCellEligibleFor(next, targetRow, targetColumn)) {
        skipped += 1
        return
      }
      next[targetRow][targetColumn] = value
    }))
    setSheet(next)
    setPreview(null)
    setNotice(skipped
      ? `${pastedRows.length} righe incollate · ${skipped} celle fuori settore ignorate.`
      : `Incollate ${pastedRows.length} righe nel foglio.`)
  }

  function reloadCurrentPrices() {
    setPreview(null); setError(null); setNotice('Caricamento dell’intero catalogo in corso…')
    void loadFullPriceSheet()
  }

  function clearSheet() {
    setSheet(blankSheet())
    setSheetInitialized(true)
    setPreview(null); setSupplierMapping({}); setProductMapping({})
  }

  const hasSheetPrices = sheet.slice(1).some(row => row.slice(2).some(cell => cell.trim()))
  const hasOrderNames = sheet.slice(1).some(row => row[0]?.trim())

  function isSheetCellEligibleFor(grid: string[][], rowIndex: number, columnIndex: number) {
    const catalog = sheetCatalog || matrix
    if (rowIndex === 0 || columnIndex < 2 || !catalog) return true
    const productRef = (grid[rowIndex]?.[1] || '').trim().toLocaleLowerCase('it-IT')
    const supplierHeader = (grid[0]?.[columnIndex] || '').trim().toLocaleLowerCase('it-IT')
    if (!productRef || !supplierHeader) return true
    const product = catalog.rows.find(item =>
      item.sku_interno?.toLocaleLowerCase('it-IT') === productRef
      || item.canonical_name.toLocaleLowerCase('it-IT') === productRef,
    )
    const supplier = catalog.suppliers.find(item => item.name.toLocaleLowerCase('it-IT') === supplierHeader)
    if (!product || !supplier) return true
    return product.eligible_supplier_ids.includes(supplier.id)
  }

  function isSheetCellEligible(rowIndex: number, columnIndex: number) {
    return isSheetCellEligibleFor(sheet, rowIndex, columnIndex)
  }

  async function saveAssessment() {
    if (!ruleProductId || !ruleSupplierId) return setError('Seleziona prodotto e fornitore.')
    setLoading(true); setError(null)
    try {
      await fetchWithAuth('/smart-price-sheet/assessments', {
        method: 'PUT', body: JSON.stringify({ product_id: ruleProductId, supplier_id: ruleSupplierId, status: assessmentStatus, quality_score: quality, reason: reason.trim() || null }),
      })
      setNotice('Valutazione salvata e registrata nell’audit.'); await loadRules(); await loadMatrix()
    } catch (err) { setError(errorMessage(err)) } finally { setLoading(false) }
  }

  async function savePolicy() {
    if (!ruleProductId) return setError('Seleziona il prodotto.')
    setLoading(true); setError(null)
    try {
      await fetchWithAuth('/smart-price-sheet/policies', {
        method: 'PUT', body: JSON.stringify({ product_id: ruleProductId, selection_mode: selectionMode, preferred_supplier_id: preferredSupplierId || null, minimum_quality: minimumQuality, max_price_premium_percent: premiumPercent, max_price_premium_absolute: premiumAbsolute, allow_spot: allowSpot }),
      })
      setNotice('Regola di acquisto salvata e attiva.'); await loadRules(); await loadMatrix()
    } catch (err) { setError(errorMessage(err)) } finally { setLoading(false) }
  }

  async function updateDeviation(id: string, status: 'acknowledged' | 'accepted_exception') {
    setLoading(true); setError(null)
    try {
      await fetchWithAuth(`/smart-price-sheet/deviations/${id}`, {
        method: 'PATCH', body: JSON.stringify({ status }),
      })
      setNotice(status === 'acknowledged' ? 'Deviazione presa in carico.' : 'Eccezione accettata e tracciata.')
      await loadHistory()
    } catch (err) { setError(errorMessage(err)) } finally { setLoading(false) }
  }

  function PreviewPanel() {
    if (!preview) return null
    return (
      <div className="glass-panel" style={{ ...panel, border: `1px solid ${preview.errors.length ? '#ef4444' : '#10b981'}` }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', gap: 12, alignItems: 'center', flexWrap: 'wrap' }}>
          <strong>Anteprima obbligatoria</strong>
          <span style={{ color: 'var(--text-secondary)', fontSize: 13 }}>
            {preview.counts.create} nuovi · {preview.counts.update} aggiornati · {preview.counts.unchanged} invariati · {preview.order_name_changes?.length || 0} nomi rapidi · {preview.counts.errors} errori
          </span>
        </div>
        {preview.errors.map((item, index) => (
          <div key={index} style={{ color: '#fca5a5', fontSize: 13, display: 'flex', gap: 10, alignItems: 'center', flexWrap: 'wrap' }}>
            <span>Riga {item.row || '—'}: {item.message}</span>
            {item.type === 'supplier_scope' && item.supplier_id && item.category && <button className="btn" onClick={() => {
              setSectorSupplierId(item.supplier_id || '')
              setActiveTab('sectors')
              setPreview(null)
              void loadSupplierSectors(item.supplier_id)
            }}><Building2 size={14} /> Configura settore</button>}
          </div>
        ))}
        {preview.supplier_mapping.filter(item => !item.supplier_id).map(item => (
          <label key={item.header} style={{ display: 'grid', gridTemplateColumns: 'minmax(180px,1fr) 2fr', gap: 12, alignItems: 'center' }}>
            <span>Colonna “{item.header}”</span>
            <select style={input} value={supplierMapping[item.header] || ''} onChange={event => setSupplierMapping(current => ({ ...current, [item.header]: Number(event.target.value) }))}>
              <option value="">Associa il fornitore…</option>
              {matrix?.suppliers.map(supplier => <option key={supplier.id} value={supplier.id}>{supplier.name}</option>)}
            </select>
          </label>
        ))}
        {preview.product_mapping.filter(item => !item.product_id).map(item => (
          <label key={item.reference} style={{ display: 'grid', gridTemplateColumns: 'minmax(180px,1fr) 2fr', gap: 12, alignItems: 'center' }}>
            <span>“{item.reference}”</span>
            <select style={input} value={productMapping[item.reference] || ''} onChange={event => setProductMapping(current => ({ ...current, [item.reference]: Number(event.target.value) }))}>
              <option value="">Associa il prodotto principale…</option>
              {products.map(product => <option key={product.id} value={product.id}>{product.order_name ? `${product.order_name} — ` : ''}{product.canonical_name}</option>)}
            </select>
          </label>
        ))}
        {!!preview.order_name_changes?.length && <div style={{ padding: 12, borderRadius: 8, background: 'rgba(59,130,246,.08)', fontSize: 13 }}>
          <strong>Nomi rapidi da aggiornare</strong>
          {preview.order_name_changes.map(item => <div key={item.product_id} style={{ color: 'var(--text-secondary)', marginTop: 5 }}>{item.canonical_name}: {item.old_order_name || 'nessuno'} → <b style={{ color: 'white' }}>{item.new_order_name}</b></div>)}
        </div>}
        {(preview.errors.length > 0) && <button className="btn" onClick={createPastePreview}>Ricalcola anteprima</button>}
        <div style={{ maxHeight: 280, overflow: 'auto' }}>
          <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 13 }}>
            <thead><tr><th style={{ textAlign: 'left' }}>Prodotto</th><th>Fornitore</th><th>Prima</th><th>Dopo</th><th>Esito</th></tr></thead>
            <tbody>{preview.changes.slice(0, 300).map((item, index) => <tr key={index}>
              <td style={{ padding: 8 }}>{item.product_name}</td><td style={{ textAlign: 'center' }}>{item.supplier_name}</td><td style={{ textAlign: 'center' }}>{money(item.old_price)}</td><td style={{ textAlign: 'center' }}>{money(item.new_price)}</td><td style={{ textAlign: 'center' }}>{item.action}</td>
            </tr>)}</tbody>
          </table>
        </div>
        <button className="btn btn-primary" disabled={!preview.can_commit || loading} onClick={commitPreview}><Check size={16} /> Conferma e aggiorna listino</button>
      </div>
    )
  }

  return <div style={{ display: 'flex', flexDirection: 'column', gap: 20 }}>
    <div className="glass-panel" style={{ padding: '4px 12px', display: 'flex', gap: 6, overflowX: 'auto' }}>
      {tabs.filter(tab => isAdmin || tab.id === 'matrix' || tab.id === 'history').map(tab => { const Icon = tab.icon; return <button key={tab.id} onClick={() => { setActiveTab(tab.id); setPreview(null); setError(null) }} style={{ padding: '13px 16px', border: 0, borderBottom: activeTab === tab.id ? '2px solid var(--accent-blue)' : '2px solid transparent', background: 'transparent', color: activeTab === tab.id ? 'white' : 'var(--text-secondary)', display: 'flex', gap: 8, alignItems: 'center', cursor: 'pointer', whiteSpace: 'nowrap' }}><Icon size={17} />{tab.label}</button> })}
    </div>
    {error && <div className="glass-panel" style={{ padding: 14, color: '#fca5a5' }}><AlertTriangle size={16} /> {error}</div>}
    {notice && <div className="glass-panel" style={{ padding: 14, color: '#6ee7b7' }}><Check size={16} /> {notice}</div>}

    {activeTab === 'matrix' && <>
      <div className="glass-panel" style={panel}>
        <div style={{ display: 'flex', gap: 12, flexWrap: 'wrap', alignItems: 'center' }}>
          <div style={{ position: 'relative', flex: '1 1 260px' }}><Search size={16} style={{ position: 'absolute', left: 12, top: 12 }} /><input style={{ ...input, width: '100%', boxSizing: 'border-box', paddingLeft: 36 }} value={search} onChange={event => setSearch(event.target.value)} onKeyDown={event => { if (event.key === 'Enter') { setOffset(0); void loadMatrix() } }} placeholder="Cerca prodotto o SKU…" /></div>
          <button className="btn" onClick={() => { setOffset(0); void loadMatrix() }}><RefreshCw size={16} /> Aggiorna</button>
          <span style={{ color: 'var(--text-secondary)', fontSize: 13 }}>{matrix?.total || 0} prodotti</span>
        </div>
        <details><summary style={{ cursor: 'pointer', color: 'var(--text-secondary)' }}>Colonne fornitori ({selectedSupplierIds.length}/{matrix?.suppliers.length || 0})</summary><div style={{ display: 'flex', gap: 12, flexWrap: 'wrap', paddingTop: 12 }}>{matrix?.suppliers.map(supplier => <label key={supplier.id} style={{ fontSize: 13 }}><input type="checkbox" checked={selectedSupplierIds.includes(supplier.id)} onChange={() => setSelectedSupplierIds(current => current.includes(supplier.id) ? current.filter(id => id !== supplier.id) : [...current, supplier.id])} /> {supplier.name}</label>)}</div></details>
        {loading ? <div style={{ padding: 30, textAlign: 'center' }}>Caricamento…</div> : <div style={{ overflow: 'auto', maxHeight: '65vh' }}><table style={{ minWidth: 700, width: '100%', borderCollapse: 'collapse', fontSize: 13 }}>
          <thead style={{ position: 'sticky', top: 0, background: '#11111a', zIndex: 2 }}><tr><th style={{ textAlign: 'left', padding: 12, minWidth: 240 }}>Prodotto principale</th>{visibleSuppliers.map(supplier => <th key={supplier.id} style={{ padding: 12, minWidth: 155 }}>{supplier.name}</th>)}</tr></thead>
          <tbody>{matrix?.rows.map(row => <tr key={row.product_id} style={{ borderTop: '1px solid var(--border-glass)' }}>
            <td style={{ padding: 12 }}>
              <strong>{row.order_name || row.canonical_name}</strong>
              {row.order_name && <div style={{ color: 'var(--text-secondary)', fontSize: 11 }}>{row.canonical_name}</div>}
              <div style={{ color: 'var(--text-secondary)', fontSize: 11 }}>{row.sku_interno || 'SKU mancante'} · {row.category || 'Senza categoria'}</div>
              {row.requires_manual_selection && <small style={{ color: '#fbbf24' }}>Scelta manuale richiesta</small>}
            </td>
            {visibleSuppliers.map(supplier => {
              const offer = row.offers[String(supplier.id)]
              const relevant = row.eligible_supplier_ids.includes(supplier.id)
              return <td key={supplier.id} style={{ textAlign: 'center', padding: 8, opacity: offer && !offer.eligible ? .55 : 1, background: offer?.is_recommended ? 'rgba(16,185,129,.08)' : !relevant ? 'rgba(255,255,255,.012)' : 'transparent' }}>
                {relevant ? <button disabled={!isAdmin} onClick={() => isAdmin && setEditing({ product: row, supplier, price: offer?.price || '', uom: offer?.uom || row.comparison_unit || 'piece' })} style={{ width: '100%', padding: 8, borderRadius: 8, cursor: isAdmin ? 'pointer' : 'default', color: offer?.is_recommended ? '#6ee7b7' : 'white', border: offer?.is_absolute_cheapest ? '1px solid #3b82f6' : '1px solid transparent', background: 'rgba(255,255,255,.025)' }}>
                  {offer ? <><strong>{money(offer.price)}</strong><div style={{ fontSize: 10, color: 'var(--text-secondary)' }}>{offer.source_type}{offer.is_recommended ? ' · CONSIGLIATO' : ''}{offer.assessment.status === 'blocked' ? ' · BLOCCATO' : ''}</div></> : <>{isAdmin && <Pencil size={13} />} {isAdmin ? 'inserisci' : '—'}</>}
                </button> : <span title="Fornitore fuori dal settore del prodotto" style={{ color: '#5f6574', fontSize: 11 }}>fuori settore</span>}
              </td>
            })}
          </tr>)}</tbody>
        </table></div>}
        <div style={{ display: 'flex', justifyContent: 'space-between' }}><button className="btn" disabled={offset === 0} onClick={() => setOffset(Math.max(0, offset - 50))}>Indietro</button><button className="btn" disabled={!matrix || offset + 50 >= matrix.total} onClick={() => setOffset(offset + 50)}>Avanti</button></div>
      </div>
      {editing && <div className="glass-panel" style={panel}><strong>Modifica sicura: {editing.product.canonical_name} · {editing.supplier.name}</strong><div style={{ display: 'flex', gap: 10, flexWrap: 'wrap' }}><input autoFocus style={input} value={editing.price} onChange={event => setEditing({ ...editing, price: event.target.value })} placeholder="Prezzo" /><input style={input} value={editing.uom} onChange={event => setEditing({ ...editing, uom: event.target.value })} placeholder="Unità" /><button className="btn btn-primary" onClick={createCellPreview}>Genera anteprima</button><button className="btn" onClick={() => setEditing(null)}>Annulla</button></div></div>}
      <PreviewPanel />
    </>}

    {activeTab === 'paste' && <>
      <div className="glass-panel" style={{ ...panel, gap: 14 }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', gap: 14, flexWrap: 'wrap' }}>
          <div>
            <h3 style={{ margin: 0 }}>Foglio prezzi</h3>
            <p style={{ color: 'var(--text-secondary)', margin: '5px 0 0' }}>
              Colonna A = nome rapido facoltativo per gli ordini. Colonna B = nome reale e leggibile del prodotto. Da C in poi = fornitori. Incolla direttamente da Excel o Google Sheets.
            </p>
          </div>
          <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
            <button className="btn" onClick={reloadCurrentPrices}><RotateCcw size={15} /> Prezzi correnti</button>
            <button className="btn" onClick={clearSheet}><Trash2 size={15} /> Svuota</button>
          </div>
        </div>

        <div style={{ border: '1px solid var(--border-glass)', borderRadius: 10, overflow: 'auto', maxHeight: '58vh', background: 'rgba(5,7,14,.55)' }}>
          <table style={{ borderCollapse: 'separate', borderSpacing: 0, width: 'max-content', minWidth: '100%', fontSize: 13 }}>
            <thead style={{ position: 'sticky', top: 0, zIndex: 5 }}>
              <tr>
                <th style={{ width: 44, minWidth: 44, height: 28, position: 'sticky', left: 0, zIndex: 7, background: '#171923', borderRight: '1px solid #343745', borderBottom: '1px solid #343745' }} />
                {sheet[0]?.map((_, columnIndex) => <th key={columnIndex} style={{ minWidth: columnIndex === 0 ? 190 : columnIndex === 1 ? 280 : 155, height: 28, padding: '0 8px', textAlign: 'center', color: '#9ca3af', background: '#171923', borderRight: '1px solid #343745', borderBottom: '1px solid #343745', fontWeight: 600 }}>{columnLabel(columnIndex)}</th>)}
              </tr>
            </thead>
            <tbody>
              {sheet.map((row, rowIndex) => <tr key={rowIndex}>
                <th style={{ width: 44, minWidth: 44, height: 36, position: 'sticky', left: 0, zIndex: 4, textAlign: 'center', color: '#9ca3af', background: '#171923', borderRight: '1px solid #343745', borderBottom: '1px solid #292c37', fontWeight: 500 }}>{rowIndex + 1}</th>
                {row.map((cell, columnIndex) => {
                  const eligible = isSheetCellEligible(rowIndex, columnIndex)
                  const width = columnIndex === 0 ? 190 : columnIndex === 1 ? 280 : 155
                  return <td key={columnIndex} style={{ padding: 0, minWidth: width, borderRight: '1px solid #292c37', borderBottom: '1px solid #292c37', background: !eligible ? 'rgba(70,70,80,.16)' : rowIndex === 0 ? 'rgba(59,130,246,.10)' : columnIndex < 2 ? 'rgba(255,255,255,.025)' : 'transparent' }}>
                    <input
                      aria-label={`Cella ${columnLabel(columnIndex)}${rowIndex + 1}`}
                      value={cell}
                      disabled={!eligible}
                      title={!eligible ? 'Fornitore fuori dal settore di questo prodotto' : undefined}
                      onChange={event => updateSheetCell(rowIndex, columnIndex, event.target.value)}
                      onPaste={event => pasteIntoSheet(event, rowIndex, columnIndex)}
                      placeholder={rowIndex === 0 ? (columnIndex === 0 ? 'Nome rapido (facoltativo)' : columnIndex === 1 ? 'Prodotto reale' : 'Nome fornitore') : columnIndex === 0 ? 'Es. GUANTI' : columnIndex === 1 ? 'Descrizione reale del prodotto' : eligible ? '—' : 'fuori settore'}
                      style={{ width: '100%', minWidth: width, height: 36, boxSizing: 'border-box', padding: '0 10px', border: 0, outline: 'none', color: eligible ? 'white' : '#5f6574', background: 'transparent', fontWeight: rowIndex === 0 || columnIndex < 2 ? 600 : 400, textAlign: columnIndex > 1 && rowIndex > 0 ? 'right' : 'left', cursor: eligible ? 'text' : 'not-allowed' }}
                      onFocus={event => { event.currentTarget.style.boxShadow = 'inset 0 0 0 2px #3b82f6' }}
                      onBlur={event => { event.currentTarget.style.boxShadow = 'none' }}
                    />
                  </td>
                })}
              </tr>)}
            </tbody>
          </table>
        </div>

        <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
          <button className="btn" onClick={() => setSheet(current => [...current, Array(current[0]?.length || MIN_SHEET_COLUMNS).fill('')])}><Plus size={15} /> Riga</button>
          <button className="btn" onClick={() => setSheet(current => current.map(row => [...row, '']))}><Plus size={15} /> Fornitore</button>
          <span style={{ alignSelf: 'center', color: 'var(--text-secondary)', fontSize: 12 }}>{sheet.length - 1} righe · {Math.max(0, (sheet[0]?.length || 2) - 2)} colonne fornitore</span>
        </div>

        <div style={{ display: 'flex', gap: 12, flexWrap: 'wrap', alignItems: 'end', paddingTop: 2 }}>
          <label style={{ display: 'flex', flexDirection: 'column', gap: 5, fontSize: 13 }}>Validità <input type="date" style={input} value={effectiveDate} onChange={event => setEffectiveDate(event.target.value)} /></label>
          <label style={{ display: 'flex', flexDirection: 'column', gap: 5, fontSize: 13 }}>Unità predefinita <input style={input} value={defaultUom} onChange={event => setDefaultUom(event.target.value)} /></label>
          <button className="btn btn-primary" disabled={(!hasSheetPrices && !hasOrderNames) || loading} onClick={createPastePreview}><ClipboardPaste size={16} /> Controlla modifiche</button>
          <span style={{ color: 'var(--text-secondary)', fontSize: 12, alignSelf: 'center' }}>Nessun dato viene salvato prima della conferma.</span>
        </div>
      </div>
      <PreviewPanel />
    </>}

    {activeTab === 'sectors' && <div className="glass-panel" style={panel}>
      <div>
        <h3 style={{ margin: 0 }}>Settori del fornitore</h3>
        <p style={{ color: 'var(--text-secondary)', margin: '6px 0 0', maxWidth: 900 }}>
          Scegli cosa può vendere ogni fornitore. In <b>Automatico</b> il sistema usa fatture, listini e associazioni già presenti; <b>Abilitato</b> forza la visualizzazione; <b>Escluso</b> la blocca sempre, anche se esistono dati storici.
        </p>
      </div>
      <label style={{ display: 'flex', flexDirection: 'column', gap: 6, maxWidth: 520 }}>
        <span style={{ fontSize: 13, color: 'var(--text-secondary)' }}>Fornitore da configurare</span>
        <select style={input} value={sectorSupplierId} onChange={event => setSectorSupplierId(Number(event.target.value) || '')}>
          {sectorData?.suppliers.map(supplier => <option key={supplier.id} value={supplier.id}>{supplier.name}</option>)}
        </select>
      </label>
      {loading && !sectorData ? <div>Caricamento settori…</div> : <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit,minmax(300px,1fr))', gap: 12 }}>
        {sectorData?.suppliers.find(supplier => supplier.id === sectorSupplierId)?.sectors.map(sector => {
          const key = `${sectorSupplierId}:${sector.category}`
          const choices: Array<{ mode: SectorMode; label: string }> = [
            { mode: 'auto', label: 'Automatico' },
            { mode: 'enabled', label: 'Abilitato' },
            { mode: 'disabled', label: 'Escluso' },
          ]
          return <div key={sector.category} style={{ padding: 14, border: '1px solid var(--border-glass)', borderRadius: 10, background: 'rgba(255,255,255,.018)', display: 'flex', flexDirection: 'column', gap: 10 }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', gap: 10, alignItems: 'center' }}>
              <strong>{sector.category}</strong>
              <span style={{ fontSize: 11, color: sector.effective_enabled ? '#6ee7b7' : '#9ca3af' }}>{sector.effective_enabled ? 'VISIBILE' : 'NASCOSTO'}</span>
            </div>
            {sector.mode === 'auto' && <small style={{ color: 'var(--text-secondary)' }}>Decisione automatica: {sector.inferred ? 'dati commerciali trovati' : 'nessun dato trovato'}</small>}
            <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap' }}>
              {choices.map(choice => <button
                key={choice.mode}
                className={sector.mode === choice.mode ? 'btn btn-primary' : 'btn'}
                disabled={sectorSaving === key}
                onClick={() => void saveSupplierSector(sector.category, choice.mode)}
                style={{ padding: '7px 10px', fontSize: 12 }}
              >{choice.label}</button>)}
            </div>
          </div>
        })}
      </div>}
    </div>}

    {activeTab === 'rules' && <><div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit,minmax(330px,1fr))', gap: 16 }}><div className="glass-panel" style={panel}><h3 style={{ margin: 0 }}>Qualità prodotto-fornitore</h3><select style={input} value={ruleProductId} onChange={event => setRuleProductId(Number(event.target.value) || '')}><option value="">Prodotto…</option>{products.map(item => <option key={item.id} value={item.id}>{item.canonical_name} ({item.sku_interno})</option>)}</select><select style={input} value={ruleSupplierId} onChange={event => setRuleSupplierId(Number(event.target.value) || '')}><option value="">Fornitore…</option>{matrix?.suppliers.map(item => <option key={item.id} value={item.id}>{item.name}</option>)}</select><select style={input} value={assessmentStatus} onChange={event => setAssessmentStatus(event.target.value)}><option value="approved">Approvato</option><option value="discouraged">Sconsigliato</option><option value="blocked">Bloccato</option></select><label>Qualità {quality}/5 <input type="range" min="1" max="5" value={quality} onChange={event => setQuality(Number(event.target.value))} /></label><textarea style={input} value={reason} onChange={event => setReason(event.target.value)} placeholder="Motivazione (obbligatoria se sconsigliato/bloccato)" /><button className="btn btn-primary" onClick={saveAssessment}><Save size={16} /> Salva valutazione</button></div><div className="glass-panel" style={panel}><h3 style={{ margin: 0 }}>Regola di acquisto</h3><p style={{ color: 'var(--text-secondary)', margin: 0 }}>Si applica al prodotto selezionato.</p><select style={input} value={selectionMode} onChange={event => setSelectionMode(event.target.value)}><option value="best_eligible_price">Miglior prezzo idoneo</option><option value="absolute_lowest">Minimo assoluto (con avvisi qualità)</option><option value="manual">Fornitore preferito manuale</option></select><select style={input} value={preferredSupplierId} onChange={event => setPreferredSupplierId(Number(event.target.value) || '')}><option value="">Nessun fornitore preferito</option>{matrix?.suppliers.map(item => <option key={item.id} value={item.id}>{item.name}</option>)}</select><label>Qualità minima <input type="number" min="1" max="5" style={input} value={minimumQuality} onChange={event => setMinimumQuality(Number(event.target.value))} /></label><div style={{ display: 'flex', gap: 10 }}><input style={{ ...input, width: '50%' }} value={premiumPercent} onChange={event => setPremiumPercent(event.target.value)} placeholder="Premium %" /><input style={{ ...input, width: '50%' }} value={premiumAbsolute} onChange={event => setPremiumAbsolute(event.target.value)} placeholder="Premium €" /></div><label><input type="checkbox" checked={allowSpot} onChange={event => setAllowSpot(event.target.checked)} /> Consenti prezzi spot</label><button className="btn btn-primary" onClick={savePolicy}><Save size={16} /> Salva regola</button></div></div><div className="glass-panel" style={panel}><strong>Configurazioni attive: {assessments.length} valutazioni · {policies.length} policy</strong>{assessments.slice(0, 12).map(item => <div key={item.id} style={{ fontSize: 13, color: 'var(--text-secondary)' }}>{item.product_name} · {item.supplier_name}: <b style={{ color: item.status === 'blocked' ? '#f87171' : 'white' }}>{item.status}</b>, qualità {item.quality_score}/5</div>)}</div></>}

    {activeTab === 'history' && <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit,minmax(360px,1fr))', gap: 16 }}><div className="glass-panel" style={panel}><h3 style={{ margin: 0 }}>Versioni prezzo</h3><div style={{ maxHeight: 520, overflow: 'auto' }}>{historyRows.map(item => <div key={item.id} style={{ padding: '10px 0', borderBottom: '1px solid var(--border-glass)', fontSize: 13 }}><strong>{item.description}</strong> · {item.supplier_name}<div style={{ color: 'var(--text-secondary)' }}>{money(item.price)} / {item.uom} · {item.valid_from} → {item.valid_to || 'attivo'}</div></div>)}</div></div><div className="glass-panel" style={panel}><h3 style={{ margin: 0 }}>Audit regole</h3><div style={{ maxHeight: 300, overflow: 'auto' }}>{auditRows.map((item, index) => <div key={`${item.entity_type}-${item.entity_id}-${index}`} style={{ padding: '10px 0', borderBottom: '1px solid var(--border-glass)', fontSize: 13 }}>{item.entity_type} #{item.entity_id} · {item.action}<div style={{ color: 'var(--text-secondary)' }}>{new Date(item.occurred_at).toLocaleString('it-IT')} · utente #{item.actor_id}</div></div>)}</div><h3>Scostamenti policy ({deviations.length})</h3>{deviations.slice(0, 20).map(item => <div key={item.id} style={{ color: '#fbbf24', fontSize: 13, padding: '8px 0' }}><div>{item.deviation_type}: {item.reason} · <b>{item.status}</b></div>{item.status === 'open' && <div style={{ display: 'flex', gap: 8, marginTop: 6 }}><button className="btn" onClick={() => updateDeviation(item.id, 'acknowledged')}>Presa in carico</button><button className="btn" onClick={() => updateDeviation(item.id, 'accepted_exception')}>Accetta eccezione</button></div>}</div>)}</div></div>}
  </div>
}
