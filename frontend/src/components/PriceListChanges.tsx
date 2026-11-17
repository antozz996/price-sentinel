import { useCallback, useEffect, useState } from 'react';
import type { CSSProperties } from 'react';
import { fetchWithAuth } from '../api';

type Change = {
  id: number; fornitore_id: number; fornitore: string; prodotto: string; tipo: string;
  prezzo_vecchio?: string | null; prezzo_nuovo?: string | null; unita?: string | null;
  decorrenza: string; motivo?: string | null; nota?: string | null; impatto_annuo?: string | null;
};
type SupplierRow = { fornitore_id: number; fornitore: string; telefono?: string | null; path?: string | null; ultima_conferma_at?: string | null };
type Overview = {
  oggi: string; prossima_data_fissa: string; contatore: number;
  sospese: Change[]; aumenti: Change[];
  ribassi: { numero: number; risparmio_annuo?: string | null; giorni: number };
  solleciti: { scadenza?: string | null; fornitori: SupplierRow[] };
  non_confermati: { giorni: number; fornitori: SupplierRow[] };
};
type LinkView = { id: number; attivo: boolean; path?: string | null; created_at: string; ultima_conferma_at?: string | null };
type SupplierLink = { fornitore_id: number; fornitore: string; telefono?: string | null; link: LinkView | null };
type Outcome = { applicate: number; chiusi: number; superate: number };

const BASE = '/supplier-price-links';
const card: CSSProperties = { border: '1px solid var(--line)', borderRadius: 'var(--radius-lg)', padding: 16, background: 'var(--bg-card)', marginBottom: 16 };
const row: CSSProperties = { display: 'flex', flexWrap: 'wrap', gap: 8, justifyContent: 'space-between', alignItems: 'center', padding: '10px 0', borderTop: '1px solid var(--line)' };
const muted: CSSProperties = { color: 'var(--text-secondary)', fontSize: '0.85rem' };
const buttons: CSSProperties = { display: 'flex', flexWrap: 'wrap', gap: 6, marginTop: 6, justifyContent: 'flex-end' };
const publicOrigin = (((import.meta as any).env?.VITE_PUBLIC_APP_URL || '').trim() || window.location.origin).replace(/\/$/, '');

const euro = (value?: string | null) =>
  value == null ? '—' : `€ ${Number(value).toLocaleString('it-IT', { minimumFractionDigits: 2, maximumFractionDigits: 4 })}`;
const day = (iso?: string | null) => (iso ? new Date(iso.length === 10 ? `${iso}T12:00:00` : iso).toLocaleDateString('it-IT') : 'mai');
const TIPI: Record<string, string> = { aumento: 'Aumento', ribasso: 'Ribasso', non_trattato: 'Non lo tratta più', nuova_offerta: 'Offerta nuova' };

const post = (path: string, body?: unknown) => fetchWithAuth(`${BASE}${path}`, {
  method: 'POST',
  ...(body === undefined ? {} : { body: JSON.stringify(body) }),
});

function outcomeMessage(res: { decorrenza?: string; esito?: Outcome } | null, fallback: string) {
  const esito = res?.esito;
  if (esito?.superate) return 'Il listino era già cambiato nel frattempo: modifica superata, prezzo non toccato.';
  if (esito?.applicate || esito?.chiusi) return 'Fatto: il listino è aggiornato da oggi.';
  return res?.decorrenza ? `Fatto: entra nel listino dal ${day(res.decorrenza)}.` : fallback;
}

function phoneForWhatsApp(value?: string | null) {
  let digits = (value || '').replace(/\D/g, '');
  if (digits.startsWith('00')) digits = digits.slice(2);
  if (digits.length === 10 && digits.startsWith('3')) digits = '39' + digits;
  return digits.length >= 8 ? digits : '';
}

function whatsAppUrl(telefono: string | null | undefined, path: string | null | undefined, text: string) {
  const phone = phoneForWhatsApp(telefono);
  if (!phone || !path) return '';
  return `https://wa.me/${phone}?text=${encodeURIComponent(`${text} ${publicOrigin}${path}`)}`;
}

