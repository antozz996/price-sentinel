import { useEffect, useMemo, useState } from 'react'
import { AlertTriangle, Building2, Check, ClipboardPaste, History, Pencil, Plus, RefreshCw, RotateCcw, Search, Table2, Trash2 } from 'lucide-react'
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
  policy?: {
    selection_mode: 'manual' | 'best_eligible_price' | 'absolute_lowest'
    preferred_supplier_id?: number | null
    reason?: string | null
  } | null
}
type MatrixResponse = {
  total: number
  limit: number
  offset: number
  category_counts?: Record<string, number>
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
        : rowIndex === 0 && columnIndex === 1
        ? 'Prodotto reale'
        : rowIndex === 0 && columnIndex === 2
        ? 'Unità di misura'
        : '',
    ),
  )
}

function sheetFromMatrix(matrix: MatrixResponse): string[][] {
  const suppliers = matrix.suppliers
  const rows = [
    ['Nome rapido ordine (facoltativo)', 'Prodotto reale', 'Unità di misura', ...suppliers.map(supplier => supplier.name)],
    ...matrix.rows.map(row => [
      row.order_name || '',
      row.canonical_name,
      row.comparison_unit || 'Pz',
      ...suppliers.map(supplier => row.offers[String(supplier.id)]?.price || ''),
    ]),
  ]
  const rowCount = Math.max(MIN_SHEET_ROWS, rows.length)
  const columnCount = Math.max(MIN_SHEET_COLUMNS, suppliers.length + 3)
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

const MACRO_CATEGORIES = [
  { id: 'Beverage', label: 'Beverage', icon: '🍹', color: '#3b82f6', bg: 'rgba(59,130,246,0.15)', border: '#3b82f6' },
  { id: 'Food', label: 'Food', icon: '🍽️', color: '#f59e0b', bg: 'rgba(245,158,11,0.15)', border: '#f59e0b' },
  { id: 'Materiali di consumo', label: 'Materiali di consumo', icon: '📦', color: '#10b981', bg: 'rgba(16,185,129,0.15)', border: '#10b981' },
] as const

type MacroCategory = typeof MACRO_CATEGORIES[number]['id']

export default function SmartPriceSheet({ isAdmin }: { isAdmin: boolean }) {
  const [activeTab, setActiveTab] = useState<(typeof tabs)[number]['id']>('matrix')
  const [matrix, setMatrix] = useState<MatrixResponse | null>(null)
  const [selectedMatrixCategory, setSelectedMatrixCategory] = useState<string>('all')
  const [sheetCatalog, setSheetCatalog] = useState<MatrixResponse | null>(null)
  const [products, setProducts] = useState<Product[]>([])
  const [search, setSearch] = useState('')
  const [offset, setOffset] = useState(0)
  const [selectedSupplierIds, setSelectedSupplierIds] = useState<number[]>([])
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [notice, setNotice] = useState<string | null>(null)

  const [activeCategorySheet, setActiveCategorySheet] = useState<MacroCategory>('Beverage')
  const [categorySheets, setCategorySheets] = useState<Record<string, string[][]>>({
    'Beverage': blankSheet(),
    'Food': blankSheet(),
    'Materiali di consumo': blankSheet(),
  })
  const sheet = categorySheets[activeCategorySheet] || blankSheet()

  function setSheet(updater: string[][] | ((current: string[][]) => string[][])) {
    setCategorySheets(prev => {
      const current = prev[activeCategorySheet] || blankSheet()
      const next = typeof updater === 'function' ? updater(current) : updater
      return { ...prev, [activeCategorySheet]: next }
    })
  }

  const [sheetInitialized, setSheetInitialized] = useState(false)
  const [effectiveDate, setEffectiveDate] = useState(new Date().toISOString().slice(0, 10))
  const [defaultUom, setDefaultUom] = useState('piece')
  const [autoCreateProducts, setAutoCreateProducts] = useState(true)
  const [supplierMapping, setSupplierMapping] = useState<Record<string, number>>({})
  const [productMapping, setProductMapping] = useState<Record<string, number>>({})
  const [preview, setPreview] = useState<Preview | null>(null)
  const [sectorData, setSectorData] = useState<SupplierSectorResponse | null>(null)
  const [sectorSupplierId, setSectorSupplierId] = useState<number | ''>('')
  const [sectorSaving, setSectorSaving] = useState<string | null>(null)

  const [editing, setEditing] = useState<{ product: MatrixRow; supplier: Supplier; price: string; uom: string } | null>(null)
  const [forceLabel, setForceLabel] = useState('')
  const [historyRows, setHistoryRows] = useState<any[]>([])
  const [auditRows, setAuditRows] = useState<any[]>([])
  const [deviations, setDeviations] = useState<any[]>([])

  async function loadMatrix(customOffset?: number, customCategory?: string) {
    setLoading(true)
    setError(null)
    try {
      const currentOffset = customOffset !== undefined ? customOffset : offset
      const currentCat = customCategory !== undefined ? customCategory : selectedMatrixCategory
      const query = new URLSearchParams({ limit: '100', offset: String(currentOffset) })
      if (search.trim()) query.set('search', search.trim())
      if (currentCat && currentCat !== 'all') query.set('category', currentCat)
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

  async function handleSetForcedSupplier(productId: number, supplierId: number | null, labelText?: string | null) {
    setLoading(true); setError(null)
    try {
      if (supplierId) {
        await fetchWithAuth('/smart-price-sheet/policies', {
          method: 'PUT',
          body: JSON.stringify({
            product_id: productId,
            selection_mode: 'manual',
            preferred_supplier_id: supplierId,
            reason: (labelText || 'Fornitore forzato').trim(),
            minimum_quality: 1,
            max_price_premium_percent: 0,
            max_price_premium_absolute: 0,
            allow_spot: true,
          }),
        })
        setNotice(`⭐ Acquisto forzato con successo da questo fornitore!`)
      } else {
        await fetchWithAuth('/smart-price-sheet/policies', {
          method: 'PUT',
          body: JSON.stringify({
            product_id: productId,
            selection_mode: 'best_eligible_price',
            preferred_supplier_id: null,
            reason: null,
            minimum_quality: 1,
            max_price_premium_percent: 0,
            max_price_premium_absolute: 0,
            allow_spot: true,
          }),
        })
        setNotice(`🔄 Forzatura rimossa. Acquisto ripristinato in automatico al miglior prezzo.`)
      }
      setEditing(null)
      await loadMatrix()
    } catch (err) {
      setError(errorMessage(err))
    } finally {
      setLoading(false)
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

  useEffect(() => {
    void loadMatrix()
  }, [offset, selectedMatrixCategory])
  useEffect(() => {
    if (activeTab === 'paste') void loadProducts()
    if (activeTab === 'sectors') void loadSupplierSectors()
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
        body: JSON.stringify({
          text: sheetText(sheet),
          supplier_mapping: supplierMapping,
          product_mapping: productMapping,
          effective_date: effectiveDate,
          default_uom: defaultUom,
          create_missing_products: autoCreateProducts,
          category: activeCategorySheet,
        }),
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
      const createdProdMsg = result.result.products_created ? `${result.result.products_created} prodotti creati nel catalogo, ` : ''
      setNotice(`Aggiornamento completato: ${createdProdMsg}${result.result.created} prezzi nuovi, ${result.result.updated} storicizzati, ${result.result.order_names_updated || 0} nomi rapidi, ${result.result.aliases_created || 0} descrizioni riconosciute per il futuro.`)
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
      ? `${pastedRows.length} righe incollate nel foglio ${activeCategorySheet} · ${skipped} celle fuori settore ignorate.`
      : `Incollate ${pastedRows.length} righe nel foglio ${activeCategorySheet}.`)
  }

  async function reloadCurrentPrices() {
    setLoading(true); setError(null)
    try {
      const data = await fetchWithAuth('/smart-price-sheet/matrix?limit=500&offset=0') as MatrixResponse
      const filteredRows = data.rows.filter(r => (r.category || '').toLowerCase() === activeCategorySheet.toLowerCase())
      const matrixForCategory = { ...data, rows: filteredRows.length ? filteredRows : data.rows }
      setSheet(sheetFromMatrix(matrixForCategory))
      setNotice(`Foglio "${activeCategorySheet}" caricato con ${filteredRows.length} prodotti.`)
    } catch (err) {
      setError(errorMessage(err))
    } finally {
      setLoading(false)
    }
  }

  function clearSheet() {
    setSheet(blankSheet())
    setSheetInitialized(true)
    setPreview(null); setSupplierMapping({}); setProductMapping({})
  }

  const hasSheetPrices = sheet.slice(1).some(row => row.slice(3).some(cell => cell.trim()))
  const hasOrderNames = sheet.slice(1).some(row => row[0]?.trim())

  function isSheetCellEligibleFor(grid: string[][], rowIndex: number, columnIndex: number) {
    const catalog = sheetCatalog || matrix
    if (rowIndex === 0 || columnIndex < 3 || !catalog) return true
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
    const autoCreateCount = preview.product_mapping.filter(m => m.method === 'auto_create').length
    const autoSuppliersCount = preview.supplier_mapping.filter(m => m.method === 'auto_create').length
    const isReady = preview.can_commit && preview.errors.length === 0
    return (
      <div className="glass-panel" style={{ ...panel, border: `1px solid ${preview.errors.length ? '#ef4444' : '#10b981'}`, background: preview.errors.length ? 'rgba(239,68,68,0.03)' : 'rgba(16,185,129,0.03)' }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', gap: 12, alignItems: 'center', flexWrap: 'wrap' }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
            <strong>Anteprima modifiche</strong>
            {isReady ? (
              <span style={{ fontSize: 12, background: 'rgba(16,185,129,0.18)', color: '#6ee7b7', border: '1px solid #10b981', padding: '3px 10px', borderRadius: 12, fontWeight: 700 }}>
                ✅ Elaborazione completata al 100% · Pronto per la conferma
              </span>
            ) : (
              <span style={{ fontSize: 12, background: 'rgba(239,68,68,0.18)', color: '#fca5a5', border: '1px solid #ef4444', padding: '3px 10px', borderRadius: 12, fontWeight: 700 }}>
                ⚠️ Errori da risolvere prima di confermare
              </span>
            )}
          </div>
          <span style={{ color: 'var(--text-secondary)', fontSize: 13 }}>
            {preview.counts.create} prezzi nuovi · {preview.counts.update} aggiornati · {preview.counts.unchanged} invariati · {preview.order_name_changes?.length || 0} nomi rapidi
            {autoCreateCount > 0 && <span style={{ color: '#60a5fa', fontWeight: 600 }}> · {autoCreateCount} nuovi prodotti da creare</span>}
            {autoSuppliersCount > 0 && <span style={{ color: '#a78bfa', fontWeight: 600 }}> · {autoSuppliersCount} nuovi fornitori provvisori</span>}
            {' · '}{preview.counts.errors > 0 ? `${preview.counts.errors} errori` : 'Nessun errore'}
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
        {preview.supplier_mapping.filter(item => !item.supplier_id && item.method !== 'auto_create').map(item => (
          <label key={item.header} style={{ display: 'grid', gridTemplateColumns: 'minmax(180px,1fr) 2fr', gap: 12, alignItems: 'center' }}>
            <span>Colonna “{item.header}”</span>
            <select style={input} value={supplierMapping[item.header] ?? ''} onChange={event => setSupplierMapping(current => ({ ...current, [item.header]: Number(event.target.value) }))}>
              <option value="-1">✨ Crea come nuovo fornitore "{item.header}" (provvisorio)</option>
              <option value="" disabled>──────────────</option>
              {matrix?.suppliers.map(supplier => <option key={supplier.id} value={supplier.id}>{supplier.name}</option>)}
            </select>
          </label>
        ))}
        {preview.product_mapping.filter(item => !item.product_id && item.method !== 'auto_create').map(item => (
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
            <thead><tr><th style={{ textAlign: 'left' }}>Prodotto</th><th>Fornitore</th><th>UoM</th><th>Prima</th><th>Dopo</th><th>Esito</th></tr></thead>
            <tbody>{preview.changes.slice(0, 300).map((item, index) => <tr key={index}>
              <td style={{ padding: 8 }}>{item.product_name}</td><td style={{ textAlign: 'center' }}>{item.supplier_name}</td><td style={{ textAlign: 'center', fontWeight: 600, color: '#60a5fa' }}>{item.uom}</td><td style={{ textAlign: 'center' }}>{money(item.old_price)}</td><td style={{ textAlign: 'center' }}>{money(item.new_price)}</td><td style={{ textAlign: 'center' }}>{item.action}</td>
            </tr>)}</tbody>
          </table>
        </div>
        <button
          className="btn btn-primary"
          disabled={!preview.can_commit || loading}
          onClick={commitPreview}
          style={{ padding: '12px 24px', fontSize: 14, fontWeight: 700 }}
        >
          {loading ? '⏳ Salvataggio nel database in corso…' : '✓ Conferma e aggiorna listino'}
        </button>
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
        <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap', alignItems: 'center', paddingTop: 2 }}>
          <span style={{ fontSize: 13, color: 'var(--text-secondary)', fontWeight: 600 }}>Categoria:</span>
          {(() => {
            const totalAll = matrix?.category_counts
              ? Object.values(matrix.category_counts).reduce((a, b) => a + b, 0)
              : (matrix?.total || 0)
            return (
              <button
                type="button"
                className="btn"
                onClick={() => {
                  setOffset(0)
                  setSelectedMatrixCategory('all')
                }}
                style={{
                  padding: '4px 12px',
                  fontSize: 12,
                  borderRadius: 20,
                  background: selectedMatrixCategory === 'all' ? 'var(--primary-color)' : 'rgba(255,255,255,0.05)',
                  color: selectedMatrixCategory === 'all' ? 'white' : 'var(--text-secondary)',
                  border: selectedMatrixCategory === 'all' ? '1px solid var(--primary-color)' : '1px solid var(--border-glass)'
                }}
              >
                Tutte ({totalAll})
              </button>
            )
          })()}
          {MACRO_CATEGORIES.map(cat => {
            const count = matrix?.category_counts?.[cat.id] || 0
            const isSelected = selectedMatrixCategory === cat.id
            return (
              <button
                key={cat.id}
                type="button"
                className="btn"
                onClick={() => {
                  setOffset(0)
                  setSelectedMatrixCategory(cat.id)
                }}
                style={{
                  padding: '4px 12px',
                  fontSize: 12,
                  borderRadius: 20,
                  background: isSelected ? cat.bg : 'rgba(255,255,255,0.05)',
                  color: isSelected ? cat.color : 'var(--text-secondary)',
                  border: isSelected ? `1px solid ${cat.border}` : '1px solid var(--border-glass)',
                  fontWeight: isSelected ? 600 : 400
                }}
              >
                {cat.icon} {cat.label} ({count})
              </button>
            )
          })}
        </div>
        <details><summary style={{ cursor: 'pointer', color: 'var(--text-secondary)' }}>Colonne fornitori ({selectedSupplierIds.length}/{matrix?.suppliers.length || 0})</summary><div style={{ display: 'flex', gap: 12, flexWrap: 'wrap', paddingTop: 12 }}>{matrix?.suppliers.map(supplier => <label key={supplier.id} style={{ fontSize: 13 }}><input type="checkbox" checked={selectedSupplierIds.includes(supplier.id)} onChange={() => setSelectedSupplierIds(current => current.includes(supplier.id) ? current.filter(id => id !== supplier.id) : [...current, supplier.id])} /> {supplier.name}</label>)}</div></details>
        {loading ? <div style={{ padding: 30, textAlign: 'center' }}>Caricamento…</div> : <div style={{ overflow: 'auto', maxHeight: '65vh' }}><table style={{ minWidth: 700, width: '100%', borderCollapse: 'collapse', fontSize: 13 }}>
          <thead style={{ position: 'sticky', top: 0, background: '#11111a', zIndex: 2 }}><tr><th style={{ textAlign: 'left', padding: 12, minWidth: 240 }}>Prodotto principale</th>{visibleSuppliers.map(supplier => <th key={supplier.id} style={{ padding: 12, minWidth: 155 }}>{supplier.name}</th>)}</tr></thead>
          <tbody>{(matrix?.rows || []).map(row => <tr key={row.product_id} style={{ borderTop: '1px solid var(--border-glass)' }}>
            <td style={{ padding: 12 }}>
              <strong>{row.order_name || row.canonical_name}</strong>
              {row.order_name && <div style={{ color: 'var(--text-secondary)', fontSize: 11 }}>{row.canonical_name}</div>}
              <div style={{ color: 'var(--text-secondary)', fontSize: 11, display: 'flex', gap: 6, alignItems: 'center', marginTop: 2 }}>
                <span>{row.sku_interno || 'SKU mancante'}</span>
                <span>·</span>
                <span style={{
                  color: row.category === 'Food' ? '#f59e0b' : row.category === 'Materiali di consumo' ? '#10b981' : '#60a5fa',
                  background: row.category === 'Food' ? 'rgba(245,158,11,0.1)' : row.category === 'Materiali di consumo' ? 'rgba(16,185,129,0.1)' : 'rgba(59,130,246,0.1)',
                  padding: '1px 6px',
                  borderRadius: 4,
                  fontSize: 10,
                  fontWeight: 600
                }}>
                  {row.category || 'Beverage'}
                </span>
              </div>
              {row.requires_manual_selection && <small style={{ color: '#fbbf24' }}>Scelta manuale richiesta</small>}
            </td>
            {visibleSuppliers.map(supplier => {
              const offer = row.offers[String(supplier.id)]
              const relevant = row.eligible_supplier_ids.includes(supplier.id)
              const isForced = row.policy?.selection_mode === 'manual' && row.policy?.preferred_supplier_id === supplier.id
              const isAutoRecommended = (!row.policy || row.policy.selection_mode !== 'manual') && Boolean(offer?.is_recommended)
              const isOtherWhenForced = row.policy?.selection_mode === 'manual' && row.policy?.preferred_supplier_id !== supplier.id

              let borderStyle = '1px solid transparent'
              let bgStyle = 'rgba(255,255,255,.025)'
              let textColor = 'white'

              if (isForced) {
                borderStyle = '2px solid #f59e0b'
                bgStyle = 'rgba(245,158,11,0.15)'
                textColor = '#fde68a'
              } else if (isAutoRecommended) {
                borderStyle = '1px solid #10b981'
                bgStyle = 'rgba(16,185,129,.10)'
                textColor = '#6ee7b7'
              }

              return <td key={supplier.id} style={{ textAlign: 'center', padding: 8, opacity: offer && !offer.eligible ? .55 : 1, background: !relevant ? 'rgba(255,255,255,.012)' : 'transparent' }}>
                {relevant ? <button
                  disabled={!isAdmin}
                  onClick={() => {
                    if (isAdmin) {
                      setEditing({ product: row, supplier, price: offer?.price || '', uom: offer?.uom || row.comparison_unit || 'piece' })
                      setForceLabel(row.policy?.preferred_supplier_id === supplier.id ? (row.policy?.reason || '') : '')
                    }
                  }}
                  style={{
                    width: '100%',
                    padding: '8px 10px',
                    borderRadius: 8,
                    cursor: isAdmin ? 'pointer' : 'default',
                    color: textColor,
                    border: borderStyle,
                    background: bgStyle,
                    display: 'flex',
                    flexDirection: 'column',
                    alignItems: 'center',
                    gap: 3,
                    boxShadow: isForced ? '0 0 12px rgba(245,158,11,0.25)' : 'none'
                  }}
                >
                  {offer ? <>
                    <strong>{money(offer.price)}</strong>
                    <div style={{ fontSize: 10, display: 'flex', flexDirection: 'column', alignItems: 'center', gap: 1 }}>
                      {isForced ? (
                        <span style={{ color: '#fbbf24', fontWeight: 700, background: 'rgba(0,0,0,0.4)', padding: '1px 5px', borderRadius: 4 }}>
                          ⭐ SCELTO {row.policy?.reason ? `· ${row.policy.reason}` : ''}
                        </span>
                      ) : isAutoRecommended ? (
                        <span style={{ color: '#6ee7b7', fontWeight: 600 }}>✓ CONSIGLIATO</span>
                      ) : isOtherWhenForced ? (
                        <span style={{ color: 'var(--text-secondary)' }}>alternativo</span>
                      ) : (
                        <span style={{ color: 'var(--text-secondary)' }}>{offer.source_type}</span>
                      )}
                    </div>
                  </> : <>{isAdmin && <Pencil size={13} />} {isAdmin ? 'inserisci' : '—'}</>}
                </button> : <span title="Fornitore fuori dal settore del prodotto" style={{ color: '#5f6574', fontSize: 11 }}>fuori settore</span>}
              </td>
            })}
          </tr>)}</tbody>
        </table></div>}
        <div style={{ display: 'flex', justifyContent: 'space-between' }}><button className="btn" disabled={offset === 0} onClick={() => setOffset(Math.max(0, offset - 50))}>Indietro</button><button className="btn" disabled={!matrix || offset + 50 >= matrix.total} onClick={() => setOffset(offset + 50)}>Avanti</button></div>
      </div>

      {editing && (
        <div className="glass-panel" style={{ ...panel, border: '1px solid #3b82f6', background: 'rgba(15,23,42,0.95)', boxShadow: '0 20px 40px rgba(0,0,0,0.6)' }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', borderBottom: '1px solid var(--border-glass)', paddingBottom: 12 }}>
            <div>
              <div style={{ fontSize: 11, color: 'var(--text-secondary)', textTransform: 'uppercase', letterSpacing: 1 }}>Configurazione Prodotto & Fornitore</div>
              <h3 style={{ margin: '4px 0 0', fontSize: 17 }}>{editing.product.canonical_name} <span style={{ color: 'var(--text-secondary)', fontWeight: 400 }}>con</span> <span style={{ color: '#60a5fa' }}>{editing.supplier.name}</span></h3>
            </div>
            <button className="btn" onClick={() => setEditing(null)}>Chiudi</button>
          </div>

          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(280px, 1fr))', gap: 20 }}>
            {/* Sezione 1: Modifica Prezzo */}
            <div style={{ display: 'flex', flexDirection: 'column', gap: 10, padding: 14, background: 'rgba(255,255,255,0.02)', borderRadius: 8, border: '1px solid var(--border-glass)' }}>
              <strong>💰 Aggiorna Prezzo Listino</strong>
              <div style={{ display: 'flex', gap: 10 }}>
                <label style={{ flex: 1, display: 'flex', flexDirection: 'column', gap: 4, fontSize: 12 }}>
                  Prezzo (€)
                  <input autoFocus style={input} value={editing.price} onChange={event => setEditing({ ...editing, price: event.target.value })} placeholder="Es. 4.50" />
                </label>
                <label style={{ width: 100, display: 'flex', flexDirection: 'column', gap: 4, fontSize: 12 }}>
                  Unità (UoM)
                  <input style={input} value={editing.uom} onChange={event => setEditing({ ...editing, uom: event.target.value })} placeholder="Pz, Lt, Kg" />
                </label>
              </div>
              <button className="btn btn-primary" onClick={createCellPreview} style={{ alignSelf: 'flex-start' }}><Check size={15} /> Aggiorna Prezzo</button>
            </div>

            {/* Sezione 2: Forza Acquisto & Etichetta */}
            <div style={{ display: 'flex', flexDirection: 'column', gap: 10, padding: 14, background: 'rgba(245,158,11,0.03)', borderRadius: 8, border: '1px solid rgba(245,158,11,0.2)' }}>
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                <strong style={{ color: '#f59e0b' }}>⭐ Forza Acquisto & Etichetta</strong>
                {editing.product.policy?.selection_mode === 'manual' && editing.product.policy?.preferred_supplier_id === editing.supplier.id && (
                  <span style={{ fontSize: 11, background: 'rgba(245,158,11,0.2)', color: '#fbbf24', padding: '2px 8px', borderRadius: 10, fontWeight: 700 }}>ATTUALMENTE FORZATO</span>
                )}
              </div>
              <p style={{ margin: 0, fontSize: 12, color: 'var(--text-secondary)' }}>
                Forzando questo fornitore, il sistema lo sceglierà sempre per questo prodotto con la relativa etichetta.
              </p>
              <label style={{ display: 'flex', flexDirection: 'column', gap: 4, fontSize: 12 }}>
                Etichetta / Motivazione:
                <input
                  style={input}
                  value={forceLabel}
                  onChange={e => setForceLabel(e.target.value)}
                  placeholder="Es. Scelto da Direzione, Qualità top, Consegna rapida"
                />
              </label>
              <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap' }}>
                {['⭐ Scelto da Direzione', '🏆 Qualità Top', '🚀 Consegna Rapida', '📦 Formato Esclusivo'].map(preset => (
                  <button
                    key={preset}
                    type="button"
                    className="btn"
                    onClick={() => setForceLabel(preset)}
                    style={{ fontSize: 11, padding: '4px 8px', background: 'rgba(255,255,255,0.04)' }}
                  >
                    {preset}
                  </button>
                ))}
              </div>
              <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap', marginTop: 4 }}>
                <button
                  type="button"
                  className="btn"
                  onClick={() => handleSetForcedSupplier(editing.product.product_id, editing.supplier.id, forceLabel)}
                  style={{ background: '#f59e0b', color: '#111', fontWeight: 700, border: 'none', padding: '8px 14px' }}
                >
                  ⭐ Forza Acquisto da {editing.supplier.name}
                </button>
                {editing.product.policy?.selection_mode === 'manual' && editing.product.policy?.preferred_supplier_id === editing.supplier.id && (
                  <button
                    type="button"
                    className="btn"
                    onClick={() => handleSetForcedSupplier(editing.product.product_id, null, null)}
                    style={{ color: '#fca5a5' }}
                  >
                    🔄 Ripristina Automatico
                  </button>
                )}
              </div>
            </div>
          </div>
        </div>
      )}

      <PreviewPanel />
    </>}

    {activeTab === 'paste' && <>
      <div className="glass-panel" style={{ ...panel, gap: 14 }}>
        {/* 3 Category Sheets Switcher */}
        <div style={{ display: 'flex', gap: 10, flexWrap: 'wrap', padding: '12px 14px', background: 'rgba(255,255,255,0.025)', borderRadius: 10, border: '1px solid var(--border-glass)', alignItems: 'center' }}>
          <span style={{ fontSize: 13, fontWeight: 700, color: 'white', marginRight: 4 }}>Seleziona Foglio da compilare:</span>
          {MACRO_CATEGORIES.map(cat => {
            const isSelected = activeCategorySheet === cat.id
            const rowCount = Math.max(0, (categorySheets[cat.id]?.length || 1) - 1)
            return (
              <button
                key={cat.id}
                type="button"
                onClick={() => {
                  setActiveCategorySheet(cat.id as MacroCategory)
                  setPreview(null)
                  setError(null)
                }}
                style={{
                  padding: '8px 16px',
                  borderRadius: 8,
                  border: isSelected ? `2px solid ${cat.border}` : '1px solid rgba(255,255,255,0.08)',
                  background: isSelected ? cat.bg : 'rgba(255,255,255,0.03)',
                  color: isSelected ? 'white' : 'var(--text-secondary)',
                  cursor: 'pointer',
                  fontSize: 13,
                  fontWeight: isSelected ? 700 : 500,
                  display: 'flex',
                  alignItems: 'center',
                  gap: 8,
                  transition: 'all 0.2s ease',
                  boxShadow: isSelected ? `0 0 16px ${cat.bg}` : 'none'
                }}
              >
                <span style={{ fontSize: 16 }}>{cat.icon}</span>
                <span>Foglio <b>{cat.label}</b></span>
                {rowCount > 0 && <span style={{ fontSize: 11, background: 'rgba(0,0,0,0.35)', padding: '2px 7px', borderRadius: 10, color: cat.color }}>{rowCount} righe</span>}
              </button>
            )
          })}
        </div>

        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', gap: 14, flexWrap: 'wrap' }}>
          <div>
            <h3 style={{ margin: 0, display: 'flex', alignItems: 'center', gap: 8 }}>
              <span>Foglio Prezzi</span>
              <span style={{ fontSize: 13, fontWeight: 600, color: activeCategorySheet === 'Food' ? '#f59e0b' : activeCategorySheet === 'Materiali di consumo' ? '#10b981' : '#60a5fa', background: activeCategorySheet === 'Food' ? 'rgba(245,158,11,0.12)' : activeCategorySheet === 'Materiali di consumo' ? 'rgba(16,185,129,0.12)' : 'rgba(59,130,246,0.12)', padding: '2px 10px', borderRadius: 6, border: '1px solid var(--border-glass)' }}>
                Settore: {activeCategorySheet}
              </span>
            </h3>
            <p style={{ color: 'var(--text-secondary)', margin: '5px 0 0' }}>
              Colonna A = nome rapido facoltativo. Colonna B = nome reale del prodotto. Colonna C = Unità di misura (UoM). Da D in poi = fornitori.
            </p>
          </div>
          <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
            <button className="btn" onClick={reloadCurrentPrices}><RotateCcw size={15} /> Prezzi correnti {activeCategorySheet}</button>
            <button className="btn" onClick={clearSheet}><Trash2 size={15} /> Svuota</button>
          </div>
        </div>

        <div style={{ border: '1px solid var(--border-glass)', borderRadius: 10, overflow: 'auto', maxHeight: '58vh', background: 'rgba(5,7,14,.55)' }}>
          <table style={{ borderCollapse: 'separate', borderSpacing: 0, width: 'max-content', minWidth: '100%', fontSize: 13 }}>
            <thead style={{ position: 'sticky', top: 0, zIndex: 5 }}>
              <tr>
                <th style={{ width: 44, minWidth: 44, height: 28, position: 'sticky', left: 0, zIndex: 7, background: '#171923', borderRight: '1px solid #343745', borderBottom: '1px solid #343745' }} />
                {sheet[0]?.map((_, columnIndex) => <th key={columnIndex} style={{ minWidth: columnIndex === 0 ? 170 : columnIndex === 1 ? 260 : columnIndex === 2 ? 110 : 150, height: 28, padding: '0 8px', textAlign: 'center', color: '#9ca3af', background: '#171923', borderRight: '1px solid #343745', borderBottom: '1px solid #343745', fontWeight: 600 }}>{columnLabel(columnIndex)}</th>)}
              </tr>
            </thead>
            <tbody>
              {sheet.map((row, rowIndex) => <tr key={rowIndex}>
                <th style={{ width: 44, minWidth: 44, height: 36, position: 'sticky', left: 0, zIndex: 4, textAlign: 'center', color: '#9ca3af', background: '#171923', borderRight: '1px solid #343745', borderBottom: '1px solid #292c37', fontWeight: 500 }}>{rowIndex + 1}</th>
                {row.map((cell, columnIndex) => {
                  const eligible = isSheetCellEligible(rowIndex, columnIndex)
                  const width = columnIndex === 0 ? 170 : columnIndex === 1 ? 260 : columnIndex === 2 ? 110 : 150
                  return <td key={columnIndex} style={{ padding: 0, minWidth: width, borderRight: '1px solid #292c37', borderBottom: '1px solid #292c37', background: !eligible ? 'rgba(70,70,80,.16)' : rowIndex === 0 ? 'rgba(59,130,246,.10)' : columnIndex < 3 ? 'rgba(255,255,255,.025)' : 'transparent' }}>
                    <input
                      aria-label={`Cella ${columnLabel(columnIndex)}${rowIndex + 1}`}
                      value={cell}
                      disabled={!eligible}
                      title={!eligible ? 'Fornitore fuori dal settore di questo prodotto' : undefined}
                      onChange={event => updateSheetCell(rowIndex, columnIndex, event.target.value)}
                      onPaste={event => pasteIntoSheet(event, rowIndex, columnIndex)}
                      placeholder={rowIndex === 0 ? (columnIndex === 0 ? 'Nome rapido (facoltativo)' : columnIndex === 1 ? 'Prodotto reale' : columnIndex === 2 ? 'Unità di misura' : 'Nome fornitore') : columnIndex === 0 ? 'Es. GUANTI' : columnIndex === 1 ? 'Descrizione reale del prodotto' : columnIndex === 2 ? 'Es. Pz, Lt, Kg' : eligible ? '—' : 'fuori settore'}
                      style={{ width: '100%', minWidth: width, height: 36, boxSizing: 'border-box', padding: '0 10px', border: 0, outline: 'none', color: eligible ? 'white' : '#5f6574', background: 'transparent', fontWeight: rowIndex === 0 || columnIndex < 3 ? 600 : 400, textAlign: columnIndex > 2 && rowIndex > 0 ? 'right' : 'left', cursor: eligible ? 'text' : 'not-allowed' }}
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
          <span style={{ alignSelf: 'center', color: 'var(--text-secondary)', fontSize: 12 }}>{sheet.length - 1} righe · {Math.max(0, (sheet[0]?.length || 3) - 3)} colonne fornitore</span>
        </div>

        <div style={{ display: 'flex', gap: 12, flexWrap: 'wrap', alignItems: 'center', paddingTop: 4 }}>
          <label style={{ display: 'flex', flexDirection: 'column', gap: 5, fontSize: 13 }}>Validità <input type="date" style={input} value={effectiveDate} onChange={event => setEffectiveDate(event.target.value)} /></label>
          <label style={{ display: 'flex', flexDirection: 'column', gap: 5, fontSize: 13 }}>Unità fallback (nuovi) <input style={{ ...input, width: 90 }} value={defaultUom} onChange={event => setDefaultUom(event.target.value)} placeholder="Pz" /></label>
          <label style={{ display: 'flex', gap: 8, alignItems: 'center', fontSize: 13, cursor: 'pointer', background: autoCreateProducts ? 'rgba(59,130,246,.12)' : 'rgba(255,255,255,.03)', padding: '9px 12px', borderRadius: 8, border: autoCreateProducts ? '1px solid #3b82f6' : '1px solid var(--border-glass)', alignSelf: 'flex-end' }}>
            <input type="checkbox" checked={autoCreateProducts} onChange={e => setAutoCreateProducts(e.target.checked)} />
            <span style={{ color: autoCreateProducts ? '#93c5fd' : 'inherit' }}>✨ <b>Crea automaticamente</b> prodotti mancanti</span>
          </label>
          <button className="btn btn-primary" disabled={(!hasSheetPrices && !hasOrderNames) || loading} onClick={createPastePreview} style={{ alignSelf: 'flex-end' }}><ClipboardPaste size={16} /> Controlla modifiche</button>
          <span style={{ color: 'var(--text-secondary)', fontSize: 12, maxWidth: 350 }}>
            L'unità di misura viene determinata dalla colonna <b>C (Unità di misura)</b> o dall'anagrafica.
          </span>
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

    {activeTab === 'history' && <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit,minmax(360px,1fr))', gap: 16 }}><div className="glass-panel" style={panel}><h3 style={{ margin: 0 }}>Versioni prezzo</h3><div style={{ maxHeight: 520, overflow: 'auto' }}>{historyRows.map(item => <div key={item.id} style={{ padding: '10px 0', borderBottom: '1px solid var(--border-glass)', fontSize: 13 }}><strong>{item.description}</strong> · {item.supplier_name}<div style={{ color: 'var(--text-secondary)' }}>{money(item.price)} / {item.uom} · {item.valid_from} → {item.valid_to || 'attivo'}</div></div>)}</div></div><div className="glass-panel" style={panel}><h3 style={{ margin: 0 }}>Audit regole</h3><div style={{ maxHeight: 300, overflow: 'auto' }}>{auditRows.map((item, index) => <div key={`${item.entity_type}-${item.entity_id}-${index}`} style={{ padding: '10px 0', borderBottom: '1px solid var(--border-glass)', fontSize: 13 }}>{item.entity_type} #{item.entity_id} · {item.action}<div style={{ color: 'var(--text-secondary)' }}>{new Date(item.occurred_at).toLocaleString('it-IT')} · utente #{item.actor_id}</div></div>)}</div><h3>Scostamenti policy ({deviations.length})</h3>{deviations.slice(0, 20).map(item => <div key={item.id} style={{ color: '#fbbf24', fontSize: 13, padding: '8px 0' }}><div>{item.deviation_type}: {item.reason} · <b>{item.status}</b></div>{item.status === 'open' && <div style={{ display: 'flex', gap: 8, marginTop: 6 }}><button className="btn" onClick={() => updateDeviation(item.id, 'acknowledged')}>Presa in carico</button><button className="btn" onClick={() => updateDeviation(item.id, 'accepted_exception')}>Accetta eccezione</button></div>}</div>)}</div></div>}
  </div>
}
