import { useEffect, useState } from 'react'
import { CheckCircle2, History, Link2, Search, Unlink } from 'lucide-react'
import { fetchWithAuth } from '../api'

type Supplier = { id: number; name: string }
type Equivalence = {
  id: number
  canonical_supplier_id: number
  canonical_supplier_name: string
  equivalent_supplier_id: number
  equivalent_supplier_name: string
  is_active: boolean
  reason: string
  approved_by_email: string
  approved_at: string
  updated_by_email: string
  updated_at: string
}
type AuditEntry = {
  id: number
  equivalence_id: number
  action: string
  canonical_supplier_name: string
  equivalent_supplier_name: string
  reason: string
  actor_email: string
  occurred_at: string
}

const panel: React.CSSProperties = {
  background: 'var(--bg-glass)',
  border: '1px solid var(--border-glass)',
  borderRadius: 12,
  padding: 18,
}

function SupplierPicker({
  label,
  selected,
  onSelect,
}: {
  label: string
  selected: Supplier | null
  onSelect: (supplier: Supplier) => void
}) {
  const [query, setQuery] = useState('')
  const [results, setResults] = useState<Supplier[]>([])

  const search = async () => {
    if (query.trim().length < 2) return
    setResults(
      await fetchWithAuth(
        `/reconciliations/supplier-equivalences/search?query=${encodeURIComponent(query.trim())}`,
      ),
    )
  }

  return (
    <div style={{ minWidth: 250, flex: 1 }}>
      <strong style={{ fontSize: 12 }}>{label}</strong>
      {selected && (
        <div style={{ color: '#60a5fa', margin: '7px 0', fontSize: 13 }}>
          Selezionato: {selected.name} #{selected.id}
        </div>
      )}
      <div style={{ display: 'flex', gap: 8, marginTop: 7 }}>
        <input
          value={query}
          onChange={(event) => setQuery(event.target.value)}
          placeholder="Cerca fornitore"
          style={{ flex: 1 }}
        />
        <button className="btn" type="button" onClick={() => void search()}>
          <Search size={14} />
        </button>
      </div>
      {results.map((supplier) => (
        <button
          className="btn"
          type="button"
          key={supplier.id}
          onClick={() => {
            onSelect(supplier)
            setResults([])
          }}
          style={{ width: '100%', justifyContent: 'flex-start', marginTop: 6 }}
        >
          {supplier.name} #{supplier.id}
        </button>
      ))}
    </div>
  )
}

