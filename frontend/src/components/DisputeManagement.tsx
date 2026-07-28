import { useEffect, useMemo, useState } from 'react'
import {
  AlertTriangle,
  CheckCircle2,
  Clipboard,
  Download,
  FilePlus2,
  Loader2,
  Mail,
  MessageCircle,
  Paperclip,
  Plus,
  RefreshCw,
  Send,
  WalletCards,
} from 'lucide-react'
import { API_BASE, fetchWithAuth, getHeaders } from '../api'

type Candidate = {
  source: 'reconciliation' | 'legacy'
  id: number
  location_id: number
  supplier_id: number
  reconciliation_id?: string
  fattura_id?: number
  reason: string
  description?: string
  amount?: string
}

type CaseAnomaly = {
  id: number
  claimed_amount: string
  recognized_amount: string
  recovered_amount: string
  reason_snapshot: string
  evidence_snapshot: Record<string, unknown>
}

type Communication = {
  id: string
  channel: string
  status: string
  recipient?: string
  subject?: string
  body_snapshot: string
}

type CreditNote = {
  id: string
  document_number: string
  issue_date: string
  total_amount: string
  status: string
}

type DisputeCase = {
  id: string
  case_code: string
  location_id: number
  supplier_id: number
  supplier_name?: string
  location_name?: string
  status: string
  title: string
  owner_email?: string
  due_date?: string
  internal_notes?: string
  requested_amount: string
  recognized_amount: string
  recovered_amount: string
  unrecovered_amount: string
  version: number
  anomalies: CaseAnomaly[]
  communications: Communication[]
  responses: Array<{id:string;channel:string;response_text:string;received_at:string}>
  attachments: Array<{id:string;filename:string;size_bytes:number;description?:string}>
  credit_notes: CreditNote[]
  audit_events: Array<{id:number;action:string;created_at:string}>
}

type Dashboard = {
  total_anomalies: number
  total_detected: string
  total_contested: string
  total_recognized: string
  total_recovered: string
  total_outstanding: string
  open_cases: number
  overdue_cases: number
  missing_credit_notes: number
  average_resolution_days?: string
  by_location: Array<Record<string, string | number>>
  by_supplier: Array<Record<string, string | number>>
  by_cause: Array<Record<string, string | number>>
  monthly_trend: Array<Record<string, string | number>>
}

const panel: React.CSSProperties = {
  border: '1px solid var(--border-glass)',
  borderRadius: 14,
  background: 'rgba(255,255,255,.025)',
  padding: 18,
}

const money = (value: string | number | undefined) =>
  new Intl.NumberFormat('it-IT', { style: 'currency', currency: 'EUR' })
    .format(Number(value || 0))

const label: Record<string, string> = {
  draft: 'Bozza',
  ready_to_send: 'Pronta',
  sent: 'Inviata',
  supplier_replied: 'Risposta ricevuta',
  credit_note_expected: 'Nota di credito attesa',
  partially_recovered: 'Recuperata in parte',
  recovered: 'Recuperata',
  rejected: 'Respinta',
  closed: 'Chiusa',
  cancelled: 'Annullata',
}

function Badge({ status }: {status:string}) {
  const good = ['recovered', 'closed', 'confirmed'].includes(status)
  const bad = ['rejected', 'cancelled'].includes(status)
  return <span style={{
    display:'inline-flex',padding:'4px 8px',borderRadius:99,fontSize:10,fontWeight:700,
    color:good?'#34d399':bad?'#f87171':'#60a5fa',
    background:good?'rgba(16,185,129,.12)':bad?'rgba(239,68,68,.12)':'rgba(59,130,246,.12)',
  }}>{label[status] || status}</span>
}

