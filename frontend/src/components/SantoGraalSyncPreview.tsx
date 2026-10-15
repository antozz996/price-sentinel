import { useState } from 'react'
import { fetchWithAuth } from '../api'

const GOOGLE_CLIENT_ID = '52128477187-k0hkvu9vj0v3sbk7tf07rehhvosg0ors.apps.googleusercontent.com'
const GOOGLE_SCOPE = 'https://www.googleapis.com/auth/spreadsheets.readonly'
const GOOGLE_API = 'https://sheets.googleapis.com/v4/spreadsheets'

const SOURCE_RANGES = [
  { title: 'FOOD', range: "'FOOD'!A1:J1000" },
  { title: 'BEVERAGE', range: "'BEVERAGE'!A1:L1000" },
  { title: 'COMPARAZIONE MATERIALI', range: "'COMPARAZIONE MATERIALI'!A1:N1000" },
  { title: 'FRUTTA E VERDURA', range: "'FRUTTA E VERDURA'!A1:J1000" },
  { title: 'GIOCATTOLI', range: "'GIOCATTOLI'!A1:O1000" },
  { title: 'CONTROLLO_ESCLUSIONI', range: "'CONTROLLO_ESCLUSIONI'!A1:F100" },
]

type Candidate = {
  source_sheet: string
  source_cell: string
  product: string
  supplier: string
  quoted_value: unknown
  status: string
  reasons: string[]
  reference_unit?: string | null
}
type CatalogProduct = { id: number; sku_interno: string | null; canonical_name: string; order_name: string | null; comparison_unit: string; is_active: boolean }
type CandidateGroup = { key: string; sheet: string; product: string; unit: string; rows: Candidate[] }
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
  candidates: Candidate[]
}

