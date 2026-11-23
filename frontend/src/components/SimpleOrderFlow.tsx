import { useEffect, useMemo, useState } from 'react'
import { ArrowLeft, CheckCircle2, Loader2, LogOut, Minus, Plus, Search, Send } from 'lucide-react'
import { API_BASE, getHeaders } from '../api'
import {
  getSectorUoms,
  isWaterProduct,
  normalizeDefaultUom,
  orderSector,
  type LocationItem,
  type ProductItem,
  type SectorOrderDraftResponse,
  type SectorOrderUserProfile,
  type SupplierOrderBundle,
} from './SectorOrderBuilder'

/*
 * Simple order flow for sector managers (responsabile_*): home with one ORDINA button,
 * sector choice (sectors not enabled for the user are greyed out), a plain product list
 * with quantities, then one WhatsApp button per supplier.
 * Same endpoints and payload as SectorOrderBuilder: elabora prepares the supplier
 * bundles with the recommended supplier per product, salva records them.
 */

const SECTORS = [
  { id: 'Food', label: 'Food', icon: '🍽️' },
  { id: 'Beverage', label: 'Beverage', icon: '🍹' },
  { id: 'Materiali di consumo', label: 'Materiali', icon: '📦' },
]
const PAGE = 80

type Step = 'home' | 'sector' | 'order' | 'done'
type Choice = { supplier_id: number; supplier_name: string; price: number | null; offer_id: string | null }

const euro = (value: number | null | undefined) =>
  value == null ? '' : `€ ${value.toLocaleString('it-IT', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`

const tomorrow = () => {
  const d = new Date()
  d.setDate(d.getDate() + 1)
  return d.toISOString().split('T')[0]
}

function allowedSectors(profile: SectorOrderUserProfile): string[] {
  const raw = profile.settore_abilitato
  if (!raw || raw === 'all') return SECTORS.map(s => s.id)
  return raw.split(',').map(s => s.trim()).filter(Boolean)
}

async function loadCatalog(deliveryDate: string): Promise<{ products: ProductItem[]; locations: LocationItem[] }> {
  const headers = getHeaders()
  const day = encodeURIComponent(deliveryDate)
  const [locRes, prodRes, firstRes] = await Promise.all([
    fetch(`${API_BASE}/location/`, { headers }),
    fetch(`${API_BASE}/products`, { headers }),
    fetch(`${API_BASE}/smart-price-sheet/matrix?limit=500&data=${day}`, { headers }),
  ])
  if (!prodRes.ok || !firstRes.ok) throw new Error('Catalogo non disponibile')
  const first = await firstRes.json()
  const rows: any[] = [...(first.rows || [])]
  const offsets: number[] = []
  for (let offset = 500; offset < Number(first.total || 0); offset += 500) offsets.push(offset)
  const pages = await Promise.all(offsets.map(async offset => {
    const res = await fetch(`${API_BASE}/smart-price-sheet/matrix?limit=500&offset=${offset}&data=${day}`, { headers })
    if (!res.ok) throw new Error('Catalogo non disponibile')
    return (await res.json()).rows || []
  }))
  pages.forEach(page => rows.push(...page))
  const byId = new Map<number, any>(rows.map(r => [r.product_id, r]))

  const products = ((await prodRes.json()) as ProductItem[])
    .filter(p => p.is_active)
    .map(p => {
      const m = byId.get(p.id)
      if (!m) return p
      const supplierId = m.selected_supplier_id || m.recommended_supplier_id
      const offer = (supplierId && m.offers?.[String(supplierId)]) || (Object.values(m.offers || {})[0] as any)
      const variants = (m.variant_offers || []).map((off: any) => ({
        offer_id: String(off.offer_id), supplier_id: Number(off.supplier_id),
        supplier_name: String(off.supplier_name), description: String(off.description),
        brand: off.brand || null, pack_qty: off.pack_qty ?? null, volume_ml: off.volume_ml ?? null,
        weight_g: off.weight_g ?? null, price: Number(off.price),
        comparison_price: off.comparison_price == null ? null : Number(off.comparison_price),
        comparison_unit: off.comparison_unit || null,
      }))
      const finalId = supplierId || offer?.supplier_id || null
      return {
        ...p,
        category: m.category || p.category,
        subcategory: m.subcategory || p.subcategory,
        order_name: m.order_name || p.order_name,
        prezzo_listino: variants.some((v: any) => v.supplier_id === finalId) ? null : (offer ? parseFloat(offer.price) : null),
        fornitore_consigliato_id: finalId,
        fornitore_consigliato_nome: offer?.supplier_name || null,
        variant_offers: variants,
      }
    })
  const locations = locRes.ok ? ((await locRes.json()) as LocationItem[]) : []
  return { products, locations: Array.isArray(locations) ? locations : [] }
}

