import { useState, useEffect } from 'react';
import { FileSpreadsheet, Download, CheckCircle2, AlertCircle } from 'lucide-react';
import { API_BASE, getHeaders } from '../api';

interface Fornitore {
  id: number;
  nome_azienda: string;
}

export default function PriceListManager() {
  const [fornitori, setFornitori] = useState<Fornitore[]>([]);
  const [selectedFornitore, setSelectedFornitore] = useState<string>('');
  const [file, setFile] = useState<File | null>(null);
  const [uploading, setUploading] = useState(false);
  const [uploadingMulti, setUploadingMulti] = useState(false);
  const [activeTab, setActiveTab] = useState<'standard' | 'multi'>('standard');
  const [message, setMessage] = useState<{ text: string, type: 'success' | 'error' } | null>(null);

  const loadFornitori = async (signal?: AbortSignal) => {
    try {
      const res = await fetch(`${API_BASE}/fornitori/`, {
        headers: getHeaders(),
        signal
      });
      const data = await res.json();
      if (Array.isArray(data)) {
        setFornitori(data);
      } else {
        console.error("Risposta API non valida", data);
        setFornitori([]);
      }
    } catch (err: any) {
      if (err.name !== 'AbortError') {
        console.error("Errore caricamento fornitori", err);
        setFornitori([]);
      }
    }
  };

  useEffect(() => {
    const controller = new AbortController();
    loadFornitori(controller.signal);
    return () => controller.abort();
  }, []);

  const handleUpload = async () => {
    if (!selectedFornitore || !file) {
      alert("Seleziona un fornitore e un file Excel");
      return;
    }

    setUploading(true);
    setMessage(null);

    const formData = new FormData();
    formData.append('file', file);

    try {
      const headers = getHeaders();
      delete headers['Content-Type'];

      const res = await fetch(`${API_BASE}/listino/import-excel/${selectedFornitore}`, {
        method: 'POST',
        headers,
        body: formData,
      });

      const result = await res.json();
      if (res.ok) {
        if (result.mode === 'validation_failed') {
          setMessage({ text: `Validazione fallita. Errori: ${result.errors?.length || 0}`, type: 'error' });
          return;
        }
        
        let msg = `Importato con successo! Aggiunti: ${result.inserted}.`;
        if (result.updated > 0) msg += ` Aggiornati: ${result.updated}.`;
        if (result.skipped_duplicates > 0) msg += ` Saltati (già presenti e invariati): ${result.skipped_duplicates}.`;
        
        setMessage({ text: msg, type: 'success' });
        setFile(null);
      } else {
        let errorMsg = result.detail || 'Impossibile caricare il listino';
        if (typeof errorMsg === 'object') {
           errorMsg = Array.isArray(errorMsg) ? errorMsg.map((e:any) => e.msg).join(', ') : JSON.stringify(errorMsg);
        }
        setMessage({ text: `Errore: ${errorMsg}`, type: 'error' });
      }
    } catch (err) {
      setMessage({ text: 'Errore di rete o server non raggiungibile', type: 'error' });
    } finally {
      setUploading(false);
    }
  };

  const handleUploadMulti = async () => {
    if (!file) {
      alert("Seleziona un file Excel comparativo");
      return;
    }

    setUploadingMulti(true);
    setMessage(null);

    const formData = new FormData();
    formData.append('file', file);

    try {
      const headers = getHeaders();
      delete headers['Content-Type'];

      const res = await fetch(`${API_BASE}/listino/import-multi-supplier`, {
        method: 'POST',
        headers,
        body: formData,
      });

      const result = await res.json();
      if (res.ok) {
        if (result.mode === 'validation_failed') {
          setMessage({ text: `Validazione fallita. Errori: ${result.errors?.length || 0}`, type: 'error' });
          return;
        }
        
        let msg = `Importato con successo! Righe elaborate: ${result.total_rows}. Rilevati fornitori: ${result.suppliers_detected?.join(', ')}. Aggiunti: ${result.inserted}.`;
        if (result.updated > 0) msg += ` Aggiornati: ${result.updated}.`;
        if (result.skipped_duplicates > 0) msg += ` Saltati: ${result.skipped_duplicates}.`;
        
        setMessage({ text: msg, type: 'success' });
        setFile(null);
        await loadFornitori(); // Refresh active list of suppliers to show new ones
      } else {
        let errorMsg = result.detail || 'Impossibile caricare il listino comparativo';
        if (typeof errorMsg === 'object') {
           errorMsg = Array.isArray(errorMsg) ? errorMsg.map((e:any) => e.msg).join(', ') : JSON.stringify(errorMsg);
        }
        setMessage({ text: `Errore: ${errorMsg}`, type: 'error' });
      }
    } catch (err) {
      setMessage({ text: 'Errore di rete o server non raggiungibile', type: 'error' });
    } finally {
      setUploadingMulti(false);
    }
  };

  const handleDownloadTemplate = async () => {
    try {
      const nomeFornitore = fornitori.find(f => f.id === Number(selectedFornitore))?.nome_azienda || 'Generico';
      const res = await fetch(`${API_BASE}/listino/template-excel?NomeFornitore=${encodeURIComponent(nomeFornitore)}`, {
        headers: getHeaders(),
      });
      if (!res.ok) {
        throw new Error('Errore durante il download del template');
      }
      const blob = await res.blob();
      const url = window.URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = `template_listino_${nomeFornitore.replace(/ /g, '_').toLowerCase()}.xlsx`;
      document.body.appendChild(a);
      a.click();
      a.remove();
      window.URL.revokeObjectURL(url);
    } catch (err) {
      console.error(err);
      alert('Impossibile scaricare il template');
    }
  };

  return (
    <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(400px, 1fr))', gap: '32px', maxWidth: '1200px', margin: '0 auto' }}>
      
      {/* Colonna Sinistra: Importazione */}
      <div className="glass-panel" style={{ padding: '32px' }}>
        <div style={{ textAlign: 'center', marginBottom: '30px' }}>
          <h2 style={{ marginBottom: '12px' }}>Importa Listino Master</h2>
          <p style={{ color: 'var(--text-secondary)' }}>Carica il listino concordato in formato Excel per attivare l'audit automatico.</p>
        </div>

        {/* Tabs per tipologia di listino */}
        <div style={{ display: 'flex', borderBottom: '1px solid var(--border-glass)', marginBottom: '24px' }}>
          <button
            onClick={() => { setActiveTab('standard'); setMessage(null); setFile(null); }}
            style={{
              flex: 1,
              padding: '12px',
              background: 'none',
              border: 'none',
              borderBottom: activeTab === 'standard' ? '2px solid var(--accent-blue)' : 'none',
              color: activeTab === 'standard' ? 'white' : 'var(--text-secondary)',
              fontWeight: 600,
              cursor: 'pointer',
              fontSize: '0.9rem',
              outline: 'none'
            }}
          >
            Template Standard
          </button>
          <button
            onClick={() => { setActiveTab('multi'); setMessage(null); setFile(null); }}
            style={{
              flex: 1,
              padding: '12px',
              background: 'none',
              border: 'none',
              borderBottom: activeTab === 'multi' ? '2px solid var(--accent-blue)' : 'none',
              color: activeTab === 'multi' ? 'white' : 'var(--text-secondary)',
              fontWeight: 600,
              cursor: 'pointer',
              fontSize: '0.9rem',
              outline: 'none'
            }}
          >
            Listino Comparativo
          </button>
        </div>

        <div style={{ display: 'flex', flexDirection: 'column', gap: '24px' }}>
          
          {activeTab === 'standard' ? (
            <>
              {/* Step 1: Scarica Template */}
              <div style={{ border: '1px solid var(--border-glass)', padding: '20px', borderRadius: 'var(--border-radius-md)', background: 'rgba(255,255,255,0.02)' }}>
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                  <div>
                    <h4 style={{ marginBottom: '4px' }}>1. Utilizza il Template</h4>
                    <p style={{ fontSize: '0.85rem', color: 'var(--text-secondary)' }}>Assicurati che le colonne corrispondano allo standard di Price Sentinel.</p>
                  </div>
                  <button onClick={handleDownloadTemplate} className="btn" style={{ textDecoration: 'none' }}>
                    <Download size={18} /> Scarica Template
                  </button>
                </div>
              </div>

              {/* Step 2: Seleziona Fornitore */}
              <div>
                <label style={{ display: 'block', marginBottom: '8px', fontSize: '0.9rem', fontWeight: 600 }}>2. Seleziona Fornitore</label>
                <select 
                  value={selectedFornitore} 
                  onChange={(e) => setSelectedFornitore(e.target.value)}
                  style={{ width: '100%', padding: '12px', background: 'var(--bg-secondary)', border: '1px solid var(--border-glass)', borderRadius: 'var(--border-radius-md)', color: 'white', outline: 'none' }}
                >
                  <option value="">-- Seleziona un fornitore --</option>
                  {fornitori.map(f => <option key={f.id} value={f.id}>{f.nome_azienda}</option>)}
                </select>
              </div>

              {/* Step 3: Upload */}
              <div style={{ border: '2px dashed var(--border-glass)', padding: '40px', textAlign: 'center', borderRadius: 'var(--border-radius-md)', transition: 'var(--transition-smooth)' }}>
                <input 
                  type="file" 
                  id="fileInput" 
                  accept=".xlsx" 
                  onChange={(e) => setFile(e.target.files?.[0] || null)}
                  style={{ display: 'none' }}
                />
                <label htmlFor="fileInput" style={{ cursor: 'pointer' }}>
                  <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', gap: '12px' }}>
                    <FileSpreadsheet size={48} color={file ? 'var(--status-green)' : 'var(--text-secondary)'} />
                    <div style={{ fontWeight: 500 }}>{file ? file.name : 'Trascina o clicca per caricare il listino Excel'}</div>
                    <p style={{ fontSize: '0.75rem', color: 'var(--text-secondary)' }}>Solo file .xlsx supportati</p>
                  </div>
                </label>
              </div>

              {message && (
                <div style={{ 
                  padding: '12px', 
                  borderRadius: 'var(--border-radius-md)', 
                  background: message.type === 'success' ? 'var(--status-green-bg)' : 'var(--status-red-bg)',
                  color: message.type === 'success' ? 'var(--status-green)' : 'var(--status-red)',
                  display: 'flex', alignItems: 'center', gap: '10px', fontSize: '0.9rem'
                }}>
                  {message.type === 'success' ? <CheckCircle2 size={18}/> : <AlertCircle size={18}/>}
                  {message.text}
                </div>
              )}

              <button 
                className="btn btn-primary" 
                disabled={uploading || !file || !selectedFornitore}
                onClick={handleUpload}
                style={{ width: '100%', padding: '16px', fontSize: '1rem', marginTop: '12px', opacity: (uploading || !file || !selectedFornitore) ? 0.6 : 1 }}
              >
                {uploading ? 'Caricamento in corso...' : 'Importa Listino'}
              </button>
            </>
          ) : (
            <>
              {/* Info Comparativo */}
              <div style={{ border: '1px solid var(--border-glass)', padding: '20px', borderRadius: 'var(--border-radius-md)', background: 'rgba(255,255,255,0.02)' }}>
                <h4 style={{ marginBottom: '4px' }}>Come funziona l'importazione comparativa</h4>
                <p style={{ fontSize: '0.85rem', color: 'var(--text-secondary)', margin: 0, lineHeight: '1.4' }}>
                  Carica un file Excel con colonne multiple. Le prime due colonne devono identificare il <strong>PRODOTTO</strong> e l'<strong>UNITA DI MISURA (o PESO)</strong>. Le colonne successive conterranno i prezzi di listino di ciascun fornitore (es: <em>MARR</em>, <em>MELIUS</em>, <em>DAC</em>). I fornitori mancanti verranno creati automaticamente.
                </p>
              </div>

              {/* Step 2: Upload */}
              <div style={{ border: '2px dashed var(--border-glass)', padding: '40px', textAlign: 'center', borderRadius: 'var(--border-radius-md)', transition: 'var(--transition-smooth)' }}>
                <input 
                  type="file" 
                  id="fileInputMulti" 
                  accept=".xlsx" 
                  onChange={(e) => setFile(e.target.files?.[0] || null)}
                  style={{ display: 'none' }}
                />
                <label htmlFor="fileInputMulti" style={{ cursor: 'pointer' }}>
                  <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', gap: '12px' }}>
                    <FileSpreadsheet size={48} color={file ? 'var(--status-green)' : 'var(--text-secondary)'} />
                    <div style={{ fontWeight: 500 }}>{file ? file.name : 'Trascina o clicca per caricare il listino Comparativo'}</div>
                    <p style={{ fontSize: '0.75rem', color: 'var(--text-secondary)' }}>Solo file .xlsx supportati</p>
                  </div>
                </label>
              </div>

              {message && (
                <div style={{ 
                  padding: '12px', 
                  borderRadius: 'var(--border-radius-md)', 
                  background: message.type === 'success' ? 'var(--status-green-bg)' : 'var(--status-red-bg)',
                  color: message.type === 'success' ? 'var(--status-green)' : 'var(--status-red)',
                  display: 'flex', alignItems: 'center', gap: '10px', fontSize: '0.9rem'
                }}>
                  {message.type === 'success' ? <CheckCircle2 size={18}/> : <AlertCircle size={18}/>}
                  {message.text}
                </div>
              )}

              <button 
                className="btn btn-primary" 
                disabled={uploadingMulti || !file}
                onClick={handleUploadMulti}
                style={{ width: '100%', padding: '16px', fontSize: '1rem', marginTop: '12px', opacity: (uploadingMulti || !file) ? 0.6 : 1 }}
              >
                {uploadingMulti ? 'Caricamento in corso...' : 'Importa Listino Comparativo'}
              </button>
            </>
          )}

        </div>
      </div>

      {/* Colonna Destra: Gestione Listini Attivi */}
      <div className="glass-panel" style={{ padding: '32px', display: 'flex', flexDirection: 'column' }}>
        <div style={{ marginBottom: '24px' }}>
          <h2 style={{ marginBottom: '12px' }}>Gestione Listini Caricati</h2>
          <p style={{ color: 'var(--text-secondary)' }}>Svuota i listini dei fornitori per eliminare i dati caricati per errore o vecchi test.</p>
        </div>

        <div style={{ display: 'flex', flexDirection: 'column', gap: '12px', overflowY: 'auto', maxHeight: '600px' }}>
          {fornitori.map(f => (
            <div key={f.id} style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', padding: '16px', background: 'rgba(255,255,255,0.02)', border: '1px solid var(--border-glass)', borderRadius: 'var(--border-radius-md)' }}>
              <div>
                <div style={{ fontWeight: 600 }}>{f.nome_azienda}</div>
                <div style={{ fontSize: '0.75rem', color: 'var(--text-secondary)' }}>ID Fornitore: {f.id}</div>
              </div>
              <button 
                className="btn"
                onClick={async () => {
                  if (!window.confirm(`Sei sicuro di voler eliminare TUTTI i prodotti a listino per il fornitore ${f.nome_azienda}? L'operazione è irreversibile.`)) return;
                  
                  try {
                    const res = await fetch(`${API_BASE}/listino/fornitore/${f.id}`, {
                      method: 'DELETE',
                      headers: getHeaders()
                    });
                    if (res.ok) {
                      alert(`Listino di ${f.nome_azienda} svuotato con successo.`);
                    } else {
                      const data = await res.json();
                      alert(`Errore: ${data.detail || 'Impossibile svuotare il listino'}`);
                    }
                  } catch (err) {
                    alert('Errore di rete');
                  }
                }}
                style={{ padding: '8px 12px', background: 'var(--status-red-bg)', color: 'var(--status-red)', borderColor: 'rgba(239, 68, 68, 0.3)', fontSize: '0.85rem' }}
              >
                Svuota Listino
              </button>
            </div>
          ))}
        </div>
      </div>

    </div>
  );
}
