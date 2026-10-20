import { useEffect, useState } from 'react'
import { fetchWithAuth } from '../api'

const GOOGLE_CLIENT_ID = '52128477187-k0hkvu9vj0v3sbk7tf07rehhvosg0ors.apps.googleusercontent.com'
const GOOGLE_SCOPE = 'https://www.googleapis.com/auth/spreadsheets.readonly'
const GOOGLE_API = 'https://sheets.googleapis.com/v4/spreadsheets'

const SOURCE_RANGES = [
  { title: 'FOOD', range: "'FOOD'!A1:K1000" },
  { title: 'Carne', range: "'Carne'!A1:K1000" },
  { title: 'Pesce', range: "'Pesce'!A1:K1000" },
  { title: 'Varie', range: "'Varie'!A1:K1000" },
  { title: 'BEVERAGE', range: "'BEVERAGE'!A1:L1000" },
  { title: 'COMPARAZIONE MATERIALI', range: "'COMPARAZIONE MATERIALI'!A1:N1000" },
  { title: 'FRUTTA E VERDURA', range: "'FRUTTA E VERDURA'!A1:J1000" },
  { title: 'GIOCATTOLI', range: "'GIOCATTOLI'!A1:O1000" },
  { title: 'CONTROLLO_ESCLUSIONI', range: "'CONTROLLO_ESCLUSIONI'!A1:F100" },
]

type Candidate = {
  sector?: string
  subcategory?: string | null
  source_sheet: string
  source_row: number
  source_original_row?: number | null
  source_cell: string
  product: string
  supplier: string
  quoted_value: unknown
  status: string
  reasons: string[]
  reference_unit?: string | null
  supplier_price_unit?: string | null
  numeric_price?: string | number | null
}
type CatalogProduct = { id: number; sku_interno: string | null; canonical_name: string; order_name: string | null; comparison_unit: string; is_active: boolean }
type MappingOption = { value: string; label: string; group: 'Catalogo prodotti' | 'Listino attivo' }
type ListinoMappingRow = { sku_interno: string; descrizione: string; unita_misura: string }
type CandidateGroup = { key: string; sheet: string; product: string; unit: string; rows: Candidate[] }
type SupplierRecord = { id: number; nome_azienda: string; partita_iva?: string }
type ContractPreview = {
  preview_token: string
  status: string
  can_commit: boolean
  expires_at: string
  counts: { create: number; update: number; unchanged: number; errors: number }
  errors: Array<{ type?: string; row?: number; message: string }>
}
type ContractCommitResult = {
  status: string
  result: { created?: number; updated?: number; unchanged?: number; products_created?: number; suppliers_created?: number; aliases_created?: number }
}
type SectorSummary = {
  sector: string
  tab: string
  products: number
  quotes: number
  excluded: number
  blocked: number
  review: number
  skipped_empty: number
}
type DryRunReport = {
  candidate_count: number
  missing_sources: string[]
  warnings: unknown[]
  no_contract_writes: boolean
  rules: { price_semantics: string; auto_commit_enabled: boolean }
  sector_summary: SectorSummary[]
  food_audit?: { present: boolean; valid: boolean; products: number; categorized_products: number; products_without_subcategory: number; orphan_category_rows: number; ambiguous_category_products: number }
  candidates: Candidate[]
}

const REASON_LABELS: Record<string, string> = {
  canonical_id_not_mapped: 'Prodotto da associare al catalogo Price Sentinel',
  source_row_reference_missing: 'Riga originale FOOD assente o non valida',
  food_subcategory_missing: 'Prodotto FOOD senza sottocategoria: revisione necessaria',
  ambiguous_food_subcategory: 'Prodotto presente in più sottocategorie: chiarire prima dell’importazione',
  supplier_identity_and_net_price_need_verification: 'Identità fornitore e prezzo netto da verificare',
  unit_mapping_needed: 'Unità di misura da chiarire',
  unit_mismatch_needs_conversion: 'Unità diverse: conversione rinviata',
  unit_not_specified: 'Unità di misura mancante',
  zero_or_negative: 'Prezzo nullo o negativo',
  formula_error: 'La formula della cella restituisce un errore',
  invalid_price: 'Prezzo non valido',
  unsupported_price: 'Formato del prezzo non supportato',
  textual_price: 'Valore prezzo non numerico',
  sheet_exclusion: 'Quotazione esclusa nel foglio',
  precision_review: 'Oltre 4 decimali: normalizzato a 4 decimali in importazione',
  derived_supplier_lookup: 'Prezzo letto da una formula/lookup derivata',
}

function normalizeName(value: string): string {
  return value.normalize('NFD').replace(/[\u0300-\u036f]/g, '').toLocaleLowerCase().replace(/[^a-z0-9]+/g, ' ').trim().replace(/\s+/g, ' ')
}

function displayStatus(status: string): string {
  if (status === 'needs_mapping') return 'Da associare'
  if (status === 'blocked') return 'Bloccato'
  return status
}

function displayReasons(reasons: string[]): string {
  return reasons.map(reason => REASON_LABELS[reason] || reason.replace(/_/g, ' ')).join(', ')
}

function spreadsheetIdFromUrl(value: string): string {
  const match = value.match(/docs\.google\.com\/spreadsheets\/d\/([A-Za-z0-9_-]+)/)
  if (!match) throw new Error('Incolla il link del Google Sheet “santo graal”.')
  return match[1]
}

function loadSavedProductMappings(spreadsheetId: string): Record<string, string> {
  try {
    const value = JSON.parse(localStorage.getItem('ps.santo-graal.product-mappings:' + spreadsheetId) || '{}')
    return value && typeof value === 'object' && !Array.isArray(value) ? value : {}
  } catch {
    return {}
  }
}

function saveProductMapping(spreadsheetId: string, key: string, value: string): void {
  try {
    const saved = loadSavedProductMappings(spreadsheetId)
    if (value) saved[key] = value
    else delete saved[key]
    localStorage.setItem('ps.santo-graal.product-mappings:' + spreadsheetId, JSON.stringify(saved))
  } catch {
    // Import stays usable if browser storage is unavailable.
  }
}