const reminderText = (deadline?: string | null) =>
  `Buongiorno, vi chiediamo di controllare i vostri prezzi${deadline ? ` entro il ${day(deadline)}` : ''}: basta aprire il link, `
  + 'cambiare solo quelli diversi oppure premere «confermo tutto invariato».';
const newLinkText = 'Buongiorno, da oggi potete aggiornare i vostri prezzi quando volete da questo link, sempre lo stesso: '
  + 'cambiate solo quelli diversi oppure premete «confermo tutto invariato». I ribassi valgono subito, gli aumenti dal 1° o dal 15 del mese.';

function ChangeLine({ change, canApprove, onDone }: { change: Change; canApprove: boolean; onDone: (msg: string) => void }) {
  const impact = change.impatto_annuo ? Number(change.impatto_annuo) : null;
  const [busy, setBusy] = useState(false);
  const [forcing, setForcing] = useState(false);
  const [price, setPrice] = useState('');
  const [error, setError] = useState('');

  const run = async (action: () => Promise<any>, fallback: string) => {
    setBusy(true); setError('');
    try { onDone(outcomeMessage(await action(), fallback)); }
    catch (err: any) { setError(err.message || 'Operazione non riuscita'); setBusy(false); }
  };
  const forcePrice = () => {
    const text = price.trim().replace(/\s|€/g, '');
    const value = Number(text.includes(',') ? text.replace(/\./g, '').replace(',', '.') : text);
    if (!(value > 0)) { setError('Scrivi un prezzo valido, per esempio 2,35'); return; }
    run(() => post(`/changes/${change.id}/force`, { prezzo: value.toFixed(4) }), 'Fatto: prezzo deciso dall\'ufficio.');
  };

  return (
    <div style={row}>
      <div style={{ minWidth: 220, flex: 1 }}>
        <strong>{change.prodotto}</strong>
        <div style={muted}>{change.fornitore} · {TIPI[change.tipo] || change.tipo} · dal {day(change.decorrenza)}</div>
        {change.motivo && <div style={{ ...muted, color: 'var(--warn)' }}>{change.motivo}</div>}
        {change.nota && <div style={muted}>Nota del fornitore: {change.nota}</div>}
      </div>
      <div style={{ textAlign: 'right' }}>
        <div>{euro(change.prezzo_vecchio)} → <strong>{change.tipo === 'non_trattato' ? 'chiuso' : euro(change.prezzo_nuovo)}</strong>{change.unita ? ` / ${change.unita}` : ''}</div>
        <div style={muted}>{impact == null ? 'nessun acquisto negli ultimi 12 mesi' : `${impact > 0 ? '+' : ''}${euro(change.impatto_annuo)} l'anno`}</div>
        {forcing ? (
          <div style={buttons}>
            <input value={price} onChange={e => setPrice(e.target.value)} placeholder="Prezzo deciso, es. 2,35" inputMode="decimal" style={{ width: 170 }} autoFocus />
            <button className="btn" disabled={busy} onClick={forcePrice}>Salva prezzo</button>
            <button className="btn" disabled={busy} onClick={() => { setForcing(false); setError(''); }}>Annulla</button>
          </div>
        ) : (
          <div style={buttons}>
            {canApprove && <button className="btn" disabled={busy} onClick={() => run(() => post(`/changes/${change.id}/approve`), 'Fatto.')}>Via libera</button>}
            <button className="btn" disabled={busy} onClick={() => run(() => post(`/changes/${change.id}/reject`), 'Rifiutata: il prezzo resta quello di prima.')}>Rifiuta</button>
            <button className="btn" disabled={busy} onClick={() => setForcing(true)}>Altro prezzo</button>
          </div>
        )}
        {error && <div style={{ ...muted, color: 'var(--danger, #c0392b)' }}>{error}</div>}
      </div>
    </div>
  );
}

function SupplierLine({ supplier, deadline }: { supplier: SupplierRow; deadline?: string | null }) {
  const url = whatsAppUrl(supplier.telefono, supplier.path, reminderText(deadline));
  return (
    <div style={row}>
      <div>
        <strong>{supplier.fornitore}</strong>
        <div style={muted}>Ultima conferma: {day(supplier.ultima_conferma_at)}</div>
      </div>
      {url
        ? <a className="btn" href={url} target="_blank" rel="noopener noreferrer">Sollecita su WhatsApp</a>
        : <span style={muted}>{supplier.path ? 'manca il telefono' : 'link da rigenerare'}</span>}
    </div>
  );
}

