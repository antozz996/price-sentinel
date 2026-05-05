import { useState, useEffect } from 'react';
import { FileUp, FileArchive, CheckCircle2, AlertCircle, Loader2, History, Info } from 'lucide-react';
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

export default function ManualUpload() {
  const [files, setFiles] = useState<File[]>([]);
  const [note, setNote] = useState('');
  const [uploading, setUploading] = useState(false);
  const [summary, setSummary] = useState<BatchSummary | null>(null);
  const [history, setHistory] = useState<BatchHistoryItem[]>([]);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    loadHistory();
  }, []);

  async function loadHistory() {
    try {
      const data = await fetchWithAuth('/ingestion/uploads');
      setHistory(data);
    } catch (err) {
      console.error("Errore caricamento storico", err);
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
    } catch (err) {
      setError("Si è verificato un errore durante l'elaborazione dei file.");
    } finally {
      setUploading(false);
    }
  };

  return (
    <div style={{ display: 'grid', gridTemplateColumns: '1fr 350px', gap: '24px' }}>
      
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
            disabled={uploading || files.length === 0}
            onClick={handleUpload}
            style={{ padding: '16px', fontSize: '1rem', display: 'flex', justifyContent: 'center', gap: '12px' }}
          >
            {uploading ? <Loader2 className="spinner" /> : <FileUp size={20} />}
            {uploading ? 'Elaborazione in corso...' : 'Inizia Caricamento'}
          </button>

        </div>
      </div>

      {/* Colonna Destra: Storico */}
      <div className="glass-panel" style={{ padding: '24px' }}>
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

    </div>
  );
}
