import { useEffect, useMemo, useState } from 'react'
import {
  Building2,
  CheckCircle2,
  Circle,
  Plus,
  Pencil,
  Trash2,
  RefreshCw,
  Save,
  TriangleAlert,
  Sliders,
  Store,
  FileText,
  Users,
  X,
  Check
} from 'lucide-react'
import { API_BASE, fetchWithAuth, getHeaders } from '../api'

type LocationItem = {
  id: number
  nome_struttura: string
  piva_riferimento: string
  tipologia: 'balneare' | 'ristorante' | 'discoteca' | 'evento'
}

type Settings = {
  location_id: number
  configured: boolean
  price_tolerance_absolute: string
  price_tolerance_percent: string
  important_anomaly_threshold: string
  stalled_reconciliation_days: number
  missing_credit_note_days: number
  notifications_enabled: boolean
}

type Readiness = {
  location_id: number
  location_name: string
  users: number
  suppliers: number
  suppliers_with_contact: number
  active_products: number
  approved_aliases: number
  price_lists: number
  liquidstock_venue_mapped: boolean
  liquidstock_orders: number
  invoices: number
  reconciliations: number
  disputes: number
  settings_configured: boolean
  settings: Settings
}

export default function ClientOnboarding() {
  const [profile, setProfile] = useState<{ ruolo: string; location_id?: number } | null>(null)
  const [activeSubTab, setActiveSubTab] = useState<'sedi' | 'thresholds'>('sedi')
  const [locations, setLocations] = useState<LocationItem[]>([])
  const [selectedLocationId, setSelectedLocationId] = useState<number | ''>('')
  const [readiness, setReadiness] = useState<Readiness | null>(null)
  const [settings, setSettings] = useState<Settings | null>(null)
  
  // UI states
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [notice, setNotice] = useState('')

  // Modal Sede Form
  const [showLocationModal, setShowLocationModal] = useState(false)
  const [editingLocation, setEditingLocation] = useState<LocationItem | null>(null)
  const [formNome, setFormNome] = useState('')
  const [formPiva, setFormPiva] = useState('')
  const [formTipo, setFormTipo] = useState<'balneare' | 'ristorante' | 'discoteca' | 'evento'>('balneare')
  const [submittingModal, setSubmittingModal] = useState(false)

  const headers = getHeaders()

  const loadBase = async () => {
    setBusy(true)
    setError('')
    try {
      const me = await fetchWithAuth('/auth/me')
      setProfile(me)
      const rows: LocationItem[] = await fetchWithAuth('/location/')
      setLocations(rows)
      if (rows.length > 0) {
        setSelectedLocationId(current => (current ? current : me.location_id || rows[0].id))
      }
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : 'Dati non disponibili')
    } finally {
      setBusy(false)
    }
  }

  useEffect(() => {
    void loadBase()
  }, [])

  const loadReadiness = async (id: number) => {
    if (!id) return
    setBusy(true)
    setError('')
    setNotice('')
    try {
      const data = await fetchWithAuth(`/onboarding/locations/${id}/readiness`)
      setReadiness(data)
      setSettings(data.settings)
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : 'Verifica non riuscita')
    } finally {
      setBusy(false)
    }
  }

  useEffect(() => {
    if (selectedLocationId) {
      void loadReadiness(Number(selectedLocationId))
    }
  }, [selectedLocationId])

  // Open Modal Create/Edit Location
  const openModal = (loc?: LocationItem) => {
    if (loc) {
      setEditingLocation(loc)
      setFormNome(loc.nome_struttura)
      setFormPiva(loc.piva_riferimento)
      setFormTipo(loc.tipologia)
    } else {
      setEditingLocation(null)
      setFormNome('')
      setFormPiva('')
      setFormTipo('balneare')
    }
    setShowLocationModal(true)
  }

  // Save Location (Create or Update)
  const handleSaveLocation = async (e: React.FormEvent) => {
    e.preventDefault()
    if (!formNome.trim() || formPiva.trim().length !== 11) {
      setError('Compila tutti i campi. La Partita IVA deve essere esattamente di 11 cifre numeriche.')
      return
    }

    setSubmittingModal(true)
    setError('')
    setNotice('')

    try {
      if (editingLocation) {
        const res = await fetch(`${API_BASE}/location/${editingLocation.id}`, {
          method: 'PATCH',
          headers,
          body: JSON.stringify({
            nome_struttura: formNome.trim(),
            piva_riferimento: formPiva.trim(),
            tipologia: formTipo,
          }),
        })
        const data = await res.json()
        if (!res.ok) throw new Error(data.detail || 'Errore durante la modifica della sede')
        setNotice('Sede aggiornata con successo!')
      } else {
        const res = await fetch(`${API_BASE}/location/`, {
          method: 'POST',
          headers,
          body: JSON.stringify({
            nome_struttura: formNome.trim(),
            piva_riferimento: formPiva.trim(),
            tipologia: formTipo,
          }),
        })
        const data = await res.json()
        if (!res.ok) throw new Error(data.detail || 'Errore durante la creazione della sede')
        setNotice('Nuova sede aziendale creata con successo!')
      }

      setShowLocationModal(false)
      await loadBase()
    } catch (err: any) {
      setError(err.message || 'Errore nel salvataggio')
    } finally {
      setSubmittingModal(false)
    }
  }

  // Delete Location
  const handleDeleteLocation = async (loc: LocationItem) => {
    if (!window.confirm(`Sei sicuro di voler eliminare la sede "${loc.nome_struttura}" (P.IVA ${loc.piva_riferimento})?`)) return

    setBusy(true)
    setError('')
    try {
      const res = await fetch(`${API_BASE}/location/${loc.id}`, {
        method: 'DELETE',
        headers,
      })
      if (!res.ok) {
        const errData = await res.json()
        throw new Error(errData.detail || "Impossibile eliminare la sede (potrebbero esserci fatture o utenti associati)")
      }
      setNotice(`Sede "${loc.nome_struttura}" eliminata con successo.`)
      await loadBase()
    } catch (err: any) {
      setError(err.message || "Errore durante l'eliminazione")
    } finally {
      setBusy(false)
    }
  }

  // Save Threshold Settings
  const handleSaveSettings = async () => {
    if (!selectedLocationId || !settings) return
    setBusy(true)
    setError('')
    setNotice('')
    try {
      const saved = await fetchWithAuth(`/onboarding/locations/${selectedLocationId}/settings`, {
        method: 'PUT',
        body: JSON.stringify({
          price_tolerance_absolute: settings.price_tolerance_absolute,
          price_tolerance_percent: settings.price_tolerance_percent,
          important_anomaly_threshold: settings.important_anomaly_threshold,
          stalled_reconciliation_days: settings.stalled_reconciliation_days,
          missing_credit_note_days: settings.missing_credit_note_days,
          notifications_enabled: settings.notifications_enabled,
        }),
      })
      setSettings(saved)
      setNotice('Parametri e soglie operative salvati con successo per la sede!')
      await loadReadiness(Number(selectedLocationId))
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : 'Salvataggio non riuscito')
    } finally {
      setBusy(false)
    }
  }

  const steps = useMemo(
    () =>
      readiness
        ? ([
            ['Utente operativo', readiness.users > 0, `${readiness.users} utenti collegati`],
            ['Fornitori attivi', readiness.suppliers > 0, `${readiness.suppliers} fornitori · ${readiness.suppliers_with_contact} con email`],
            ['Catalogo & Alias', readiness.active_products > 0 && readiness.approved_aliases > 0, `${readiness.active_products} prodotti · ${readiness.approved_aliases} alias`],
            ['Listini Master', readiness.price_lists > 0, `${readiness.price_lists} righe di listino concordato`],
            ['Fatture importate', readiness.invoices > 0, `${readiness.invoices} fatture registrate per questa sede`],
            ['Soglie di controllo', readiness.settings_configured, readiness.settings_configured ? 'Soglie configurate' : 'Soglie da impostare'],
            ['Riconciliazioni ordini', readiness.reconciliations > 0, `${readiness.reconciliations} riconciliazioni elaborate`],
            ['Contestazioni gestite', readiness.disputes >= 0, `${readiness.disputes} pratiche di contestazione`],
          ] as Array<[string, boolean, string]>)
        : [],
    [readiness],
  )
  const completed = steps.filter(([, done]) => done).length

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: '24px' }}>
      
      {/* Alert Notices */}
      {error && (
        <div style={{ padding: '12px 16px', borderRadius: '8px', background: 'rgba(239,68,68,0.15)', color: '#ef4444', border: '1px solid rgba(239,68,68,0.3)', display: 'flex', alignItems: 'center', gap: '10px' }}>
          <TriangleAlert size={18} />
          <span>{error}</span>
        </div>
      )}
      {notice && (
        <div style={{ padding: '12px 16px', borderRadius: '8px', background: 'rgba(16,185,129,0.15)', color: '#10b981', border: '1px solid rgba(16,185,129,0.3)', display: 'flex', alignItems: 'center', gap: '10px' }}>
          <CheckCircle2 size={18} />
          <span>{notice}</span>
        </div>
      )}

      {/* KPI Stats Bar */}
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(220px, 1fr))', gap: '16px' }}>
        <div className="glass-panel" style={{ padding: '18px 20px', display: 'flex', alignItems: 'center', gap: '16px' }}>
          <div style={{ width: '44px', height: '44px', borderRadius: '10px', background: 'rgba(59,130,246,0.15)', color: '#3b82f6', display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
            <Building2 size={22} />
          </div>
          <div>
            <div style={{ fontSize: '0.8rem', color: 'var(--text-secondary)' }}>Sedi Aziendali</div>
            <div style={{ fontSize: '1.4rem', fontWeight: 700, marginTop: '2px' }}>{locations.length}</div>
          </div>
        </div>

        <div className="glass-panel" style={{ padding: '18px 20px', display: 'flex', alignItems: 'center', gap: '16px' }}>
          <div style={{ width: '44px', height: '44px', borderRadius: '10px', background: 'rgba(16,185,129,0.15)', color: '#10b981', display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
            <FileText size={22} />
          </div>
          <div>
            <div style={{ fontSize: '0.8rem', color: 'var(--text-secondary)' }}>Fatture Totali Sede Attiva</div>
            <div style={{ fontSize: '1.4rem', fontWeight: 700, marginTop: '2px' }}>{readiness?.invoices || 0}</div>
          </div>
        </div>

        <div className="glass-panel" style={{ padding: '18px 20px', display: 'flex', alignItems: 'center', gap: '16px' }}>
          <div style={{ width: '44px', height: '44px', borderRadius: '10px', background: 'rgba(245,158,11,0.15)', color: '#f59e0b', display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
            <Users size={22} />
          </div>
          <div>
            <div style={{ fontSize: '0.8rem', color: 'var(--text-secondary)' }}>Utenti & Manager</div>
            <div style={{ fontSize: '1.4rem', fontWeight: 700, marginTop: '2px' }}>{readiness?.users || 0}</div>
          </div>
        </div>
      </div>

      {/* Main Glass Panel */}
      <div className="glass-panel" style={{ padding: '24px', display: 'flex', flexDirection: 'column', gap: '20px' }}>
        
        {/* Navigation Tabs & Actions */}
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', flexWrap: 'wrap', gap: '16px', borderBottom: '1px solid var(--border-glass)', paddingBottom: '16px' }}>
          <div style={{ display: 'flex', gap: '12px' }}>
            <button
              onClick={() => setActiveSubTab('sedi')}
              style={{
                padding: '10px 18px',
                borderRadius: '8px',
                border: 'none',
                cursor: 'pointer',
                fontWeight: 600,
                fontSize: '0.9rem',
                display: 'flex',
                alignItems: 'center',
                gap: '8px',
                background: activeSubTab === 'sedi' ? 'var(--accent-blue, #3b82f6)' : 'rgba(255,255,255,0.05)',
                color: 'white',
              }}
            >
              <Store size={16} />
              Gestione Sedi & Location ({locations.length})
            </button>

            <button
              onClick={() => setActiveSubTab('thresholds')}
              style={{
                padding: '10px 18px',
                borderRadius: '8px',
                border: 'none',
                cursor: 'pointer',
                fontWeight: 600,
                fontSize: '0.9rem',
                display: 'flex',
                alignItems: 'center',
                gap: '8px',
                background: activeSubTab === 'thresholds' ? 'var(--accent-blue, #3b82f6)' : 'rgba(255,255,255,0.05)',
                color: 'white',
              }}
            >
              <Sliders size={16} />
              Soglie di Controllo & Diagnostica
            </button>
          </div>

          <div style={{ display: 'flex', gap: '10px' }}>
            {profile?.ruolo === 'admin' && activeSubTab === 'sedi' && (
              <button onClick={() => openModal()} className="btn btn-primary" style={{ display: 'flex', alignItems: 'center', gap: '8px', fontSize: '0.85rem' }}>
                <Plus size={16} />
                Nuova Sede
              </button>
            )}

            <button
              onClick={() => {
                void loadBase()
                if (selectedLocationId) void loadReadiness(Number(selectedLocationId))
              }}
              disabled={busy}
              title="Ricarica dati"
              style={{
                background: 'rgba(255,255,255,0.05)',
                border: '1px solid var(--border-glass)',
                borderRadius: '8px',
                padding: '9px 12px',
                color: 'var(--text-secondary)',
                cursor: 'pointer',
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'center',
              }}
            >
              <RefreshCw size={15} className={busy ? 'animate-spin' : ''} />
            </button>
          </div>
        </div>

        {/* ──────────────────────────────────────────────────────────── */}
        {/* SUBTAB 1: GESTIONE SEDI & LOCATION (ANAGRAFICA)              */}
        {/* ──────────────────────────────────────────────────────────── */}
        {activeSubTab === 'sedi' && (
          <div style={{ display: 'flex', flexDirection: 'column', gap: '18px' }}>
            {locations.length === 0 ? (
              <div style={{ textAlign: 'center', padding: '50px 0', color: 'var(--text-secondary)' }}>
                <Store size={36} style={{ margin: '0 auto 12px', opacity: 0.4 }} />
                <p style={{ margin: 0, fontSize: '1rem', fontWeight: 600 }}>Nessuna sede configurata</p>
                <p style={{ margin: '6px 0 16px', fontSize: '0.85rem' }}>Aggiungi la prima sede per associare le fatture passive ricevute dal Sistema di Interscambio.</p>
                {profile?.ruolo === 'admin' && (
                  <button onClick={() => openModal()} className="btn btn-primary" style={{ margin: '0 auto' }}>
                    <Plus size={16} />
                    Crea Prima Sede
                  </button>
                )}
              </div>
            ) : (
              <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(340px, 1fr))', gap: '16px' }}>
                {locations.map(loc => (
                  <div
                    key={loc.id}
                    className="glass-panel"
                    style={{
                      padding: '20px',
                      display: 'flex',
                      flexDirection: 'column',
                      justifyContent: 'space-between',
                      gap: '16px',
                      border: '1px solid rgba(255,255,255,0.08)',
                      background: selectedLocationId === loc.id ? 'rgba(59,130,246,0.06)' : 'rgba(255,255,255,0.02)',
                      borderLeft: selectedLocationId === loc.id ? '4px solid #3b82f6' : '1px solid rgba(255,255,255,0.08)',
                    }}
                  >
                    <div>
                      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', gap: '10px' }}>
                        <div>
                          <div style={{ fontWeight: 700, fontSize: '1.05rem', color: 'white' }}>{loc.nome_struttura}</div>
                          <div style={{ fontSize: '0.8rem', color: 'var(--text-secondary)', marginTop: '3px' }}>
                            P.IVA Cessionario: <strong style={{ color: 'white' }}>{loc.piva_riferimento}</strong>
                          </div>
                        </div>

                        <span
                          style={{
                            fontSize: '0.72rem',
                            padding: '3px 8px',
                            borderRadius: '10px',
                            background: 'rgba(59,130,246,0.15)',
                            color: '#3b82f6',
                            fontWeight: 700,
                            textTransform: 'uppercase',
                          }}
                        >
                          {loc.tipologia}
                        </span>
                      </div>
                    </div>

                    {/* Card Actions */}
                    <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', paddingTop: '12px', borderTop: '1px solid rgba(255,255,255,0.06)' }}>
                      <button
                        type="button"
                        onClick={() => {
                          setSelectedLocationId(loc.id)
                          setActiveSubTab('thresholds')
                        }}
                        style={{
                          background: 'none',
                          border: 'none',
                          color: '#0ea5e9',
                          cursor: 'pointer',
                          padding: 0,
                          fontSize: '0.8rem',
                          fontWeight: 600,
                        }}
                      >
                        Configura Soglie & Diagnostica →
                      </button>

                      {profile?.ruolo === 'admin' && (
                        <div style={{ display: 'flex', gap: '6px' }}>
                          <button
                            type="button"
                            onClick={() => openModal(loc)}
                            title="Modifica Sede"
                            style={{
                              background: 'rgba(255,255,255,0.05)',
                              border: '1px solid var(--border-glass)',
                              borderRadius: '6px',
                              padding: '5px 8px',
                              color: 'var(--text-secondary)',
                              cursor: 'pointer',
                            }}
                          >
                            <Pencil size={13} />
                          </button>
                          <button
                            type="button"
                            onClick={() => handleDeleteLocation(loc)}
                            title="Elimina Sede"
                            style={{
                              background: 'rgba(239,68,68,0.1)',
                              border: '1px solid rgba(239,68,68,0.2)',
                              borderRadius: '6px',
                              padding: '5px 8px',
                              color: '#ef4444',
                              cursor: 'pointer',
                            }}
                          >
                            <Trash2 size={13} />
                          </button>
                        </div>
                      )}
                    </div>
                  </div>
                ))}
              </div>
            )}
          </div>
        )}

        {/* ──────────────────────────────────────────────────────────── */}
        {/* SUBTAB 2: SOGLIE DI CONTROLLO & DIAGNOSTICA AVANZATA         */}
        {/* ──────────────────────────────────────────────────────────── */}
        {activeSubTab === 'thresholds' && (
          <div style={{ display: 'flex', flexDirection: 'column', gap: '20px' }}>
            
            {/* Selettore Sede */}
            <div style={{ display: 'flex', alignItems: 'center', gap: '14px', flexWrap: 'wrap' }}>
              <label style={{ fontSize: '0.9rem', fontWeight: 600, color: 'var(--text-secondary)' }}>
                Seleziona Sede da Configurare:
              </label>
              <select
                value={selectedLocationId}
                onChange={e => setSelectedLocationId(Number(e.target.value))}
                disabled={profile?.ruolo !== 'admin'}
                style={{
                  padding: '9px 14px',
                  background: '#13131c',
                  border: '1px solid var(--border-glass)',
                  borderRadius: '8px',
                  color: 'white',
                  fontSize: '0.9rem',
                  fontWeight: 600,
                  minWidth: '240px',
                }}
              >
                {locations.map(loc => (
                  <option key={loc.id} value={loc.id}>
                    {loc.nome_struttura} ({loc.piva_riferimento})
                  </option>
                ))}
              </select>
            </div>

            {readiness && (
              <>
                {/* Progress Card */}
                <div style={{ padding: '16px 20px', borderRadius: '10px', background: 'rgba(59,130,246,0.06)', border: '1px solid rgba(59,130,246,0.25)' }}>
                  <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '10px' }}>
                    <div>
                      <div style={{ fontSize: '0.8rem', color: 'var(--text-secondary)' }}>Stato Operativo Sede</div>
                      <h3 style={{ margin: '2px 0 0', fontSize: '1.2rem', color: 'white' }}>{readiness.location_name}</h3>
                    </div>
                    <strong style={{ fontSize: '1.5rem', color: '#60a5fa' }}>
                      {completed} / {steps.length}
                    </strong>
                  </div>
                  <div style={{ height: '8px', borderRadius: '4px', background: 'rgba(255,255,255,0.08)', overflow: 'hidden' }}>
                    <div style={{ height: '100%', width: `${steps.length ? (completed / steps.length) * 100 : 0}%`, background: '#3b82f6', transition: 'width 0.3s ease' }} />
                  </div>
                </div>

                {/* Checklist Griglia */}
                <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(220px, 1fr))', gap: '12px' }}>
                  {steps.map(([name, done, detail]) => (
                    <div
                      key={name}
                      style={{
                        padding: '14px',
                        borderRadius: '8px',
                        border: '1px solid var(--border-glass)',
                        background: 'rgba(255,255,255,0.02)',
                        display: 'flex',
                        flexDirection: 'column',
                        gap: '6px',
                      }}
                    >
                      <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                        {done ? <CheckCircle2 size={16} color="#34d399" /> : <Circle size={16} color="#94a3b8" />}
                        <strong style={{ fontSize: '0.85rem', color: 'white' }}>{name}</strong>
                      </div>
                      <span style={{ fontSize: '0.75rem', color: 'var(--text-secondary)' }}>{detail}</span>
                    </div>
                  ))}
                </div>

                {/* Form Soglie Esplicite */}
                {settings && (
                  <div style={{ padding: '20px', borderRadius: '10px', border: '1px solid var(--border-glass)', background: 'rgba(255,255,255,0.02)', display: 'flex', flexDirection: 'column', gap: '16px' }}>
                    <div>
                      <h4 style={{ margin: '0 0 4px', fontSize: '1rem', fontWeight: 700 }}>Soglie di Riconciliazione & Tolleranze Prezzo</h4>
                      <p style={{ margin: 0, fontSize: '0.8rem', color: 'var(--text-secondary)' }}>
                        Definisci entro quali limiti una discrepanza di prezzo viene tollerata automaticamente e quando deve essere bloccata come anomalia grave.
                      </p>
                    </div>

                    <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(220px, 1fr))', gap: '14px' }}>
                      <label style={{ display: 'flex', flexDirection: 'column', gap: '6px', fontSize: '0.82rem', color: 'var(--text-secondary)' }}>
                        Tolleranza Assoluta Prezzo (€)
                        <input
                          type="number"
                          min="0"
                          step="0.01"
                          value={settings.price_tolerance_absolute}
                          onChange={e => setSettings({ ...settings, price_tolerance_absolute: e.target.value })}
                          style={{ padding: '9px', background: 'rgba(0,0,0,0.25)', border: '1px solid var(--border-glass)', borderRadius: '6px', color: 'white' }}
                        />
                      </label>

                      <label style={{ display: 'flex', flexDirection: 'column', gap: '6px', fontSize: '0.82rem', color: 'var(--text-secondary)' }}>
                        Tolleranza Percentuale (%)
                        <input
                          type="number"
                          min="0"
                          step="0.1"
                          value={settings.price_tolerance_percent}
                          onChange={e => setSettings({ ...settings, price_tolerance_percent: e.target.value })}
                          style={{ padding: '9px', background: 'rgba(0,0,0,0.25)', border: '1px solid var(--border-glass)', borderRadius: '6px', color: 'white' }}
                        />
                      </label>

                      <label style={{ display: 'flex', flexDirection: 'column', gap: '6px', fontSize: '0.82rem', color: 'var(--text-secondary)' }}>
                        Soglia Anomalia Grave / Importante (€)
                        <input
                          type="number"
                          min="0.01"
                          step="0.01"
                          value={settings.important_anomaly_threshold}
                          onChange={e => setSettings({ ...settings, important_anomaly_threshold: e.target.value })}
                          style={{ padding: '9px', background: 'rgba(0,0,0,0.25)', border: '1px solid var(--border-glass)', borderRadius: '6px', color: 'white' }}
                        />
                      </label>

                      <label style={{ display: 'flex', flexDirection: 'column', gap: '6px', fontSize: '0.82rem', color: 'var(--text-secondary)' }}>
                        Giorni Limite Riconciliazione Ferma
                        <input
                          type="number"
                          min="1"
                          max="90"
                          value={settings.stalled_reconciliation_days}
                          onChange={e => setSettings({ ...settings, stalled_reconciliation_days: Number(e.target.value) })}
                          style={{ padding: '9px', background: 'rgba(0,0,0,0.25)', border: '1px solid var(--border-glass)', borderRadius: '6px', color: 'white' }}
                        />
                      </label>

                      <label style={{ display: 'flex', flexDirection: 'column', gap: '6px', fontSize: '0.82rem', color: 'var(--text-secondary)' }}>
                        Giorni Sollecito Nota di Credito
                        <input
                          type="number"
                          min="1"
                          max="180"
                          value={settings.missing_credit_note_days}
                          onChange={e => setSettings({ ...settings, missing_credit_note_days: Number(e.target.value) })}
                          style={{ padding: '9px', background: 'rgba(0,0,0,0.25)', border: '1px solid var(--border-glass)', borderRadius: '6px', color: 'white' }}
                        />
                      </label>

                      <div style={{ display: 'flex', alignItems: 'center', paddingTop: '18px' }}>
                        <label style={{ display: 'flex', gap: '10px', alignItems: 'center', cursor: 'pointer', fontSize: '0.85rem', color: 'white' }}>
                          <input
                            type="checkbox"
                            checked={settings.notifications_enabled}
                            onChange={e => setSettings({ ...settings, notifications_enabled: e.target.checked })}
                            style={{ width: '16px', height: '16px', accentColor: '#3b82f6' }}
                          />
                          Notifiche & Avvisi Operativi Attivi
                        </label>
                      </div>
                    </div>

                    {profile?.ruolo === 'admin' && (
                      <button
                        type="button"
                        className="btn btn-primary"
                        onClick={handleSaveSettings}
                        disabled={busy}
                        style={{ alignSelf: 'flex-start', marginTop: '8px', display: 'flex', alignItems: 'center', gap: '8px' }}
                      >
                        <Save size={15} />
                        Salva Configurazione Sede
                      </button>
                    )}
                  </div>
                )}
              </>
            )}
          </div>
        )}
      </div>

      {/* ──────────────────────────────────────────────────────────── */}
      {/* MODAL: NUOVA / MODIFICA SEDE                                 */}
      {/* ──────────────────────────────────────────────────────────── */}
      {showLocationModal && (
        <div
          style={{
            position: 'fixed',
            inset: 0,
            background: 'rgba(0,0,0,0.75)',
            zIndex: 1100,
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            padding: '20px',
          }}
        >
          <div
            className="glass-panel"
            style={{
              width: '100%',
              maxWidth: '480px',
              padding: '28px',
              display: 'flex',
              flexDirection: 'column',
              gap: '20px',
              border: '1px solid rgba(255,255,255,0.15)',
            }}
          >
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
              <h3 style={{ margin: 0, fontSize: '1.2rem', fontWeight: 700 }}>
                {editingLocation ? 'Modifica Sede Aziendale' : 'Nuova Sede Aziendale'}
              </h3>
              <button
                type="button"
                onClick={() => setShowLocationModal(false)}
                style={{ background: 'none', border: 'none', color: 'var(--text-secondary)', cursor: 'pointer' }}
              >
                <X size={20} />
              </button>
            </div>

            <form onSubmit={handleSaveLocation} style={{ display: 'flex', flexDirection: 'column', gap: '16px' }}>
              <label style={{ display: 'flex', flexDirection: 'column', gap: '6px', fontSize: '0.82rem', color: 'var(--text-secondary)' }}>
                Nome Struttura / Ragione Sociale *
                <input
                  type="text"
                  required
                  placeholder="Es. Lido Playaluna SRL"
                  value={formNome}
                  onChange={e => setFormNome(e.target.value)}
                  style={{
                    padding: '11px',
                    background: 'rgba(0,0,0,0.25)',
                    border: '1px solid var(--border-glass)',
                    borderRadius: '8px',
                    color: 'white',
                  }}
                />
              </label>

              <label style={{ display: 'flex', flexDirection: 'column', gap: '6px', fontSize: '0.82rem', color: 'var(--text-secondary)' }}>
                Partita IVA Cessionario (11 cifre) *
                <input
                  type="text"
                  required
                  maxLength={11}
                  placeholder="Es. 09146931218"
                  value={formPiva}
                  onChange={e => setFormPiva(e.target.value.replace(/\D/g, ''))}
                  style={{
                    padding: '11px',
                    background: 'rgba(0,0,0,0.25)',
                    border: '1px solid var(--border-glass)',
                    borderRadius: '8px',
                    color: 'white',
                    fontFamily: 'monospace',
                    letterSpacing: '1px',
                  }}
                />
              </label>

              <label style={{ display: 'flex', flexDirection: 'column', gap: '6px', fontSize: '0.82rem', color: 'var(--text-secondary)' }}>
                Tipologia Attività
                <select
                  value={formTipo}
                  onChange={e => setFormTipo(e.target.value as any)}
                  style={{
                    padding: '11px',
                    background: '#13131c',
                    border: '1px solid var(--border-glass)',
                    borderRadius: '8px',
                    color: 'white',
                  }}
                >
                  <option value="balneare">Stabilimento Balneare</option>
                  <option value="ristorante">Ristorante / Pizzeria</option>
                  <option value="discoteca">Cocktail Bar / Discoteca</option>
                  <option value="evento">Location Eventi / Catering</option>
                </select>
              </label>

              <div style={{ display: 'flex', justifyContent: 'flex-end', gap: '10px', marginTop: '10px' }}>
                <button
                  type="button"
                  className="btn btn-secondary"
                  disabled={submittingModal}
                  onClick={() => setShowLocationModal(false)}
                >
                  Annulla
                </button>
                <button type="submit" className="btn btn-primary" disabled={submittingModal}>
                  {submittingModal ? <RefreshCw className="animate-spin" size={16} /> : <Check size={16} />}
                  {editingLocation ? 'Aggiorna Sede' : 'Crea Sede'}
                </button>
              </div>
            </form>
          </div>
        </div>
      )}

    </div>
  )
}
