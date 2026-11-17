import { useEffect, useMemo, useState } from 'react';
import type { CSSProperties } from 'react';
import { ArrowDown, ArrowUp, BarChart3, Download, Info, RefreshCw, Search, X } from 'lucide-react';
import { API_BASE, getHeaders } from '../api';

type Fonte = 'fatture' | 'ordini';
type Granularita = 'settimana' | 'mese';
type SortKey = 'nome' | 'quantita' | 'righe' | 'spesa_totale' | 'prezzo_medio';

interface QuantitaUnita { unita: string; quantita: number }

interface Volumi {
  quantita_per_unita: QuantitaUnita[];
  quantita_normalizzata: number | null;
  unita_normalizzata: string | null;
  quantita_omaggio: number;
  righe: number;
  documenti: number;
  spesa_totale: number;
  prezzo_medio: number | null;
  prezzo_medio_unita: string | null;
}

interface FornitoreVolumi extends Volumi { fornitore_id: number; nome: string }

interface ProdottoVolumi extends Volumi {
  sku_interno: string;
  product_id: number | null;
  nome: string;
  categoria: string | null;
  sottocategoria: string | null;
  unita_confronto: string | null;
  fornitori: FornitoreVolumi[];
}

interface Periodo extends Volumi { periodo: string }

interface Dettaglio {
  sku_interno: string;
  nome: string;
  granularita: Granularita;
  periodi: Periodo[];
}

interface Opzioni {
  fornitori: { id: number; nome: string }[];
  categorie: { nome: string; sottocategorie: string[] }[];
}

const isoDate = (d: Date) => {
  const local = new Date(d.getTime() - d.getTimezoneOffset() * 60000);
  return local.toISOString().slice(0, 10);
};

const today = new Date();
const DEFAULT_A = isoDate(today);
const DEFAULT_DA = isoDate(new Date(today.getFullYear(), today.getMonth(), today.getDate() - 29));

const fmtQty = new Intl.NumberFormat('it-IT', { maximumFractionDigits: 3 });
const fmtEur = new Intl.NumberFormat('it-IT', { style: 'currency', currency: 'EUR' });
const fmtPrice = new Intl.NumberFormat('it-IT', { style: 'currency', currency: 'EUR', minimumFractionDigits: 2, maximumFractionDigits: 4 });

const formatDate = (iso: string) => {
  const [y, m, d] = iso.split('-');
  return `${d}/${m}/${y}`;
};

const MESI = ['Gen', 'Feb', 'Mar', 'Apr', 'Mag', 'Giu', 'Lug', 'Ago', 'Set', 'Ott', 'Nov', 'Dic'];
const formatPeriodo = (iso: string, granularita: Granularita) => {
  if (granularita === 'mese') {
    const [y, m] = iso.split('-');
    return `${MESI[Number(m) - 1]} ${y}`;
  }
  return `Settimana dal ${formatDate(iso)}`;
};

/** Quantità leggibile: normalizzata se affidabile, altrimenti per unità (mai sommate). */
function QuantityCell({ v, strong = true }: { v: Volumi; strong?: boolean }) {
  if (v.quantita_normalizzata !== null) {
    const raw = v.quantita_per_unita.map(q => `${fmtQty.format(q.quantita)} ${q.unita}`).join(' + ');
    return (
      <span title={`Quantità registrate: ${raw}`}>
        <span style={{ fontWeight: strong ? 600 : 500 }}>{fmtQty.format(v.quantita_normalizzata)} {v.unita_normalizzata}</span>
        {v.quantita_omaggio > 0 && (
          <span style={{ display: 'block', fontSize: '0.72rem', color: 'var(--text-muted)' }}>di cui omaggio {fmtQty.format(v.quantita_omaggio)}</span>
        )}
      </span>
    );
  }
  return (
    <span style={{ display: 'flex', flexDirection: 'column', gap: '2px' }}>
      {v.quantita_per_unita.map(q => (
        <span key={q.unita} style={{ fontWeight: strong ? 600 : 500 }}>{fmtQty.format(q.quantita)} {q.unita}</span>
      ))}
      {v.quantita_per_unita.length > 1 && (
        <span style={{ fontSize: '0.72rem', color: 'var(--warn)' }}>unità non convertibili</span>
      )}
    </span>
  );
}

