import { useEffect, useMemo, useState } from 'react'
import { AlertTriangle, Building2, Check, ClipboardPaste, Download, History, Pencil, Plus, RefreshCw, RotateCcw, Search, Table2, Trash2 } from 'lucide-react'
import { API_BASE, fetchWithAuth, getHeaders } from '../api'

type Supplier = { id: number; name: string; vat: string }
type Product = { id: number; sku_interno?: string | null; canonical_name: string; order_name?: string | null }
type Offer = {
  supplier_id: number
  supplier_name: string
  price: string
  uom?: string | null
  source_type: 'contratto' | 'spot'
  // Prezzo nell'unità di confronto della voce; null = fuori classifica.
  unit_price_normalized?: string | null
  comparison_reliable?: boolean
  conversion_note?: string | null
  invoice_date?: string | null
  stale?: boolean
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
  subcategory?: string | null
  comparison_unit: string
  acquisti?: number
  spesa?: string
  ultimo_acquisto?: string | null
  quantita?: string
  quantita_unita?: string | null
  quantita_non_convertita?: Record<string, string>
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
  subcategory_counts?: Record<string, number>
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
    old_uom?: string | null
    action: 'create' | 'update' | 'unchanged'
  }>
  errors: Array<{ type: string; row?: number; header?: string; reference?: string; message: string; supplier_id?: number; category?: string | null }>
  warnings?: Array<{ type: string; row?: number; message: string }>
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
const input: React.CSSProperties = { padding: '10px 12px', background: 'var(--bg-inset)', color: 'var(--text-primary)', border: '1px solid var(--line)', borderRadius: 'var(--radius-sm)' }
const tabs = [
  { id: 'matrix', label: 'Matrice', icon: Table2 },
  { id: 'paste', label: 'Foglio prezzi', icon: ClipboardPaste },
  { id: 'sectors', label: 'Settori fornitori', icon: Building2 },
  { id: 'history', label: 'Storico e audit', icon: History },
] as const

type MatrixSort = 'nome' | 'acquisti' | 'spesa' | 'quantita'
type MatrixPeriod = 'tutto' | '12m'
const MATRIX_SORT_KEY = 'smartPriceSheet.matrixSort'

function readMatrixSort(): MatrixSort {
  try {
    const stored = window.localStorage.getItem(MATRIX_SORT_KEY)
    return stored === 'acquisti' || stored === 'spesa' || stored === 'quantita' ? stored : 'nome'
  } catch {
    return 'nome'
  }
}

function storeMatrixSort(value: MatrixSort) {
  try {
    window.localStorage.setItem(MATRIX_SORT_KEY, value)
  } catch {
    // storage non disponibile: la scelta vale solo per questa sessione
  }
}

function euro(value?: string | null) {
  const amount = Number(value || 0)
  return amount ? amount.toLocaleString('it-IT', { style: 'currency', currency: 'EUR' }) : '—'
}

function italianQuantity(value?: string | number | null) {
  return Number(value || 0).toLocaleString('it-IT', { maximumFractionDigits: 3 })
}

function quantityLabel(row: { quantita?: string; quantita_unita?: string | null }) {
  const amount = Number(row.quantita || 0)
  if (!amount) return '—'
  return row.quantita_unita ? `${italianQuantity(amount)} ${row.quantita_unita}` : italianQuantity(amount)
}

function notConvertedTitle(row: { quantita_non_convertita?: Record<string, string> }) {
  const parts = Object.entries(row.quantita_non_convertita || {}).map(([unit, qty]) => `${italianQuantity(qty)} ${unit}`)
  return parts.length ? `${parts.join(' + ')} non convertibili nell'unità del prodotto` : ''
}

function italianDate(value?: string | null) {
  if (!value) return '—'
  const [year, month, day] = value.slice(0, 10).split('-')
  return `${day}/${month}/${year}`
}

function money(value?: string | null) {
  return value ? `€ ${Number(value).toLocaleString('it-IT', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}` : '—'
}

function shortDate(value?: string | null) {
  if (!value) return ''
  const [year, month, day] = value.slice(0, 10).split('-')
  return `${day}/${month}/${year}`
}

// Stessa famiglia di unità del backend (services.normalization.unit_family):
// Pz = pezzo/bottiglia, CT = qualsiasi confezione, Kg, Lt. null = vuota o sconosciuta.
const UNIT_FAMILIES: Record<string, string> = {}
for (const [family, spellings] of Object.entries({
  Pz: ['pz', 'pezzo', 'pezzi', 'piece', 'pieces', 'unita', 'unit', 'nr', 'n', 'numero', 'bt', 'btl', 'bot', 'bottiglia', 'bottiglie', 'bottle', 'fl'],
  CT: ['ct', 'cartone', 'cartoni', 'cs', 'css', 'cassa', 'casse', 'crt', 'box', 'cf', 'cnf', 'conf', 'confezione', 'confezioni'],
  Kg: ['kg', 'k', 'kgm', 'kgs', 'kilo', 'chilo', 'chili', 'chilogrammi', 'chilogrammo', 'kilogrammi'],
  Lt: ['l', 'lt', 'ltr', 'litro', 'litri', 'liter', 'litre'],
})) for (const spelling of spellings) UNIT_FAMILIES[spelling] = family

function unitFamily(value?: string | null): string | null {
  const key = (value || '').normalize('NFD').replace(/[̀-ͯ]/g, '').toLowerCase().replace(/\s+/g, '').replace(/^\.+|\.+$/g, '')
  return key ? UNIT_FAMILIES[key] || null : null
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
        ? 'Nome informale / rapido ordine (facoltativo)'
        : rowIndex === 0 && columnIndex === 1
        ? 'Prodotto reale'
        : rowIndex === 0 && columnIndex === 2
        ? 'Unità di misura'
        : '',
    ),
  )
}

type SheetHints = Record<string, string>

// Precarica SOLO i listini già espressi nella famiglia di unità della colonna C.
// Gli spot (prezzi di fattura), i listini senza unità o in un'altra unità restano
// celle vuote con il prezzo come suggerimento: una cella vuota non scrive nulla,
// mentre un valore precaricato verrebbe letto come prezzo nell'unità della colonna C.
function sheetFromMatrix(matrix: MatrixResponse): { grid: string[][]; hints: SheetHints } {
  const suppliers = matrix.suppliers || []
  const hints: SheetHints = {}
  const rows = [
    ['Nome informale / rapido ordine (facoltativo)', 'Prodotto reale', 'Unità di misura', ...suppliers.map(supplier => supplier.name)],
    ...matrix.rows.map((row, index) => {
      const columnC = row.comparison_unit || 'Pz'
      return [
        row.order_name || '',
        row.canonical_name,
        columnC,
        ...suppliers.map((supplier, supplierIndex) => {
          const offer = row.offers[String(supplier.id)]
          if (!offer) return ''
          const family = unitFamily(offer.uom)
          if (offer.source_type === 'contratto' && family && family === unitFamily(columnC)) return offer.price
          const key = `${index + 1}:${supplierIndex + 3}`
          hints[key] = offer.source_type === 'spot'
            ? `fattura ${money(offer.price)}${offer.uom ? ` / ${offer.uom}` : ''}`
            : `listino ${money(offer.price)} / ${offer.uom || 'unità mancante'}`
          return ''
        }),
      ]
    }),
  ]
  const rowCount = Math.max(MIN_SHEET_ROWS, rows.length)
  const columnCount = Math.max(MIN_SHEET_COLUMNS, suppliers.length + 3)
  const grid = Array.from({ length: rowCount }, (_, rowIndex) =>
    Array.from({ length: columnCount }, (_, columnIndex) => rows[rowIndex]?.[columnIndex] || ''),
  )
  return { grid, hints }
}