function loadGoogleIdentityServices(): Promise<void> {
  const google = (window as any).google
  if (google?.accounts?.oauth2) return Promise.resolve()
  return new Promise((resolve, reject) => {
    const existing = document.querySelector<HTMLScriptElement>('script[data-google-identity-services]')
    if (existing) {
      if (existing.dataset.loadState === 'loaded' && (window as any).google?.accounts?.oauth2) {
        resolve()
        return
      }
      if (existing.dataset.loadState === 'failed') existing.remove()
      else {
        const timeout = window.setTimeout(() => reject(new Error('Il login Google non risponde. Ricarica la pagina e riprova.')), 15000)
        existing.addEventListener('load', () => {
          window.clearTimeout(timeout)
          if ((window as any).google?.accounts?.oauth2) resolve()
          else reject(new Error('Google Identity Services non è disponibile dopo il caricamento.'))
        }, { once: true })
        existing.addEventListener('error', () => {
          window.clearTimeout(timeout)
          existing.dataset.loadState = 'failed'
          reject(new Error('Impossibile caricare il login Google.'))
        }, { once: true })
        return
      }
    }
    const script = document.createElement('script')
    script.src = 'https://accounts.google.com/gsi/client'
    script.async = true
    script.defer = true
    script.dataset.googleIdentityServices = 'true'
    const timeout = window.setTimeout(() => {
      script.dataset.loadState = 'failed'
      reject(new Error('Il login Google non risponde. Ricarica la pagina e riprova.'))
    }, 15000)
    script.onload = () => {
      window.clearTimeout(timeout)
      if ((window as any).google?.accounts?.oauth2) {
        script.dataset.loadState = 'loaded'
        resolve()
      } else {
        script.dataset.loadState = 'failed'
        reject(new Error('Google Identity Services non è disponibile dopo il caricamento.'))
      }
    }
    script.onerror = () => {
      window.clearTimeout(timeout)
      script.dataset.loadState = 'failed'
      reject(new Error('Impossibile caricare il login Google.'))
    }
    document.head.appendChild(script)
  })
}

function requestReadToken(): Promise<string> {
  return new Promise((resolve, reject) => {
    const google = (window as any).google
    if (!google?.accounts?.oauth2) {
      reject(new Error('Servizio di autorizzazione Google non disponibile.'))
      return
    }
    let settled = false
    const timeout = window.setTimeout(() => {
      if (settled) return
      settled = true
      reject(new Error('Autorizzazione Google non completata. Consenti i popup per localhost e riprova.'))
    }, 60000)
    const finish = (callback: () => void) => {
      if (settled) return
      settled = true
      window.clearTimeout(timeout)
      callback()
    }
    const client = google.accounts.oauth2.initTokenClient({
      client_id: GOOGLE_CLIENT_ID,
      scope: GOOGLE_SCOPE,
      callback: (response: any) => {
        if (response?.error || !response?.access_token) {
          const message = response?.error === 'origin_mismatch'
            ? 'Origine OAuth non autorizzata. Apri PRICE SENTINEL V2 da http://localhost:18084.'
            : response?.error_description || response?.error || 'Accesso Google non completato.'
          finish(() => reject(new Error(message)))
          return
        }
        finish(() => resolve(response.access_token as string))
      },
      error_callback: (error: any) => finish(() => reject(new Error(error?.message || 'Popup Google non disponibile. Consenti i popup per localhost.'))),
    })
    // Google ricorda il consenso già concesso; non forziamo una nuova schermata di consenso a ogni lettura.
    try {
      client.requestAccessToken()
    } catch (error) {
      finish(() => reject(error instanceof Error ? error : new Error('Popup Google non disponibile.')))
    }
  })
}

async function googleGet(url: string, token: string): Promise<any> {
  const controller = new AbortController()
  const timeout = window.setTimeout(() => controller.abort(), 30000)
  let response: Response
  try {
    response = await fetch(url, { method: 'GET', headers: { Authorization: 'Bearer ' + token }, signal: controller.signal })
  } catch (error) {
    if (controller.signal.aborted) throw new Error('La lettura di Google Sheets ha superato 30 secondi. Riprova.')
    throw error
  } finally { window.clearTimeout(timeout) }
  if (!response.ok) {
    const body = await response.json().catch(() => ({}))
    const message = body?.error?.message || 'Google Sheets ha restituito HTTP ' + response.status
    throw new Error(message)
  }
  return response.json()
}

async function fetchPreviewApi(url: string, options: RequestInit = {}): Promise<any> {
  const controller = new AbortController()
  const timeout = window.setTimeout(() => controller.abort(), 30000)
  try { return await fetchWithAuth(url, { ...options, signal: controller.signal }) }
  catch (error) {
    if (controller.signal.aborted) throw new Error('La richiesta a Price Sentinel ha superato 30 secondi. Riprova.')
    throw error
  } finally { window.clearTimeout(timeout) }
}