const REASON_LABELS: Record<string, string> = {
  canonical_id_not_mapped: 'Prodotto da associare al catalogo Price Sentinel',
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
  precision_review: 'Precisione del prezzo da verificare',
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

function loadGoogleIdentityServices(): Promise<void> {
  const google = (window as any).google
  if (google?.accounts?.oauth2) return Promise.resolve()
  return new Promise((resolve, reject) => {
    const existing = document.querySelector<HTMLScriptElement>('script[data-google-identity-services]')
    if (existing) {
      existing.addEventListener('load', () => resolve(), { once: true })
      existing.addEventListener('error', () => reject(new Error('Impossibile caricare il login Google.')), { once: true })
      return
    }
    const script = document.createElement('script')
    script.src = 'https://accounts.google.com/gsi/client'
    script.async = true
    script.defer = true
    script.dataset.googleIdentityServices = 'true'
    script.onload = () => resolve()
    script.onerror = () => reject(new Error('Impossibile caricare il login Google.'))
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
    const client = google.accounts.oauth2.initTokenClient({
      client_id: GOOGLE_CLIENT_ID,
      scope: GOOGLE_SCOPE,
      callback: (response: any) => {
        if (response?.error || !response?.access_token) {
          reject(new Error(response?.error_description || response?.error || 'Accesso Google non completato.'))
          return
        }
        resolve(response.access_token as string)
      },
      error_callback: (error: any) => reject(new Error(error?.message || 'Popup Google non disponibile.')),
    })
    // Google ricorda il consenso già concesso; non forziamo una nuova schermata di consenso a ogni lettura.
    client.requestAccessToken()
  })
}

async function googleGet(url: string, token: string): Promise<any> {
  const response = await fetch(url, {
    method: 'GET',
    headers: { Authorization: 'Bearer ' + token },
  })
  if (!response.ok) {
    const body = await response.json().catch(() => ({}))
    const message = body?.error?.message || 'Google Sheets ha restituito HTTP ' + response.status
    throw new Error(message)
  }
  return response.json()
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
  const [catalogError, setCatalogError] = useState<string | null>(null)
  const [viewMode, setViewMode] = useState<'groups' | 'rows'>('groups')
  const [groupSearch, setGroupSearch] = useState('')
  const [stagedMappings, setStagedMappings] = useState<Record<string, string>>({})

  async function runReadOnlyPreview() {
    setBusy(true)
    setError(null)
    setNotice(null)
    let token: string | null = googleToken
    try {
      localStorage.setItem('ps.santo-graal.url', sourceUrl.trim())
      const spreadsheetId = spreadsheetIdFromUrl(sourceUrl.trim())
      if (!token) {
        await loadGoogleIdentityServices()
        token = await requestReadToken()
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

      const preview = await fetchWithAuth('/smart-price-sheet/google-dry-run', {
        method: 'POST',
        body: JSON.stringify({ spreadsheet_id: spreadsheetId, title, values }),
      }) as DryRunReport
      setReport(preview)
      setStagedMappings({})
      setNotice('Lettura completata. È un’anteprima: nessun prezzo è stato scritto o attivato.')
      setCatalogError(null)
      try {
        const catalog = await fetchWithAuth('/products') as CatalogProduct[]
        setCatalogProducts(Array.isArray(catalog) ? catalog.filter(product => product.is_active !== false) : [])
      } catch {
        setCatalogProducts([])
        setCatalogError('Catalogo non disponibile: puoi consultare i gruppi, ma non selezionare un prodotto Price Sentinel.')
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
  const exactProductsFor = (name: string) => catalogProducts.filter(product =>
    normalizeName(product.canonical_name) === normalizeName(name)
    || Boolean(product.order_name && normalizeName(product.order_name) === normalizeName(name))
  )

  return (
    <section className="glass-panel" style={{ padding: 20, display: 'flex', flexDirection: 'column', gap: 14 }}>
      <div>
        <h3 style={{ margin: 0 }}>Collega il Santo Graal</h3>
        <p style={{ color: 'var(--text-secondary)', margin: '6px 0 0', maxWidth: 900 }}>
          I prezzi del foglio sono già pattuiti: non c’è una nuova approvazione commerciale da dare. Questa schermata controlla l’associazione ai prodotti Price Sentinel e segnala righe con dati da verificare. È solo un’anteprima: non importa né attiva i prezzi. La conversione delle unità resta rinviata.
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
        <button type="button" className="btn btn-primary" disabled={busy || !sourceUrl.trim()} onClick={() => void runReadOnlyPreview()}>
          {busy ? 'Lettura e controllo…' : report ? 'Aggiorna dal foglio' : 'Accedi a Google e prepara anteprima'}
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
        {viewMode === 'groups' ? <div style={{ overflowX: 'auto' }}>
          <table style={{ borderCollapse: 'collapse', width: '100%', fontSize: 12 }}>
            <thead><tr>{['Scheda', 'Prodotto nel foglio', 'Unità', 'Offerte (fornitore · cella · prezzo)', 'Suggerimento esatto', 'Associa in anteprima'].map(label => <th key={label} style={{ textAlign: 'left', padding: 8, borderBottom: '1px solid var(--border-glass)', verticalAlign: 'top' }}>{label}</th>)}</tr></thead>
            <tbody>
              {groups.map(group => {
                const exact = exactProductsFor(group.product)
                const suggested = exact.length === 1 ? exact[0] : null
                const selected = stagedMappings[group.key] || ''
                return <tr key={group.key}>
                  <td style={{ padding: 8, verticalAlign: 'top' }}>{group.sheet}</td>
                  <td style={{ padding: 8, verticalAlign: 'top' }}><strong>{group.product}</strong><div style={{ color: 'var(--text-secondary)', marginTop: 4 }}>{group.rows.length} offerte</div></td>
                  <td style={{ padding: 8, verticalAlign: 'top' }}>{group.unit || '—'}</td>
                  <td style={{ padding: 8, verticalAlign: 'top', minWidth: 260 }}>{group.rows.map(row => <div key={row.source_cell + row.supplier} style={{ marginBottom: 4 }}>{row.supplier} · {row.source_cell} · {String(row.quoted_value ?? '—')} <span style={{ color: row.status === 'blocked' ? '#fca5a5' : '#fbbf24' }}>({displayStatus(row.status)})</span></div>)}</td>
                  <td style={{ padding: 8, verticalAlign: 'top' }}>{suggested ? <>{suggested.canonical_name}<div style={{ color: 'var(--text-secondary)' }}>corrispondenza esatta</div></> : exact.length > 1 ? <span style={{ color: '#fbbf24' }}>Più corrispondenze esatte: scegli manualmente</span> : <span style={{ color: 'var(--text-secondary)' }}>Nessuna corrispondenza esatta</span>}</td>
                  <td style={{ padding: 8, verticalAlign: 'top', minWidth: 220 }}>
                    <select aria-label={'Associa ' + group.product} value={selected} onChange={event => setStagedMappings(previous => ({ ...previous, [group.key]: event.target.value }))} disabled={catalogProducts.length === 0} style={{ width: '100%', padding: '8px 10px', background: '#171821', color: 'white', border: '1px solid var(--border-glass)', borderRadius: 8 }}>
                      <option value="">Da valutare</option>
                      {suggested && !catalogProducts.some(product => String(product.id) === selected) && <option value={String(suggested.id)}>{suggested.canonical_name}</option>}
                      {catalogProducts.map(product => <option key={product.id} value={String(product.id)}>{product.canonical_name}{product.sku_interno ? ' · ' + product.sku_interno : ''}</option>)}
                    </select>
                    {selected && <small style={{ display: 'block', color: '#fbbf24', marginTop: 4 }}>Scelta provvisoria, non salvata</small>}
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
          {Object.values(stagedMappings).filter(Boolean).length} associazioni selezionate in questa sessione. Le selezioni si azzerano aggiornando l’anteprima e non sono ancora salvate nel catalogo.
        </div>}
        <strong style={{ color: '#6ee7b7' }}>Nessuna modifica al foglio o al listino Price Sentinel.</strong>
      </>}
    </section>
  )
}