// Testo per l'anteprima con le sole celle modificate rispetto al foglio precaricato.
// Senza foglio precaricato (foglio vuoto o incollato) si invia tutto come prima.
function changedSheetForPreview(sheet: string[][], baseline?: string[][]): { text: string; changedCells: number; changedOrderNames: number } {
  const value = (grid: string[][] | undefined, row: number, column: number) => (grid?.[row]?.[column] || '').trim()
  if (!baseline) {
    const changedCells = sheet.slice(1).reduce((total, row) => total + row.slice(3).filter(cell => cell.trim()).length, 0)
    const changedOrderNames = sheet.slice(1).filter(row => row[0]?.trim()).length
    return { text: sheetText(sheet), changedCells, changedOrderNames }
  }
  const width = sheet[0]?.length || 0
  const columnMoved = (column: number) => value(sheet, 0, column) !== value(baseline, 0, column)
  const rowMoved = (row: number) => value(sheet, row, 1) !== value(baseline, row, 1)
  const cellChanged = (row: number, column: number) => {
    const current = value(sheet, row, column)
    return Boolean(current) && (rowMoved(row) || columnMoved(column) || current !== value(baseline, row, column))
  }
  const orderChanged = (row: number) => Boolean(value(sheet, row, 0)) && (rowMoved(row) || value(sheet, row, 0) !== value(baseline, row, 0))
  const keptRows: number[] = []
  const keptColumns = new Set<number>()
  let changedCells = 0
  let changedOrderNames = 0
  for (let row = 1; row < sheet.length; row += 1) {
    let keep = false
    for (let column = 3; column < width; column += 1) {
      if (cellChanged(row, column)) { keep = true; keptColumns.add(column); changedCells += 1 }
    }
    if (orderChanged(row)) { keep = true; changedOrderNames += 1 }
    if (keep) keptRows.push(row)
  }
  const columns = [0, 1, 2, ...Array.from(keptColumns).sort((a, b) => a - b)]
  const lines = [
    columns.map(column => sheet[0][column] || '').join('\t'),
    ...keptRows.map(row => columns.map(column => {
      if (column === 0) return orderChanged(row) ? value(sheet, row, 0) : ''
      if (column < 3) return value(sheet, row, column)
      return cellChanged(row, column) ? value(sheet, row, column) : ''
    }).join('\t')),
  ]
  return { text: lines.join('\n'), changedCells, changedOrderNames }
}

async function fetchAllMatrixPages(category: string, subcategory?: string): Promise<MatrixResponse> {
  // Food ha 968 voci attive: una sola pagina da 500 ne perdeva 468.
  const base = `/smart-price-sheet/matrix?limit=500&category=${encodeURIComponent(category)}${subcategory && subcategory !== 'all' ? `&subcategory=${encodeURIComponent(subcategory)}` : ''}`
  const first = await fetchWithAuth(`${base}&offset=0`) as MatrixResponse
  const rows = [...first.rows]
  while (rows.length < first.total) {
    const next = await fetchWithAuth(`${base}&offset=${rows.length}`) as MatrixResponse
    if (!next.rows.length) break
    rows.push(...next.rows)
  }
  return { ...first, rows }
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
  // Keep this selector limited to the sectors used by the active purchasing workflow.
  { id: 'Beverage', label: 'Beverage', icon: '🍹', color: 'var(--accent-text)', bg: 'var(--accent-bg)', border: 'var(--accent)' },
  { id: 'Food', label: 'Food', icon: '🍽️', color: 'var(--warn)', bg: 'var(--warn-bg)', border: 'var(--warn)' },
  { id: 'Materiali', label: 'Materiali di consumo', icon: '📦', color: 'var(--ok)', bg: 'var(--ok-bg)', border: 'var(--ok)' },
  { id: 'Attrezzatura', label: 'Attrezzatura', icon: '🔧', color: 'var(--info)', bg: 'var(--info-bg)', border: 'var(--info)' },
  { id: 'Gelati confezionati', label: 'Gelati confezionati', icon: '🍦', color: 'var(--info)', bg: 'var(--info-bg)', border: 'var(--info)' },
] as const

type MacroCategory = typeof MACRO_CATEGORIES[number]['id']
const MATRIX_PAGE_SIZE = 100