function LinkLine({ supplier, onChanged }: { supplier: SupplierLink; onChanged: (s: SupplierLink) => void }) {
  const [busy, setBusy] = useState(false);
  const [note, setNote] = useState('');
  const link = supplier.link;
  const fullUrl = link?.path ? `${publicOrigin}${link.path}` : '';
  const wa = whatsAppUrl(supplier.telefono, link?.path, newLinkText);

  const act = async (path: string, confirmText?: string) => {
    if (confirmText && !window.confirm(confirmText)) return;
    setBusy(true); setNote('');
    try {
      const res = await post(path);
      onChanged({ ...supplier, link: res?.link ?? null });
    } catch (err: any) { setNote(err.message || 'Operazione non riuscita'); }
    setBusy(false);
  };
  const copy = async () => {
    try { await navigator.clipboard.writeText(fullUrl); setNote('Link copiato'); }
    catch { setNote(fullUrl); }
  };

  return (
    <div style={row}>
      <div style={{ minWidth: 200, flex: 1 }}>
        <strong>{supplier.fornitore}</strong>
        <div style={muted}>
          {link ? `Link attivo dal ${day(link.created_at)} · ultima conferma: ${day(link.ultima_conferma_at)}` : 'Nessun link'}
        </div>
        {note && <div style={{ ...muted, wordBreak: 'break-all' }}>{note}</div>}
      </div>
      <div style={buttons}>
        {!link && <button className="btn" disabled={busy} onClick={() => act(`/supplier/${supplier.fornitore_id}`)}>Crea link</button>}
        {fullUrl && <button className="btn" disabled={busy} onClick={copy}>Copia link</button>}
        {wa && <a className="btn" href={wa} target="_blank" rel="noopener noreferrer">Manda su WhatsApp</a>}
        {link && <button className="btn" disabled={busy} onClick={() => act(`/supplier/${supplier.fornitore_id}`,
          'Rinnovare il link? Quello vecchio smette di funzionare e va mandato il nuovo al fornitore.')}>Rinnova</button>}
        {link && <button className="btn" disabled={busy} onClick={() => act(`/supplier/${supplier.fornitore_id}/revoke`,
          'Disattivare il link? Il fornitore non potrà più aggiornare i prezzi finché non ne crei uno nuovo.')}>Disattiva</button>}
      </div>
    </div>
  );
}

function SupplierLinks() {
  const [rows, setRows] = useState<SupplierLink[] | null>(null);
  const [error, setError] = useState('');
  const [search, setSearch] = useState('');
  const [open, setOpen] = useState(false);

  useEffect(() => {
    if (!open || rows) return;
    fetchWithAuth(`${BASE}/suppliers`)
      .then(data => setRows(data.fornitori))
      .catch(err => setError(err.message || 'Errore nel caricamento'));
  }, [open, rows]);

  const shown = (rows || []).filter(r => r.fornitore.toLowerCase().includes(search.trim().toLowerCase()));
  const active = (rows || []).filter(r => r.link).length;

  return (
    <div style={card}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', gap: 8, flexWrap: 'wrap' }}>
        <h3 style={{ margin: 0 }}>Link dei fornitori</h3>
        <button className="btn" onClick={() => setOpen(!open)}>{open ? 'Chiudi' : 'Apri'}</button>
      </div>
      <div style={muted}>Il link è sempre lo stesso: il fornitore lo apre quando vuole e cambia solo i prezzi diversi.</div>
      {open && (error ? <div style={row}>{error}</div> : !rows ? <div style={{ ...row, ...muted }}>Caricamento…</div> : (
        <>
          <div style={{ ...row, justifyContent: 'flex-start' }}>
            <input value={search} onChange={e => setSearch(e.target.value)} placeholder="Cerca fornitore" style={{ minWidth: 220 }} />
            <span style={muted}>{active} link attivi su {rows.length} fornitori</span>
          </div>
          {shown.map(s => (
            <LinkLine key={s.fornitore_id} supplier={s}
              onChanged={next => setRows(prev => (prev || []).map(r => (r.fornitore_id === next.fornitore_id ? next : r)))} />
          ))}
        </>
      ))}
    </div>
  );
}

