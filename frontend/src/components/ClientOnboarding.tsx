import { useEffect, useMemo, useState } from 'react'
import {
  CheckCircle2,
  Circle,
  Loader2,
  RefreshCw,
  Save,
  ShieldCheck,
  TriangleAlert,
} from 'lucide-react'
import { fetchWithAuth } from '../api'

type Location = {id:number;nome_struttura:string}
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
  location_id:number
  location_name:string
  users:number
  suppliers:number
  suppliers_with_contact:number
  active_products:number
  approved_aliases:number
  price_lists:number
  liquidstock_venue_mapped:boolean
  liquidstock_orders:number
  invoices:number
  reconciliations:number
  disputes:number
  settings_configured:boolean
  settings:Settings
}

const panel:React.CSSProperties={border:'1px solid var(--border-glass)',borderRadius:14,padding:17,background:'rgba(255,255,255,.025)'}

export default function ClientOnboarding() {
  const [profile,setProfile]=useState<{ruolo:string;location_id?:number}|null>(null)
  const [locations,setLocations]=useState<Location[]>([])
  const [locationId,setLocationId]=useState<number|''>('')
  const [readiness,setReadiness]=useState<Readiness|null>(null)
  const [settings,setSettings]=useState<Settings|null>(null)
  const [busy,setBusy]=useState(false)
  const [error,setError]=useState('')
  const [notice,setNotice]=useState('')

  const loadBase=async()=>{
    setBusy(true);setError('')
    try{
      const me=await fetchWithAuth('/auth/me');setProfile(me)
      const rows:Location[]=await fetchWithAuth('/location/')
      setLocations(rows)
      setLocationId(current=>current||me.location_id||rows[0]?.id||'')
    }catch(caught){setError(caught instanceof Error?caught.message:'Onboarding non disponibile')}
    finally{setBusy(false)}
  }
  useEffect(()=>{void loadBase()},[])

  const loadReadiness=async(id:number)=>{
    setBusy(true);setError('');setNotice('')
    try{
      const data=await fetchWithAuth(`/onboarding/locations/${id}/readiness`)
      setReadiness(data);setSettings(data.settings)
    }catch(caught){setError(caught instanceof Error?caught.message:'Verifica non riuscita')}
    finally{setBusy(false)}
  }
  useEffect(()=>{if(locationId)void loadReadiness(Number(locationId))},[locationId])

  const save=async()=>{
    if(!locationId||!settings)return
    setBusy(true);setError('');setNotice('')
    try{
      const saved=await fetchWithAuth(`/onboarding/locations/${locationId}/settings`,{
        method:'PUT',
        body:JSON.stringify({
          price_tolerance_absolute:settings.price_tolerance_absolute,
          price_tolerance_percent:settings.price_tolerance_percent,
          important_anomaly_threshold:settings.important_anomaly_threshold,
          stalled_reconciliation_days:settings.stalled_reconciliation_days,
          missing_credit_note_days:settings.missing_credit_note_days,
          notifications_enabled:settings.notifications_enabled,
        }),
      })
      setSettings(saved);setNotice('Configurazione salvata per la sede selezionata.')
      await loadReadiness(Number(locationId))
    }catch(caught){setError(caught instanceof Error?caught.message:'Salvataggio non riuscito')}
    finally{setBusy(false)}
  }

  const steps=useMemo(()=>readiness?[
    ['Utente operativo',readiness.users>0,`${readiness.users} utenti attivi`],
    ['Fornitori',readiness.suppliers>0,`${readiness.suppliers} fornitori · ${readiness.suppliers_with_contact} con contatto email`],
    ['Catalogo e alias',readiness.active_products>0&&readiness.approved_aliases>0,`${readiness.active_products} prodotti · ${readiness.approved_aliases} alias approvati`],
    ['Listini',readiness.price_lists>0,`${readiness.price_lists} righe listino`],
    ['Mapping LiquidStock',readiness.liquidstock_venue_mapped,readiness.liquidstock_venue_mapped?'Venue associata':'Associazione venue richiesta'],
    ['Impostazioni riconciliazione',readiness.settings_configured,readiness.settings_configured?'Configurate':'Salva le soglie esplicite'],
    ['Primo ordine ricevuto',readiness.liquidstock_orders>0,`${readiness.liquidstock_orders} sotto-ordini sincronizzati`],
    ['Prima fattura reale',readiness.invoices>0,`${readiness.invoices} fatture importate`],
    ['Prima riconciliazione',readiness.reconciliations>0,`${readiness.reconciliations} riconciliazioni`],
  ] as Array<[string,boolean,string]>:[],[readiness])
  const completed=steps.filter(([,done])=>done).length

  return <div style={{display:'grid',gap:18}} data-testid="client-onboarding">
    <div style={{display:'flex',justifyContent:'space-between',gap:12,flexWrap:'wrap'}}>
      <div><h2 style={{margin:0}}>Attivazione nuova sede</h2><p style={{color:'var(--text-secondary)'}}>Checklist reale, senza generare fatture o dati demo nel database operativo.</p></div>
      <button className="btn" onClick={()=>locationId&&void loadReadiness(Number(locationId))} disabled={busy}><RefreshCw size={15}/> Aggiorna</button>
    </div>
    {busy&&<div style={{color:'var(--text-secondary)'}}><Loader2 size={15}/> Verifica…</div>}
    {error&&<div style={{...panel,color:'#f87171',borderColor:'rgba(239,68,68,.35)'}}><TriangleAlert size={16}/> {error}</div>}
    {notice&&<div style={{...panel,color:'#34d399',borderColor:'rgba(16,185,129,.35)'}}><CheckCircle2 size={16}/> {notice}</div>}
    <div style={panel}><label style={{display:'grid',gap:6,maxWidth:420}}><span>Sede da attivare</span><select value={locationId} onChange={event=>setLocationId(Number(event.target.value))} disabled={profile?.ruolo!=='admin'}>{locations.map(item=><option key={item.id} value={item.id}>{item.nome_struttura}</option>)}</select></label></div>
    {readiness&&<>
      <div style={{...panel,borderColor:'rgba(59,130,246,.35)'}}>
        <div style={{display:'flex',justifyContent:'space-between'}}><div><small>Avanzamento</small><h3>{readiness.location_name}</h3></div><strong style={{fontSize:25,color:'#60a5fa'}}>{completed}/{steps.length}</strong></div>
        <div style={{height:8,borderRadius:9,background:'rgba(255,255,255,.08)',overflow:'hidden'}}><div style={{height:'100%',width:`${steps.length?completed/steps.length*100:0}%`,background:'#3b82f6'}}/></div>
      </div>
      <div style={{display:'grid',gridTemplateColumns:'repeat(auto-fit,minmax(230px,1fr))',gap:10}}>{steps.map(([name,done,detail])=><div key={name} style={panel}>{done?<CheckCircle2 size={18} color="#34d399"/>:<Circle size={18} color="#94a3b8"/>}<strong style={{display:'block',marginTop:8}}>{name}</strong><small style={{color:'var(--text-secondary)'}}>{detail}</small></div>)}</div>
      {settings&&<div style={panel}><h3>Soglie esplicite</h3><p style={{color:'var(--text-secondary)',fontSize:13}}>Usate soltanto dopo l’associazione manuale della fattura. Nessuna conversione di unità o matching fuzzy viene confermato automaticamente.</p><div style={{display:'grid',gridTemplateColumns:'repeat(auto-fit,minmax(190px,1fr))',gap:10}}>
        <label>Tolleranza assoluta €<input type="number" min="0" step=".01" value={settings.price_tolerance_absolute} onChange={event=>setSettings({...settings,price_tolerance_absolute:event.target.value})}/></label>
        <label>Tolleranza percentuale %<input type="number" min="0" step=".1" value={settings.price_tolerance_percent} onChange={event=>setSettings({...settings,price_tolerance_percent:event.target.value})}/></label>
        <label>Soglia anomalia importante €<input type="number" min=".01" step=".01" value={settings.important_anomaly_threshold} onChange={event=>setSettings({...settings,important_anomaly_threshold:event.target.value})}/></label>
        <label>Giorni riconciliazione ferma<input type="number" min="1" max="90" value={settings.stalled_reconciliation_days} onChange={event=>setSettings({...settings,stalled_reconciliation_days:Number(event.target.value)})}/></label>
        <label>Giorni nota di credito mancante<input type="number" min="1" max="180" value={settings.missing_credit_note_days} onChange={event=>setSettings({...settings,missing_credit_note_days:Number(event.target.value)})}/></label>
        <label style={{display:'flex',gap:8,alignItems:'center'}}><input type="checkbox" checked={settings.notifications_enabled} onChange={event=>setSettings({...settings,notifications_enabled:event.target.checked})}/> Avvisi operativi abilitati</label>
      </div>{profile?.ruolo==='admin'&&<button className="btn btn-primary" onClick={()=>void save()} style={{marginTop:14}}><Save size={14}/> Salva configurazione sede</button>}</div>}
      <div style={{...panel,borderColor:'rgba(16,185,129,.3)'}}><ShieldCheck size={20} color="#34d399"/><strong style={{display:'block',marginTop:7}}>Dati demo separati dai reali</strong><small style={{color:'var(--text-secondary)'}}>Questa pagina è diagnostica e configurativa: non crea fatture, prezzi, associazioni o ordini.</small></div>
    </>}
  </div>
}