export default function SantoGraalSyncPreview() {
  const [sourceUrl, setSourceUrl] = useState(() => localStorage.getItem('ps.santo-graal.url') || '')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [notice, setNotice] = useState<string | null>(null)
  const [report, setReport] = useState<DryRunReport | null>(null)
  const [googleToken, setGoogleToken] = useState<string | null>(null)
  const [statusFilter, setStatusFilter] = useState('blocked')
  const [sheetFilter, setSheetFilter] = useState('all')
  const [catalogProducts, setCatalogProducts] = useState<CatalogProduct[]>([])
  const [mappingOptions, setMappingOptions] = useState<MappingOption[]>([])
  const [catalogError, setCatalogError] = useState<string | null>(null)
  const [viewMode, setViewMode] = useState<'groups' | 'rows'>('groups')
  const [groupSearch, setGroupSearch] = useState('')
  const [stagedMappings, setStagedMappings] = useState<Record<string, string>>({})
  const [catalogBootstrapBusy, setCatalogBootstrapBusy] = useState(false)
  const [supplierOptions, setSupplierOptions] = useState<SupplierRecord[]>([])
  const [supplierMappings, setSupplierMappings] = useState<Record<string, string>>({})
  const [supplierLoadError, setSupplierLoadError] = useState<string | null>(null)
  const [priceImportBusy, setPriceImportBusy] = useState(false)
  const [priceCommitBusy, setPriceCommitBusy] = useState(false)
  const [priceImportError, setPriceImportError] = useState<string | null>(null)
  const [pricePreview, setPricePreview] = useState<ContractPreview | null>(null)
  const [priceCommitResult, setPriceCommitResult] = useState<ContractCommitResult | null>(null)
  const [googleReady, setGoogleReady] = useState(Boolean((window as any).google?.accounts?.oauth2))

  useEffect(() => {
    let active = true
    void loadGoogleIdentityServices().then(() => { if (active) setGoogleReady(true) }).catch(error => {
      if (active) setError(error instanceof Error ? error.message : 'Impossibile caricare il login Google.')
    })
    return () => { active = false }
  }, [])

  async function runReadOnlyPreview() {
    setBusy(true)
    setError(null)
    setNotice(null)
    let token: string | null = googleToken
    try {
      localStorage.setItem('ps.santo-graal.url', sourceUrl.trim())
      const spreadsheetId = spreadsheetIdFromUrl(sourceUrl.trim())
      if (!token) {
        if (!(window as any).google?.accounts?.oauth2) throw new Error('Il login Google si sta ancora caricando. Attendi qualche secondo e riprova.')
        // Start the popup synchronously in the click handler, while browser user activation is available.
        const tokenRequest = requestReadToken()
        token = await tokenRequest
        setGoogleToken(token)
      }

      const metadataUrl = GOOGLE_API + '/' + encodeURIComponent(spreadsheetId)
        + '?fields=' + encodeURIComponent('spreadsheetId,properties(title),sheets.properties(title)')
      const metadata = await googleGet(metadataUrl, token)
      const title = String(metadata?.properties?.title || '')
      if (title.trim().toLocaleLowerCase() !== 'santo graal') {
        throw new Error('Il file selezionato non è il Google Sheet “santo graal”.')
      }

      const sheetTitles = new Set((metadata.sheets || []).map((sheet: any) => sheet?.properties?.title))
      const missing = SOURCE_RANGES.map(item => item.title).filter(title => !sheetTitles.has(title))
      if (missing.length) {
        throw new Error('Mancano schede richieste: ' + missing.join(', '))
      }

      const params = new URLSearchParams()
      SOURCE_RANGES.forEach(item => params.append('ranges', item.range))
      params.set('valueRenderOption', 'UNFORMATTED_VALUE')
      const valuesUrl = GOOGLE_API + '/' + encodeURIComponent(spreadsheetId)
        + '/values:batchGet?' + params.toString()
      const valuesResponse = await googleGet(valuesUrl, token)
      const values: Record<string, unknown[][]> = {}
      const ranges = valuesResponse?.valueRanges || []
      if (ranges.length !== SOURCE_RANGES.length) {
        throw new Error('Google ha restituito un insieme incompleto di schede. Nessun dato è stato importato.')
      }
      SOURCE_RANGES.forEach((item, index) => {
        values[item.title] = ranges[index]?.values || []
      })

      const preview = await fetchPreviewApi('/smart-price-sheet/google-dry-run', {
        method: 'POST',
        body: JSON.stringify({ spreadsheet_id: spreadsheetId, title, values }),
      }) as DryRunReport
      setReport(preview)
      setStagedMappings({})
      setPricePreview(null)
      setPriceCommitResult(null)
      setPriceImportError(null)
      setNotice('Lettura completata. È un’anteprima: nessun prezzo è stato scritto o attivato.')
      setCatalogError(null)
      setCatalogProducts([])
      setMappingOptions([])
      try {
        const catalog = await fetchPreviewApi('/products') as CatalogProduct[]
        const activeProducts = Array.isArray(catalog) ? catalog.filter(product => product.is_active !== false) : []
        setCatalogProducts(activeProducts)
        const automaticMappings = exactStagedMappings(preview.candidates, activeProducts)
        const savedMappings = loadSavedProductMappings(spreadsheetId)
        const validSavedMappings: Record<string, string> = {}
        Object.entries(savedMappings).forEach(([savedKey, value]) => {
          const candidate = preview.candidates.find(item => {
            const currentKey = [item.source_sheet, normalizeName(item.product), normalizeName(item.reference_unit || '')].join('|')
            const legacyFoodKey = ['Carne', 'Pesce', 'Varie'].includes(item.source_sheet)
              ? ['FOOD', normalizeName(item.product), normalizeName(item.reference_unit || '')].join('|')
              : null
            return currentKey === savedKey || legacyFoodKey === savedKey
          })
          const product = value.startsWith('sku:')
            ? activeProducts.find(row => row.sku_interno === value.slice(4))
            : value.startsWith('product:')
              ? activeProducts.find(row => String(row.id) === value.slice(8))
              : undefined
          if (candidate?.reference_unit && product?.sku_interno
            && normalizeName(product.comparison_unit) === normalizeName(candidate.reference_unit)) {
            const currentKey = [candidate.source_sheet, normalizeName(candidate.product), normalizeName(candidate.reference_unit)].join('|')
            validSavedMappings[currentKey] = value
          }
        })
        setStagedMappings({ ...automaticMappings, ...validSavedMappings })
        const productOptions: MappingOption[] = activeProducts.map(product => ({
          value: product.sku_interno ? 'sku:' + product.sku_interno : 'product:' + product.id,
          label: product.canonical_name + (product.sku_interno ? ' · ' + product.sku_interno : ''),
          group: 'Catalogo prodotti',
        }))
        let listinoOptions: MappingOption[] = []
        try {
          const currentListino = await fetchPreviewApi('/listini/?limit=10000') as ListinoMappingRow[]
          const unique = new Map<string, ListinoMappingRow>()
          if (Array.isArray(currentListino)) {
            currentListino.forEach(row => {
              if (row.sku_interno && !unique.has(row.sku_interno)) unique.set(row.sku_interno, row)
            })
          }
          listinoOptions = Array.from(unique.values()).map(row => ({
            value: 'sku:' + row.sku_interno,
            label: row.descrizione + ' · ' + row.sku_interno + (row.unita_misura ? ' · ' + row.unita_misura : ''),
            group: 'Listino attivo',
          }))
        } catch {
          // Il catalogo canonico resta utilizzabile anche se il listino non è disponibile.
        }
        const combined = [...productOptions, ...listinoOptions.filter(option => !productOptions.some(product => product.value === option.value))]
        setMappingOptions(combined)
        if (combined.length === 0) {
          setCatalogError('Il catalogo prodotti e il listino attivo non restituiscono SKU selezionabili. Il raggruppamento funziona, ma prima di associare devi caricare/creare gli articoli nel Price Sentinel.')
        } else if (activeProducts.length === 0) {
          setCatalogError('Catalogo canonico vuoto: puoi associare i gruppi agli SKU già presenti nel listino attivo. Le scelte restano provvisorie.')
        }
      } catch {
        setCatalogProducts([])
        setMappingOptions([])
        setCatalogError('Non riesco a leggere il catalogo prodotti. Riprova aggiornando l’anteprima; nessun dato è stato modificato.')
      }
      try {
        const supplierData = await fetchPreviewApi('/fornitori') as SupplierRecord[]
        const activeSuppliers = Array.isArray(supplierData) ? supplierData : []
        setSupplierOptions(activeSuppliers)
        setSupplierLoadError(null)
        const sourceNames = Array.from(new Map(preview.candidates
          .filter(isImportableCandidate)
          .map(item => [normalizeName(item.supplier), item.supplier] as const)).values())
        const automatic: Record<string, string> = {}
        sourceNames.forEach(name => {
          const normalized = normalizeName(name)
          let matches = activeSuppliers.filter(item => normalizeName(item.nome_azienda) === normalized)
          if (matches.length !== 1) {
            const compact = normalized.replace(/\s+/g, '')
            matches = activeSuppliers.filter(item => normalizeName(item.nome_azienda).replace(/\s+/g, '').includes(compact))
          }
          if (matches.length === 1) automatic[normalized] = String(matches[0].id)
        })
        setSupplierMappings(previous => ({ ...automatic, ...previous }))
      } catch {
        setSupplierOptions([])
        setSupplierLoadError('Non riesco a leggere i fornitori di Price Sentinel. Senza una corrispondenza fornitore non importo i prezzi.')
      }
    } catch (err) {
      const message = err instanceof Error ? err.message : 'Anteprima non riuscita.'
      if (message.includes('HTTP 401')) setGoogleToken(null)
      setError(message.includes('HTTP 401') ? 'La sessione di Google è scaduta. Premi di nuovo “Aggiorna dal foglio” per rinnovarla.' : message)
    } finally {
      setBusy(false)
    }
  }

  const blockedCount = report?.candidates.filter(item => item.status === 'blocked').length || 0
  const mappingCount = report?.candidates.filter(item => item.status === 'needs_mapping').length || 0
  const sheetTitles = Array.from(new Set(report?.candidates.map(item => item.source_sheet) || [])).sort()
  const visibleCandidates = (report?.candidates || []).filter(item =>
    (statusFilter === 'all' || item.status === statusFilter)
    && (sheetFilter === 'all' || item.source_sheet === sheetFilter)
  )
  const groups = Array.from(visibleCandidates.reduce((map, item) => {
    const unit = item.reference_unit || ''
    const key = [item.source_sheet, normalizeName(item.product), normalizeName(unit)].join('|')
    const group = map.get(key) || { key, sheet: item.source_sheet, product: item.product, unit, rows: [] as Candidate[] }
    group.rows.push(item)
    map.set(key, group)
    return map
  }, new Map<string, CandidateGroup>()).values()).filter(group =>
    !groupSearch.trim() || normalizeName(group.product).includes(normalizeName(groupSearch))
      || group.rows.some(row => normalizeName(row.supplier).includes(normalizeName(groupSearch)))
  ).sort((a, b) => a.sheet.localeCompare(b.sheet) || a.product.localeCompare(b.product))
  const exactProductsFor = (name: string, unit: string) => catalogProducts.filter(product =>
    normalizeName(product.comparison_unit) === normalizeName(unit)
    && (normalizeName(product.canonical_name) === normalizeName(name)
      || Boolean(product.order_name && normalizeName(product.order_name) === normalizeName(name)))
  )
  const exactStagedMappings = (candidates: Candidate[], products: CatalogProduct[]) => {
    const result: Record<string, string> = {}
    const groups = new Map<string, { sheet: string; product: string; unit: string }>()
    candidates.filter(item => item.status === 'needs_mapping' && item.reference_unit).forEach(item => {
      const unit = item.reference_unit!.trim()
      const key = [item.source_sheet, normalizeName(item.product), normalizeName(unit)].join('|')
      if (!groups.has(key)) groups.set(key, { sheet: item.source_sheet, product: item.product, unit })
    })
    groups.forEach((group, key) => {
      const matches = products.filter(product =>
        normalizeName(product.comparison_unit) === normalizeName(group.unit)
        && normalizeName(product.canonical_name) === normalizeName(group.product)
      )
      if (matches.length === 1) {
        result[key] = matches[0].sku_interno ? 'sku:' + matches[0].sku_interno : 'product:' + matches[0].id
      }
    })
    return result
  }

  const isImportableCandidate = (item: Candidate) => {
    const blockedReasons = new Set([
      'unit_mapping_needed', 'unit_mismatch_needs_conversion', 'unit_not_specified',
      'supplier_identity_and_net_price_need_verification',
    ])
    return item.status === 'needs_mapping'
      && Boolean(item.reference_unit?.trim())
      && item.numeric_price !== null && item.numeric_price !== undefined
      && !item.reasons.some(reason => blockedReasons.has(reason))
      && normalizeName(item.reference_unit || '') === normalizeName(item.supplier_price_unit || item.reference_unit || '')
  }
  const bootstrapProducts = Array.from((report?.candidates || [])
    .filter(item => item.status === 'needs_mapping' && item.reference_unit?.trim())
    .reduce((map, item) => {
      const unit = item.reference_unit!.trim()
      const key = [item.source_sheet, normalizeName(item.product), normalizeName(unit)].join('|')
      if (!map.has(key)) {
        map.set(key, {
          source_sheet: item.source_sheet,
          canonical_name: item.product.trim(),
          comparison_unit: unit,
          category: item.sector || item.source_sheet,
          subcategory: item.subcategory || undefined,
        })
      }
      return map
    }, new Map<string, { source_sheet: string; canonical_name: string; comparison_unit: string; category: string; subcategory?: string }>()).values())

  async function initializeCatalogFromSheet() {
    if (!bootstrapProducts.length || catalogBootstrapBusy) return
    const confirmed = window.confirm(
      'ALLINEAMENTO CATALOGO SANTO GRAAL\n\nGli articoli già presenti saranno classificati secondo il foglio; FRUTTA E VERDURA verrà associato a Food → Frutta. Gli articoli mancanti saranno creati con SKU stabili e unità indicate nel foglio. Non verranno modificati prezzi, fornitori o dati nel Google Sheet. Continuare?'
    )
    if (!confirmed) return
    setCatalogBootstrapBusy(true)
    setCatalogError(null)
    try {
      const result = await fetchWithAuth('/product-identity/santo-graal/bootstrap-catalog', {
        method: 'POST',
        body: JSON.stringify({ items: bootstrapProducts }),
      }) as { created_count: number; already_present_count: number; total_count: number; classification_updated_count?: number }
      const catalog = await fetchPreviewApi('/products') as CatalogProduct[]
      const activeProducts = Array.isArray(catalog) ? catalog.filter(product => product.is_active !== false) : []
      setCatalogProducts(activeProducts)
      setStagedMappings(exactStagedMappings(report?.candidates || [], activeProducts))
      setMappingOptions(activeProducts.map(product => ({
        value: product.sku_interno ? 'sku:' + product.sku_interno : 'product:' + product.id,
        label: product.canonical_name + (product.sku_interno ? ' · ' + product.sku_interno : ''),
        group: 'Catalogo prodotti',
      })))
      setCatalogError(null)
      setNotice('Catalogo allineato: ' + result.created_count + ' nuovi articoli, ' + result.already_present_count + ' già presenti, ' + (result.classification_updated_count || 0) + ' classificazioni aggiornate. Prezzi e fornitori non sono stati modificati.')
    } catch (err) {
      const message = err instanceof Error ? err.message : 'Inizializzazione catalogo non riuscita.'
      setCatalogError('Catalogo non creato. ' + message)
    } finally {
      setCatalogBootstrapBusy(false)
    }
  }

  const importableCandidates = (report?.candidates || []).filter(isImportableCandidate)
  const precisionReviewCount = importableCandidates.filter(item => item.reasons.includes('precision_review')).length
  const importableSupplierNames = Array.from(new Map(importableCandidates
    .map(item => [normalizeName(item.supplier), item.supplier] as const)).values())

  async function preparePriceImport() {
    if (!report || priceImportBusy) return
    setPriceImportBusy(true)
    setPriceImportError(null)
    setPricePreview(null)
    setPriceCommitResult(null)
    try {
      const rowsBySku = new Map<string, { productId: number; unit: string; prices: Map<string, string> }>()
      const productMapping: Record<string, number> = {}
      const supplierHeaders = importableSupplierNames
      const supplierMapping: Record<string, number> = {}
      const missingSuppliers = supplierHeaders.filter(name => !supplierMappings[normalizeName(name)])
      if (missingSuppliers.length) throw new Error('Associa prima questi fornitori agli omonimi presenti in Price Sentinel: ' + missingSuppliers.join(', '))
      supplierHeaders.forEach(name => { supplierMapping[name] = Number(supplierMappings[normalizeName(name)]) })

      const conflicts: string[] = []
      const unmappedProducts = new Set<string>()
      for (const item of importableCandidates) {
        const groupKey = [item.source_sheet, normalizeName(item.product), normalizeName(item.reference_unit || '')].join('|')
        const selectedValue = stagedMappings[groupKey]
        const product = selectedValue?.startsWith('sku:')
          ? catalogProducts.find(row => row.sku_interno === selectedValue.slice(4))
          : selectedValue?.startsWith('product:')
            ? catalogProducts.find(row => String(row.id) === selectedValue.slice(8))
            : undefined
        if (!product?.sku_interno) {
          unmappedProducts.add(item.product + ' [' + item.source_sheet + ', ' + (item.reference_unit || 'unità mancante') + ']')
          continue
        }
        if (normalizeName(product.comparison_unit) !== normalizeName(item.reference_unit || '')) {
          unmappedProducts.add(item.product + ' [unità foglio: ' + (item.reference_unit || 'mancante') + ', catalogo: ' + product.comparison_unit + ']')
          continue
        }
        const row = rowsBySku.get(product.sku_interno) || { productId: product.id, unit: item.reference_unit!.trim(), prices: new Map<string, string>() }
        if (normalizeName(row.unit) !== normalizeName(item.reference_unit || '')) {
          conflicts.push(product.sku_interno + ': unità di misura diverse')
          continue
        }
        const supplierKey = normalizeName(item.supplier)
        const price = String(item.numeric_price)
        const previous = row.prices.get(supplierKey)
        if (previous !== undefined && previous !== price) {
          conflicts.push(product.canonical_name + ' / ' + item.supplier + ': prezzi discordanti in più righe del foglio')
          continue
        }
        row.prices.set(supplierKey, price)
        rowsBySku.set(product.sku_interno, row)
        productMapping[product.sku_interno] = product.id
      }
      if (conflicts.length) throw new Error('Conflitti nel foglio: ' + conflicts.slice(0, 8).join('; '))
      if (unmappedProducts.size) {
        throw new Error(unmappedProducts.size + ' prodotti importabili non sono associati o hanno unità diverse. Non preparo un import parziale. Completa le associazioni indicate e riprova. Esempi: ' + Array.from(unmappedProducts).slice(0, 8).join('; '))
      }
      if (!rowsBySku.size) throw new Error('Nessuna riga pronta: prima inizializza il catalogo e completa le associazioni prodotto.')

      const header = ['Prodotto', 'Unita di misura', ...supplierHeaders].join('\t')
      const bodyRows = Array.from(rowsBySku.entries()).map(([sku, row]) => [
        sku, row.unit, ...supplierHeaders.map(name => row.prices.get(normalizeName(name)) || ''),
      ].join('\t'))
      const textValue = [header, ...bodyRows].join('\n')
      const result = await fetchWithAuth('/smart-price-sheet/preview', {
        method: 'POST',
        body: JSON.stringify({
          text: textValue, supplier_mapping: supplierMapping, product_mapping: productMapping,
          default_uom: 'Pz', create_missing_products: false,
        }),
      }) as ContractPreview
      setPricePreview(result)
      if (!result.can_commit) {
        const firstErrors = (result.errors || []).slice(0, 5).map(item => item.message).filter(Boolean)
        throw new Error('L’anteprima ha ' + (result.counts?.errors || result.errors?.length || 0) + ' controlli bloccanti. ' + firstErrors.join(' · '))
      }
    } catch (err) {
      setPriceImportError(err instanceof Error ? err.message : 'Anteprima import prezzi non riuscita.')
    } finally {
      setPriceImportBusy(false)
    }
  }

  async function commitPriceImport() {
    if (!pricePreview?.can_commit || priceCommitBusy) return
    const counts = pricePreview.counts
    const confirmed = window.confirm(
      'REGISTRAZIONE PREZZI GIÀ PATTUITI\n\nVerranno registrati nel Listino Master Price Sentinel solo i prezzi dell’anteprima, con aggiornamento storico append-only e creazione degli alias fornitore. Le righe bloccate o non comparabili restano escluse. Il Google Sheet non verrà modificato. Creazioni: ' + counts.create + ', revisioni: ' + counts.update + ', invariati: ' + counts.unchanged + '. Procedere?'
    )
    if (!confirmed) return
    setPriceCommitBusy(true)
    setPriceImportError(null)
    try {
      const result = await fetchWithAuth('/smart-price-sheet/commit', {
        method: 'POST',
        body: JSON.stringify({ preview_token: pricePreview.preview_token, confirm: true }),
      }) as ContractCommitResult
      setPriceCommitResult(result)
      const summary = result.result || {}
      setNotice('Import completato. Creati: ' + (summary.created ?? 0) + ', aggiornati: ' + (summary.updated ?? 0) + ', invariati: ' + (summary.unchanged ?? 0) + '.')
    } catch (err) {
      setPriceImportError(err instanceof Error ? err.message : 'Import prezzi non riuscito.')
    } finally {
      setPriceCommitBusy(false)
    }
  }

  return (
    <section className="glass-panel" style={{ padding: 20, display: 'flex', flexDirection: 'column', gap: 14 }}>
      <div>
        <h3 style={{ margin: 0 }}>Collega il Santo Graal</h3>
        <p style={{ color: 'var(--text-secondary)', margin: '6px 0 0', maxWidth: 900 }}>
          I prezzi del foglio sono già pattuiti: non serve una nuova approvazione commerciale. Associa i prodotti, controlla l’anteprima e registra le quotazioni importabili. Il foglio resta invariato; le righe non comparabili restano escluse finché le unità non vengono chiarite.
        </p>
      </div>
      <label style={{ display: 'flex', flexDirection: 'column', gap: 6, maxWidth: 900 }}>
        <span style={{ fontSize: 13, color: 'var(--text-secondary)' }}>Link Google Sheet</span>
        <input
          value={sourceUrl}
          onChange={event => setSourceUrl(event.target.value)}
          placeholder="https://docs.google.com/spreadsheets/d/…"
          style={{ padding: '10px 12px', background: 'rgba(255,255,255,.035)', color: 'white', border: '1px solid var(--border-glass)', borderRadius: 8 }}
          autoComplete="off"
        />
      </label>
      <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
        <button type="button" className="btn btn-primary" disabled={busy || !sourceUrl.trim() || !googleReady} onClick={() => void runReadOnlyPreview()}>
          {busy ? 'Lettura e controllo…' : !googleReady ? 'Caricamento accesso Google…' : report ? 'Aggiorna dal foglio' : 'Accedi a Google e prepara anteprima'}
        </button>
        <span style={{ alignSelf: 'center', color: 'var(--text-secondary)', fontSize: 12 }}>
          Accesso in sola lettura · dopo il primo consenso, il pulsante aggiorna i dati senza rifare il login
        </span>
      </div>
      {error && <div role="alert" style={{ color: '#fca5a5', padding: 10, border: '1px solid rgba(248,113,113,.35)', borderRadius: 8 }}>{error}</div>}
      {notice && <div role="status" style={{ color: '#6ee7b7', padding: 10, border: '1px solid rgba(110,231,183,.3)', borderRadius: 8 }}>{notice}</div>}
      {report && <>
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit,minmax(160px,1fr))', gap: 8 }}>
          <div style={{ padding: 12, borderRadius: 8, background: 'rgba(255,255,255,.035)' }}><b>{report.candidate_count}</b><div style={{ color: 'var(--text-secondary)', fontSize: 12 }}>righe prezzo rilevate</div></div>
          <div style={{ padding: 12, borderRadius: 8, background: 'rgba(255,255,255,.035)' }}><b>{report.sector_summary.reduce((n, item) => n + item.review, 0)}</b><div style={{ color: 'var(--text-secondary)', fontSize: 12 }}>con associazione da completare</div></div>
          <div style={{ padding: 12, borderRadius: 8, background: 'rgba(255,255,255,.035)' }}><b>{report.sector_summary.reduce((n, item) => n + item.blocked, 0)}</b><div style={{ color: 'var(--text-secondary)', fontSize: 12 }}>bloccate dai controlli</div></div>
          <div style={{ padding: 12, borderRadius: 8, background: 'rgba(255,255,255,.035)' }}><b>{report.warnings.length}</b><div style={{ color: 'var(--text-secondary)', fontSize: 12 }}>avvisi</div></div>
        </div>
        {report.food_audit && <div role={report.food_audit.products_without_subcategory || report.food_audit.orphan_category_rows || report.food_audit.ambiguous_category_products ? 'alert' : 'status'} style={{ color: report.food_audit.products_without_subcategory || report.food_audit.orphan_category_rows || report.food_audit.ambiguous_category_products ? '#fbbf24' : '#6ee7b7', padding: 10, border: '1px solid rgba(251,191,36,.35)', borderRadius: 8 }}>FOOD è il master dei prezzi: {report.food_audit.products} prodotti, {report.food_audit.categorized_products} classificati dalle schede figlie, {report.food_audit.products_without_subcategory} senza sottocategoria e {report.food_audit.orphan_category_rows} righe figlie non presenti nel master. I casi senza classificazione restano bloccati.</div>}
        {report.missing_sources.length > 0 && <div role="alert" style={{ color: '#fca5a5' }}>Schede mancanti: {report.missing_sources.join(', ')}</div>}
        <div style={{ display: 'flex', gap: 10, flexWrap: 'wrap', alignItems: 'end' }}>
          <label style={{ display: 'flex', flexDirection: 'column', gap: 5, color: 'var(--text-secondary)', fontSize: 12 }}>
            Mostra esito
            <select value={statusFilter} onChange={event => setStatusFilter(event.target.value)} style={{ padding: '8px 10px', background: '#171821', color: 'white', border: '1px solid var(--border-glass)', borderRadius: 8 }}>
              <option value="blocked">Bloccate dai controlli ({blockedCount})</option>
              <option value="needs_mapping">Da associare ({mappingCount})</option>
              <option value="all">Tutte ({report.candidate_count})</option>
            </select>
          </label>
          <label style={{ display: 'flex', flexDirection: 'column', gap: 5, color: 'var(--text-secondary)', fontSize: 12 }}>
            Scheda dello Sheet
            <select value={sheetFilter} onChange={event => setSheetFilter(event.target.value)} style={{ padding: '8px 10px', background: '#171821', color: 'white', border: '1px solid var(--border-glass)', borderRadius: 8 }}>
              <option value="all">Tutte le schede</option>
              {sheetTitles.map(title => <option key={title} value={title}>{title}</option>)}
            </select>
          </label>
          <span style={{ color: 'var(--text-secondary)', fontSize: 12 }}>{visibleCandidates.length} righe visualizzate · la cella indica dove controllare il dato nello Sheet</span>
        </div>
        <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap', alignItems: 'center' }}>
          <button type="button" className={viewMode === 'groups' ? 'btn btn-primary' : 'btn'} onClick={() => setViewMode('groups')}>Raggruppa prodotti</button>
          <button type="button" className={viewMode === 'rows' ? 'btn btn-primary' : 'btn'} onClick={() => setViewMode('rows')}>Mostra righe singole</button>
          {viewMode === 'groups' && <input aria-label="Cerca prodotto o fornitore" value={groupSearch} onChange={event => setGroupSearch(event.target.value)} placeholder="Cerca prodotto o fornitore…" style={{ minWidth: 230, padding: '8px 10px', background: '#171821', color: 'white', border: '1px solid var(--border-glass)', borderRadius: 8 }} />}
          <span style={{ color: 'var(--text-secondary)', fontSize: 12 }}>{viewMode === 'groups' ? groups.length + ' gruppi · ' + visibleCandidates.length + ' righe prezzo' : visibleCandidates.length + ' righe visualizzate'}</span>
        </div>
        {catalogError && <div role="status" style={{ color: '#fbbf24', fontSize: 12 }}>{catalogError}</div>}
        {report && <div style={{ padding: 12, border: '1px solid var(--border-glass)', borderRadius: 8, display: 'flex', flexDirection: 'column', gap: 10 }}>
          <div>
            <strong>Fornitori del Santo Graal</strong>
            <div style={{ color: 'var(--text-secondary)', fontSize: 12, marginTop: 3 }}>
              {importableSupplierNames.length} fornitori · {importableCandidates.length} quotazioni importabili · unità non confrontabili e righe escluse restano fuori
              {precisionReviewCount > 0 && <div style={{ color: '#fbbf24', marginTop: 3 }}>{precisionReviewCount} prezzi con oltre 4 decimali saranno arrotondati a 4 (es. 3,733821 → 3,7338) e riportati nell’anteprima.</div>}
            </div>
          </div>
          {supplierLoadError && <div role="alert" style={{ color: '#fca5a5', fontSize: 12 }}>{supplierLoadError}</div>}
          {importableSupplierNames.length > 0 && <details>
            <summary style={{ cursor: 'pointer', color: 'var(--text-secondary)', fontSize: 12 }}>Controlla o completa gli abbinamenti fornitori</summary>
            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit,minmax(260px,1fr))', gap: 8, marginTop: 10 }}>
              {importableSupplierNames.map(name => <label key={normalizeName(name)} style={{ display: 'flex', flexDirection: 'column', gap: 4, color: 'var(--text-secondary)', fontSize: 12 }}>
                {name}
                <select value={supplierMappings[normalizeName(name)] || ''} onChange={event => {
                  setSupplierMappings(previous => ({ ...previous, [normalizeName(name)]: event.target.value }))
                  setPricePreview(null); setPriceImportError(null); setPriceCommitResult(null)
                }} style={{ padding: '8px 10px', background: '#171821', color: 'white', border: '1px solid var(--border-glass)', borderRadius: 8 }}>
                  <option value="">Da associare</option>
                  {supplierOptions.map(supplier => <option key={supplier.id} value={String(supplier.id)}>{supplier.nome_azienda}{supplier.partita_iva ? ' · ' + supplier.partita_iva : ''}</option>)}
                </select>
              </label>)}
            </div>
          </details>}
          <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap', alignItems: 'center' }}>
            <button type="button" className="btn btn-primary" disabled={priceImportBusy || importableCandidates.length === 0 || catalogProducts.length === 0} onClick={() => void preparePriceImport()}>
              {priceImportBusy ? 'Controllo listino…' : 'Prepara import prezzi pattuiti'}
            </button>
            <span style={{ color: 'var(--text-secondary)', fontSize: 12 }}>Prima genera un’anteprima completa. Le righe non scrivono nulla finché non confermi la registrazione.</span>
          </div>
          {priceImportError && <div role="alert" style={{ color: '#fca5a5', fontSize: 12 }}>{priceImportError}</div>}
          {pricePreview && <div role="status" style={{ padding: 10, background: 'rgba(255,255,255,.035)', borderRadius: 8 }}>
            <strong>{pricePreview.can_commit ? 'Anteprima pronta' : 'Anteprima bloccata'}</strong>
            <span style={{ marginLeft: 8, color: 'var(--text-secondary)', fontSize: 12 }}>
              Nuovi: {pricePreview.counts.create} · Revisioni: {pricePreview.counts.update} · Invariati: {pricePreview.counts.unchanged} · Controlli bloccanti: {pricePreview.counts.errors}
            </span>
            {pricePreview.errors?.length > 0 && <ul style={{ margin: '8px 0 0', color: '#fca5a5', fontSize: 12 }}>
              {pricePreview.errors.slice(0, 8).map((item, index) => <li key={index}>{item.message}</li>)}
            </ul>}
            {pricePreview.can_commit && !priceCommitResult && <button type="button" className="btn btn-primary" disabled={priceCommitBusy} onClick={() => void commitPriceImport()} style={{ marginTop: 10 }}>
              {priceCommitBusy ? 'Registrazione prezzi…' : 'Registra i prezzi già pattuiti'}
            </button>}
          </div>}
          {priceCommitResult && <div style={{ color: '#6ee7b7', fontSize: 13 }}>
            Import completato · voci create {priceCommitResult.result.created ?? 0} · revisioni {priceCommitResult.result.updated ?? 0} · invariati {priceCommitResult.result.unchanged ?? 0} · alias creati {priceCommitResult.result.aliases_created ?? 0}
          </div>}
        </div>}
        {bootstrapProducts.length > 0 && <button
          type="button"
          className="btn btn-primary"
          disabled={catalogBootstrapBusy}
          onClick={() => void initializeCatalogFromSheet()}
          style={{ alignSelf: 'flex-start' }}
        >
          {catalogBootstrapBusy ? 'Allineamento catalogo…' : 'Allinea Food → Frutta e categorie (' + bootstrapProducts.length + ' articoli)'}
        </button>}
        {viewMode === 'groups' ? <div style={{ overflowX: 'auto' }}>
          <table style={{ borderCollapse: 'collapse', width: '100%', fontSize: 12 }}>
            <thead><tr>{['Scheda', 'Prodotto nel foglio', 'Unità', 'Offerte (fornitore · cella · prezzo)', 'Suggerimento esatto', 'Associa in anteprima'].map(label => <th key={label} style={{ textAlign: 'left', padding: 8, borderBottom: '1px solid var(--border-glass)', verticalAlign: 'top' }}>{label}</th>)}</tr></thead>
            <tbody>
              {groups.map(group => {
                const exact = exactProductsFor(group.product, group.unit)
                const suggested = exact.length === 1 ? exact[0] : null
                const suggestedValue = suggested ? (suggested.sku_interno ? 'sku:' + suggested.sku_interno : 'product:' + suggested.id) : ''
                const selected = stagedMappings[group.key] || ''
                return <tr key={group.key}>
                  <td style={{ padding: 8, verticalAlign: 'top' }}>{group.sheet}</td>
                  <td style={{ padding: 8, verticalAlign: 'top' }}><strong>{group.product}</strong><div style={{ color: 'var(--text-secondary)', marginTop: 4 }}>{group.rows.length} offerte</div></td>
                  <td style={{ padding: 8, verticalAlign: 'top' }}>{group.unit || '—'}</td>
                  <td style={{ padding: 8, verticalAlign: 'top', minWidth: 260 }}>{group.rows.map(row => <div key={row.source_cell + row.supplier} style={{ marginBottom: 4 }}>{row.supplier} · {row.source_cell} · {String(row.quoted_value ?? '—')} <span style={{ color: row.status === 'blocked' ? '#fca5a5' : '#fbbf24' }}>({displayStatus(row.status)})</span></div>)}</td>
                  <td style={{ padding: 8, verticalAlign: 'top' }}>{suggested ? <>{suggested.canonical_name}<div style={{ color: 'var(--text-secondary)' }}>corrispondenza esatta</div></> : exact.length > 1 ? <span style={{ color: '#fbbf24' }}>Più corrispondenze esatte: scegli manualmente</span> : <span style={{ color: 'var(--text-secondary)' }}>Nessuna corrispondenza esatta</span>}</td>
                  <td style={{ padding: 8, verticalAlign: 'top', minWidth: 220 }}>
                    <select aria-label={'Associa ' + group.product} value={selected} onChange={event => {
                      const value = event.target.value
                      setStagedMappings(previous => ({ ...previous, [group.key]: value }))
                      try {
                        const id = spreadsheetIdFromUrl(sourceUrl.trim())
                        saveProductMapping(id, group.key, value)
                      } catch {
                        // The choice will be saved after a valid Santo Graal link is provided.
                      }
                      setPricePreview(null); setPriceImportError(null); setPriceCommitResult(null)
                    }} disabled={mappingOptions.length === 0} style={{ width: '100%', padding: '8px 10px', background: '#171821', color: 'white', border: '1px solid var(--border-glass)', borderRadius: 8 }}>
                      <option value="">Da valutare</option>
                      {suggested && !mappingOptions.some(option => option.value === suggestedValue) && <option value={suggestedValue}>{suggested.canonical_name}</option>}
                      {(['Catalogo prodotti', 'Listino attivo'] as const).map(groupName => {
                        const options = mappingOptions.filter(option => option.group === groupName)
                        return options.length ? <optgroup key={groupName} label={groupName}>{options.map(option => <option key={option.value} value={option.value}>{option.label}</option>)}</optgroup> : null
                      })}
                    </select>
                    {selected && <small style={{ display: 'block', color: '#fbbf24', marginTop: 4 }}>Salvata in questo browser</small>}
                  </td>
                </tr>
              })}
            </tbody>
          </table>
          {groups.length === 0 && <p style={{ color: 'var(--text-secondary)', fontSize: 12 }}>Nessun gruppo corrisponde ai filtri selezionati.</p>}
        </div> : <div style={{ overflowX: 'auto' }}>
          <table style={{ borderCollapse: 'collapse', width: '100%', fontSize: 12 }}>
            <thead><tr>{['Scheda', 'Cella', 'Prodotto', 'Fornitore', 'Prezzo letto', 'Esito', 'Motivo del controllo'].map(label => <th key={label} style={{ textAlign: 'left', padding: 8, borderBottom: '1px solid var(--border-glass)' }}>{label}</th>)}</tr></thead>
            <tbody>
              {visibleCandidates.map(item => <tr key={item.source_sheet + item.source_cell}>
                <td style={{ padding: 8 }}>{item.source_sheet}</td><td style={{ padding: 8 }}>{item.source_cell}</td>
                <td style={{ padding: 8 }}>{item.product}</td><td style={{ padding: 8 }}>{item.supplier}</td>
                <td style={{ padding: 8 }}>{String(item.quoted_value ?? '—')}</td>
                <td style={{ padding: 8, color: item.status === 'blocked' ? '#fca5a5' : '#fbbf24' }}>{displayStatus(item.status)}</td>
                <td style={{ padding: 8, color: 'var(--text-secondary)' }}>{displayReasons(item.reasons)}</td>
              </tr>)}
            </tbody>
          </table>
          {visibleCandidates.length === 0 && <p style={{ color: 'var(--text-secondary)', fontSize: 12 }}>Nessuna riga corrisponde ai filtri selezionati.</p>}
        </div>}
        {viewMode === 'groups' && <div style={{ color: 'var(--text-secondary)', fontSize: 12 }}>
          {Object.values(stagedMappings).filter(Boolean).length} associazioni disponibili. Le scelte manuali vengono ricordate in questo browser per questo Google Sheet.
        </div>}
        <strong style={{ color: '#6ee7b7' }}>Il foglio non viene modificato. Il Listino Master cambia solo dopo la conferma di “Registra i prezzi già pattuiti”.</strong>
      </>}
    </section>
  )
}