export default function DisputeManagement() {
  const [cases, setCases] = useState<DisputeCase[]>([])
  const [dashboard, setDashboard] = useState<Dashboard | null>(null)
  const [candidates, setCandidates] = useState<Candidate[]>([])
  const [selected, setSelected] = useState<DisputeCase | null>(null)
  const [candidateIds, setCandidateIds] = useState<string[]>([])
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [notice, setNotice] = useState('')
  const [showCreate, setShowCreate] = useState(false)
  const [title, setTitle] = useState('')
  const [dueDate, setDueDate] = useState('')
  const [communication, setCommunication] = useState<Communication | null>(null)
  const [communicationBody, setCommunicationBody] = useState('')
  const [channel, setChannel] = useState<'whatsapp'|'email'|'copy'>('email')
  const [recipient, setRecipient] = useState('')
  const [responseText, setResponseText] = useState('')
  const [creditNumber, setCreditNumber] = useState('')
  const [creditDate, setCreditDate] = useState('')
  const [creditAmounts, setCreditAmounts] = useState<Record<number,string>>({})
  const [recognized, setRecognized] = useState<Record<number,string>>({})
  const [claimAmounts, setClaimAmounts] = useState<Record<string,string>>({})

  const load = async () => {
    setBusy(true); setError('')
    try {
      const [caseRows, metrics] = await Promise.all([
        fetchWithAuth('/disputes'),
        fetchWithAuth('/disputes/dashboard'),
      ])
      setCases(caseRows)
      setDashboard(metrics)
      if (selected) {
        const fresh = await fetchWithAuth(`/disputes/${selected.id}`)
        setSelected(fresh)
      }
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : 'Caricamento non riuscito')
    } finally { setBusy(false) }
  }

  useEffect(() => { void load() }, [])

  const loadCandidates = async () => {
    setBusy(true); setError('')
    try {
      setCandidates(await fetchWithAuth('/disputes/candidates?limit=200'))
      setShowCreate(true)
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : 'Anomalie non disponibili')
    } finally { setBusy(false) }
  }

  const act = async (message: string, operation: () => Promise<unknown>) => {
    setBusy(true);setError('');setNotice('')
    try {
      const result = await operation()
      if (result && typeof result === 'object' && 'case_code' in result) {
        setSelected(result as DisputeCase)
      }
      setNotice(message)
      await load()
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : 'Operazione non riuscita')
    } finally { setBusy(false) }
  }

  const toggleCandidate = (candidate: Candidate) => {
    const key = `${candidate.source}:${candidate.id}`
    const first = candidates.find(item => candidateIds.includes(`${item.source}:${item.id}`))
    if (first && (first.location_id !== candidate.location_id
      || first.supplier_id !== candidate.supplier_id
      || first.source !== candidate.source
      || first.reconciliation_id !== candidate.reconciliation_id)) {
      setError('Seleziona anomalie della stessa sede, dello stesso fornitore e della stessa riconciliazione.')
      return
    }
    setCandidateIds(current => current.includes(key)
      ? current.filter(item => item !== key)
      : [...current, key])
  }

  const createCase = () => act('Contestazione creata in bozza.', async () => {
    const chosen = candidates.filter(item => candidateIds.includes(`${item.source}:${item.id}`))
    if (!chosen.length) throw new Error('Seleziona almeno un’anomalia.')
    if (chosen.some(item => Number(claimAmounts[`${item.source}:${item.id}`] ?? item.amount ?? 0) <= 0)) {
      throw new Error('Inserisci un importo positivo per ogni anomalia selezionata.')
    }
    const created = await fetchWithAuth('/disputes', {
      method:'POST',
      body:JSON.stringify({
        title: title || `Contestazione ${chosen[0].description || chosen[0].reason}`,
        due_date: dueDate || null,
        anomalies: chosen.map(item => item.source === 'reconciliation'
          ? { reconciliation_anomaly_id:item.id, claimed_amount:claimAmounts[`${item.source}:${item.id}`] ?? item.amount }
          : { legacy_anomaly_id:item.id, claimed_amount:claimAmounts[`${item.source}:${item.id}`] ?? item.amount }),
      }),
    })
    setShowCreate(false);setCandidateIds([]);setClaimAmounts({});setTitle('');setDueDate('')
    return created
  })

  const transition = (target_status:string, reason?:string) => {
    if (!selected) return
    void act(`Stato aggiornato: ${label[target_status] || target_status}.`, () =>
      fetchWithAuth(`/disputes/${selected.id}/transition`, {
        method:'POST',
        body:JSON.stringify({expected_version:selected.version,target_status,reason}),
      }))
  }

  const prepareCommunication = (bodyOverride?: string) => {
    if (!selected) return
    void act('Comunicazione preparata; nessun invio automatico effettuato.', async () => {
      const created = await fetchWithAuth(`/disputes/${selected.id}/communications`, {
        method:'POST',
        body:JSON.stringify({
          channel,
          recipient:recipient || null,
          body_override:bodyOverride?.trim() || null,
        }),
      })
      setCommunication(created)
      setCommunicationBody(created.body_snapshot)
      return null
    })
  }

  const communicationEvent = (action:string) => {
    if (!selected || !communication) return Promise.resolve()
    return act(`Evento comunicazione registrato: ${action}.`, () =>
      fetchWithAuth(`/disputes/${selected.id}/communications/${communication.id}/events`, {
        method:'POST',body:JSON.stringify({action}),
      }))
  }

  const copyMessage = async () => {
    if (!communication) return
    await navigator.clipboard.writeText(communication.body_snapshot)
    await communicationEvent('copied')
  }

  const openCommunication = async () => {
    if (!communication) return
    if (communication.channel === 'whatsapp') {
      const number = (communication.recipient || '').replace(/[^\d]/g, '')
      if (!number) { setError('Numero WhatsApp mancante o non valido.'); return }
      window.open(`https://wa.me/${number}?text=${encodeURIComponent(communication.body_snapshot)}`, '_blank', 'noopener,noreferrer')
    } else if (communication.channel === 'email') {
      window.open(`mailto:${encodeURIComponent(communication.recipient || '')}?subject=${encodeURIComponent(communication.subject || '')}&body=${encodeURIComponent(communication.body_snapshot)}`, '_blank', 'noopener,noreferrer')
    }
    await communicationEvent('opened')
  }

  const saveRecognition = () => {
    if (!selected) return
    void act('Importi riconosciuti registrati.', () => fetchWithAuth(`/disputes/${selected.id}/recognition`, {
      method:'POST',
      body:JSON.stringify({
        expected_version:selected.version,
        allocations:selected.anomalies.map(item => ({
          case_anomaly_id:item.id,
          amount:recognized[item.id] ?? item.recognized_amount,
        })),
      }),
    }))
  }

  const saveResponse = () => {
    if (!selected || !responseText.trim()) return
    void act('Risposta del fornitore registrata.', async () => {
      const result = await fetchWithAuth(`/disputes/${selected.id}/responses`, {
        method:'POST',
        body:JSON.stringify({
          channel:'email', response_text:responseText,
          received_at:new Date().toISOString(),
          communication_id:communication?.id || null,
        }),
      })
      setResponseText('')
      return result
    })
  }

  const saveCreditNote = () => {
    if (!selected) return
    const allocations = selected.anomalies
      .map(item => ({case_anomaly_id:item.id,amount:Number(creditAmounts[item.id] || 0)}))
      .filter(item => item.amount > 0)
    const total = allocations.reduce((sum,item) => sum + item.amount,0)
    void act('Nota di credito registrata e allocata.', async () => {
      const result = await fetchWithAuth(`/disputes/${selected.id}/credit-notes`, {
        method:'POST',
        body:JSON.stringify({
          document_number:creditNumber,
          issue_date:creditDate,
          total_amount:total,
          source:'manual',
          allocations,
        }),
      })
      setCreditNumber('');setCreditDate('');setCreditAmounts({})
      return result
    })
  }

  const uploadAttachment = async (file: File) => {
    if (!selected) return
    const form = new FormData();form.append('file',file)
    setBusy(true);setError('')
    try {
      const token = localStorage.getItem('token')
      const response = await fetch(`${API_BASE}/disputes/${selected.id}/attachments`, {
        method:'POST',headers:token?{Authorization:`Bearer ${token}`}:{},body:form,
      })
      if (!response.ok) throw new Error((await response.json()).detail || 'Upload non riuscito')
      setNotice('Allegato salvato e verificato.')
      await load()
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : 'Upload non riuscito')
    } finally { setBusy(false) }
  }

  const downloadPdf = async () => {
    if (!selected) return
    const response = await fetch(`${API_BASE}/disputes/${selected.id}/pdf`, {headers:getHeaders()})
    if (!response.ok) { setError('PDF non disponibile'); return }
    const url = URL.createObjectURL(await response.blob())
    const anchor=document.createElement('a');anchor.href=url;anchor.download=`${selected.case_code}.pdf`;anchor.click()
    URL.revokeObjectURL(url)
  }

  const selectedClaim = useMemo(() =>
    candidates.filter(item => candidateIds.includes(`${item.source}:${item.id}`))
      .reduce((sum,item) => sum + Number(claimAmounts[`${item.source}:${item.id}`] ?? item.amount ?? 0),0), [candidates,candidateIds,claimAmounts])

  return <div style={{display:'flex',flexDirection:'column',gap:18}} data-testid="dispute-management">
    <div style={{display:'flex',justifyContent:'space-between',alignItems:'flex-start',gap:12,flexWrap:'wrap'}}>
      <div><h2 style={{margin:0}}>Contestazioni e recuperi</h2><p style={{color:'var(--text-secondary)',marginTop:6}}>Dall’anomalia alla nota di credito, con conferme manuali e audit completo.</p></div>
      <div style={{display:'flex',gap:8}}>
        <button className="btn" onClick={()=>void load()} disabled={busy}><RefreshCw size={15}/> Aggiorna</button>
        <button className="btn btn-primary" onClick={()=>void loadCandidates()} disabled={busy}><Plus size={15}/> Nuova contestazione</button>
      </div>
    </div>
    {busy&&<div style={{display:'flex',gap:8,color:'var(--text-secondary)'}}><Loader2 size={16} className="spin"/> Aggiornamento…</div>}
    {error&&<div style={{...panel,borderColor:'rgba(239,68,68,.4)',color:'#f87171'}}><AlertTriangle size={16}/> {error}</div>}
    {notice&&<div style={{...panel,borderColor:'rgba(16,185,129,.35)',color:'#34d399'}}><CheckCircle2 size={16}/> {notice}</div>}
    {dashboard&&<div style={{display:'grid',gridTemplateColumns:'repeat(auto-fit,minmax(155px,1fr))',gap:10}}>
      {[
        ['Anomalie',dashboard.total_anomalies],['Contestato',money(dashboard.total_contested)],
        ['Riconosciuto',money(dashboard.total_recognized)],['Recuperato',money(dashboard.total_recovered)],
        ['Da recuperare',money(dashboard.total_outstanding)],['Pratiche aperte',dashboard.open_cases],
        ['Scadute',dashboard.overdue_cases],['NC mancanti',dashboard.missing_credit_notes],
      ].map(([name,value])=><div key={String(name)} style={panel}><small style={{color:'var(--text-secondary)'}}>{name}</small><strong style={{display:'block',fontSize:22,marginTop:7}}>{value}</strong></div>)}
    </div>}
    {showCreate&&<div style={{...panel,borderColor:'rgba(59,130,246,.45)'}}>
      <h3>Nuova contestazione</h3>
      <div style={{display:'flex',gap:8,flexWrap:'wrap',marginBottom:12}}>
        <input placeholder="Titolo pratica" value={title} onChange={event=>setTitle(event.target.value)} style={{flex:'1 1 260px'}}/>
        <input type="date" value={dueDate} onChange={event=>setDueDate(event.target.value)}/>
      </div>
      <div style={{maxHeight:300,overflow:'auto',display:'grid',gap:7}}>
        {candidates.length===0&&<p style={{color:'var(--text-secondary)'}}>Nessuna anomalia disponibile.</p>}
        {candidates.map(item=>{
          const key=`${item.source}:${item.id}`;const checked=candidateIds.includes(key)
          return <label key={key} style={{padding:10,border:'1px solid var(--border-glass)',borderRadius:9,display:'flex',gap:9,cursor:'pointer',background:checked?'rgba(59,130,246,.12)':'',alignItems:'center'}}>
            <input type="checkbox" checked={checked} onChange={()=>toggleCandidate(item)}/>
            <span style={{flex:1}}><strong>{item.description||item.reason}</strong><small style={{display:'block',color:'var(--text-secondary)'}}>{item.source} · sede {item.location_id} · fornitore {item.supplier_id}</small></span>
            <input aria-label={`Importo ${item.description||item.reason}`} type="number" min=".01" step=".01" value={claimAmounts[key]??item.amount??''} onClick={event=>event.stopPropagation()} onChange={event=>setClaimAmounts(current=>({...current,[key]:event.target.value}))} style={{width:115}}/>
          </label>
        })}
      </div>
      <div style={{display:'flex',justifyContent:'space-between',alignItems:'center',marginTop:12}}>
        <strong>Totale selezionato: {money(selectedClaim)}</strong>
        <div style={{display:'flex',gap:8}}><button className="btn" onClick={()=>setShowCreate(false)}>Chiudi</button><button className="btn btn-primary" onClick={()=>void createCase()} disabled={!candidateIds.length}>Crea bozza</button></div>
      </div>
    </div>}
    <div style={{display:'grid',gridTemplateColumns:'minmax(280px,.75fr) minmax(0,1.6fr)',gap:16,alignItems:'start'}}>
      <div style={{...panel,display:'grid',gap:8}}>
        <h3 style={{marginTop:0}}>Pratiche</h3>
        {cases.length===0&&<p style={{color:'var(--text-secondary)'}}>Nessuna contestazione. Crea la prima dalle anomalie validate.</p>}
        {cases.map(item=><button key={item.id} onClick={()=>{setSelected(item);setCommunication(null);setCommunicationBody('')}} style={{textAlign:'left',padding:12,borderRadius:10,border:selected?.id===item.id?'1px solid #3b82f6':'1px solid var(--border-glass)',background:'rgba(255,255,255,.025)',color:'white'}}>
          <strong>{item.case_code}</strong><div style={{fontSize:12,margin:'5px 0'}}>{item.title}</div>
          <small style={{color:'var(--text-secondary)'}}>{item.supplier_name||`Fornitore ${item.supplier_id}`} · {money(item.unrecovered_amount)}</small><div style={{marginTop:7}}><Badge status={item.status}/></div>
        </button>)}
      </div>
      {!selected?<div style={panel}><WalletCards size={32} color="#60a5fa"/><h3>Seleziona una pratica</h3><p style={{color:'var(--text-secondary)'}}>Qui gestirai comunicazioni, risposte e recuperi senza modificare le fatture originali.</p></div>:
      <div style={{display:'grid',gap:14}}>
        <div style={panel}>
          <div style={{display:'flex',justifyContent:'space-between',gap:10,flexWrap:'wrap'}}><div><small style={{color:'#60a5fa'}}>{selected.case_code} · v{selected.version}</small><h2 style={{margin:'5px 0'}}>{selected.title}</h2><span>{selected.location_name} · {selected.supplier_name}</span></div><Badge status={selected.status}/></div>
          <div style={{display:'grid',gridTemplateColumns:'repeat(4,1fr)',gap:8,marginTop:15}}>
            {[['Richiesto',selected.requested_amount],['Riconosciuto',selected.recognized_amount],['Recuperato',selected.recovered_amount],['Residuo',selected.unrecovered_amount]].map(([name,value])=><div key={name}><small style={{color:'var(--text-secondary)'}}>{name}</small><strong style={{display:'block'}}>{money(value)}</strong></div>)}
          </div>
          <div style={{display:'flex',gap:8,flexWrap:'wrap',marginTop:16}}>
            {selected.status==='draft'&&<button className="btn btn-primary" onClick={()=>transition('ready_to_send')}><CheckCircle2 size={14}/> Rendi pronta</button>}
            <button className="btn" onClick={()=>void downloadPdf()}><Download size={14}/> PDF</button>
            {!['closed','cancelled'].includes(selected.status)&&<button className="btn" style={{color:'#f87171'}} onClick={()=>{const reason=prompt('Motivo obbligatorio (minimo 8 caratteri)');if(reason)transition('cancelled',reason)}}>Annulla</button>}
            {['recovered','rejected','partially_recovered','credit_note_expected'].includes(selected.status)&&<button className="btn" onClick={()=>{const reason=prompt('Motivo di chiusura (minimo 8 caratteri)');if(reason)transition('closed',reason)}}>Chiudi pratica</button>}
          </div>
        </div>
        <div style={panel}><h3>Anomalie contestate</h3><div style={{display:'grid',gap:8}}>{selected.anomalies.map(item=><div key={item.id} style={{borderTop:'1px solid var(--border-glass)',paddingTop:9}}><strong>{item.reason_snapshot}</strong><div style={{display:'flex',gap:15,fontSize:12,color:'var(--text-secondary)'}}><span>Richiesto {money(item.claimed_amount)}</span><span>Riconosciuto {money(item.recognized_amount)}</span><span>Recuperato {money(item.recovered_amount)}</span></div></div>)}</div></div>
        {!['closed','cancelled'].includes(selected.status)&&<div style={panel}>
          <h3>Comunicazione al fornitore</h3><div style={{display:'flex',gap:8,flexWrap:'wrap'}}>
            <select value={channel} onChange={event=>setChannel(event.target.value as typeof channel)}><option value="email">Email</option><option value="whatsapp">WhatsApp</option><option value="copy">Solo copia</option></select>
            <input placeholder={channel==='email'?'Email fornitore':'Numero con prefisso internazionale'} value={recipient} onChange={event=>setRecipient(event.target.value)} style={{flex:'1 1 260px'}}/>
            <button className="btn" onClick={()=>prepareCommunication()}><FilePlus2 size={14}/> Prepara</button>
          </div>
          {communication&&<div style={{marginTop:12,display:'grid',gap:8}}><textarea rows={9} value={communicationBody} onChange={event=>setCommunicationBody(event.target.value)}/>{communicationBody!==communication.body_snapshot&&<button className="btn" onClick={()=>prepareCommunication(communicationBody)} disabled={!communicationBody.trim()}><FilePlus2 size={14}/> Salva nuova versione del messaggio</button>}<div style={{display:'flex',gap:8,flexWrap:'wrap'}}><button className="btn" onClick={()=>void copyMessage()} disabled={communicationBody!==communication.body_snapshot}><Clipboard size={14}/> Copia</button>{channel!=='copy'&&<button className="btn" onClick={()=>void openCommunication()} disabled={communicationBody!==communication.body_snapshot}>{channel==='email'?<Mail size={14}/>:<MessageCircle size={14}/>} Apri</button>}<button className="btn btn-primary" onClick={()=>void communicationEvent('confirmed')} disabled={communicationBody!==communication.body_snapshot}><Send size={14}/> Conferma invio manuale</button></div><small style={{color:'var(--text-secondary)'}}>Stato: {communication.status}. L’apertura non costituisce prova di consegna. Le modifiche creano una nuova versione immutabile.</small></div>}
        </div>}
        {['sent','supplier_replied','credit_note_expected','partially_recovered'].includes(selected.status)&&<div style={panel}><h3>Risposta e importo riconosciuto</h3><textarea rows={3} placeholder="Risposta ricevuta dal fornitore" value={responseText} onChange={event=>setResponseText(event.target.value)}/><button className="btn" onClick={saveResponse} style={{marginTop:8}}>Registra risposta</button><div style={{marginTop:14,display:'grid',gap:7}}>{selected.anomalies.map(item=><label key={item.id} style={{display:'flex',justifyContent:'space-between',gap:8}}><span>{item.reason_snapshot} (max {money(item.claimed_amount)})</span><input type="number" min={item.recovered_amount} max={item.claimed_amount} step=".01" value={recognized[item.id]??item.recognized_amount} onChange={event=>setRecognized(current=>({...current,[item.id]:event.target.value}))}/></label>)}</div><button className="btn" onClick={saveRecognition} style={{marginTop:8}}>Salva riconoscimento</button></div>}
        {['sent','supplier_replied','credit_note_expected','partially_recovered'].includes(selected.status)&&<div style={panel}><h3>Nota di credito</h3><div style={{display:'flex',gap:8,flexWrap:'wrap'}}><input placeholder="Numero documento" value={creditNumber} onChange={event=>setCreditNumber(event.target.value)}/><input type="date" value={creditDate} onChange={event=>setCreditDate(event.target.value)}/></div><div style={{display:'grid',gap:7,marginTop:10}}>{selected.anomalies.map(item=><label key={item.id} style={{display:'flex',justifyContent:'space-between',gap:8}}><span>{item.reason_snapshot} · residuo {money(Number(item.claimed_amount)-Number(item.recovered_amount))}</span><input type="number" min="0" step=".01" value={creditAmounts[item.id]||''} onChange={event=>setCreditAmounts(current=>({...current,[item.id]:event.target.value}))}/></label>)}</div><button className="btn btn-primary" onClick={saveCreditNote} disabled={!creditNumber||!creditDate} style={{marginTop:10}}><WalletCards size={14}/> Registra e alloca</button></div>}
        <div style={panel}><h3>Evidenze</h3><label className="btn" style={{display:'inline-flex',cursor:'pointer'}}><Paperclip size={14}/> Aggiungi allegato<input type="file" hidden accept=".pdf,.png,.jpg,.jpeg,.txt,.csv" onChange={event=>{const file=event.target.files?.[0];if(file)void uploadAttachment(file)}}/></label><div style={{marginTop:9}}>{selected.attachments.map(item=><div key={item.id}>{item.filename} · {(item.size_bytes/1024).toFixed(1)} KB</div>)}</div></div>
        <div style={panel}><h3>Audit</h3>{selected.audit_events.slice().reverse().slice(0,12).map(item=><div key={item.id} style={{fontSize:12,borderTop:'1px solid var(--border-glass)',padding:'7px 0'}}>{new Date(item.created_at).toLocaleString('it-IT')} · {item.action}</div>)}</div>
      </div>}
    </div>
  </div>
}