interface Props {
  userProfile: SectorOrderUserProfile
  accountName: string
  onLogout: () => void
}

export default function SimpleOrderFlow({ userProfile, accountName, onLogout }: Props) {
  const [step, setStep] = useState<Step>('home')
  const [sector, setSector] = useState<string>('')
  const [deliveryDate, setDeliveryDate] = useState(tomorrow)
  const [catalog, setCatalog] = useState<{ products: ProductItem[]; locations: LocationItem[] } | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [search, setSearch] = useState('')
  const [shown, setShown] = useState(PAGE)
  const [qty, setQty] = useState<Record<number, number>>({})
  const [uoms, setUoms] = useState<Record<number, string>>({})
  const [variants, setVariants] = useState<Record<number, Choice>>({})
  const [locationId, setLocationId] = useState<number | ''>(userProfile.location_id || '')
  const [sending, setSending] = useState(false)
  const [result, setResult] = useState<SectorOrderDraftResponse | null>(null)
  const [opened, setOpened] = useState<Record<number, boolean>>({})
  const allowed = useMemo(() => allowedSectors(userProfile), [userProfile])

  useEffect(() => {
    if (step !== 'order') return
    let cancelled = false
    setLoading(true)
    setError(null)
    loadCatalog(deliveryDate)
      .then(data => {
        if (cancelled) return
        setCatalog(data)
        if (!userProfile.location_id && data.locations.length === 1) setLocationId(data.locations[0].id)
      })
      .catch(() => { if (!cancelled) setError('Non riesco a caricare i prodotti. Riprova tra poco.') })
      .finally(() => { if (!cancelled) setLoading(false) })
    return () => { cancelled = true }
  }, [step, deliveryDate, userProfile.location_id])

  useEffect(() => { setShown(PAGE) }, [search, sector])

  const sectorProducts = useMemo(() => {
    const term = search.trim().toLowerCase()
    return (catalog?.products || [])
      .filter(p => orderSector(p.category) === sector)
      .filter(p => !term || p.canonical_name.toLowerCase().includes(term) || (p.order_name || '').toLowerCase().includes(term)
        || (p.brand || '').toLowerCase().includes(term))
      .sort((a, b) => (a.order_name || a.canonical_name).localeCompare(b.order_name || b.canonical_name, 'it'))
  }, [catalog, sector, search])

  const choiceFor = (p: ProductItem): Choice | null => {
    if (p.variant_offers?.length) return variants[p.id] || null
    if (!p.fornitore_consigliato_id) return null
    return { supplier_id: p.fornitore_consigliato_id, supplier_name: p.fornitore_consigliato_nome || '', price: p.prezzo_listino ?? null, offer_id: null }
  }
  const uomFor = (p: ProductItem) => (p.variant_offers?.length ? 'conf' : uoms[p.id] || normalizeDefaultUom(p.comparison_unit, p.category))

  const basket = useMemo(() => (catalog?.products || []).filter(p => (qty[p.id] || 0) > 0), [catalog, qty])

  const changeQty = (id: number, delta: number) => setQty(current => {
    const next = Math.max(0, Math.round(((current[id] || 0) + delta) * 100) / 100)
    const copy = { ...current }
    if (next === 0) delete copy[id]
    else copy[id] = next
    return copy
  })

  const reset = () => {
    setQty({}); setUoms({}); setVariants({}); setResult(null); setOpened({}); setSearch(''); setError(null)
  }

  async function sendOrder() {
    setError(null)
    if (!locationId) { setError('Scegli la sede a cui consegnare.'); return }
    const missing = basket.find(p => p.variant_offers?.length && !variants[p.id])
    if (missing) { setError(`Scegli marca e formato per ${missing.order_name || missing.canonical_name}.`); return }
    const water = basket.find(p => isWaterProduct(p) && !['BT', 'PZ'].includes(uomFor(p).toUpperCase()))
    const payload = {
      location_id: Number(locationId),
      settore: sector,
      data_consegna: deliveryDate || null,
      note: null,
      water_freebie_product_id: water ? water.id : null,
      items: basket.map(p => {
        const choice = choiceFor(p)
        return {
          product_id: p.id, sku_interno: p.sku_interno, canonical_name: p.canonical_name, order_name: p.order_name,
          quantita: qty[p.id], comparison_unit: uomFor(p), category: p.category,
          preferred_supplier_id: choice?.supplier_id ?? null, preferred_offer_id: choice?.offer_id ?? null,
          prezzo_unitario: choice?.price ?? null,
        }
      }),
    }
    setSending(true)
    try {
      const headers = { ...getHeaders(), 'Content-Type': 'application/json' }
      const draftRes = await fetch(`${API_BASE}/ordini/settore/elabora`, { method: 'POST', headers, body: JSON.stringify(payload) })
      if (!draftRes.ok) throw new Error((await draftRes.json().catch(() => ({}))).detail || 'Ordine non preparato')
      const draft: SectorOrderDraftResponse = await draftRes.json()
      const saveRes = await fetch(`${API_BASE}/ordini/settore/salva`, {
        method: 'POST', headers,
        body: JSON.stringify({ location_id: draft.location_id, settore: draft.settore, data_consegna: draft.data_consegna,
          note: draft.note, bundles: draft.fornitori_ordini }),
      })
      if (!saveRes.ok) throw new Error((await saveRes.json().catch(() => ({}))).detail || 'Ordine non registrato')
      setResult(draft)
      setStep('done')
      window.scrollTo({ top: 0 })
    } catch (e: any) {
      setError(typeof e?.message === 'string' ? e.message : 'Qualcosa non ha funzionato. Riprova.')
    } finally {
      setSending(false)
    }
  }

  const openWhatsApp = (bundle: SupplierOrderBundle) => {
    window.open(bundle.whatsapp_url, '_blank')
    setOpened(current => ({ ...current, [bundle.fornitore_id]: true }))
  }

  const back = (to: Step) => (
    <button type="button" onClick={() => setStep(to)} style={styles.back} aria-label="Indietro">
      <ArrowLeft size={20} /> Indietro
    </button>
  )

  return (
    <div style={styles.page}>
      <header style={styles.header}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 10, minWidth: 0 }}>
          <img src="/logo.svg" alt="" width={32} height={32} />
          <strong style={{ letterSpacing: '0.5px', whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>{accountName.toUpperCase()}</strong>
        </div>
        <button type="button" onClick={onLogout} style={styles.logout}>
          <LogOut size={18} /> Esci
        </button>
      </header>

      {step === 'home' && (
        <main style={styles.center}>
          <p style={{ color: 'var(--text-secondary)', margin: 0 }}>Ciao {userProfile.nome_completo || ''}</p>
          <button type="button" onClick={() => { reset(); setStep(allowed.length === 1 ? 'order' : 'sector'); if (allowed.length === 1) setSector(allowed[0]) }} style={styles.bigTile}>
            ORDINA
          </button>
        </main>
      )}

      {step === 'sector' && (
        <main style={styles.main}>
          {back('home')}
          <h1 style={styles.title}>Scegli il settore</h1>
          <div style={styles.sectorGrid}>
            {SECTORS.map(s => {
              const enabled = allowed.includes(s.id)
              return (
                <button key={s.id} type="button" disabled={!enabled}
                  onClick={() => { setSector(s.id); setStep('order') }}
                  style={{ ...styles.sectorTile, ...(enabled ? {} : styles.sectorOff) }}
                  aria-label={enabled ? s.label : `${s.label}: non abilitato`}>
                  <span style={{ fontSize: 40 }} aria-hidden>{s.icon}</span>
                  <span style={{ fontWeight: 800, fontSize: '1.1rem' }}>{s.label}</span>
                  {!enabled && <small>Non abilitato</small>}
                </button>
              )
            })}
          </div>
        </main>
      )}

      {step === 'order' && (
        <main style={{ ...styles.main, paddingBottom: 110 }}>
          {back(allowed.length === 1 ? 'home' : 'sector')}
          <h1 style={styles.title}>{SECTORS.find(s => s.id === sector)?.label || sector}</h1>
          <div style={styles.filters}>
            <label style={styles.field}>
              <span>Consegna</span>
              <input type="date" value={deliveryDate} onChange={e => setDeliveryDate(e.target.value || tomorrow())} style={styles.input} />
            </label>
            {!userProfile.location_id && (catalog?.locations.length || 0) > 1 && (
              <label style={styles.field}>
                <span>Sede</span>
                <select value={locationId} onChange={e => setLocationId(e.target.value ? Number(e.target.value) : '')} style={styles.input}>
                  <option value="">Scegli…</option>
                  {catalog!.locations.map(l => <option key={l.id} value={l.id}>{l.nome_struttura}</option>)}
                </select>
              </label>
            )}
          </div>
          <div style={styles.searchBox}>
            <Search size={18} style={{ color: 'var(--text-secondary)' }} />
            <input value={search} onChange={e => setSearch(e.target.value)} placeholder="Cerca prodotto" style={styles.searchInput} aria-label="Cerca prodotto" />
          </div>

          {loading && <div style={styles.note}><Loader2 size={20} className="spin" /> Carico i prodotti…</div>}
          {!loading && catalog && sectorProducts.length === 0 && <div style={styles.note}>Nessun prodotto trovato.</div>}

          <ul style={styles.list}>
            {sectorProducts.slice(0, shown).map(p => {
              const q = qty[p.id] || 0
              const choice = choiceFor(p)
              return (
                <li key={p.id} style={{ ...styles.row, ...(q > 0 ? styles.rowOn : {}) }}>
                  <div style={{ minWidth: 0, flex: 1 }}>
                    <div style={{ fontWeight: 700 }}>{p.order_name || p.canonical_name}</div>
                    {!p.variant_offers?.length && (
                      <small style={{ color: 'var(--text-secondary)' }}>
                        {choice ? `${choice.supplier_name}${choice.price != null ? ` · ${euro(choice.price)}` : ''}` : 'Fornitore da definire'}
                      </small>
                    )}
                    {p.variant_offers?.length ? (
                      <select value={variants[p.id]?.offer_id || ''} style={{ ...styles.input, marginTop: 6, width: '100%' }}
                        onChange={e => {
                          const off = p.variant_offers!.find(v => v.offer_id === e.target.value)
                          setVariants(current => {
                            const copy = { ...current }
                            if (off) copy[p.id] = { supplier_id: off.supplier_id, supplier_name: off.supplier_name, price: off.price, offer_id: off.offer_id }
                            else delete copy[p.id]
                            return copy
                          })
                        }}
                        aria-label={`Marca e formato di ${p.order_name || p.canonical_name}`}>
                        <option value="">Scegli marca e formato…</option>
                        {p.variant_offers.map(v => (
                          <option key={v.offer_id} value={v.offer_id}>{[v.brand, v.description].filter(Boolean).join(' ')} · {euro(v.price)} · {v.supplier_name}</option>
                        ))}
                      </select>
                    ) : q > 0 && (
                      <select value={uomFor(p)} onChange={e => setUoms(current => ({ ...current, [p.id]: e.target.value }))}
                        style={{ ...styles.input, marginTop: 6, padding: '4px 8px' }} aria-label="Unità">
                        {getSectorUoms(p.category).map(u => <option key={u.id} value={u.id}>{u.label}</option>)}
                      </select>
                    )}
                  </div>
                  <div style={styles.stepper}>
                    <button type="button" onClick={() => changeQty(p.id, -1)} disabled={q === 0} style={styles.stepBtn} aria-label="Meno"><Minus size={18} /></button>
                    <input inputMode="decimal" value={q || ''} placeholder="0" aria-label="Quantità"
                      onChange={e => {
                        const v = parseFloat(e.target.value.replace(',', '.'))
                        changeQty(p.id, (Number.isFinite(v) ? v : 0) - q)
                      }} style={styles.qty} />
                    <button type="button" onClick={() => changeQty(p.id, 1)} style={{ ...styles.stepBtn, ...styles.stepPlus }} aria-label="Più"><Plus size={18} /></button>
                  </div>
                </li>
              )
            })}
          </ul>
          {sectorProducts.length > shown && (
            <button type="button" onClick={() => setShown(n => n + PAGE)} style={styles.more}>Mostra altri ({sectorProducts.length - shown})</button>
          )}

          <div style={styles.bar}>
            {error && <div style={styles.error}>{error}</div>}
            <button type="button" disabled={basket.length === 0 || sending} onClick={sendOrder}
              style={{ ...styles.send, ...(basket.length === 0 || sending ? { opacity: 0.5, cursor: 'default' } : {}) }}>
              {sending ? <Loader2 size={20} className="spin" /> : <Send size={20} />}
              {basket.length === 0 ? 'Scegli i prodotti' : `Invia ordine · ${basket.length} ${basket.length === 1 ? 'prodotto' : 'prodotti'}`}
            </button>
          </div>
        </main>
      )}

      {step === 'done' && result && (
        <main style={styles.main}>
          <div style={{ textAlign: 'center', margin: '8px 0 20px' }}>
            <CheckCircle2 size={48} style={{ color: 'var(--ok)' }} />
            <h1 style={{ ...styles.title, marginTop: 8 }}>Ordine registrato</h1>
            <p style={{ color: 'var(--text-secondary)', margin: 0 }}>Ora mandalo a ogni fornitore su WhatsApp.</p>
          </div>
          <ul style={styles.list}>
            {result.fornitori_ordini.map(b => (
              <li key={b.fornitore_id} style={{ ...styles.row, flexDirection: 'column', alignItems: 'stretch', gap: 10 }}>
                <div>
                  <div style={{ fontWeight: 800 }}>{b.fornitore_nome}</div>
                  <small style={{ color: 'var(--text-secondary)' }}>
                    {b.numero_articoli} {b.numero_articoli === 1 ? 'prodotto' : 'prodotti'}{b.totale_ordine ? ` · ${euro(b.totale_ordine)}` : ''}
                  </small>
                </div>
                <button type="button" onClick={() => openWhatsApp(b)} style={{ ...styles.whatsapp, ...(opened[b.fornitore_id] ? styles.whatsappDone : {}) }}>
                  {opened[b.fornitore_id] ? <><CheckCircle2 size={18} /> Aperto su WhatsApp</> : <><Send size={18} /> Invia su WhatsApp</>}
                </button>
              </li>
            ))}
          </ul>
          <button type="button" onClick={() => { reset(); setStep('home') }} style={{ ...styles.more, marginTop: 20 }}>Nuovo ordine</button>
        </main>
      )}
    </div>
  )
}