export default function SupplierEquivalencesPanel() {
  const [authorized, setAuthorized] = useState<boolean | null>(null)
  const [rows, setRows] = useState<Equivalence[]>([])
  const [audit, setAudit] = useState<AuditEntry[]>([])
  const [canonical, setCanonical] = useState<Supplier | null>(null)
  const [equivalent, setEquivalent] = useState<Supplier | null>(null)
  const [reason, setReason] = useState('')
  const [confirmed, setConfirmed] = useState(false)
  const [showAudit, setShowAudit] = useState(false)
  const [busy, setBusy] = useState(false)
  const [message, setMessage] = useState('')
  const [error, setError] = useState('')

  const load = async () => {
    try {
      const data = await fetchWithAuth(
        '/reconciliations/supplier-equivalences?include_inactive=true',
      )
      setRows(data)
      setAuthorized(true)
    } catch (caught) {
      const text = caught instanceof Error ? caught.message : ''
      if (text.includes('403')) {
        setAuthorized(false)
        return
      }
      setAuthorized(true)
      setError(text || 'Equivalenze non disponibili')
    }
  }

  useEffect(() => {
    void load()
  }, [])

  const create = async () => {
    if (!canonical || !equivalent || !confirmed || reason.trim().length < 8) {
      setError('Seleziona due fornitori, inserisci la motivazione e conferma esplicitamente.')
      return
    }
    setBusy(true)
    setError('')
    try {
      await fetchWithAuth('/reconciliations/supplier-equivalences', {
        method: 'POST',
        body: JSON.stringify({
          canonical_supplier_id: canonical.id,
          equivalent_supplier_id: equivalent.id,
          reason: reason.trim(),
          confirm: true,
        }),
      })
      setCanonical(null)
      setEquivalent(null)
      setReason('')
      setConfirmed(false)
      setMessage('Equivalenza approvata e registrata nello storico.')
      await load()
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : 'Creazione non riuscita')
    } finally {
      setBusy(false)
    }
  }

  const changeState = async (row: Equivalence) => {
    const action = row.is_active ? 'disattivare' : 'riattivare'
    const changeReason = window.prompt(
      `Motivazione obbligatoria per ${action} l’equivalenza:`,
    )
    if (!changeReason || changeReason.trim().length < 8) return
    if (
      !window.confirm(
        `Confermi esplicitamente di voler ${action} ${row.canonical_supplier_name} ↔ ${row.equivalent_supplier_name}?`,
      )
    ) return
    setBusy(true)
    setError('')
    try {
      await fetchWithAuth(`/reconciliations/supplier-equivalences/${row.id}`, {
        method: 'PATCH',
        body: JSON.stringify({
          is_active: !row.is_active,
          reason: changeReason.trim(),
          confirm: true,
        }),
      })
      setMessage(`Equivalenza ${row.is_active ? 'disattivata' : 'riattivata'}.`)
      await load()
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : 'Modifica non riuscita')
    } finally {
      setBusy(false)
    }
  }

  const loadAudit = async () => {
    setShowAudit(!showAudit)
    if (!showAudit && audit.length === 0) {
      try {
        setAudit(
          await fetchWithAuth('/reconciliations/supplier-equivalences/audit'),
        )
      } catch (caught) {
        setError(caught instanceof Error ? caught.message : 'Storico non disponibile')
      }
    }
  }

  if (authorized !== true) return null

  return (
    <section style={panel} data-testid="supplier-equivalences">
      <h3>Equivalenze identità fornitori</h3>
      <p style={{ color: 'var(--text-secondary)', fontSize: 12 }}>
        Solo associazioni esplicite e auditabili. I fornitori, le fatture e gli alias
        originali non vengono modificati.
      </p>
      <div style={{ display: 'flex', gap: 14, flexWrap: 'wrap' }}>
        <SupplierPicker
          label="Fornitore canonico (fatture)"
          selected={canonical}
          onSelect={setCanonical}
        />
        <SupplierPicker
          label="Fornitore equivalente (ordini/alias)"
          selected={equivalent}
          onSelect={setEquivalent}
        />
      </div>
      <textarea
        value={reason}
        onChange={(event) => setReason(event.target.value)}
        placeholder="Motivazione obbligatoria dell’equivalenza"
        style={{ width: '100%', minHeight: 70, marginTop: 12 }}
      />
      <label style={{ display: 'flex', gap: 8, alignItems: 'center', marginTop: 10 }}>
        <input
          type="checkbox"
          checked={confirmed}
          onChange={(event) => setConfirmed(event.target.checked)}
        />
        Confermo esplicitamente che i due record rappresentano la stessa identità
        commerciale.
      </label>
      <button
        className="btn btn-primary"
        type="button"
        disabled={busy}
        onClick={() => void create()}
        style={{ marginTop: 12 }}
      >
        <Link2 size={14} /> Approva equivalenza
      </button>
      {message && (
        <p style={{ color: '#4ade80' }}>
          <CheckCircle2 size={14} /> {message}
        </p>
      )}
      {error && <p style={{ color: '#f87171' }}>{error}</p>}

      <div style={{ display: 'flex', flexDirection: 'column', gap: 8, marginTop: 18 }}>
        {rows.map((row) => (
          <div
            key={row.id}
            style={{
              border: '1px solid var(--border-glass)',
              borderRadius: 9,
              padding: 12,
              display: 'flex',
              justifyContent: 'space-between',
              gap: 12,
              flexWrap: 'wrap',
            }}
          >
            <div>
              <strong>
                {row.canonical_supplier_name} #{row.canonical_supplier_id} ↔{' '}
                {row.equivalent_supplier_name} #{row.equivalent_supplier_id}
              </strong>
              <div style={{ fontSize: 11, color: 'var(--text-secondary)', marginTop: 5 }}>
                {row.is_active ? 'ATTIVA' : 'DISATTIVATA'} · {row.reason} · approvata
                da {row.approved_by_email} il{' '}
                {new Date(row.approved_at).toLocaleString('it-IT')}
              </div>
            </div>
            <button
              className="btn"
              type="button"
              disabled={busy}
              onClick={() => void changeState(row)}
            >
              {row.is_active ? <Unlink size={14} /> : <Link2 size={14} />}
              {row.is_active ? 'Disattiva' : 'Riattiva'}
            </button>
          </div>
        ))}
      </div>
      <button
        className="btn"
        type="button"
        onClick={() => void loadAudit()}
        style={{ marginTop: 12 }}
      >
        <History size={14} /> {showAudit ? 'Nascondi storico' : 'Mostra storico audit'}
      </button>
      {showAudit && (
        <div style={{ marginTop: 10, fontSize: 12 }}>
          {audit.map((entry) => (
            <div key={entry.id} style={{ padding: '7px 0', borderBottom: '1px solid var(--border-glass)' }}>
              {entry.action} · {entry.canonical_supplier_name} ↔{' '}
              {entry.equivalent_supplier_name} · {entry.actor_email} ·{' '}
              {new Date(entry.occurred_at).toLocaleString('it-IT')} · {entry.reason}
            </div>
          ))}
        </div>
      )}
    </section>
  )
}
