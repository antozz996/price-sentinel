import { useEffect, useState } from 'react'
import {
  AlertTriangle,
  BellRing,
  CheckCircle2,
  Loader2,
  Play,
  RefreshCw,
} from 'lucide-react'
import { fetchWithAuth } from '../api'

type Alert = {
  id: string
  alert_type: string
  severity: 'info' | 'warning' | 'critical'
  status: 'open' | 'acknowledged' | 'resolved'
  location_id?: number
  entity_type: string
  entity_id: string
  title: string
  message: string
  details: Record<string, unknown>
  first_detected_at: string
  last_detected_at: string
}

type Run = {
  id: string
  status: string
  alerts_detected: number
  alerts_created: number
  alerts_resolved: number
  completed_at?: string
}

const card: React.CSSProperties = {
  border: '1px solid var(--border-glass)',
  borderRadius: 13,
  padding: 16,
  background: 'rgba(255,255,255,.025)',
}

export default function OperationalAlerts() {
  const [alerts, setAlerts] = useState<Alert[]>([])
  const [profile, setProfile] = useState<{ruolo:string} | null>(null)
  const [lastRun, setLastRun] = useState<Run | null>(null)
  const [filter, setFilter] = useState<'active'|'resolved'>('active')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [notice, setNotice] = useState('')

  const load = async () => {
    setBusy(true); setError('')
    try {
      const [rows, me] = await Promise.all([
        fetchWithAuth('/automation/alerts?limit=250'),
        fetchWithAuth('/auth/me'),
      ])
      setAlerts(rows)
      setProfile(me)
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : 'Monitor non disponibile')
    } finally { setBusy(false) }
  }

  useEffect(() => { void load() }, [])

  const run = async () => {
    setBusy(true);setError('');setNotice('')
    try {
      const result = await fetchWithAuth('/automation/run', {method:'POST'})
      setLastRun(result)
      setNotice(`Controllo completato: ${result.alerts_detected} condizioni rilevate, ${result.alerts_created} nuovi avvisi.`)
      await load()
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : 'Controllo non riuscito')
    } finally { setBusy(false) }
  }

  const acknowledge = async (id:string) => {
    setBusy(true);setError('')
    try {
      await fetchWithAuth(`/automation/alerts/${id}/acknowledge`, {method:'POST'})
      await load()
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : 'Conferma non riuscita')
    } finally { setBusy(false) }
  }

  const visible = alerts.filter(item => filter === 'resolved'
    ? item.status === 'resolved'
    : item.status !== 'resolved')
  const critical = alerts.filter(item => item.status !== 'resolved' && item.severity === 'critical').length
  const warning = alerts.filter(item => item.status !== 'resolved' && item.severity === 'warning').length

  return <div style={{display:'grid',gap:18}} data-testid="operational-alerts">
    <div style={{display:'flex',justifyContent:'space-between',gap:12,flexWrap:'wrap'}}>
      <div>
        <h2 style={{margin:0}}>Monitor operativo</h2>
        <p style={{color:'var(--text-secondary)'}}>Segnala blocchi e scadenze. Non associa fatture e non prende decisioni economiche.</p>
      </div>
      <div style={{display:'flex',gap:8}}>
        <button className="btn" onClick={()=>void load()} disabled={busy}><RefreshCw size={15}/> Aggiorna</button>
        {profile?.ruolo==='admin'&&<button className="btn btn-primary" onClick={()=>void run()} disabled={busy}><Play size={15}/> Esegui controllo</button>}
      </div>
    </div>
    {busy&&<div style={{color:'var(--text-secondary)'}}><Loader2 size={15}/> Elaborazione…</div>}
    {error&&<div style={{...card,borderColor:'rgba(239,68,68,.4)',color:'#f87171'}}><AlertTriangle size={16}/> {error}</div>}
    {notice&&<div style={{...card,borderColor:'rgba(16,185,129,.4)',color:'#34d399'}}><CheckCircle2 size={16}/> {notice}</div>}
    <div style={{display:'grid',gridTemplateColumns:'repeat(auto-fit,minmax(180px,1fr))',gap:10}}>
      <div style={card}><small>Critici aperti</small><strong style={{display:'block',fontSize:25,color:critical?'#f87171':'#34d399'}}>{critical}</strong></div>
      <div style={card}><small>Avvisi aperti</small><strong style={{display:'block',fontSize:25,color:warning?'#fbbf24':'#34d399'}}>{warning}</strong></div>
      <div style={card}><small>Ultimo controllo</small><strong style={{display:'block',marginTop:8}}>{lastRun?.status||'automatico / non eseguito qui'}</strong></div>
    </div>
    <div style={{display:'flex',gap:8}}>
      <button className={`btn ${filter==='active'?'btn-primary':''}`} onClick={()=>setFilter('active')}>Attivi</button>
      <button className={`btn ${filter==='resolved'?'btn-primary':''}`} onClick={()=>setFilter('resolved')}>Risolti</button>
    </div>
    <div style={{display:'grid',gap:10}}>
      {!visible.length&&<div style={card}><BellRing size={28} color="#34d399"/><h3>Nessun avviso</h3><p style={{color:'var(--text-secondary)'}}>Non risultano condizioni operative da gestire in questa vista.</p></div>}
      {visible.map(item=><article key={item.id} style={{...card,borderColor:item.severity==='critical'?'rgba(239,68,68,.35)':item.severity==='warning'?'rgba(245,158,11,.35)':'rgba(59,130,246,.3)'}}>
        <div style={{display:'flex',justifyContent:'space-between',gap:10,flexWrap:'wrap'}}>
          <div><small style={{color:item.severity==='critical'?'#f87171':item.severity==='warning'?'#fbbf24':'#60a5fa'}}>{item.severity.toUpperCase()} · {item.alert_type}</small><h3 style={{margin:'5px 0'}}>{item.title}</h3><p style={{margin:0,color:'var(--text-secondary)'}}>{item.message}</p></div>
          {item.status==='open'&&<button className="btn" onClick={()=>void acknowledge(item.id)}><CheckCircle2 size={14}/> Preso in carico</button>}
        </div>
        <small style={{display:'block',marginTop:10,color:'var(--text-secondary)'}}>Ultimo rilevamento: {new Date(item.last_detected_at).toLocaleString('it-IT')} · {item.entity_type} {item.entity_id}</small>
      </article>)}
    </div>
  </div>
}