export default function PriceListChanges() {
  const [data, setData] = useState<Overview | null>(null);
  const [error, setError] = useState('');
  const [message, setMessage] = useState('');

  const load = useCallback(() => {
    fetchWithAuth(`${BASE}/overview`)
      .then(setData)
      .catch(err => setError(err.message || 'Errore nel caricamento'));
  }, []);
  useEffect(load, [load]);
  const done = (msg: string) => { setMessage(msg); load(); };

  if (error) return <div style={card}>{error}</div>;
  if (!data) return <div style={card}>Caricamento…</div>;
  const { sospese, aumenti, ribassi, solleciti, non_confermati } = data;

  return (
    <div>
      <div style={{ ...card, display: 'flex', flexWrap: 'wrap', gap: 24 }}>
        <div><div style={muted}>Da guardare</div><strong style={{ fontSize: '1.6rem' }}>{data.contatore}</strong></div>
        <div><div style={muted}>Sospese</div><strong style={{ fontSize: '1.6rem' }}>{sospese.length}</strong></div>
        <div><div style={muted}>Aumenti in arrivo</div><strong style={{ fontSize: '1.6rem' }}>{aumenti.length}</strong></div>
        <div><div style={muted}>Prossima data fissa</div><strong style={{ fontSize: '1.6rem' }}>{day(data.prossima_data_fissa)}</strong></div>
      </div>

      {message && <div style={{ ...card, borderColor: 'var(--accent, var(--line))' }}>{message}</div>}

      {sospese.length > 0 && (
        <div style={{ ...card, borderColor: 'var(--warn)' }}>
          <h3 style={{ margin: 0 }}>Sospese: servono il tuo via libera</h3>
          <div style={muted}>Non entrano nel listino finché l'ufficio non le guarda. Con «Altro prezzo» scrivi il prezzo concordato al posto di quello inviato.</div>
          {sospese.map(change => <ChangeLine key={change.id} change={change} canApprove onDone={done} />)}
        </div>
      )}

      <div style={card}>
        <h3 style={{ margin: 0 }}>Aumenti in arrivo</h3>
        <div style={muted}>In alto quelli che costano di più, calcolati sugli acquisti degli ultimi 12 mesi. Se non lo accetti, premi «Rifiuta» prima della data.</div>
        {aumenti.length === 0
          ? <div style={{ ...row, ...muted }}>Nessun aumento programmato.</div>
          : aumenti.map(change => <ChangeLine key={change.id} change={change} canApprove={false} onDone={done} />)}
      </div>

      <div style={card}>
        <strong>Ribassi negli ultimi {ribassi.giorni} giorni: {ribassi.numero}</strong>
        {ribassi.numero > 0 && <span> · risparmio stimato {euro(ribassi.risparmio_annuo)} l'anno</span>}
      </div>

      {solleciti.scadenza && (
        <div style={card}>
          <h3 style={{ margin: 0 }}>Da sollecitare prima del {day(solleciti.scadenza)}</h3>
          <div style={muted}>Fornitori che non hanno ancora controllato i prezzi dall'ultima data fissa.</div>
          {solleciti.fornitori.length === 0
            ? <div style={{ ...row, ...muted }}>Tutti hanno già confermato.</div>
            : solleciti.fornitori.map(s => <SupplierLine key={s.fornitore_id} supplier={s} deadline={solleciti.scadenza} />)}
        </div>
      )}

      <div style={card}>
        <h3 style={{ margin: 0 }}>Listini non confermati da {non_confermati.giorni} giorni</h3>
        {non_confermati.fornitori.length === 0
          ? <div style={{ ...row, ...muted }}>Nessuno.</div>
          : non_confermati.fornitori.map(s => <SupplierLine key={s.fornitore_id} supplier={s} />)}
      </div>

      <SupplierLinks />
    </div>
  );
}
