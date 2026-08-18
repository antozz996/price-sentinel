import { useState, useEffect } from 'react';
import { FileSpreadsheet, Download, CheckCircle2, AlertCircle, Sparkles, RefreshCw, Check, ArrowDownToLine, Zap } from 'lucide-react';
import { API_BASE, getHeaders } from '../api';

interface Fornitore {
  id: number;
  nome_azienda: string;
}

interface ExtractedItem {
  sku_interno: string;
  descrizione: string;
  codice_fornitore: string | null;
  prezzo_pattuito: number;
  unita_misura: string;
  data_inizio_validita: string;
  ultima_data: string;
  totale_acquistato: number;
  occorrenze: number;
}

interface ExtractedResult {
  fornitore_id: number;
  fornitore_nome: string;
  total_items: number;
  price_strategy: string;
  items: ExtractedItem[];
}

export default function PriceListManager() {
  const [fornitori, setFornitori] = useState<Fornitore[]>([]);
  const [selectedFornitore, setSelectedFornitore] = useState<string>('');
  const [file, setFile] = useState<File | null>(null);
  const [uploading, setUploading] = useState(false);
  const [uploadingMulti, setUploadingMulti] = useState(false);
  const [activeTab, setActiveTab] = useState<'standard' | 'multi' | 'extract'>('extract');
  const [message, setMessage] = useState<{ text: string, type: 'success' | 'error' } | null>(null);
  const [validationErrors, setValidationErrors] = useState<{ row: number, column: string, message: string }[]>([]);

  // Extraction states
  const [extractSupplier, setExtractSupplier] = useState<string>('');
  const [priceStrategy, setPriceStrategy] = useState<'latest' | 'min' | 'avg'>('latest');
  const [extractLoading, setExtractLoading] = useState(false);
  const [importingDirect, setImportingDirect] = useState(false);
  const [extractedData, setExtractedData] = useState<ExtractedResult | null>(null);

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
    setValidationErrors([]);

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
          setValidationErrors(result.errors || []);
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
        setValidationErrors([]);
      }
    } catch {
      setMessage({ text: 'Errore di rete o server non raggiungibile', type: 'error' });
      setValidationErrors([]);
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
    setValidationErrors([]);

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
          setValidationErrors(result.errors || []);
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
        setValidationErrors([]);
      }
    } catch {
      setMessage({ text: 'Errore di rete o server non raggiungibile', type: 'error' });
      setValidationErrors([]);
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

  const handleExtractPreview = async () => {
    if (!extractSupplier) {
      setMessage({ text: 'Seleziona un fornitore per estrarre il listino', type: 'error' });
      return;
    }

    setExtractLoading(true);
    setMessage(null);
    try {
      const res = await fetch(`${API_BASE}/listino/extract-from-invoices/${extractSupplier}?price_strategy=${priceStrategy}&format=json`, {
        headers: getHeaders()
      });
      if (!res.ok) {
        const errData = await res.json();
        throw new Error(errData.detail || "Errore durante l'estrazione degli articoli dalle fatture");
      }
      const data = await res.json();
      setExtractedData(data);
      if (data.total_items === 0) {
        setMessage({ text: 'Nessun articolo trovato nelle fatture di questo fornitore.', type: 'error' });
      }
    } catch (err: any) {
      console.error(err);
      setMessage({ text: err.message || "Errore durante l'estrazione", type: 'error' });
    } finally {
      setExtractLoading(false);
    }
  };

  const handleDownloadExtractedExcel = async () => {
    if (!extractSupplier) return;
    try {
      const res = await fetch(`${API_BASE}/listino/extract-from-invoices/${extractSupplier}?price_strategy=${priceStrategy}&format=excel`, {
        headers: getHeaders()
      });
      if (!res.ok) throw new Error("Errore durante la generazione del file Excel");

      const blob = await res.blob();
      const url = window.URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      const fornName = fornitori.find(f => f.id === Number(extractSupplier))?.nome_azienda || 'Fornitore';
      a.download = `listino_estratto_${fornName.replace(/ /g, '_').toLowerCase()}.xlsx`;
      document.body.appendChild(a);
      a.click();
      a.remove();
      window.URL.revokeObjectURL(url);
    } catch (err: any) {
      alert(err.message || 'Impossibile scaricare il file Excel');
    }
  };

  const handleImportExtractedDirect = async () => {
    if (!extractSupplier) return;
    if (!window.confirm("Vuoi importare direttamente questi articoli nel Listino Master? Eventuali prezzi già presenti verranno aggiornati.")) return;

    setImportingDirect(true);
    setMessage(null);
    try {
      const res = await fetch(`${API_BASE}/listino/import-from-invoices/${extractSupplier}?price_strategy=${priceStrategy}`, {
        method: 'POST',
        headers: getHeaders()
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.detail || "Errore durante l'importazione diretta");

      setMessage({ text: data.message || 'Listino importato con successo!', type: 'success' });
    } catch (err: any) {
      setMessage({ text: err.message, type: 'error' });
    } finally {
      setImportingDirect(false);
    }
  };

  return (
    <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(400px, 1fr))', gap: '32px', maxWidth: '1200px', margin: '0 auto' }}>
      
      {/* Colonna Sinistra: Importazione & Estrazione */}
      <div className="glass-panel" style={{ padding: '32px' }}>
        <div style={{ textAlign: 'center', marginBottom: '30px' }}>
          <h2 style={{ marginBottom: '12px' }}>Gestione Listini Prezzi</h2>
          <p style={{ color: 'var(--text-secondary)' }}>Estrai i listini direttamente dalle fatture caricate o importa file Excel concordati.</p>
        </div>

        {/* Tabs per tipologia di listino */}
        <div style={{ display: 'flex', borderBottom: '1px solid var(--border-glass)', marginBottom: '24px' }}>
          <button
            onClick={() => { setActiveTab('extract'); setMessage(null); setFile(null); }}
            style={{
              flex: 1,
              padding: '12px',
              background: 'none',
              border: 'none',
              borderBottom: activeTab === 'extract' ? '2px solid var(--accent-blue)' : 'none',
              color: activeTab === 'extract' ? 'white' : 'var(--text-secondary)',
              fontWeight: 600,
              cursor: 'pointer',
              fontSize: '0.88rem',
              outline: 'none',
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
              gap: '6px'
            }}
          >
            <Sparkles size={15} style={{ color: '#f59e0b' }} />
            Estrai da Fatture
          </button>
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
              fontSize: '0.88rem',
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
              fontSize: '0.88rem',
              outline: 'none'
            }}
          >
            Listino Comparativo
          </button>
        </div>

        <div style={{ display: 'flex', flexDirection: 'column', gap: '24px' }}>
          
          {activeTab === 'extract' && (
            <>
              <div style={{ border: '1px solid var(--border-glass)', padding: '20px', borderRadius: 'var(--border-radius-md)', background: 'rgba(255,255,255,0.02)' }}>
                <div style={{ display: 'flex', alignItems: 'center', gap: '10px', marginBottom: '8px' }}>
                  <Sparkles size={18} style={{ color: '#f59e0b' }} />
                  <h4 style={{ margin: 0, fontSize: '1rem', fontWeight: 700 }}>Estrai Listino Prezzi da Fatture Caricate</h4>
                </div>
                <p style={{ fontSize: '0.85rem', color: 'var(--text-secondary)', margin: 0, lineHeight: 1.4 }}>
                  Price Sentinel analizza tutte le fatture caricate del fornitore (es. <em>LINEA CATERING</em>) e genera automaticamente l'elenco degli articoli con i prezzi netti effettivi.
                </p>
              </div>

              {/* Seleziona Fornitore */}
              <div>
                <label style={{ display: 'block', marginBottom: '8px', fontSize: '0.9rem', fontWeight: 600 }}>1. Seleziona Fornitore</label>
                <select 
                  value={extractSupplier} 
                  onChange={(e) => { setExtractSupplier(e.target.value); setExtractedData(null); }}
                  style={{ width: '100%', padding: '12px', background: 'var(--bg-secondary)', border: '1px solid var(--border-glass)', borderRadius: 'var(--border-radius-md)', color: 'white', outline: 'none' }}
                >
                  <option value="">-- Scegli fornitore per estrazione --</option>
                  {fornitori.map(f => (
                    <option key={f.id} value={f.id}>{f.nome_azienda} (ID: {f.id})</option>
                  ))}
                </select>
              </div>

              {/* Strategia di prezzo */}
              <div>
                <label style={{ display: 'block', marginBottom: '8px', fontSize: '0.9rem', fontWeight: 600 }}>2. Criterio di Calcolo Prezzo</label>
                <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(140px, 1fr))', gap: '10px' }}>
                  <button
                    type="button"
                    onClick={() => { setPriceStrategy('latest'); setExtractedData(null); }}
                    style={{
                      padding: '10px',
                      borderRadius: '8px',
                      border: priceStrategy === 'latest' ? '1px solid var(--accent-blue)' : '1px solid var(--border-glass)',
                      background: priceStrategy === 'latest' ? 'rgba(59,130,246,0.15)' : 'rgba(255,255,255,0.02)',
                      color: priceStrategy === 'latest' ? '#3b82f6' : 'white',
                      cursor: 'pointer',
                      fontSize: '0.82rem',
                      fontWeight: priceStrategy === 'latest' ? 600 : 400,
                      textAlign: 'left'
                    }}
                  >
                    <div style={{ display: 'flex', alignItems: 'center', gap: '6px' }}><Zap size={14} /> Ultimo Prezzo</div>
                    <div style={{ fontSize: '0.72rem', color: 'var(--text-secondary)', marginTop: '4px' }}>Fattura più recente</div>
                  </button>

                  <button
                    type="button"
                    onClick={() => { setPriceStrategy('min'); setExtractedData(null); }}
                    style={{
                      padding: '10px',
                      borderRadius: '8px',
                      border: priceStrategy === 'min' ? '1px solid var(--accent-blue)' : '1px solid var(--border-glass)',
                      background: priceStrategy === 'min' ? 'rgba(59,130,246,0.15)' : 'rgba(255,255,255,0.02)',
                      color: priceStrategy === 'min' ? '#3b82f6' : 'white',
                      cursor: 'pointer',
                      fontSize: '0.82rem',
                      fontWeight: priceStrategy === 'min' ? 600 : 400,
                      textAlign: 'left'
                    }}
                  >
                    <div style={{ display: 'flex', alignItems: 'center', gap: '6px' }}><ArrowDownToLine size={14} /> Prezzo Minimo</div>
                    <div style={{ fontSize: '0.72rem', color: 'var(--text-secondary)', marginTop: '4px' }}>Miglior prezzo storico</div>
                  </button>

                  <button
                    type="button"
                    onClick={() => { setPriceStrategy('avg'); setExtractedData(null); }}
                    style={{
                      padding: '10px',
                      borderRadius: '8px',
                      border: priceStrategy === 'avg' ? '1px solid var(--accent-blue)' : '1px solid var(--border-glass)',
                      background: priceStrategy === 'avg' ? 'rgba(59,130,246,0.15)' : 'rgba(255,255,255,0.02)',
                      color: priceStrategy === 'avg' ? '#3b82f6' : 'white',
                      cursor: 'pointer',
                      fontSize: '0.82rem',
                      fontWeight: priceStrategy === 'avg' ? 600 : 400,
                      textAlign: 'left'
                    }}
                  >
                    <div style={{ display: 'flex', alignItems: 'center', gap: '6px' }}><RefreshCw size={14} /> Prezzo Medio</div>
                    <div style={{ fontSize: '0.72rem', color: 'var(--text-secondary)', marginTop: '4px' }}>Media ponderata volumi</div>
                  </button>
                </div>
              </div>

              <button 
                className="btn btn-primary" 
                disabled={extractLoading || !extractSupplier}
                onClick={handleExtractPreview}
                style={{ width: '100%', padding: '14px', fontSize: '0.95rem', display: 'flex', alignItems: 'center', justifyContent: 'center', gap: '8px', opacity: (extractLoading || !extractSupplier) ? 0.6 : 1 }}
              >
                {extractLoading ? <RefreshCw size={16} className="animate-spin" /> : <Sparkles size={16} />}
                {extractLoading ? 'Estrazione in corso...' : 'Analizza e Mostra Articoli da Fatture'}
              </button>

              {/* Risultato Estrazione */}
              {extractedData && (
                <div style={{ display: 'flex', flexDirection: 'column', gap: '14px', marginTop: '10px' }}>
                  <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', padding: '12px 16px', background: 'rgba(59,130,246,0.1)', border: '1px solid rgba(59,130,246,0.3)', borderRadius: '8px' }}>
                    <div>
                      <div style={{ fontWeight: 600, color: 'white', fontSize: '0.9rem' }}>
                        {extractedData.total_items} articoli estrapolati per {extractedData.fornitore_nome}
                      </div>
                      <div style={{ fontSize: '0.75rem', color: 'var(--text-secondary)', marginTop: '2px' }}>
                        Criterio attivo: <strong>{extractedData.price_strategy.toUpperCase()}</strong>
                      </div>
                    </div>
                    <span style={{ fontSize: '0.85rem', color: '#3b82f6', fontWeight: 700 }}>
                      ✓ Pronto all'uso
                    </span>
                  </div>

                  {/* Tabella Anteprima */}
                  <div style={{ maxHeight: '260px', overflowY: 'auto', border: '1px solid var(--border-glass)', borderRadius: '8px' }}>
                    <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: '0.78rem', textAlign: 'left' }}>
                      <thead style={{ background: '#101018', position: 'sticky', top: 0, zIndex: 1 }}>
                        <tr style={{ borderBottom: '1px solid var(--border-glass)' }}>
                          <th style={{ padding: '8px 12px' }}>Articolo</th>
                          <th style={{ padding: '8px 10px', textAlign: 'right' }}>Prezzo (€)</th>
                          <th style={{ padding: '8px 8px', textAlign: 'center' }}>UoM</th>
                          <th style={{ padding: '8px 8px', textAlign: 'center' }}>Fatture</th>
                        </tr>
                      </thead>
                      <tbody>
                        {extractedData.items.map((it, idx) => (
                          <tr key={idx} style={{ borderBottom: '1px solid rgba(255,255,255,0.04)' }}>
                            <td style={{ padding: '8px 12px' }}>
                              <div style={{ fontWeight: 500, color: 'white' }}>{it.descrizione}</div>
                              <div style={{ fontSize: '0.7rem', color: 'var(--text-secondary)' }}>SKU: {it.sku_interno}</div>
                            </td>
                            <td style={{ padding: '8px 10px', textAlign: 'right', fontWeight: 600, color: '#10b981' }}>
                              € {it.prezzo_pattuito.toFixed(4)}
                            </td>
                            <td style={{ padding: '8px 8px', textAlign: 'center', color: 'var(--text-secondary)' }}>
                              {it.unita_misura}
                            </td>
                            <td style={{ padding: '8px 8px', textAlign: 'center', color: 'var(--text-secondary)' }}>
                              {it.occorrenze}
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>

                  {/* Pulsanti Azione */}
                  <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '12px' }}>
                    <button
                      type="button"
                      className="btn"
                      onClick={handleDownloadExtractedExcel}
                      style={{ padding: '12px', display: 'flex', alignItems: 'center', justifyContent: 'center', gap: '8px', fontSize: '0.85rem' }}
                    >
                      <Download size={16} /> Scarica Excel (.xlsx)
                    </button>
                    <button
                      type="button"
                      className="btn btn-primary"
                      disabled={importingDirect}
                      onClick={handleImportExtractedDirect}
                      style={{ padding: '12px', display: 'flex', alignItems: 'center', justifyContent: 'center', gap: '8px', fontSize: '0.85rem' }}
                    >
                      {importingDirect ? <RefreshCw size={16} className="animate-spin" /> : <Check size={16} />}
                      {importingDirect ? 'Importazione...' : 'Importa a Listino'}
                    </button>
                  </div>
                </div>
              )}
            </>
          )}

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
                  display: 'flex', flexDirection: 'column', gap: '10px', fontSize: '0.9rem'
                }}>
                  <div style={{ display: 'flex', alignItems: 'center', gap: '10px' }}>
                    {message.type === 'success' ? <CheckCircle2 size={18}/> : <AlertCircle size={18}/>}
                    <span>{message.text}</span>
                  </div>
                  
                  {message.type === 'error' && validationErrors.length > 0 && (
                    <div style={{
                      maxHeight: '150px',
                      overflowY: 'auto',
                      borderTop: '1px solid rgba(239, 68, 68, 0.2)',
                      paddingTop: '10px',
                      fontSize: '0.8rem',
                      display: 'flex',
                      flexDirection: 'column',
                      gap: '4px',
                      color: '#fca5a5',
                      textAlign: 'left'
                    }}>
                      <strong style={{ color: 'white' }}>Dettagli errori:</strong>
                      {validationErrors.map((err, idx) => (
                        <div key={idx}>
                          • Riga {err.row}, Colonna {err.column}: {err.message}
                        </div>
                      ))}
                    </div>
                  )}
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
                  display: 'flex', flexDirection: 'column', gap: '10px', fontSize: '0.9rem'
                }}>
                  <div style={{ display: 'flex', alignItems: 'center', gap: '10px' }}>
                    {message.type === 'success' ? <CheckCircle2 size={18}/> : <AlertCircle size={18}/>}
                    <span>{message.text}</span>
                  </div>
                  
                  {message.type === 'error' && validationErrors.length > 0 && (
                    <div style={{
                      maxHeight: '150px',
                      overflowY: 'auto',
                      borderTop: '1px solid rgba(239, 68, 68, 0.2)',
                      paddingTop: '10px',
                      fontSize: '0.8rem',
                      display: 'flex',
                      flexDirection: 'column',
                      gap: '4px',
                      color: '#fca5a5',
                      textAlign: 'left'
                    }}>
                      <strong style={{ color: 'white' }}>Dettagli errori:</strong>
                      {validationErrors.map((err, idx) => (
                        <div key={idx}>
                          • Riga {err.row}, Colonna {err.column}: {err.message}
                        </div>
                      ))}
                    </div>
                  )}
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
                  } catch {
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