const styles: Record<string, React.CSSProperties> = {
  page: { minHeight: '100vh', background: 'var(--bg-app)', color: 'var(--text-primary)' },
  header: { display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 12, padding: '14px 16px', borderBottom: '1px solid var(--line)', position: 'sticky', top: 0, background: 'var(--bg-app)', zIndex: 5 },
  logout: { display: 'flex', alignItems: 'center', gap: 6, background: 'var(--bg-card)', border: '1px solid var(--line)', color: 'var(--text-primary)', borderRadius: 'var(--radius-md)', padding: '8px 12px', cursor: 'pointer', fontWeight: 600 },
  center: { display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center', gap: 20, minHeight: 'calc(100vh - 70px)', padding: 16 },
  bigTile: { width: 'min(70vw, 280px)', aspectRatio: '1 / 1', borderRadius: 48, border: 'none', background: 'var(--accent)', color: '#0b1220', fontSize: '1.6rem', fontWeight: 800, letterSpacing: '1px', cursor: 'pointer', boxShadow: '0 12px 40px rgba(79, 143, 247, 0.25)' },
  main: { maxWidth: 720, margin: '0 auto', padding: 16 },
  back: { display: 'inline-flex', alignItems: 'center', gap: 6, background: 'none', border: 'none', color: 'var(--text-secondary)', fontSize: '0.95rem', cursor: 'pointer', padding: '4px 0' },
  title: { fontSize: '1.5rem', fontWeight: 800, margin: '8px 0 16px' },
  sectorGrid: { display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(150px, 1fr))', gap: 14 },
  sectorTile: { display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center', gap: 8, minHeight: 150, borderRadius: 28, border: '1px solid var(--accent-border)', background: 'var(--accent-bg)', color: 'var(--text-primary)', cursor: 'pointer' },
  sectorOff: { background: 'var(--bg-card)', border: '1px solid var(--line)', color: 'var(--text-secondary)', opacity: 0.45, cursor: 'not-allowed', filter: 'grayscale(1)' },
  filters: { display: 'flex', gap: 12, flexWrap: 'wrap', marginBottom: 12 },
  field: { display: 'flex', flexDirection: 'column', gap: 4, fontSize: '0.8rem', color: 'var(--text-secondary)' },
  input: { background: 'var(--bg-card)', border: '1px solid var(--line)', color: 'var(--text-primary)', borderRadius: 'var(--radius-md)', padding: '8px 10px', fontSize: '0.95rem' },
  searchBox: { display: 'flex', alignItems: 'center', gap: 8, background: 'var(--bg-card)', border: '1px solid var(--line)', borderRadius: 'var(--radius-lg)', padding: '10px 12px', marginBottom: 12 },
  searchInput: { flex: 1, background: 'none', border: 'none', outline: 'none', color: 'var(--text-primary)', fontSize: '1rem' },
  note: { display: 'flex', alignItems: 'center', gap: 8, color: 'var(--text-secondary)', padding: '16px 0' },
  list: { listStyle: 'none', margin: 0, padding: 0, display: 'flex', flexDirection: 'column', gap: 8 },
  row: { display: 'flex', alignItems: 'center', gap: 12, background: 'var(--bg-card)', border: '1px solid var(--line)', borderRadius: 'var(--radius-lg)', padding: 12 },
  rowOn: { border: '1px solid var(--accent-border)', background: 'var(--accent-bg)' },
  stepper: { display: 'flex', alignItems: 'center', gap: 6, flexShrink: 0 },
  stepBtn: { width: 40, height: 40, borderRadius: 12, border: '1px solid var(--line)', background: 'var(--bg-elevated)', color: 'var(--text-primary)', display: 'flex', alignItems: 'center', justifyContent: 'center', cursor: 'pointer' },
  stepPlus: { background: 'var(--accent)', border: 'none', color: 'var(--text-on-accent)' },
  qty: { width: 48, height: 40, textAlign: 'center', background: 'var(--bg-app)', border: '1px solid var(--line)', borderRadius: 10, color: 'var(--text-primary)', fontSize: '1rem', fontWeight: 700 },
  more: { width: '100%', marginTop: 12, padding: 12, borderRadius: 'var(--radius-lg)', border: '1px solid var(--line)', background: 'var(--bg-card)', color: 'var(--text-primary)', fontWeight: 600, cursor: 'pointer' },
  bar: { position: 'fixed', left: 0, right: 0, bottom: 0, padding: '12px 16px calc(12px + env(safe-area-inset-bottom))', background: 'var(--bg-app)', borderTop: '1px solid var(--line)', display: 'flex', flexDirection: 'column', gap: 8, alignItems: 'center', zIndex: 5 },
  send: { width: '100%', maxWidth: 688, display: 'flex', alignItems: 'center', justifyContent: 'center', gap: 8, padding: 16, borderRadius: 'var(--radius-lg)', border: 'none', background: 'var(--accent)', color: 'var(--text-on-accent)', fontSize: '1.05rem', fontWeight: 800, cursor: 'pointer' },
  error: { width: '100%', maxWidth: 688, color: 'var(--crit)', fontSize: '0.9rem' },
  whatsapp: { display: 'flex', alignItems: 'center', justifyContent: 'center', gap: 8, padding: 14, borderRadius: 'var(--radius-lg)', border: 'none', background: '#25d366', color: '#06281a', fontWeight: 800, fontSize: '1rem', cursor: 'pointer' },
  whatsappDone: { background: 'var(--bg-elevated)', color: 'var(--ok)', border: '1px solid var(--ok-border)' },
}
