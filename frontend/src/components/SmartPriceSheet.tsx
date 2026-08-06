import { useEffect, useMemo, useState } from 'react'
import { AlertTriangle, Check, ClipboardPaste, History, Pencil, RefreshCw, Save, Search, Settings2, Table2 } from 'lucide-react'
import { fetchWithAuth } from '../api'

type Supplier = { id: number; name: string; vat: string }
type Product = { id: number; sku_interno?: string | null; canonical_name: string }
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
  category?: string | null
  comparison_unit: string
  offers: Record<string, Offer>
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
  errors: Array<{ type: string; row?: number; header?: string; reference?: string; message: string }>
  supplier_mapping: Array<{ header: string; supplier_id?: number | null; supplier_name?: string | null; method: string }>
  product_mapping: Array<{ reference: string; product_id?: number | null; canonical_name?: string | null; method: string }>
}

const panel: React.CSSProperties = { padding: 20, display: 'flex', flexDirection: 'column', gap: 16 }
const input: React.CSSProperties = { padding: '10px 12px', background: 'rgba(255,255,255,.035)', color: 'white', border: '1px solid var(--border-glass)', borderRadius: 8 }
const tabs = [
  { id: 'matrix', label: 'Matrice', icon: Table2 },
  { id: 'paste', label: 'Incolla prezzi', icon: ClipboardPaste },
  { id: 'rules', label: 'Qualità e regole', icon: Settings2 },
  { id: 'history', label: 'Storico e audit', icon: History },
] as const

function money(value?: string | null) {
  return value ? `€ ${Number(value).toFixed(2)}` : '—'
}

function errorMessage(error: unknown) {
  return error instanceof Error ? error.message : 'Operazione non riuscita'
}

