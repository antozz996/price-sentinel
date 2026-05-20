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
  const [message, setMessage] = useState<{ text: string, type: 'success' | 'error' } | null>(null);

  useEffect(() => {
    const controller = new AbortController();
    async function loadFornitori() {
      try {
        const res = await fetch(`${API_BASE}/fornitori/`, {
          headers: getHeaders(),
          signal: controller.signal
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
    }
    loadFornitori();
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
      const res = await fetch(`${API_BASE}/listino/import-excel/${selectedFornitore}`, {
        method: 'POST',
        headers: getHeaders(),
        body: formData,
      });

      const result = await res.json();
      if (res.ok) {
        setMessage({ text: `Importato con successo: ${result.inserted} prodotti aggiunti.`, type: 'success' });
        setFile(null);
      } else {
        setMessage({ text: `Errore: ${result.detail || 'Impossibile caricare il listino'}`, type: 'error' });
      }
    } catch (err) {
      setMessage({ text: 'Errore di rete o server non raggiungibile', type: 'error' });
    } finally {
      setUploading(false);
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
    <div className="glass-panel" style={{ padding: '32px', maxWidth: '800px', margin: '0 auto' }}>
      <div style={{ textAlign: 'center', marginBottom: '40px' }}>
        <h2 style={{ marginBottom: '12px' }}>Gestione Listini Master</h2>
        <p style={{ color: 'var(--text-secondary)' }}>Carica il listino concordato in formato Excel per attivare l'audit automatico.</p>
      </div>

      <div style={{ display: 'flex', flexDirection: 'column', gap: '24px' }}>
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
      </div>
    </div>
  );
}