const priceText = (v: Volumi) =>
  v.prezzo_medio === null ? '—' : `${fmtPrice.format(v.prezzo_medio)}/${v.prezzo_medio_unita}`;

const sortQuantity = (p: ProdottoVolumi) =>
  p.quantita_normalizzata ?? (p.quantita_per_unita.length === 1 ? p.quantita_per_unita[0].quantita : -1);

const labelStyle: CSSProperties = { fontSize: '0.75rem', color: 'var(--text-secondary)' };
const inputStyle: CSSProperties = {
  padding: '9px 10px', borderRadius: 'var(--radius-sm)', background: 'var(--bg-inset)',
  border: '1px solid var(--line)', color: 'var(--text-primary)', fontSize: '0.85rem', width: '100%', boxSizing: 'border-box',
};
const thStyle: CSSProperties = { padding: '10px 12px', textAlign: 'left', fontSize: '0.75rem', color: 'var(--text-secondary)', whiteSpace: 'nowrap' };
const tdStyle: CSSProperties = { padding: '10px 12px', fontSize: '0.85rem', verticalAlign: 'top', borderTop: '1px solid var(--line)' };

export default function PurchaseVolumeAnalysis() {
  const [fonte, setFonte] = useState<Fonte>('fatture');
  const [dataDa, setDataDa] = useState(DEFAULT_DA);
  const [dataA, setDataA] = useState(DEFAULT_A);
  const [query, setQuery] = useState('');
  const [debouncedQuery, setDebouncedQuery] = useState('');
  const [categoria, setCategoria] = useState('');
  const [sottocategoria, setSottocategoria] = useState('');
  const [fornitoreId, setFornitoreId] = useState('');

  const [opzioni, setOpzioni] = useState<Opzioni>({ fornitori: [], categorie: [] });
  const [prodotti, setProdotti] = useState<ProdottoVolumi[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [exporting, setExporting] = useState(false);
  const [sort, setSort] = useState<{ key: SortKey; dir: 'asc' | 'desc' }>({ key: 'spesa_totale', dir: 'desc' });

  const [selectedSku, setSelectedSku] = useState<string | null>(null);
  const [granularita, setGranularita] = useState<Granularita>('settimana');
  const [dettaglio, setDettaglio] = useState<Dettaglio | null>(null);
  const [loadingDettaglio, setLoadingDettaglio] = useState(false);

  useEffect(() => {
    const t = setTimeout(() => setDebouncedQuery(query.trim()), 350);
    return () => clearTimeout(t);
  }, [query]);

  useEffect(() => {
    fetch(`${API_BASE}/volumi/opzioni`, { headers: getHeaders() })
      .then(r => (r.ok ? r.json() : Promise.reject()))
      .then(setOpzioni)
      .catch(() => setOpzioni({ fornitori: [], categorie: [] }));
  }, []);

  const params = useMemo(() => {
    const p = new URLSearchParams({ fonte, data_da: dataDa, data_a: dataA });
    if (debouncedQuery) p.set('q', debouncedQuery);
    if (categoria) p.set('categoria', categoria);
    if (sottocategoria) p.set('sottocategoria', sottocategoria);
    if (fornitoreId) p.set('fornitore_id', fornitoreId);
    return p;
  }, [fonte, dataDa, dataA, debouncedQuery, categoria, sottocategoria, fornitoreId]);

  const datesValid = Boolean(dataDa && dataA && dataDa <= dataA);

  const load = async () => {
    if (!datesValid) return;
    setLoading(true);
    setError(null);
    try {
      const res = await fetch(`${API_BASE}/volumi?${params.toString()}`, { headers: getHeaders() });
      if (!res.ok) {
        const body = await res.json().catch(() => null);
        throw new Error(typeof body?.detail === 'string' ? body.detail : 'Impossibile caricare i volumi.');
      }
      const data = await res.json();
      setProdotti(data.prodotti);
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Impossibile caricare i volumi.');
      setProdotti([]);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => { load(); }, [params]); // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {
    if (!selectedSku || !datesValid) { setDettaglio(null); return; }
    let cancelled = false;
    setLoadingDettaglio(true);
    const p = new URLSearchParams(params);
    p.set('sku', selectedSku);
    p.set('granularita', granularita);
    p.delete('q');
    fetch(`${API_BASE}/volumi/dettaglio?${p.toString()}`, { headers: getHeaders() })
      .then(r => (r.ok ? r.json() : Promise.reject()))
      .then(d => { if (!cancelled) setDettaglio(d); })
      .catch(() => { if (!cancelled) setDettaglio(null); })
      .finally(() => { if (!cancelled) setLoadingDettaglio(false); });
    return () => { cancelled = true; };
  }, [selectedSku, granularita, params, datesValid]);

  const handleExport = async () => {
    setExporting(true);
    try {
      const res = await fetch(`${API_BASE}/volumi/export.csv?${params.toString()}`, { headers: getHeaders() });
      if (!res.ok) throw new Error();
      const blob = await res.blob();
      const url = URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = `analisi_volumi_${fonte}_${dataDa}_${dataA}.csv`;
      document.body.appendChild(a);
      a.click();
      a.remove();
      URL.revokeObjectURL(url);
    } catch {
      setError('Esportazione CSV non riuscita.');
    } finally {
      setExporting(false);
    }
  };

  const sorted = useMemo(() => {
    const value = (p: ProdottoVolumi): number | string => {
      switch (sort.key) {
        case 'nome': return p.nome.toLowerCase();
        case 'quantita': return sortQuantity(p);
        case 'righe': return p.righe;
        case 'spesa_totale': return p.spesa_totale;
        case 'prezzo_medio': return p.prezzo_medio ?? -1;
      }
    };
    return [...prodotti].sort((a, b) => {
      const va = value(a), vb = value(b);
      const cmp = va < vb ? -1 : va > vb ? 1 : 0;
      return sort.dir === 'asc' ? cmp : -cmp;
    });
  }, [prodotti, sort]);

  const toggleSort = (key: SortKey) =>
    setSort(s => (s.key === key ? { key, dir: s.dir === 'asc' ? 'desc' : 'asc' } : { key, dir: key === 'nome' ? 'asc' : 'desc' }));

  const SortHeader = ({ k, label, align = 'left' }: { k: SortKey; label: string; align?: 'left' | 'right' }) => (
    <th style={{ ...thStyle, textAlign: align }}>
      <button
        type="button"
        onClick={() => toggleSort(k)}
        style={{ background: 'none', border: 'none', color: 'inherit', font: 'inherit', cursor: 'pointer', display: 'inline-flex', alignItems: 'center', gap: '4px', padding: 0 }}
      >
        {label}
        {sort.key === k && (sort.dir === 'asc' ? <ArrowUp size={12} /> : <ArrowDown size={12} />)}
      </button>
    </th>
  );

  const sottocategorie = opzioni.categorie.find(c => c.nome === categoria)?.sottocategorie ?? [];
  const selected = prodotti.find(p => p.sku_interno === selectedSku) ?? null;
  const totaleSpesa = prodotti.reduce((s, p) => s + p.spesa_totale, 0);

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: '24px' }}>
      <div className="glass-panel" style={{ padding: '20px', display: 'flex', flexDirection: 'column', gap: '16px' }}>
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', flexWrap: 'wrap', gap: '12px' }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: '10px' }}>
            <BarChart3 color="var(--accent-blue)" size={22} />
            <h4 style={{ margin: 0, fontSize: '1.1rem', fontWeight: 600 }}>Filtri analisi volumi</h4>
          </div>
          <div style={{ display: 'flex', gap: '8px', flexWrap: 'wrap' }}>
            <button className="btn" onClick={load} disabled={loading || !datesValid} style={{ fontSize: '0.85rem', display: 'flex', alignItems: 'center', gap: '6px' }}>
              <RefreshCw size={14} /> Aggiorna
            </button>
            <button className="btn btn-primary" onClick={handleExport} disabled={exporting || loading || !datesValid || prodotti.length === 0} style={{ fontSize: '0.85rem', display: 'flex', alignItems: 'center', gap: '6px' }}>
              <Download size={14} /> {exporting ? 'Esportazione...' : 'Esporta CSV'}
            </button>
          </div>
        </div>

        <div style={{ display: 'flex', gap: '6px', flexWrap: 'wrap' }} role="radiogroup" aria-label="Fonte dati">
          {([
            ['fatture', 'Ricevuto (fatture)'],
            ['ordini', 'Richiesto (ordini)'],
          ] as [Fonte, string][]).map(([value, label]) => (
            <button
              key={value}
              type="button"
              role="radio"
              aria-checked={fonte === value}
              onClick={() => setFonte(value)}
              className="btn"
              style={{
                fontSize: '0.8rem',
                borderColor: fonte === value ? 'var(--accent-border)' : undefined,
                background: fonte === value ? 'var(--accent-bg)' : undefined,
                color: fonte === value ? 'var(--text-primary)' : 'var(--text-secondary)',
              }}
            >
              {label}
            </button>
          ))}
          <span style={{ fontSize: '0.75rem', color: 'var(--text-muted)', alignSelf: 'center', display: 'flex', alignItems: 'center', gap: '4px' }}>
            <Info size={12} />
            {fonte === 'fatture'
              ? 'Merce effettivamente fatturata dai fornitori (note di credito escluse).'
              : 'Quantità chieste nei nostri ordini: possono differire da quanto consegnato.'}
          </span>
        </div>

        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(170px, 1fr))', gap: '12px', alignItems: 'end' }}>
          <label style={{ display: 'flex', flexDirection: 'column', gap: '6px' }}>
            <span style={labelStyle}>Dal</span>
            <input type="date" value={dataDa} max={dataA} onChange={e => setDataDa(e.target.value)} style={inputStyle} />
          </label>
          <label style={{ display: 'flex', flexDirection: 'column', gap: '6px' }}>
            <span style={labelStyle}>Al</span>
            <input type="date" value={dataA} min={dataDa} onChange={e => setDataA(e.target.value)} style={inputStyle} />
          </label>
          <label style={{ display: 'flex', flexDirection: 'column', gap: '6px' }}>
            <span style={labelStyle}>Prodotto</span>
            <span style={{ position: 'relative', display: 'block' }}>
              <Search size={14} style={{ position: 'absolute', left: '10px', top: '50%', transform: 'translateY(-50%)', color: 'var(--text-muted)' }} />
              <input type="search" value={query} placeholder="Nome o SKU" onChange={e => setQuery(e.target.value)} style={{ ...inputStyle, paddingLeft: '30px' }} />
            </span>
          </label>
          <label style={{ display: 'flex', flexDirection: 'column', gap: '6px' }}>
            <span style={labelStyle}>Categoria</span>
            <select value={categoria} onChange={e => { setCategoria(e.target.value); setSottocategoria(''); }} style={inputStyle}>
              <option value="">Tutte</option>
              {opzioni.categorie.map(c => <option key={c.nome} value={c.nome}>{c.nome}</option>)}
            </select>
          </label>
          <label style={{ display: 'flex', flexDirection: 'column', gap: '6px' }}>
            <span style={labelStyle}>Sottocategoria</span>
            <select value={sottocategoria} onChange={e => setSottocategoria(e.target.value)} style={inputStyle} disabled={!categoria || sottocategorie.length === 0}>
              <option value="">Tutte</option>
              {sottocategorie.map(s => <option key={s} value={s}>{s}</option>)}
            </select>
          </label>
          <label style={{ display: 'flex', flexDirection: 'column', gap: '6px' }}>
            <span style={labelStyle}>Fornitore</span>
            <select value={fornitoreId} onChange={e => setFornitoreId(e.target.value)} style={inputStyle}>
              <option value="">Tutti</option>
              {opzioni.fornitori.map(f => <option key={f.id} value={String(f.id)}>{f.nome}</option>)}
            </select>
          </label>
        </div>
        {!datesValid && <div style={{ color: 'var(--crit)', fontSize: '0.8rem' }}>La data iniziale deve precedere quella finale.</div>}
      </div>

      {error && (
        <div className="glass-panel" style={{ padding: '14px 18px', color: 'var(--crit)', borderColor: 'var(--crit-border)' }}>{error}</div>
      )}

      <div className="glass-panel" style={{ padding: 0, overflow: 'hidden' }}>
        <div style={{ padding: '14px 18px', display: 'flex', justifyContent: 'space-between', flexWrap: 'wrap', gap: '8px', borderBottom: '1px solid var(--line)' }}>
          <span style={{ fontWeight: 600 }}>
            {loading ? 'Caricamento...' : `${prodotti.length} prodotti`}
            <span style={{ fontWeight: 400, color: 'var(--text-secondary)', fontSize: '0.85rem' }}> · {formatDate(dataDa || DEFAULT_DA)} – {formatDate(dataA || DEFAULT_A)}</span>
          </span>
          <span style={{ color: 'var(--text-secondary)', fontSize: '0.85rem' }}>Spesa totale {fmtEur.format(totaleSpesa)}</span>
        </div>
        <div style={{ overflowX: 'auto' }}>
          <table style={{ width: '100%', minWidth: '880px' }}>
            <thead style={{ background: 'var(--bg-inset)' }}>
              <tr>
                <SortHeader k="nome" label="Prodotto" />
                <SortHeader k="quantita" label="Quantità" align="right" />
                <SortHeader k="righe" label={fonte === 'fatture' ? 'Righe / fatture' : 'Righe / ordini'} align="right" />
                <SortHeader k="spesa_totale" label="Spesa" align="right" />
                <SortHeader k="prezzo_medio" label="Prezzo medio" align="right" />
                <th style={thStyle}>Per fornitore</th>
              </tr>
            </thead>
            <tbody>
              {!loading && sorted.length === 0 && (
                <tr><td colSpan={6} style={{ ...tdStyle, textAlign: 'center', color: 'var(--text-secondary)', padding: '28px' }}>Nessun acquisto nel periodo con questi filtri.</td></tr>
              )}
              {sorted.map(p => {
                const isSel = p.sku_interno === selectedSku;
                return (
                  <tr
                    key={p.sku_interno}
                    onClick={() => setSelectedSku(isSel ? null : p.sku_interno)}
                    style={{ cursor: 'pointer', background: isSel ? 'var(--accent-bg)' : undefined }}
                    title="Apri l'andamento del prodotto"
                  >
                    <td style={tdStyle}>
                      <div style={{ fontWeight: 600 }}>{p.nome}</div>
                      <div style={{ fontSize: '0.72rem', color: 'var(--text-muted)' }}>
                        {p.sku_interno}{p.categoria ? ` · ${p.categoria}` : ''}{p.sottocategoria ? ` / ${p.sottocategoria}` : ''}
                      </div>
                    </td>
                    <td style={{ ...tdStyle, textAlign: 'right' }}><QuantityCell v={p} /></td>
                    <td style={{ ...tdStyle, textAlign: 'right' }}>{p.righe} / {p.documenti}</td>
                    <td style={{ ...tdStyle, textAlign: 'right' }}>{fmtEur.format(p.spesa_totale)}</td>
                    <td style={{ ...tdStyle, textAlign: 'right', whiteSpace: 'nowrap' }}>{priceText(p)}</td>
                    <td style={tdStyle}>
                      <div style={{ display: 'flex', flexDirection: 'column', gap: '4px' }}>
                        {p.fornitori.map(f => (
                          <div key={f.fornitore_id} style={{ display: 'flex', justifyContent: 'space-between', gap: '10px', fontSize: '0.78rem' }}>
                            <span style={{ color: 'var(--text-secondary)' }}>{f.nome}</span>
                            <span style={{ textAlign: 'right' }}><QuantityCell v={f} strong={false} /></span>
                          </div>
                        ))}
                      </div>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      </div>

      {selectedSku && (
        <div className="glass-panel" style={{ padding: '20px', display: 'flex', flexDirection: 'column', gap: '14px' }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', flexWrap: 'wrap', gap: '10px' }}>
            <div>
              <h4 style={{ margin: 0, fontSize: '1.05rem' }}>Andamento: {selected?.nome ?? dettaglio?.nome ?? selectedSku}</h4>
              <span style={{ fontSize: '0.78rem', color: 'var(--text-secondary)' }}>{selectedSku}</span>
            </div>
            <div style={{ display: 'flex', gap: '6px', alignItems: 'center' }}>
              {(['settimana', 'mese'] as Granularita[]).map(g => (
                <button
                  key={g}
                  type="button"
                  className="btn"
                  onClick={() => setGranularita(g)}
                  style={{
                    fontSize: '0.8rem',
                    borderColor: granularita === g ? 'var(--accent-border)' : undefined,
                    background: granularita === g ? 'var(--accent-bg)' : undefined,
                  }}
                >
                  {g === 'settimana' ? 'Per settimana' : 'Per mese'}
                </button>
              ))}
              <button type="button" className="btn btn-ghost" onClick={() => setSelectedSku(null)} aria-label="Chiudi dettaglio"><X size={16} /></button>
            </div>
          </div>
          {loadingDettaglio ? (
            <div style={{ color: 'var(--text-secondary)', fontSize: '0.85rem' }}>Caricamento andamento...</div>
          ) : !dettaglio || dettaglio.periodi.length === 0 ? (
            <div style={{ color: 'var(--text-secondary)', fontSize: '0.85rem' }}>Nessun dato per il periodo selezionato.</div>
          ) : (
            <div style={{ overflowX: 'auto' }}>
              <table style={{ width: '100%', minWidth: '560px' }}>
                <thead style={{ background: 'var(--bg-inset)' }}>
                  <tr>
                    <th style={thStyle}>Periodo</th>
                    <th style={{ ...thStyle, textAlign: 'right' }}>Quantità</th>
                    <th style={{ ...thStyle, textAlign: 'right' }}>Righe</th>
                    <th style={{ ...thStyle, textAlign: 'right' }}>Spesa</th>
                    <th style={{ ...thStyle, textAlign: 'right' }}>Prezzo medio</th>
                  </tr>
                </thead>
                <tbody>
                  {dettaglio.periodi.map(p => (
                    <tr key={p.periodo}>
                      <td style={tdStyle}>{formatPeriodo(p.periodo, dettaglio.granularita)}</td>
                      <td style={{ ...tdStyle, textAlign: 'right' }}><QuantityCell v={p} /></td>
                      <td style={{ ...tdStyle, textAlign: 'right' }}>{p.righe}</td>
                      <td style={{ ...tdStyle, textAlign: 'right' }}>{fmtEur.format(p.spesa_totale)}</td>
                      <td style={{ ...tdStyle, textAlign: 'right', whiteSpace: 'nowrap' }}>{priceText(p)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
          {granularita === 'settimana' && (
            <span style={{ fontSize: '0.72rem', color: 'var(--text-muted)' }}>Le settimane iniziano di lunedì; la prima e l'ultima possono essere parziali rispetto al periodo scelto.</span>
          )}
        </div>
      )}

      <div style={{ fontSize: '0.75rem', color: 'var(--text-muted)', display: 'flex', gap: '6px', alignItems: 'flex-start' }}>
        <Info size={13} style={{ flexShrink: 0, marginTop: '2px' }} />
        <span>
          Le quantità sono convertite nell'unità di confronto del prodotto solo quando il formato è certo (alias fornitore con pezzi per confezione o peso).
          Altrimenti sono mostrate separatamente con l'unità del documento e non vengono mai sommate tra unità diverse.
          Il prezzo medio esclude gli omaggi.
        </span>
      </div>
    </div>
  );
}