export default function SmartPriceSheet() {
  const [activeTab, setActiveTab] = useState<(typeof tabs)[number]['id']>('matrix')
  const [matrix, setMatrix] = useState<MatrixResponse | null>(null)
  const [products, setProducts] = useState<Product[]>([])
  const [search, setSearch] = useState('')
  const [offset, setOffset] = useState(0)
  const [selectedSupplierIds, setSelectedSupplierIds] = useState<number[]>([])
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [notice, setNotice] = useState<string | null>(null)

  const [pasteText, setPasteText] = useState('')
  const [effectiveDate, setEffectiveDate] = useState(new Date().toISOString().slice(0, 10))
  const [defaultUom, setDefaultUom] = useState('piece')
  const [supplierMapping, setSupplierMapping] = useState<Record<string, number>>({})
  const [productMapping, setProductMapping] = useState<Record<string, number>>({})
  const [preview, setPreview] = useState<Preview | null>(null)

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

  async function loadHistory() {
    try {
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
    if (activeTab === 'rules') void loadRules()
    if (activeTab === 'history') void loadHistory()
  // Tab activation is the only trigger; loaders handle their own cached state.
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [activeTab])

  const visibleSuppliers = useMemo(
    () => (matrix?.suppliers || []).filter(item => selectedSupplierIds.includes(item.id)),
    [matrix, selectedSupplierIds],
  )

  async function createPastePreview() {
    setLoading(true); setError(null); setNotice(null)
    try {
      const data = await fetchWithAuth('/smart-price-sheet/preview', {
        method: 'POST',
        body: JSON.stringify({ text: pasteText, supplier_mapping: supplierMapping, product_mapping: productMapping, effective_date: effectiveDate, default_uom: defaultUom }),
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
      setNotice(`Listino aggiornato: ${result.result.created} nuovi, ${result.result.updated} storicizzati, ${result.result.unchanged} invariati.`)
      setPreview(null); setPasteText(''); await loadMatrix()
    } catch (err) { setError(errorMessage(err)) } finally { setLoading(false) }
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

  function PreviewPanel() {
    if (!preview) return null
    return (
      <div className="glass-panel" style={{ ...panel, border: `1px solid ${preview.errors.length ? '#ef4444' : '#10b981'}` }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', gap: 12, alignItems: 'center', flexWrap: 'wrap' }}>
          <strong>Anteprima obbligatoria</strong>
          <span style={{ color: 'var(--text-secondary)', fontSize: 13 }}>
            {preview.counts.create} nuovi · {preview.counts.update} aggiornati · {preview.counts.unchanged} invariati · {preview.counts.errors} errori
          </span>
        </div>
        {preview.errors.map((item, index) => (
          <div key={index} style={{ color: '#fca5a5', fontSize: 13 }}>Riga {item.row || '—'}: {item.message}</div>
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
              <option value="">Associa il prodotto canonico…</option>
              {products.map(product => <option key={product.id} value={product.id}>{product.canonical_name} ({product.sku_interno})</option>)}
            </select>
          </label>
        ))}
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
      {tabs.map(tab => { const Icon = tab.icon; return <button key={tab.id} onClick={() => { setActiveTab(tab.id); setPreview(null); setError(null) }} style={{ padding: '13px 16px', border: 0, borderBottom: activeTab === tab.id ? '2px solid var(--accent-blue)' : '2px solid transparent', background: 'transparent', color: activeTab === tab.id ? 'white' : 'var(--text-secondary)', display: 'flex', gap: 8, alignItems: 'center', cursor: 'pointer', whiteSpace: 'nowrap' }}><Icon size={17} />{tab.label}</button> })}
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
          <thead style={{ position: 'sticky', top: 0, background: '#11111a', zIndex: 2 }}><tr><th style={{ textAlign: 'left', padding: 12, minWidth: 240 }}>Prodotto canonico</th>{visibleSuppliers.map(supplier => <th key={supplier.id} style={{ padding: 12, minWidth: 155 }}>{supplier.name}</th>)}</tr></thead>
          <tbody>{matrix?.rows.map(row => <tr key={row.product_id} style={{ borderTop: '1px solid var(--border-glass)' }}><td style={{ padding: 12 }}><strong>{row.canonical_name}</strong><div style={{ color: 'var(--text-secondary)', fontSize: 11 }}>{row.sku_interno || 'SKU mancante'} · {row.category || 'Senza categoria'}</div>{row.requires_manual_selection && <small style={{ color: '#fbbf24' }}>Scelta manuale richiesta</small>}</td>{visibleSuppliers.map(supplier => { const offer = row.offers[String(supplier.id)]; return <td key={supplier.id} style={{ textAlign: 'center', padding: 8, opacity: offer && !offer.eligible ? .55 : 1, background: offer?.is_recommended ? 'rgba(16,185,129,.08)' : 'transparent' }}><button onClick={() => setEditing({ product: row, supplier, price: offer?.price || '', uom: offer?.uom || row.comparison_unit || 'piece' })} style={{ width: '100%', padding: 8, borderRadius: 8, cursor: 'pointer', color: offer?.is_recommended ? '#6ee7b7' : 'white', border: offer?.is_absolute_cheapest ? '1px solid #3b82f6' : '1px solid transparent', background: 'rgba(255,255,255,.025)' }}>{offer ? <><strong>{money(offer.price)}</strong><div style={{ fontSize: 10, color: 'var(--text-secondary)' }}>{offer.source_type}{offer.is_recommended ? ' · CONSIGLIATO' : ''}{offer.assessment.status === 'blocked' ? ' · BLOCCATO' : ''}</div></> : <><Pencil size={13} /> inserisci</>}</button></td>})}</tr>)}</tbody>
        </table></div>}
        <div style={{ display: 'flex', justifyContent: 'space-between' }}><button className="btn" disabled={offset === 0} onClick={() => setOffset(Math.max(0, offset - 50))}>Indietro</button><button className="btn" disabled={!matrix || offset + 50 >= matrix.total} onClick={() => setOffset(offset + 50)}>Avanti</button></div>
      </div>
      {editing && <div className="glass-panel" style={panel}><strong>Modifica sicura: {editing.product.canonical_name} · {editing.supplier.name}</strong><div style={{ display: 'flex', gap: 10, flexWrap: 'wrap' }}><input autoFocus style={input} value={editing.price} onChange={event => setEditing({ ...editing, price: event.target.value })} placeholder="Prezzo" /><input style={input} value={editing.uom} onChange={event => setEditing({ ...editing, uom: event.target.value })} placeholder="Unità" /><button className="btn btn-primary" onClick={createCellPreview}>Genera anteprima</button><button className="btn" onClick={() => setEditing(null)}>Annulla</button></div></div>}
      <PreviewPanel />
    </>}

    {activeTab === 'paste' && <><div className="glass-panel" style={panel}><div><h3 style={{ margin: 0 }}>Incolla una matrice da Excel o Google Sheets</h3><p style={{ color: 'var(--text-secondary)', marginBottom: 0 }}>Prima colonna = prodotto/SKU. Le altre colonne = fornitori. Le celle vuote vengono ignorate; nessun dato cambia fino alla conferma.</p></div><textarea style={{ ...input, minHeight: 220, fontFamily: 'monospace' }} value={pasteText} onChange={event => { setPasteText(event.target.value); setPreview(null) }} placeholder={'Prodotto\tFornitore A\tFornitore B\nAcqua 75cl\t1,20\t1,18'} /><div style={{ display: 'flex', gap: 12, flexWrap: 'wrap' }}><label>Validità <input type="date" style={input} value={effectiveDate} onChange={event => setEffectiveDate(event.target.value)} /></label><label>Unità <input style={input} value={defaultUom} onChange={event => setDefaultUom(event.target.value)} /></label><button className="btn btn-primary" disabled={!pasteText.trim() || loading} onClick={createPastePreview}><ClipboardPaste size={16} /> Analizza senza salvare</button></div></div><PreviewPanel /></>}

    {activeTab === 'rules' && <><div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit,minmax(330px,1fr))', gap: 16 }}><div className="glass-panel" style={panel}><h3 style={{ margin: 0 }}>Qualità prodotto-fornitore</h3><select style={input} value={ruleProductId} onChange={event => setRuleProductId(Number(event.target.value) || '')}><option value="">Prodotto…</option>{products.map(item => <option key={item.id} value={item.id}>{item.canonical_name} ({item.sku_interno})</option>)}</select><select style={input} value={ruleSupplierId} onChange={event => setRuleSupplierId(Number(event.target.value) || '')}><option value="">Fornitore…</option>{matrix?.suppliers.map(item => <option key={item.id} value={item.id}>{item.name}</option>)}</select><select style={input} value={assessmentStatus} onChange={event => setAssessmentStatus(event.target.value)}><option value="approved">Approvato</option><option value="discouraged">Sconsigliato</option><option value="blocked">Bloccato</option></select><label>Qualità {quality}/5 <input type="range" min="1" max="5" value={quality} onChange={event => setQuality(Number(event.target.value))} /></label><textarea style={input} value={reason} onChange={event => setReason(event.target.value)} placeholder="Motivazione (obbligatoria se sconsigliato/bloccato)" /><button className="btn btn-primary" onClick={saveAssessment}><Save size={16} /> Salva valutazione</button></div><div className="glass-panel" style={panel}><h3 style={{ margin: 0 }}>Regola di acquisto</h3><p style={{ color: 'var(--text-secondary)', margin: 0 }}>Si applica al prodotto selezionato.</p><select style={input} value={selectionMode} onChange={event => setSelectionMode(event.target.value)}><option value="best_eligible_price">Miglior prezzo idoneo</option><option value="absolute_lowest">Minimo assoluto idoneo</option><option value="manual">Scelta manuale</option></select><select style={input} value={preferredSupplierId} onChange={event => setPreferredSupplierId(Number(event.target.value) || '')}><option value="">Nessun fornitore preferito</option>{matrix?.suppliers.map(item => <option key={item.id} value={item.id}>{item.name}</option>)}</select><label>Qualità minima <input type="number" min="1" max="5" style={input} value={minimumQuality} onChange={event => setMinimumQuality(Number(event.target.value))} /></label><div style={{ display: 'flex', gap: 10 }}><input style={{ ...input, width: '50%' }} value={premiumPercent} onChange={event => setPremiumPercent(event.target.value)} placeholder="Premium %" /><input style={{ ...input, width: '50%' }} value={premiumAbsolute} onChange={event => setPremiumAbsolute(event.target.value)} placeholder="Premium €" /></div><label><input type="checkbox" checked={allowSpot} onChange={event => setAllowSpot(event.target.checked)} /> Consenti prezzi spot</label><button className="btn btn-primary" onClick={savePolicy}><Save size={16} /> Salva regola</button></div></div><div className="glass-panel" style={panel}><strong>Configurazioni attive: {assessments.length} valutazioni · {policies.length} policy</strong>{assessments.slice(0, 12).map(item => <div key={item.id} style={{ fontSize: 13, color: 'var(--text-secondary)' }}>{item.product_name} · {item.supplier_name}: <b style={{ color: item.status === 'blocked' ? '#f87171' : 'white' }}>{item.status}</b>, qualità {item.quality_score}/5</div>)}</div></>}

    {activeTab === 'history' && <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit,minmax(360px,1fr))', gap: 16 }}><div className="glass-panel" style={panel}><h3 style={{ margin: 0 }}>Versioni prezzo</h3><div style={{ maxHeight: 520, overflow: 'auto' }}>{historyRows.map(item => <div key={item.id} style={{ padding: '10px 0', borderBottom: '1px solid var(--border-glass)', fontSize: 13 }}><strong>{item.description}</strong> · {item.supplier_name}<div style={{ color: 'var(--text-secondary)' }}>{money(item.price)} / {item.uom} · {item.valid_from} → {item.valid_to || 'attivo'}</div></div>)}</div></div><div className="glass-panel" style={panel}><h3 style={{ margin: 0 }}>Audit regole</h3><div style={{ maxHeight: 300, overflow: 'auto' }}>{auditRows.map((item, index) => <div key={`${item.entity_type}-${item.entity_id}-${index}`} style={{ padding: '10px 0', borderBottom: '1px solid var(--border-glass)', fontSize: 13 }}>{item.entity_type} #{item.entity_id} · {item.action}<div style={{ color: 'var(--text-secondary)' }}>{new Date(item.occurred_at).toLocaleString('it-IT')} · utente #{item.actor_id}</div></div>)}</div><h3>Scostamenti policy ({deviations.length})</h3>{deviations.slice(0, 20).map(item => <div key={item.id} style={{ color: '#fbbf24', fontSize: 13 }}>{item.deviation_type}: {item.reason}</div>)}</div></div>}
  </div>
}
