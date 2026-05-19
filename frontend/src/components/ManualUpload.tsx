import { useState, useEffect } from 'react';
import { FileUp, FileArchive, CheckCircle2, AlertCircle, Loader2, History, Info, X, ShieldAlert, Building2, MapPin } from 'lucide-react';
import { API_BASE, fetchWithAuth } from '../api';

interface BatchSummary {
  totale_file: number;
  elaborati: number;
  gia_presenti: number;
  errori_formato: number;
  anomalie_generate: number;
}

interface BatchHistoryItem {
  id: string;
  created_at: string;
  file_totali: number;
  anomalie_generate: number;
  stato: string;
  note: string | null;
}

interface UnregisteredSupplier {
  partita_iva: string;
  nome_azienda: string;
}

interface UnregisteredLocation {
  partita_iva: string;
  nome_struttura: string;
}

export default function ManualUpload() {
  const [files, setFiles] = useState<File[]>([]);
  const [note, setNote] = useState('');
  const [uploading, setUploading] = useState(false);
  const [reprocessing, setReprocessing] = useState(false);
  const [summary, setSummary] = useState<BatchSummary | null>(null);
  const [history, setHistory] = useState<BatchHistoryItem[]>([]);
  const [error, setError] = useState<string | null>(null);

  // Unregistered entities modal state
  const [showModal, setShowModal] = useState(false);
  const [unregisteredFornitori, setUnregisteredFornitori] = useState<UnregisteredSupplier[]>([]);
  const [unregisteredLocations, setUnregisteredLocations] = useState<UnregisteredLocation[]>([]);
  
  // Custom edits in modal
  const [editSupplierNames, setEditSupplierNames] = useState<Record<string, string>>({});
  const [editLocationNames, setEditLocationNames] = useState<Record<string, string>>({});
  const [locationTypes, setLocationTypes] = useState<Record<string, string>>({});

  const [regSuccessMessage, setRegSuccessMessage] = useState<string | null>(null);
  const [registeringKey, setRegisteringKey] = useState<string | null>(null);

  useEffect(() => {
    loadHistory();
  }, []);

  async function loadHistory() {
    try {
      const data = await fetchWithAuth('/ingestion/uploads');
      if (Array.isArray(data)) {
        setHistory(data);
      } else {
        setHistory([]);
      }
    } catch (err) {
      console.error("Errore caricamento storico", err);
      setHistory([]);
    }
  }

  const handleFileChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    if (e.target.files) {
      setFiles(Array.from(e.target.files));
      setSummary(null);
      setError(null);
    }
  };

  const handleUpload = async () => {
    if (files.length === 0) return;

    setUploading(true);
    setError(null);
    setSummary(null);
    setRegSuccessMessage(null);

    const formData = new FormData();
    files.forEach(f => formData.append('files', f));
    formData.append('note', note);

    try {
      const token = localStorage.getItem('token');
      const res = await fetch(`${API_BASE}/ingestion/upload`, {
        method: 'POST',
        headers: {
          'Authorization': `Bearer ${token}`,
          'bypass-tunnel-reminder': 'true'
        },
        body: formData
      });

      if (!res.ok) throw new Error("Errore durante l'upload");

      const result = await res.json();
      setSummary(result.riepilogo);
      setFiles([]);
      setNote('');
      loadHistory();

      // Trigger modal if unregistered entities are returned
      const newForn = result.non_whitelistati_fornitori || [];
      const newLoc = result.non_registrate_location || [];

      if (newForn.length > 0 || newLoc.length > 0) {
        setUnregisteredFornitori(newForn);
        setUnregisteredLocations(newLoc);
        
        // Initialize names mapping
        const initialFornNames: Record<string, string> = {};
        newForn.forEach((f: UnregisteredSupplier) => {
          initialFornNames[f.partita_iva] = f.nome_azienda;
        });
        setEditSupplierNames(initialFornNames);

        const initialLocNames: Record<string, string> = {};
        const initialLocTypes: Record<string, string> = {};
        newLoc.forEach((l: UnregisteredLocation) => {
          initialLocNames[l.partita_iva] = l.nome_struttura;
          initialLocTypes[l.partita_iva] = 'balneare';
        });
        setEditLocationNames(initialLocNames);
        setLocationTypes(initialLocTypes);

        setShowModal(true);
      }
    } catch (err) {
      setError("Si è verificato un errore durante l'elaborazione dei file.");
    } finally {
      setUploading(false);
    }
  };

  const handleReprocessParked = async () => {
    setReprocessing(true);
    setError(null);
    setSummary(null);
    setRegSuccessMessage(null);

    try {
      const token = localStorage.getItem('token');
      const res = await fetch(`${API_BASE}/ingestion/reprocess-parked`, {
        method: 'POST',
        headers: {
          'Authorization': `Bearer ${token}`,
          'bypass-tunnel-reminder': 'true'
        }
      });

      if (!res.ok) throw new Error("Errore durante la rielaborazione");

      const result = await res.json();
      setSummary(result.riepilogo);
      loadHistory();

      // Trigger modal if unregistered entities are returned
      const newForn = result.non_whitelistati_fornitori || [];
      const newLoc = result.non_registrate_location || [];

      if (newForn.length > 0 || newLoc.length > 0) {
        setUnregisteredFornitori(newForn);
        setUnregisteredLocations(newLoc);
        
        // Initialize names mapping
        const initialFornNames: Record<string, string> = {};
        newForn.forEach((f: UnregisteredSupplier) => {
          initialFornNames[f.partita_iva] = f.nome_azienda;
        });
        setEditSupplierNames(initialFornNames);

        const initialLocNames: Record<string, string> = {};
        const initialLocTypes: Record<string, string> = {};
        newLoc.forEach((l: UnregisteredLocation) => {
          initialLocNames[l.partita_iva] = l.nome_struttura;
          initialLocTypes[l.partita_iva] = 'balneare';
        });
        setEditLocationNames(initialLocNames);
        setLocationTypes(initialLocTypes);

        setShowModal(true);
      } else {
        alert("Ottimo! Non è stata rilevata alcuna fattura sospesa o con soggetti da censire!");
      }
    } catch (err) {
      setError("Si è verificato un errore durante la scansione delle fatture sospese.");
    } finally {
      setReprocessing(false);
    }
  };

  const handleRegisterSupplier = async (piva: string) => {
    const nome = editSupplierNames[piva] || 'Fornitore Sconosciuto';
    setRegisteringKey(piva);
    setRegSuccessMessage(null);

    try {
      const token = localStorage.getItem('token');
      const res = await fetch(`${API_BASE}/fornitori/`, {
        method: 'POST',
        headers: {
          'Authorization': `Bearer ${token}`,
          'Content-Type': 'application/json'
        },
        body: JSON.stringify({
          nome_azienda: nome,
          partita_iva: piva,
          attivo_whitelist: true
        })
      });

      if (!res.ok) {
        const err = await res.json();
        throw new Error(err.detail || 'Impossibile registrare il fornitore.');
      }

      setRegSuccessMessage(`Fornitore "${nome}" registrato e abilitato in Whitelist!`);
      // Remove from list
      setUnregisteredFornitori(prev => prev.filter(f => f.partita_iva !== piva));
    } catch (err: any) {
      alert(err.message || 'Errore durante la registrazione.');
    } finally {
      setRegisteringKey(null);
    }
  };

  const handleRegisterLocation = async (piva: string) => {
    const nome = editLocationNames[piva] || `Sede P.IVA ${piva}`;
    const tipo = locationTypes[piva] || 'balneare';
    setRegisteringKey(piva);
    setRegSuccessMessage(null);

    try {
      const token = localStorage.getItem('token');
      const res = await fetch(`${API_BASE}/location/`, {
        method: 'POST',
        headers: {
          'Authorization': `Bearer ${token}`,
          'Content-Type': 'application/json'
        },
        body: JSON.stringify({
          nome_struttura: nome,
          piva_riferimento: piva,
          tipologia: tipo
        })
      });

      if (!res.ok) {
        const err = await res.json();
        throw new Error(err.detail || 'Impossibile registrare la sede.');
      }

      setRegSuccessMessage(`Sede "${nome}" registrata correttamente!`);
      // Remove from list
      setUnregisteredLocations(prev => prev.filter(l => l.partita_iva !== piva));
    } catch (err: any) {
      alert(err.message || 'Errore durante la registrazione.');
    } finally {
      setRegisteringKey(null);
    }
  };

  return (
    <div style={{ display: 'grid', gridTemplateColumns: '1fr 350px', gap: '24px', position: 'relative' }}>
      
      {/* Colonna Sinistra: Upload */}
      <div className="glass-panel" style={{ padding: '32px' }}>
        <div style={{ marginBottom: '32px' }}>
          <h2 style={{ marginBottom: '8px' }}>Carica Fatture</h2>
          <p style={{ color: 'var(--text-secondary)' }}>Carica file XML o archivi ZIP scaricati da Aruba o AdE.</p>
        </div>

        <div style={{ display: 'flex', flexDirection: 'column', gap: '24px' }}>
          
          <div style={{ 
            border: '2px dashed var(--border-glass)', 
            padding: '48px', 
            borderRadius: 'var(--border-radius-md)', 
            textAlign: 'center',
            background: files.length > 0 ? 'rgba(16, 185, 129, 0.05)' : 'transparent',
            transition: 'all 0.3s ease'
          }}>
            <input 
              type="file" 
              id="xmlUpload" 
              multiple 
              accept=".xml,.zip" 
              style={{ display: 'none' }} 
              onChange={handleFileChange}
            />
            <label htmlFor="xmlUpload" style={{ cursor: 'pointer' }}>
              <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', gap: '16px' }}>
                {files.some(f => f.name.endsWith('.zip')) ? <FileArchive size={64} color="var(--accent)" /> : <FileUp size={64} color="var(--text-secondary)" />}
                <div>
                  <div style={{ fontSize: '1.1rem', fontWeight: 600 }}>
                    {files.length > 0 ? `${files.length} file selezionati` : 'Trascina qui i tuoi file XML o ZIP'}
                  </div>
                  <p style={{ fontSize: '0.85rem', color: 'var(--text-secondary)', marginTop: '4px' }}>
                    {files.length > 0 ? files.map(f => f.name).join(', ') : 'Supporta XML singoli o archivi ZIP cumulativi'}
                  </p>
                </div>
              </div>
            </label>
          </div>

          <div>
            <label style={{ display: 'block', marginBottom: '8px', fontSize: '0.9rem', fontWeight: 600 }}>Nota opzionale</label>
            <textarea 
              value={note}
              onChange={(e) => setNote(e.target.value)}
              placeholder="es. Fatture settimana 14-20 Aprile..."
              style={{ 
                width: '100%', padding: '12px', background: 'rgba(255,255,255,0.05)', 
                border: '1px solid var(--border-glass)', borderRadius: 'var(--border-radius-md)', 
                color: 'white', minHeight: '80px', outline: 'none' 
              }}
            />
          </div>

          {error && (
            <div style={{ padding: '16px', background: 'var(--status-red-bg)', color: 'var(--status-red)', borderRadius: 'var(--border-radius-md)', display: 'flex', gap: '12px' }}>
              <AlertCircle size={20} />
              <span>{error}</span>
            </div>
          )}

          {summary && (
            <div style={{ padding: '20px', background: 'rgba(255,255,255,0.03)', border: '1px solid var(--border-glass)', borderRadius: 'var(--border-radius-md)' }}>
              <h4 style={{ marginBottom: '16px', display: 'flex', alignItems: 'center', gap: '8px' }}>
                <CheckCircle2 size={18} color="var(--status-green)" /> Elaborazione Completata
              </h4>
              <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: '12px', textAlign: 'center' }}>
                <div>
                  <div style={{ fontSize: '1.2rem', fontWeight: 700 }}>{summary.elaborati}</div>
                  <div style={{ fontSize: '0.75rem', color: 'var(--text-secondary)' }}>Processati</div>
                </div>
                <div>
                  <div style={{ fontSize: '1.2rem', fontWeight: 700, color: 'var(--status-yellow)' }}>{summary.gia_presenti}</div>
                  <div style={{ fontSize: '0.75rem', color: 'var(--text-secondary)' }}>Duplicati</div>
                </div>
                <div>
                  <div style={{ fontSize: '1.2rem', fontWeight: 700, color: 'var(--status-red)' }}>{summary.anomalie_generate}</div>
                  <div style={{ fontSize: '0.75rem', color: 'var(--text-secondary)' }}>Anomalie</div>
                </div>
              </div>
            </div>
          )}

          <button 
            className="btn btn-primary" 
            disabled={uploading || reprocessing || files.length === 0}
            onClick={handleUpload}
            style={{ padding: '16px', fontSize: '1rem', display: 'flex', justifyContent: 'center', gap: '12px' }}
          >
            {uploading ? <Loader2 className="spinner" /> : <FileUp size={20} />}
            {uploading ? 'Elaborazione in corso...' : 'Inizia Caricamento'}
          </button>

        </div>
      </div>

      {/* Colonna Destra: Storico & Scansione manuale */}
      <div className="glass-panel" style={{ padding: '24px' }}>
        
        {/* Scansione manuale delle sospese */}
        <div style={{ marginBottom: '24px', borderBottom: '1px solid var(--border-glass)', paddingBottom: '20px' }}>
          <h3 style={{ marginBottom: '12px', display: 'flex', alignItems: 'center', gap: '10px' }}>
            <ShieldAlert size={20} color="#f59e0b" /> Fatture in Sospeso
          </h3>
          <p style={{ fontSize: '0.75rem', color: 'var(--text-secondary)', marginBottom: '16px', lineHeight: '1.4' }}>
            Hai caricato file in passato prima di censire i fornitori? Rielaborali subito per sbloccarli.
          </p>
          <button 
            className="btn" 
            disabled={uploading || reprocessing}
            onClick={handleReprocessParked}
            style={{ 
              width: '100%', gap: '8px', 
              background: 'rgba(245, 158, 11, 0.1)', border: '1px solid rgba(245, 158, 11, 0.25)',
              color: '#f59e0b', display: 'flex', justifyContent: 'center', alignItems: 'center',
              fontWeight: 600, fontSize: '0.85rem', padding: '10px 0', cursor: 'pointer', transition: 'all 0.2s'
            }}
          >
            {reprocessing ? <Loader2 className="spinner" size={14} /> : <ShieldAlert size={14} />}
            {reprocessing ? 'Analisi in corso...' : 'Scansiona Fatture Sospese'}
          </button>
        </div>

        <h3 style={{ marginBottom: '20px', display: 'flex', alignItems: 'center', gap: '10px' }}>
          <History size={20} /> Storico Upload
        </h3>
        
        <div style={{ display: 'flex', flexDirection: 'column', gap: '12px' }}>
          {history.length === 0 && <p style={{ color: 'var(--text-secondary)', fontSize: '0.9rem' }}>Nessun upload recente.</p>}
          {history.map(item => (
            <div key={item.id} style={{ 
              padding: '12px', borderBottom: '1px solid var(--border-glass)', 
              display: 'flex', flexDirection: 'column', gap: '4px' 
            }}>
              <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: '0.85rem' }}>
                <span style={{ fontWeight: 600 }}>{new Date(item.created_at).toLocaleDateString()}</span>
                <span style={{ color: item.anomalie_generate > 0 ? 'var(--status-red)' : 'var(--status-green)' }}>
                  {item.anomalie_generate} anomalie
                </span>
              </div>
              <div style={{ fontSize: '0.75rem', color: 'var(--text-secondary)' }}>
                {item.file_totali} file • {item.note || 'Nessuna nota'}
              </div>
            </div>
          ))}
        </div>

        <div style={{ marginTop: '24px', padding: '12px', background: 'rgba(59, 130, 246, 0.1)', borderRadius: '8px', display: 'flex', gap: '10px' }}>
          <Info size={16} color="var(--accent)" style={{ flexShrink: 0 }} />
          <p style={{ fontSize: '0.75rem', lineHeight: '1.4' }}>
            I duplicati vengono ignorati automaticamente grazie al controllo dell'hash univoco.
          </p>
        </div>
      </div>

      {/* POPUP WIZARD MODAL FOR UNREGISTERED PIECE OF INFOS */}
      {showModal && (
        <div style={{
          position: 'fixed', top: 0, left: 0, width: '100vw', height: '100vh',
          background: 'rgba(5, 5, 10, 0.85)', backdropFilter: 'blur(8px)',
          display: 'flex', alignItems: 'center', justifyContent: 'center', zIndex: 1000,
          padding: '20px', boxSizing: 'border-box'
        }}>
          <div className="glass-panel" style={{
            width: '100%', maxWidth: '650px', padding: '28px', display: 'flex', flexDirection: 'column', gap: '20px',
            boxShadow: '0 20px 40px rgba(0,0,0,0.5)', border: '1px solid rgba(255,255,255,0.08)', position: 'relative'
          }}>
            
            {/* Header */}
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start' }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: '12px' }}>
                <ShieldAlert size={26} color="#f59e0b" />
                <div>
                  <h3 style={{ margin: 0, fontSize: '1.2rem', fontWeight: 700 }}>Rilevate Nuove Intestazioni!</h3>
                  <p style={{ margin: 0, fontSize: '0.75rem', color: 'var(--text-secondary)', marginTop: '2px' }}>
                    Alcune fatture caricate appartengono a soggetti non registrati in anagrafica.
                  </p>
                </div>
              </div>
              <button onClick={() => setShowModal(false)} style={{ background: 'transparent', border: 'none', color: 'var(--text-secondary)', cursor: 'pointer', padding: '4px' }}>
                <X size={18} />
              </button>
            </div>

            {/* Success notification inside modal */}
            {regSuccessMessage && (
              <div style={{ padding: '10px 14px', borderRadius: '6px', background: 'rgba(16,185,129,0.15)', color: '#10b981', border: '1px solid rgba(16,185,129,0.2)', fontSize: '0.8rem', display: 'flex', alignItems: 'center', gap: '6px' }}>
                <CheckCircle2 size={14} />
                <span>{regSuccessMessage}</span>
              </div>
            )}

            {/* Content Lists */}
            <div style={{ display: 'flex', flexDirection: 'column', gap: '16px', maxHeight: '400px', overflowY: 'auto', paddingRight: '4px' }}>
              
              {unregisteredFornitori.length === 0 && unregisteredLocations.length === 0 && (
                <div style={{ textAlign: 'center', padding: '24px', color: '#10b981', display: 'flex', flexDirection: 'column', alignItems: 'center', gap: '8px' }}>
                  <CheckCircle2 size={36} />
                  <span style={{ fontSize: '0.9rem', fontWeight: 600 }}>Tutti i soggetti sono stati registrati con successo!</span>
                </div>
              )}

              {/* Unregistered Suppliers list */}
              {unregisteredFornitori.map(forn => (
                <div key={forn.partita_iva} style={{
                  padding: '16px', borderRadius: '10px', background: 'rgba(255,255,255,0.02)', border: '1px solid rgba(255,255,255,0.04)',
                  display: 'flex', flexDirection: 'column', gap: '12px'
                }}>
                  <div style={{ display: 'flex', alignItems: 'center', gap: '8px', fontSize: '0.85rem', fontWeight: 600, color: 'var(--primary-color)' }}>
                    <Building2 size={16} /> Nuova P.IVA Fornitore (Mittente)
                  </div>
                  
                  <div style={{ display: 'flex', gap: '12px', alignItems: 'center' }}>
                    <div style={{ flex: 1, display: 'flex', flexDirection: 'column', gap: '4px' }}>
                      <span style={{ fontSize: '0.7rem', color: 'var(--text-secondary)' }}>Ragione Sociale rilevata (puoi modificarla):</span>
                      <input
                        type="text"
                        value={editSupplierNames[forn.partita_iva] || ''}
                        onChange={e => setEditSupplierNames({ ...editSupplierNames, [forn.partita_iva]: e.target.value })}
                        style={{ padding: '8px 12px', background: 'rgba(0,0,0,0.3)', border: '1px solid var(--border-glass)', borderRadius: '6px', color: 'white', fontSize: '0.85rem', width: '100%', boxSizing: 'border-box' }}
                      />
                    </div>
                    <div style={{ width: '140px' }}>
                      <span style={{ fontSize: '0.7rem', color: 'var(--text-secondary)' }}>Partita IVA:</span>
                      <div style={{ fontSize: '0.85rem', fontWeight: 600, padding: '8px 0' }}>{forn.partita_iva}</div>
                    </div>
                  </div>

                  <div style={{ display: 'flex', justifyContent: 'flex-end' }}>
                    <button
                      onClick={() => handleRegisterSupplier(forn.partita_iva)}
                      disabled={registeringKey === forn.partita_iva}
                      className="btn btn-primary"
                      style={{ padding: '6px 16px', fontSize: '0.8rem', height: '32px' }}
                    >
                      {registeringKey === forn.partita_iva ? 'Registrazione...' : 'Abilita e Whitelista'}
                    </button>
                  </div>
                </div>
              ))}

              {/* Unregistered Locations list */}
              {unregisteredLocations.map(loc => (
                <div key={loc.partita_iva} style={{
                  padding: '16px', borderRadius: '10px', background: 'rgba(255,255,255,0.02)', border: '1px solid rgba(255,255,255,0.04)',
                  display: 'flex', flexDirection: 'column', gap: '12px'
                }}>
                  <div style={{ display: 'flex', alignItems: 'center', gap: '8px', fontSize: '0.85rem', fontWeight: 600, color: 'var(--accent-blue)' }}>
                    <MapPin size={16} /> Nuova P.IVA Gruppo (Sede Ricevente)
                  </div>
                  
                  <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '12px' }}>
                    <div style={{ display: 'flex', flexDirection: 'column', gap: '4px' }}>
                      <span style={{ fontSize: '0.7rem', color: 'var(--text-secondary)' }}>Assegna Nome Sede:</span>
                      <input
                        type="text"
                        value={editLocationNames[loc.partita_iva] || ''}
                        onChange={e => setEditLocationNames({ ...editLocationNames, [loc.partita_iva]: e.target.value })}
                        style={{ padding: '8px 12px', background: 'rgba(0,0,0,0.3)', border: '1px solid var(--border-glass)', borderRadius: '6px', color: 'white', fontSize: '0.85rem', width: '100%', boxSizing: 'border-box' }}
                      />
                    </div>
                    <div style={{ display: 'flex', flexDirection: 'column', gap: '4px' }}>
                      <span style={{ fontSize: '0.7rem', color: 'var(--text-secondary)' }}>Tipologia Struttura:</span>
                      <select
                        value={locationTypes[loc.partita_iva] || 'balneare'}
                        onChange={e => setLocationTypes({ ...locationTypes, [loc.partita_iva]: e.target.value })}
                        style={{ padding: '8px 12px', background: 'rgba(0,0,0,0.3)', border: '1px solid var(--border-glass)', borderRadius: '6px', color: 'white', fontSize: '0.85rem', width: '100%' }}
                      >
                        <option value="balneare" style={{ background: '#13131c' }}>Balneare / Eventi</option>
                        <option value="ristorante" style={{ background: '#13131c' }}>Ristorante / Food</option>
                        <option value="discoteca" style={{ background: '#13131c' }}>Discoteca / Club</option>
                        <option value="evento" style={{ background: '#13131c' }}>Evento / Altro</option>
                      </select>
                    </div>
                  </div>

                  <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                    <span style={{ fontSize: '0.75rem', color: 'var(--text-secondary)' }}>Partita IVA Ricevente: <strong>{loc.partita_iva}</strong></span>
                    <button
                      onClick={() => handleRegisterLocation(loc.partita_iva)}
                      disabled={registeringKey === loc.partita_iva}
                      className="btn btn-primary"
                      style={{ padding: '6px 16px', fontSize: '0.8rem', height: '32px', background: 'var(--accent-blue)', borderColor: 'var(--accent-blue)' }}
                    >
                      {registeringKey === loc.partita_iva ? 'Registrazione...' : 'Crea e Associa Sede'}
                    </button>
                  </div>
                </div>
              ))}

            </div>

            {/* Footer Actions */}
            <div style={{ display: 'flex', justifyContent: 'flex-end', borderTop: '1px solid rgba(255,255,255,0.05)', paddingTop: '16px', marginTop: '4px' }}>
              <button
                onClick={() => setShowModal(false)}
                className="btn"
                style={{ padding: '8px 20px', fontSize: '0.85rem', background: 'transparent', border: '1px solid var(--border-glass)' }}
              >
                Chiudi Procedura Wizard
              </button>
            </div>

          </div>
        </div>
      )}

    </div>
  );
}