export default function SmartPriceSheet({ isAdmin }: { isAdmin: boolean }) {
  const [activeTab, setActiveTab] = useState<(typeof tabs)[number]['id']>('matrix')
  const [matrix, setMatrix] = useState<MatrixResponse | null>(null)
  const [selectedMatrixCategory, setSelectedMatrixCategory] = useState<string>('all')
  const [selectedMatrixSubcategory, setSelectedMatrixSubcategory] = useState<string>('all')
  const [allSubcategories, setAllSubcategories] = useState<Array<{ id: number; categoria_nome: string; nome: string }>>([])
  const [sheetCatalog, setSheetCatalog] = useState<MatrixResponse | null>(null)
  const [products, setProducts] = useState<Product[]>([])
  const [search, setSearch] = useState('')
  const [offset, setOffset] = useState(0)
  const [matrixSort, setMatrixSort] = useState<MatrixSort>(readMatrixSort)
  const [matrixPeriod, setMatrixPeriod] = useState<MatrixPeriod>('tutto')
  const [selectedSupplierIds, setSelectedSupplierIds] = useState<number[]>([])
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [notice, setNotice] = useState<string | null>(null)

  const [activeCategorySheet, setActiveCategorySheet] = useState<MacroCategory>('Beverage')
  const [activeSubcategorySheet, setActiveSubcategorySheet] = useState<string>('all')
  const [categorySheets, setCategorySheets] = useState<Record<string, string[][]>>(
    () => Object.fromEntries(MACRO_CATEGORIES.map(category => [category.id, blankSheet()])),
  )
  // Foglio come è stato precaricato (per inviare solo le celle modificate) e
  // suggerimenti delle celle lasciate vuote (spot e listini in un'altra unità).
  const [sheetBaselines, setSheetBaselines] = useState<Record<string, string[][]>>({})
  const [sheetHints, setSheetHints] = useState<Record<string, SheetHints>>({})

  const currentSheetKey = activeSubcategorySheet !== 'all' ? `${activeCategorySheet}:${activeSubcategorySheet}` : activeCategorySheet
  const sheet = categorySheets[currentSheetKey] || blankSheet()
  const currentHints = sheetHints[currentSheetKey] || {}
  const sheetChanges = useMemo(
    () => changedSheetForPreview(sheet, sheetBaselines[currentSheetKey]),
    [sheet, sheetBaselines, currentSheetKey],
  )

  function storeLoadedSheet(key: string, data: MatrixResponse) {
    const { grid, hints } = sheetFromMatrix(data)
    setCategorySheets(prev => ({ ...prev, [key]: grid }))
    setSheetBaselines(prev => ({ ...prev, [key]: grid }))
    setSheetHints(prev => ({ ...prev, [key]: hints }))
  }

  function setSheet(updater: string[][] | ((current: string[][]) => string[][])) {
    setCategorySheets(prev => {
      const current = prev[currentSheetKey] || blankSheet()
      const next = typeof updater === 'function' ? updater(current) : updater
      return { ...prev, [currentSheetKey]: next }
    })
  }

  const [sheetInitialized, setSheetInitialized] = useState(false)
  const [effectiveDate, setEffectiveDate] = useState(new Date().toISOString().slice(0, 10))
  const [defaultUom, setDefaultUom] = useState('Pz')
  const [autoCreateProducts, setAutoCreateProducts] = useState(false)
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

  async function loadSubcategoriesList() {
    try {
      const data = await fetchWithAuth('/categories/subcategories') as Array<{ id: number; categoria_nome: string; nome: string }>
      if (Array.isArray(data)) setAllSubcategories(data)
    } catch (err) {
      console.error(err)
    }
  }

  useEffect(() => {
    void loadSubcategoriesList()
  }, [])

  async function loadMatrix(customOffset?: number, customCategory?: string, customSubcategory?: string) {
    setLoading(true)
    setError(null)
    try {
      const currentOffset = customOffset !== undefined ? customOffset : offset
      const currentCat = customCategory !== undefined ? customCategory : selectedMatrixCategory
      const currentSubcat = customSubcategory !== undefined ? customSubcategory : selectedMatrixSubcategory
      const query = new URLSearchParams({ limit: String(MATRIX_PAGE_SIZE), offset: String(currentOffset) })
      if (search.trim()) query.set('search', search.trim())
      if (currentCat && currentCat !== 'all') query.set('category', currentCat)
      if (currentSubcat && currentSubcat !== 'all') query.set('subcategory', currentSubcat)
      query.set('sort', matrixSort)
      if (matrixPeriod !== 'tutto') query.set('periodo', matrixPeriod)
      const data = await fetchWithAuth(`/smart-price-sheet/matrix?${query}`) as MatrixResponse
      setMatrix(data)
      setSelectedSupplierIds(data.suppliers.map(item => item.id))
    } catch (err) {
      setError(errorMessage(err))
    } finally {
      setLoading(false)
    }
  }

  const [exporting, setExporting] = useState(false)
  async function exportMatrix() {
    setExporting(true)
    setError(null)
    try {
      const query = new URLSearchParams()
      if (search.trim()) query.set('search', search.trim())
      if (selectedMatrixCategory && selectedMatrixCategory !== 'all') query.set('category', selectedMatrixCategory)
      if (selectedMatrixSubcategory && selectedMatrixSubcategory !== 'all') query.set('subcategory', selectedMatrixSubcategory)
      query.set('sort', matrixSort)
      if (matrixPeriod !== 'tutto') query.set('periodo', matrixPeriod)
      const response = await fetch(`${API_BASE}/smart-price-sheet/matrix/export?${query}`, { headers: getHeaders() })
      if (!response.ok) throw new Error(`Export non riuscito (${response.status})`)
      const name = /filename="([^"]+)"/.exec(response.headers.get('Content-Disposition') || '')?.[1] || 'listino_smart.xlsx'
      const url = URL.createObjectURL(await response.blob())
      const link = document.createElement('a')
      link.href = url
      link.download = name
      document.body.appendChild(link)
      link.click()
      link.remove()
      URL.revokeObjectURL(url)
    } catch (err) {
      setError(errorMessage(err))
    } finally {
      setExporting(false)
    }
  }

  const subcategoriesForSelectedMatrix = useMemo(() => {
    if (selectedMatrixCategory === 'all') return []
    return allSubcategories.filter(s => s.categoria_nome.toLowerCase() === selectedMatrixCategory.toLowerCase())
  }, [allSubcategories, selectedMatrixCategory])

  const subcategoriesForActiveSheet = useMemo(() => {
    return allSubcategories.filter(s => s.categoria_nome.toLowerCase() === activeCategorySheet.toLowerCase())
  }, [allSubcategories, activeCategorySheet])

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
      const loaded = await Promise.all(MACRO_CATEGORIES.map(category => fetchAllMatrixPages(category.id)))
      MACRO_CATEGORIES.forEach((category, index) => storeLoadedSheet(category.id, loaded[index]))
      setSheetInitialized(true)
      setNotice(`Fogli precaricati con i soli listini nell'unità della colonna C: ${MACRO_CATEGORIES.map((category, index) => `${category.label} (${loaded[index].rows.length})`).join(', ')}. Spot e listini in un'altra unità restano vuoti con il prezzo come suggerimento.`)
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
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [offset, selectedMatrixCategory, matrixSort, matrixPeriod])
  useEffect(() => {
    if (activeTab === 'paste') void loadProducts()
    if (activeTab === 'sectors') void loadSupplierSectors()
    if (activeTab === 'history') void loadHistory()
  // Tab activation is the only trigger; loaders handle their own cached state.
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [activeTab])

  useEffect(() => {
    if (activeTab === 'paste' && !sheetInitialized) {
      void loadFullPriceSheet()
    }
  }, [activeTab, sheetInitialized])

  useEffect(() => {
    if (activeTab === 'paste') {
      const key = activeSubcategorySheet !== 'all' ? `${activeCategorySheet}:${activeSubcategorySheet}` : activeCategorySheet
      const existing = categorySheets[key]
      const hasHeaders = existing && existing[0]?.slice(3).some(cell => cell.trim())
      if (!hasHeaders) {
        void reloadCurrentPrices(activeCategorySheet, activeSubcategorySheet)
      }
    }
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [activeTab, activeCategorySheet, activeSubcategorySheet])

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
          // Solo le celle modificate: un prezzo precaricato e non toccato non si riscrive.
          text: sheetChanges.text,
          supplier_mapping: supplierMapping,
          product_mapping: productMapping,
          effective_date: effectiveDate,
          default_uom: defaultUom,
          create_missing_products: autoCreateProducts,
          category: activeCategorySheet,
          subcategory: activeSubcategorySheet !== 'all' ? activeSubcategorySheet : undefined,
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
      ? `${pastedRows.length} righe incollate nel foglio ${activeCategorySheet}${activeSubcategorySheet !== 'all' ? ` · ${activeSubcategorySheet}` : ''} · ${skipped} celle fuori settore ignorate.`
      : `Incollate ${pastedRows.length} righe nel foglio ${activeCategorySheet}${activeSubcategorySheet !== 'all' ? ` · ${activeSubcategorySheet}` : ''}.`)
  }

  async function reloadCurrentPrices(targetCat?: MacroCategory, targetSub?: string) {
    const cat = targetCat || activeCategorySheet
    const sub = targetSub !== undefined ? targetSub : activeSubcategorySheet
    const key = sub !== 'all' ? `${cat}:${sub}` : cat

    setLoading(true); setError(null)
    try {
      const data = await fetchAllMatrixPages(cat, sub)
      setSheetCatalog(data)
      storeLoadedSheet(key, data)
      const suppCount = data.suppliers?.length || 0
      setNotice(`Foglio "${cat}${sub !== 'all' ? ` · ${sub}` : ''}" caricato con ${data.rows.length} prodotti attivi e ${suppCount} fornitori collegati.`)
    } catch (err) {
      setError(errorMessage(err))
    } finally {
      setLoading(false)
    }
  }

  function clearSheet() {
    setSheet(current => {
      const headerRow = current[0] || []
      const rowCount = Math.max(MIN_SHEET_ROWS, current.length)
      const colCount = Math.max(MIN_SHEET_COLUMNS, headerRow.length)
      return Array.from({ length: rowCount }, (_, rowIndex) =>
        Array.from({ length: colCount }, (_, columnIndex) => (rowIndex === 0 ? headerRow[columnIndex] || '' : ''))
      )
    })
    setPreview(null); setSupplierMapping({}); setProductMapping({})
  }

  const hasSheetPrices = sheetChanges.changedCells > 0
  const hasOrderNames = sheetChanges.changedOrderNames > 0

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
      <div className="glass-panel" style={{ ...panel, border: `1px solid ${preview.errors.length ? 'var(--crit)' : 'var(--ok)'}`, background: preview.errors.length ? 'var(--crit-bg)' : 'var(--ok-bg)' }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', gap: 12, alignItems: 'center', flexWrap: 'wrap' }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
            <strong>Anteprima modifiche</strong>
            {isReady ? (
              <span style={{ fontSize: 12, background: 'var(--ok-bg)', color: 'var(--ok)', border: '1px solid var(--ok)', padding: '3px 10px', borderRadius: '999px', fontWeight: 700 }}>
                ✅ Elaborazione completata al 100% · Pronto per la conferma
              </span>
            ) : (
              <span style={{ fontSize: 12, background: 'var(--crit-bg)', color: 'var(--crit)', border: '1px solid var(--crit)', padding: '3px 10px', borderRadius: '999px', fontWeight: 700 }}>
                ⚠️ Errori da risolvere prima di confermare
              </span>
            )}
          </div>
          <span style={{ color: 'var(--text-secondary)', fontSize: 13 }}>
            {preview.counts.create} prezzi nuovi · {preview.counts.update} aggiornati · {preview.counts.unchanged} invariati · {preview.order_name_changes?.length || 0} nomi rapidi
            {autoCreateCount > 0 && <span style={{ color: 'var(--accent-text)', fontWeight: 600 }}> · {autoCreateCount} nuovi prodotti da creare</span>}
            {autoSuppliersCount > 0 && <span style={{ color: 'var(--info)', fontWeight: 600 }}> · {autoSuppliersCount} nuovi fornitori provvisori</span>}
            {' · '}{preview.counts.errors > 0 ? `${preview.counts.errors} errori` : 'Nessun errore'}
          </span>
        </div>
        {preview.errors.map((item, index) => (
          <div key={index} style={{ color: 'var(--crit)', fontSize: 13, display: 'flex', gap: 10, alignItems: 'center', flexWrap: 'wrap' }}>
            <span>Riga {item.row || '—'}: {item.message}</span>
            {item.type === 'supplier_scope' && item.supplier_id && item.category && <button className="btn" onClick={() => {
              setSectorSupplierId(item.supplier_id || '')
              setActiveTab('sectors')
              setPreview(null)
              void loadSupplierSectors(item.supplier_id)
            }}><Building2 size={14} /> Configura settore</button>}
          </div>
        ))}
        {(preview.warnings || []).map((item, index) => (
          <div key={`w${index}`} style={{ color: 'var(--warn)', fontSize: 13 }}>Riga {item.row || '—'}: {item.message}</div>
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
        {!!preview.order_name_changes?.length && <div style={{ padding: 12, borderRadius: 8, background: 'var(--accent-bg)', fontSize: 13 }}>
          <strong>Nomi rapidi da aggiornare</strong>
          {preview.order_name_changes.map(item => <div key={item.product_id} style={{ color: 'var(--text-secondary)', marginTop: 5 }}>{item.canonical_name}: {item.old_order_name || 'nessuno'} → <b style={{ color: 'var(--text-primary)' }}>{item.new_order_name}</b></div>)}
        </div>}
        {(preview.errors.length > 0) && <button className="btn" onClick={createPastePreview}>Ricalcola anteprima</button>}
        <div style={{ maxHeight: 280, overflow: 'auto' }}>
          <table className="ds-table" style={{ width: '100%', borderCollapse: 'collapse', fontSize: 13 }}>
            <thead><tr><th style={{ textAlign: 'left' }}>Prodotto</th><th>Fornitore</th><th>UoM</th><th>Prima</th><th>Dopo</th><th>Esito</th></tr></thead>
            <tbody>{preview.changes.slice(0, 300).map((item, index) => <tr key={index}>
              <td style={{ padding: 8 }}>{item.product_name}</td><td style={{ textAlign: 'center' }}>{item.supplier_name}</td><td style={{ textAlign: 'center', fontWeight: 600, color: 'var(--accent-text)' }}>{item.old_uom && item.old_uom !== item.uom ? `${item.old_uom} → ${item.uom}` : item.uom}</td><td style={{ textAlign: 'center', fontFamily: 'var(--font-mono)', fontVariantNumeric: 'tabular-nums' }}>{money(item.old_price)}</td><td style={{ textAlign: 'center', fontFamily: 'var(--font-mono)', fontVariantNumeric: 'tabular-nums' }}>{money(item.new_price)}</td><td style={{ textAlign: 'center' }}>{item.action}</td>
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
      {tabs.filter(tab => isAdmin || tab.id === 'matrix' || tab.id === 'history').map(tab => { const Icon = tab.icon; return <button key={tab.id} onClick={() => { setActiveTab(tab.id); setPreview(null); setError(null) }} style={{ padding: '13px 16px', border: 0, borderBottom: activeTab === tab.id ? '2px solid var(--accent-blue)' : '2px solid transparent', background: 'transparent', color: activeTab === tab.id ? 'var(--text-primary)' : 'var(--text-secondary)', display: 'flex', gap: 8, alignItems: 'center', cursor: 'pointer', whiteSpace: 'nowrap' }}><Icon size={17} />{tab.label}</button> })}
    </div>
    {error && <div className="glass-panel" style={{ padding: 14, color: 'var(--crit)' }}><AlertTriangle size={16} /> {error}</div>}
    {notice && <div className="glass-panel" style={{ padding: 14, color: 'var(--ok)' }}><Check size={16} /> {notice}</div>}

    {activeTab === 'matrix' && <>
      <div className="glass-panel" style={panel}>
        <div style={{ display: 'flex', gap: 12, flexWrap: 'wrap', alignItems: 'center' }}>
          <div style={{ position: 'relative', flex: '1 1 260px' }}><Search size={16} style={{ position: 'absolute', left: 12, top: 12 }} /><input style={{ ...input, width: '100%', boxSizing: 'border-box', paddingLeft: 36 }} value={search} onChange={event => setSearch(event.target.value)} onKeyDown={event => { if (event.key === 'Enter') { setOffset(0); void loadMatrix() } }} placeholder="Cerca prodotto o SKU…" /></div>
          <button className="btn" onClick={() => { setOffset(0); void loadMatrix() }}><RefreshCw size={16} /> Aggiorna</button>
            <button className="btn" disabled={exporting} onClick={() => void exportMatrix()} title="Scarica in Excel tutti i prodotti della vista attuale (categoria, reparto, ricerca, ordinamento e periodo)"><Download size={16} /> {exporting ? 'Esporto…' : 'Esporta Excel'}</button>
          <span style={{ color: 'var(--text-secondary)', fontSize: 13 }}>{matrix?.total || 0} prodotti</span>
          <label style={{ display: 'flex', gap: 6, alignItems: 'center', fontSize: 13, color: 'var(--text-secondary)', fontWeight: 600 }}>
            Ordina per:
            <select style={{ ...input, padding: '6px 10px' }} value={matrixSort} onChange={event => { const value = event.target.value as MatrixSort; storeMatrixSort(value); setOffset(0); setMatrixSort(value) }}>
              <option value="nome">Nome</option>
              <option value="acquisti">Più acquistati</option>
              <option value="quantita">Quantità</option>
              <option value="spesa">Spesa</option>
            </select>
          </label>
          <label style={{ display: 'flex', gap: 6, alignItems: 'center', fontSize: 13, color: 'var(--text-secondary)', fontWeight: 600 }}>
            Periodo:
            <select style={{ ...input, padding: '6px 10px' }} value={matrixPeriod} onChange={event => { setOffset(0); setMatrixPeriod(event.target.value as MatrixPeriod) }}>
              <option value="tutto">Tutto lo storico</option>
              <option value="12m">Ultimi 12 mesi</option>
            </select>
          </label>
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
                  setSelectedMatrixSubcategory('all')
                  void loadMatrix(0, 'all', 'all')
                }}
                style={{
                  padding: '4px 12px',
                  fontSize: 12,
                  borderRadius: '999px',
                  background: selectedMatrixCategory === 'all' ? 'var(--primary-color)' : 'var(--bg-elevated)',
                  color: selectedMatrixCategory === 'all' ? 'var(--text-on-accent)' : 'var(--text-secondary)',
                  border: selectedMatrixCategory === 'all' ? '1px solid var(--primary-color)' : '1px solid var(--line)'
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
                  setSelectedMatrixSubcategory('all')
                  void loadMatrix(0, cat.id, 'all')
                }}
                style={{
                  padding: '4px 12px',
                  fontSize: 12,
                  borderRadius: '999px',
                  background: isSelected ? cat.bg : 'var(--bg-elevated)',
                  color: isSelected ? cat.color : 'var(--text-secondary)',
                  border: isSelected ? `1px solid ${cat.border}` : '1px solid var(--line)',
                  fontWeight: isSelected ? 600 : 400
                }}
              >
                {cat.icon} {cat.label} ({count})
              </button>
            )
          })}
        </div>

        {/* Subcategories Filter Chips */}
        {selectedMatrixCategory !== 'all' && subcategoriesForSelectedMatrix.length > 0 && (
          <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap', alignItems: 'center', paddingTop: 2, paddingLeft: 4 }}>
            <span style={{ fontSize: 12, color: 'var(--text-secondary)', fontWeight: 600 }}>Sottocategoria:</span>
            <button
              type="button"
              className="btn"
              onClick={() => {
                setOffset(0)
                setSelectedMatrixSubcategory('all')
                void loadMatrix(0, selectedMatrixCategory, 'all')
              }}
              style={{
                padding: '3px 10px',
                fontSize: 11,
                borderRadius: '999px',
                background: selectedMatrixSubcategory === 'all' ? 'var(--accent)' : 'var(--bg-inset)',
                color: selectedMatrixSubcategory === 'all' ? 'var(--text-on-accent)' : 'var(--text-secondary)',
                border: selectedMatrixSubcategory === 'all' ? '1px solid var(--accent)' : '1px solid var(--line)'
              }}
            >
              Tutte
            </button>
            {subcategoriesForSelectedMatrix.map(sub => {
              const isSubSelected = selectedMatrixSubcategory.toLowerCase() === sub.nome.toLowerCase()
              const count = matrix?.subcategory_counts?.[sub.nome]
              return (
                <button
                  key={sub.id}
                  type="button"
                  className="btn"
                  onClick={() => {
                    setOffset(0)
                    setSelectedMatrixSubcategory(sub.nome)
                    void loadMatrix(0, selectedMatrixCategory, sub.nome)
                  }}
                  style={{
                    padding: '3px 10px',
                    fontSize: 11,
                    borderRadius: '999px',
                    background: isSubSelected ? 'var(--accent-bg)' : 'var(--bg-inset)',
                    color: isSubSelected ? 'var(--accent-text)' : 'var(--text-secondary)',
                    border: isSubSelected ? '1px solid var(--accent)' : '1px solid var(--line)',
                    fontWeight: isSubSelected ? 600 : 400
                  }}
                >
                  {sub.nome} {count !== undefined && `(${count})`}
                </button>
              )
            })}
          </div>
        )}

        <details><summary style={{ cursor: 'pointer', color: 'var(--text-secondary)' }}>Colonne fornitori ({visibleSuppliers.length}/{matrix?.suppliers.length || 0})</summary><div style={{ display: 'flex', gap: 12, flexWrap: 'wrap', paddingTop: 12 }}>{(matrix?.suppliers || []).map(supplier => <label key={supplier.id} style={{ fontSize: 13 }}><input type="checkbox" checked={selectedSupplierIds.includes(supplier.id)} onChange={() => setSelectedSupplierIds(current => current.includes(supplier.id) ? current.filter(id => id !== supplier.id) : [...current, supplier.id])} /> {supplier.name}</label>)}</div></details>
        {loading ? <div style={{ padding: 30, textAlign: 'center' }}>Caricamento…</div> : <div style={{ overflow: 'auto', maxHeight: '65vh' }}><table className="ds-table" style={{ minWidth: 700, width: '100%', borderCollapse: 'collapse', fontSize: 13 }}>
          <thead style={{ position: 'sticky', top: 0, background: 'var(--bg-inset)', zIndex: 2 }}><tr><th style={{ textAlign: 'left', padding: 12, minWidth: 240 }}>Prodotto principale</th><th style={{ padding: 12, textAlign: 'right' }} title="Fatture d'acquisto che contengono il prodotto (escluse note di credito e omaggi)">Acquisti</th><th style={{ padding: 12, textAlign: 'right', minWidth: 110 }} title="Quantità comprata nell'unità del prodotto, note di credito sottratte, omaggi esclusi">Quantità</th><th style={{ padding: 12, textAlign: 'right', minWidth: 100 }} title="Spesa netta, note di credito sottratte">Spesa</th><th style={{ padding: 12, minWidth: 100 }}>Ultimo acquisto</th>{visibleSuppliers.map(supplier => <th key={supplier.id} style={{ padding: 12, minWidth: 155 }}>{supplier.name}</th>)}</tr></thead>
          <tbody>{(matrix?.rows || []).map(row => <tr key={row.product_id} style={{ borderTop: '1px solid var(--line)' }}>
            <td style={{ padding: 12 }}>
              <strong>{row.order_name || row.canonical_name}</strong>
              {row.order_name && <div style={{ color: 'var(--text-secondary)', fontSize: 11 }}>{row.canonical_name}</div>}
              <div style={{ color: 'var(--text-secondary)', fontSize: 11, display: 'flex', gap: 6, alignItems: 'center', marginTop: 2, flexWrap: 'wrap' }}>
                <span>{row.sku_interno || 'SKU mancante'}</span>
                <span>·</span>
                <span style={{
                  color: row.category === 'Food' ? 'var(--warn)' : row.category === 'Materiali' ? 'var(--ok)' : 'var(--accent-text)',
                  background: row.category === 'Food' ? 'var(--warn-bg)' : row.category === 'Materiali' ? 'var(--ok-bg)' : 'var(--accent-bg)',
                  padding: '1px 6px',
                  borderRadius: 4,
                  fontSize: 10,
                  fontWeight: 600
                }}>
                  {row.category || 'Beverage'}
                </span>
                {row.subcategory && (
                  <span style={{
                    color: 'var(--info)',
                    background: 'var(--info-bg)',
                    padding: '1px 6px',
                    borderRadius: 4,
                    fontSize: 10,
                    fontWeight: 500,
                    border: '1px solid var(--info-border)'
                  }}>
                    {row.subcategory}
                  </span>
                )}
              </div>
              {row.requires_manual_selection && <small style={{ color: 'var(--warn)' }}>Scelta manuale richiesta</small>}
            </td>
            <td style={{ padding: 12, textAlign: 'right', fontVariantNumeric: 'tabular-nums', fontWeight: row.acquisti ? 600 : 400, color: row.acquisti ? 'var(--text-primary)' : 'var(--text-secondary)' }}>{row.acquisti || 0}</td>
            <td style={{ padding: 12, textAlign: 'right', fontVariantNumeric: 'tabular-nums', whiteSpace: 'nowrap', color: Number(row.quantita || 0) < 0 ? 'var(--crit)' : 'var(--text-secondary)' }} title={notConvertedTitle(row) || undefined}>
              {quantityLabel(row)}
              {notConvertedTitle(row) && <div style={{ fontSize: 11, color: 'var(--warn)', cursor: 'help' }}>+ altre unità</div>}
            </td>
            <td style={{ padding: 12, textAlign: 'right', fontVariantNumeric: 'tabular-nums', whiteSpace: 'nowrap', color: Number(row.spesa || 0) < 0 ? 'var(--crit)' : 'var(--text-secondary)' }}>{euro(row.spesa)}</td>
            <td style={{ padding: 12, whiteSpace: 'nowrap', color: 'var(--text-secondary)' }}>{italianDate(row.ultimo_acquisto)}</td>
            {visibleSuppliers.map(supplier => {
              const offer = row.offers[String(supplier.id)]
              const relevant = row.eligible_supplier_ids.includes(supplier.id)
              const isForced = row.policy?.selection_mode === 'manual' && row.policy?.preferred_supplier_id === supplier.id
              const isAutoRecommended = (!row.policy || row.policy.selection_mode !== 'manual') && Boolean(offer?.is_recommended)
              const isOtherWhenForced = row.policy?.selection_mode === 'manual' && row.policy?.preferred_supplier_id !== supplier.id

              let borderStyle = '1px solid transparent'
              let bgStyle = 'var(--bg-inset)'
              let textColor = 'var(--text-primary)'

              if (isForced) {
                borderStyle = '2px solid var(--warn)'
                bgStyle = 'var(--warn-bg)'
                textColor = 'var(--warn)'
              } else if (isAutoRecommended) {
                borderStyle = '1px solid var(--ok)'
                bgStyle = 'var(--ok-bg)'
                textColor = 'var(--ok)'
              }

              return <td key={supplier.id} style={{ textAlign: 'center', padding: 8, opacity: offer && !offer.eligible ? .55 : 1, background: !relevant ? 'var(--bg-inset)' : 'transparent' }}>
                {relevant ? <button
                  disabled={!isAdmin}
                  onClick={() => {
                    if (isAdmin) {
                      // Un prezzo di fattura non diventa listino da solo: per gli spot il prezzo resta da scrivere.
                      setEditing({
                        product: row,
                        supplier,
                        price: offer?.source_type === 'contratto' ? offer.price : '',
                        uom: offer?.source_type === 'contratto' && offer.uom ? offer.uom : row.comparison_unit || 'Pz',
                      })
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
                    boxShadow: 'none'
                  }}
                >
                  {offer ? <>
                    <strong style={{ fontFamily: 'var(--font-mono)', fontVariantNumeric: 'tabular-nums' }}>{money(offer.price)}{offer.uom ? ` / ${offer.uom}` : ''}</strong>
                    {offer.unit_price_normalized != null && (offer.unit_price_normalized !== offer.price || unitFamily(offer.uom) !== unitFamily(row.comparison_unit)) && (
                      <small title={offer.conversion_note || undefined} style={{ fontFamily: 'var(--font-mono)', fontVariantNumeric: 'tabular-nums', color: 'var(--text-secondary)' }}>= {money(offer.unit_price_normalized)} / {row.comparison_unit || 'Pz'}</small>
                    )}
                    {offer.unit_price_normalized == null && (
                      <small title={offer.conversion_note || undefined} style={{ color: 'var(--warn)', fontWeight: 600 }}>
                        non confrontabile · {offer.source_type === 'contratto' && !offer.uom ? 'unità mancante' : 'conversione incerta'}
                      </small>
                    )}
                    {offer.source_type === 'spot' && offer.invoice_date && (
                      <small style={{ color: offer.stale ? 'var(--warn)' : 'var(--text-secondary)' }}>fattura {shortDate(offer.invoice_date)}{offer.stale ? ' · vecchio' : ''}</small>
                    )}
                    <div style={{ fontSize: 10, display: 'flex', flexDirection: 'column', alignItems: 'center', gap: 1 }}>
                      {isForced ? (
                        <span style={{ color: 'var(--warn)', fontWeight: 700, background: 'var(--bg-inset)', padding: '1px 5px', borderRadius: 4 }}>
                          ⭐ SCELTO {row.policy?.reason ? `· ${row.policy.reason}` : ''}
                        </span>
                      ) : isAutoRecommended ? (
                        <span style={{ color: 'var(--ok)', fontWeight: 600 }}>✓ CONSIGLIATO</span>
                      ) : isOtherWhenForced ? (
                        <span style={{ color: 'var(--text-secondary)' }}>alternativo</span>
                      ) : (
                        <span style={{ color: 'var(--text-secondary)' }}>{offer.source_type === 'contratto' ? 'prezzo listino' : 'prezzo spot'}</span>
                      )}
                    </div>
                  </> : <>{isAdmin && <Pencil size={13} />} {isAdmin ? 'inserisci' : '—'}</>}
                </button> : <span title="Fornitore fuori dal settore del prodotto" style={{ color: 'var(--text-muted)', fontSize: 11 }}>fuori settore</span>}
              </td>
            })}
          </tr>)}</tbody>
        </table></div>}
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
          <button className="btn" disabled={offset === 0} onClick={() => setOffset(Math.max(0, offset - MATRIX_PAGE_SIZE))}>Indietro</button>
          <span style={{ color: 'var(--text-secondary)', fontSize: 13 }}>{matrix?.total ? `${offset + 1}–${Math.min(offset + MATRIX_PAGE_SIZE, matrix.total)} di ${matrix.total}` : '0 di 0'}</span>
          <button className="btn" disabled={!matrix || offset + MATRIX_PAGE_SIZE >= matrix.total} onClick={() => setOffset(offset + MATRIX_PAGE_SIZE)}>Avanti</button>
        </div>
      </div>

      {editing && (
        <div className="glass-panel" style={{ ...panel, border: '1px solid var(--accent-border)', background: 'var(--bg-card)', boxShadow: 'var(--shadow-pop)' }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', borderBottom: '1px solid var(--line)', paddingBottom: 12 }}>
            <div>
              <div style={{ fontSize: 11, color: 'var(--text-secondary)', textTransform: 'uppercase', letterSpacing: 1 }}>Configurazione Prodotto & Fornitore</div>
              <h3 style={{ margin: '4px 0 0', fontSize: 17 }}>{editing.product.canonical_name} <span style={{ color: 'var(--text-secondary)', fontWeight: 400 }}>con</span> <span style={{ color: 'var(--accent-text)' }}>{editing.supplier.name}</span></h3>
            </div>
            <button className="btn" onClick={() => setEditing(null)}>Chiudi</button>
          </div>

          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(280px, 1fr))', gap: 20 }}>
            {/* Sezione 1: Modifica Prezzo */}
            <div style={{ display: 'flex', flexDirection: 'column', gap: 10, padding: 14, background: 'var(--bg-inset)', borderRadius: 8, border: '1px solid var(--line)' }}>
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
            <div style={{ display: 'flex', flexDirection: 'column', gap: 10, padding: 14, background: 'var(--warn-bg)', borderRadius: 8, border: '1px solid var(--warn-border)' }}>
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                <strong style={{ color: 'var(--warn)' }}>⭐ Forza Acquisto & Etichetta</strong>
                {editing.product.policy?.selection_mode === 'manual' && editing.product.policy?.preferred_supplier_id === editing.supplier.id && (
                  <span style={{ fontSize: 11, background: 'var(--warn-bg)', color: 'var(--warn)', padding: '2px 8px', borderRadius: 10, fontWeight: 700 }}>ATTUALMENTE FORZATO</span>
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
                    style={{ fontSize: 11, padding: '4px 8px', background: 'var(--bg-inset)' }}
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
                  style={{ background: 'var(--warn)', color: 'var(--bg-app)', fontWeight: 700, border: 'none', padding: '8px 14px' }}
                >
                  ⭐ Forza Acquisto da {editing.supplier.name}
                </button>
                {editing.product.policy?.selection_mode === 'manual' && editing.product.policy?.preferred_supplier_id === editing.supplier.id && (
                  <button
                    type="button"
                    className="btn"
                    onClick={() => handleSetForcedSupplier(editing.product.product_id, null, null)}
                    style={{ color: 'var(--crit)' }}
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
        <div style={{ display: 'flex', gap: 10, flexWrap: 'wrap', padding: '12px 14px', background: 'var(--bg-inset)', borderRadius: 10, border: '1px solid var(--line)', alignItems: 'center' }}>
          <span style={{ fontSize: 13, fontWeight: 700, color: 'var(--text-primary)', marginRight: 4 }}>Seleziona Foglio da compilare:</span>
          {MACRO_CATEGORIES.map(cat => {
            const isSelected = activeCategorySheet === cat.id
            const rowCount = categorySheets[cat.id]?.slice(1).filter(r => r[1]?.trim() || r[0]?.trim()).length || 0
            return (
              <button
                key={cat.id}
                type="button"
                onClick={() => {
                  const newCat = cat.id as MacroCategory
                  setActiveCategorySheet(newCat)
                  setActiveSubcategorySheet('all')
                  setPreview(null)
                  setError(null)
                  void reloadCurrentPrices(newCat, 'all')
                }}
                style={{
                  padding: '8px 16px',
                  borderRadius: 8,
                  border: isSelected ? `2px solid ${cat.border}` : '1px solid var(--line)',
                  background: isSelected ? cat.bg : 'var(--bg-inset)',
                  color: isSelected ? 'var(--text-primary)' : 'var(--text-secondary)',
                  cursor: 'pointer',
                  fontSize: 13,
                  fontWeight: isSelected ? 700 : 500,
                  display: 'flex',
                  alignItems: 'center',
                  gap: 8,
                  transition: 'all 0.2s ease',
                  boxShadow: 'none'
                }}
              >
                <span style={{ fontSize: 16 }}>{cat.icon}</span>
                <span>Foglio <b>{cat.label}</b></span>
                {rowCount > 0 && <span style={{ fontSize: 11, background: 'var(--bg-inset)', padding: '2px 7px', borderRadius: 10, color: cat.color }}>{rowCount} righe</span>}
              </button>
            )
          })}
        </div>

        {/* Subcategories Selector for Active Sheet */}
        {subcategoriesForActiveSheet.length > 0 && (
          <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap', padding: '10px 14px', background: 'var(--bg-inset)', borderRadius: 8, border: '1px solid var(--line)', alignItems: 'center' }}>
            <span style={{ fontSize: 12, fontWeight: 600, color: 'var(--text-secondary)' }}>Sottocategoria da compilare:</span>
            <button
              type="button"
              onClick={() => {
                setActiveSubcategorySheet('all')
                setPreview(null)
                setError(null)
                void reloadCurrentPrices(activeCategorySheet, 'all')
              }}
              style={{
                padding: '5px 12px',
                borderRadius: 6,
                border: activeSubcategorySheet === 'all' ? '1px solid var(--accent)' : '1px solid var(--line)',
                background: activeSubcategorySheet === 'all' ? 'var(--accent-bg)' : 'var(--bg-inset)',
                color: activeSubcategorySheet === 'all' ? 'var(--text-primary)' : 'var(--text-secondary)',
                cursor: 'pointer',
                fontSize: 12,
                fontWeight: activeSubcategorySheet === 'all' ? 600 : 400
              }}
            >
              📋 Tutte le sottocategorie {activeCategorySheet}
            </button>
            {subcategoriesForActiveSheet.map(sub => {
              const isSubSelected = activeSubcategorySheet.toLowerCase() === sub.nome.toLowerCase()
              const subKey = `${activeCategorySheet}:${sub.nome}`
              const count = categorySheets[subKey]?.slice(1).filter(r => r[1]?.trim() || r[0]?.trim()).length || 0
              return (
                <button
                  key={sub.id}
                  type="button"
                  onClick={() => {
                    setActiveSubcategorySheet(sub.nome)
                    setPreview(null)
                    setError(null)
                    void reloadCurrentPrices(activeCategorySheet, sub.nome)
                  }}
                  style={{
                    padding: '5px 12px',
                    borderRadius: 6,
                    border: isSubSelected ? '1px solid var(--info)' : '1px solid var(--line)',
                    background: isSubSelected ? 'var(--info-bg)' : 'var(--bg-inset)',
                    color: isSubSelected ? 'var(--info)' : 'var(--text-secondary)',
                    cursor: 'pointer',
                    fontSize: 12,
                    fontWeight: isSubSelected ? 600 : 400,
                    display: 'flex',
                    alignItems: 'center',
                    gap: 6
                  }}
                >
                  <span>{sub.nome}</span>
                  {count > 0 && <span style={{ fontSize: 10, background: 'var(--bg-inset)', padding: '1px 5px', borderRadius: 8, color: 'var(--info)' }}>{count}</span>}
                </button>
              )
            })}
          </div>
        )}

        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', gap: 14, flexWrap: 'wrap' }}>
          <div>
            <h3 style={{ margin: 0, display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap' }}>
              <span>Foglio Prezzi</span>
              <span style={{ fontSize: 13, fontWeight: 600, color: activeCategorySheet === 'Food' ? 'var(--warn)' : activeCategorySheet === 'Materiali' ? 'var(--ok)' : 'var(--accent-text)', background: activeCategorySheet === 'Food' ? 'var(--warn-bg)' : activeCategorySheet === 'Materiali' ? 'var(--ok-bg)' : 'var(--accent-bg)', padding: '2px 10px', borderRadius: 6, border: '1px solid var(--line)' }}>
                Settore: {MACRO_CATEGORIES.find(category => category.id === activeCategorySheet)?.label || activeCategorySheet}
              </span>
              {activeSubcategorySheet !== 'all' && (
                <span style={{ fontSize: 13, fontWeight: 600, color: 'var(--info)', background: 'var(--info-bg)', padding: '2px 10px', borderRadius: 6, border: '1px solid var(--info-border)' }}>
                  Sottocategoria: {activeSubcategorySheet}
                </span>
              )}
            </h3>
            <p style={{ color: 'var(--text-secondary)', margin: '5px 0 0' }}>
              Colonna A = nome rapido facoltativo. Colonna B = nome reale del prodotto. Colonna C = Unità di misura (UoM). Da D in poi = fornitori.
            </p>
          </div>
          <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
            <button className="btn" onClick={() => void reloadCurrentPrices(activeCategorySheet, activeSubcategorySheet)}><RotateCcw size={15} /> Prezzi correnti {activeCategorySheet}{activeSubcategorySheet !== 'all' ? ` · ${activeSubcategorySheet}` : ''}</button>
            <button className="btn" onClick={clearSheet}><Trash2 size={15} /> Svuota</button>
          </div>
        </div>

        <div style={{ border: '1px solid var(--line)', borderRadius: 10, overflow: 'auto', maxHeight: '58vh', background: 'var(--bg-card)' }}>
          <table style={{ borderCollapse: 'separate', borderSpacing: 0, width: 'max-content', minWidth: '100%', fontSize: 13 }}>
            <thead style={{ position: 'sticky', top: 0, zIndex: 5 }}>
              <tr>
                <th style={{ width: 44, minWidth: 44, height: 28, position: 'sticky', left: 0, zIndex: 7, background: 'var(--bg-inset)', borderRight: '1px solid var(--line-strong)', borderBottom: '1px solid var(--line-strong)' }} />
                {sheet[0]?.map((_, columnIndex) => <th key={columnIndex} style={{ minWidth: columnIndex === 0 ? 170 : columnIndex === 1 ? 260 : columnIndex === 2 ? 110 : 150, height: 28, padding: '0 8px', textAlign: 'center', color: 'var(--text-secondary)', background: 'var(--bg-inset)', borderRight: '1px solid var(--line-strong)', borderBottom: '1px solid var(--line-strong)', fontWeight: 600 }}>{columnLabel(columnIndex)}</th>)}
              </tr>
            </thead>
            <tbody>
              {sheet.map((row, rowIndex) => <tr key={rowIndex}>
                <th style={{ width: 44, minWidth: 44, height: 36, position: 'sticky', left: 0, zIndex: 4, textAlign: 'center', color: 'var(--text-secondary)', background: 'var(--bg-inset)', borderRight: '1px solid var(--line-strong)', borderBottom: '1px solid var(--line)', fontWeight: 500 }}>{rowIndex + 1}</th>
                {row.map((cell, columnIndex) => {
                  const eligible = isSheetCellEligible(rowIndex, columnIndex)
                  const hint = currentHints[`${rowIndex}:${columnIndex}`]
                  const width = columnIndex === 0 ? 170 : columnIndex === 1 ? 260 : columnIndex === 2 ? 110 : 150
                  return <td key={columnIndex} style={{ padding: 0, minWidth: width, borderRight: '1px solid var(--line)', borderBottom: '1px solid var(--line)', background: !eligible ? 'var(--bg-app)' : rowIndex === 0 ? 'var(--accent-bg)' : columnIndex < 3 ? 'var(--bg-inset)' : 'transparent' }}>
                    <input
                      aria-label={`Cella ${columnLabel(columnIndex)}${rowIndex + 1}`}
                      value={cell}
                      disabled={!eligible}
                      title={!eligible ? 'Fornitore fuori dal settore di questo prodotto' : hint ? `${hint}: non precaricato. Scrivi il prezzo nell'unità della colonna C per salvarlo.` : undefined}
                      onChange={event => updateSheetCell(rowIndex, columnIndex, event.target.value)}
                      onPaste={event => pasteIntoSheet(event, rowIndex, columnIndex)}
                      placeholder={rowIndex === 0 ? (columnIndex === 0 ? 'Nome rapido (facoltativo)' : columnIndex === 1 ? 'Prodotto reale' : columnIndex === 2 ? 'Unità di misura' : 'Nome fornitore') : columnIndex === 0 ? 'Es. GUANTI' : columnIndex === 1 ? 'Descrizione reale del prodotto' : columnIndex === 2 ? 'Es. Pz, Lt, Kg' : !eligible ? 'fuori settore' : hint || '—'}
                      style={{ width: '100%', minWidth: width, height: 36, boxSizing: 'border-box', padding: '0 10px', border: 0, outline: 'none', color: eligible ? 'var(--text-primary)' : 'var(--text-muted)', background: 'transparent', fontWeight: rowIndex === 0 || columnIndex < 3 ? 600 : 400, textAlign: columnIndex > 2 && rowIndex > 0 ? 'right' : 'left', cursor: eligible ? 'text' : 'not-allowed' }}
                      onFocus={event => { event.currentTarget.style.boxShadow = 'inset 0 0 0 2px var(--accent)' }}
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
          <label style={{ display: 'flex', gap: 8, alignItems: 'center', fontSize: 13, cursor: 'pointer', background: autoCreateProducts ? 'var(--accent-bg)' : 'var(--bg-inset)', padding: '9px 12px', borderRadius: 8, border: autoCreateProducts ? '1px solid var(--accent)' : '1px solid var(--line)', alignSelf: 'flex-end' }}>
            <input type="checkbox" checked={autoCreateProducts} onChange={e => setAutoCreateProducts(e.target.checked)} />
            <span style={{ color: autoCreateProducts ? 'var(--accent-text)' : 'inherit' }}>✨ <b>Crea automaticamente</b> prodotti mancanti</span>
          </label>
          <button className="btn btn-primary" disabled={(!hasSheetPrices && !hasOrderNames) || loading} onClick={createPastePreview} style={{ alignSelf: 'flex-end' }}><ClipboardPaste size={16} /> Controlla modifiche</button>
          <span style={{ color: 'var(--text-secondary)', fontSize: 12, maxWidth: 420 }}>
            {sheetChanges.changedCells} prezzi modificati · {sheetChanges.changedOrderNames} nomi rapidi. Si inviano solo le celle cambiate; un prezzo vale nell'unità della colonna <b>C (Unità di misura)</b>. Le celle grigie suggerite (fattura o listino in un'altra unità) non vengono salvate.
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
      {loading && !sectorData ? <div role="status">Caricamento settori…</div> : !sectorData?.suppliers.length ? <div role="status" style={{ padding: 20, color: 'var(--text-secondary)' }}>Nessun fornitore disponibile per configurare i settori.</div> : !sectorData.suppliers.find(supplier => supplier.id === sectorSupplierId)?.sectors.length ? <div role="status" style={{ padding: 20, color: 'var(--text-secondary)' }}>Nessun settore configurabile per questo fornitore.</div> : <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit,minmax(300px,1fr))', gap: 12 }}>
        {sectorData?.suppliers.find(supplier => supplier.id === sectorSupplierId)?.sectors.map(sector => {
          const key = `${sectorSupplierId}:${sector.category}`
          const choices: Array<{ mode: SectorMode; label: string }> = [
            { mode: 'auto', label: 'Automatico' },
            { mode: 'enabled', label: 'Abilitato' },
            { mode: 'disabled', label: 'Escluso' },
          ]
          return <div key={sector.category} style={{ padding: 14, border: '1px solid var(--line)', borderRadius: 10, background: 'var(--bg-inset)', display: 'flex', flexDirection: 'column', gap: 10 }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', gap: 10, alignItems: 'center' }}>
              <strong>{sector.category}</strong>
              <span style={{ fontSize: 11, color: sector.effective_enabled ? 'var(--ok)' : 'var(--text-secondary)' }}>{sector.effective_enabled ? 'VISIBILE' : 'NASCOSTO'}</span>
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

    {activeTab === 'history' && <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit,minmax(360px,1fr))', gap: 16 }}><div className="glass-panel" style={panel}><h3 style={{ margin: 0 }}>Versioni prezzo</h3><div style={{ maxHeight: 520, overflow: 'auto' }}>{historyRows.map(item => <div key={item.id} style={{ padding: '10px 0', borderBottom: '1px solid var(--line)', fontSize: 13 }}><strong>{item.description}</strong> · {item.supplier_name}<div style={{ color: 'var(--text-secondary)' }}>{money(item.price)} / {item.uom} · {item.valid_from} → {item.valid_to || 'attivo'}</div></div>)}</div></div><div className="glass-panel" style={panel}><h3 style={{ margin: 0 }}>Audit regole</h3><div style={{ maxHeight: 300, overflow: 'auto' }}>{auditRows.map((item, index) => <div key={`${item.entity_type}-${item.entity_id}-${index}`} style={{ padding: '10px 0', borderBottom: '1px solid var(--line)', fontSize: 13 }}>{item.entity_type} #{item.entity_id} · {item.action}<div style={{ color: 'var(--text-secondary)' }}>{new Date(item.occurred_at).toLocaleString('it-IT')} · utente #{item.actor_id}</div></div>)}</div><h3>Scostamenti policy ({deviations.length})</h3>{deviations.slice(0, 20).map(item => <div key={item.id} style={{ color: 'var(--warn)', fontSize: 13, padding: '8px 0' }}><div>{item.deviation_type}: {item.reason} · <b>{item.status}</b></div>{item.status === 'open' && <div style={{ display: 'flex', gap: 8, marginTop: 6 }}><button className="btn" onClick={() => updateDeviation(item.id, 'acknowledged')}>Presa in carico</button><button className="btn" onClick={() => updateDeviation(item.id, 'accepted_exception')}>Accetta eccezione</button></div>}</div>)}</div></div>}
  </div>
}
