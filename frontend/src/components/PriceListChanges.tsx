import { useEffect, useState } from 'react';
import type { CSSProperties } from 'react';
import { API_BASE, fetchWithAuth } from '../api';

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

const card: CSSProperties = { border: '1px solid var(--line)', borderRadius: 'var(--radius-lg)', padding: 16, background: 'var(--bg-card)', marginBottom: 16 };
const row: CSSProperties = { display: 'flex', flexWrap: 'wrap', gap: 8, justifyContent: 'space-between', alignItems: 'center', padding: '10px 0', borderTop: '1px solid var(--line)' };
const muted: CSSProperties = { color: 'var(--text-secondary)', fontSize: '0.85rem' };
const publicOrigin = (((import.meta as any).env?.VITE_PUBLIC_APP_URL || '').trim() || window.location.origin).replace(/\/$/, '');

const euro = (value?: string | null) =>
  value == null ? '—' : `€ ${Number(value).toLocaleString('it-IT', { minimumFractionDigits: 2, maximumFractionDigits: 4 })}`;
const day = (iso?: string | null) => (iso ? new Date(iso.length === 10 ? `${iso}T12:00:00` : iso).toLocaleDateString('it-IT') : 'mai');
const TIPI: Record<string, string> = { aumento: 'Aumento', ribasso: 'Ribasso', non_trattato: 'Non lo tratta più', nuova_offerta: 'Offerta nuova' };

function phoneForWhatsApp(value?: string | null) {
  let digits = (value || '').replace(/\D/g, '');
  if (digits.startsWith('00')) digits = digits.slice(2);
  if (digits.length === 10 && digits.startsWith('3')) digits = '39' + digits;
  return digits.length >= 8 ? digits : '';
}

function whatsAppUrl(supplier: SupplierRow, deadline?: string | null) {
  const phone = phoneForWhatsApp(supplier.telefono);
  if (!phone || !supplier.path) return '';
  const when = deadline ? ` entro il ${day(deadline)}` : '';
  const text = `Buongiorno, vi chiediamo di controllare i vostri prezzi${when}: basta aprire il link, `
    + `cambiare solo quelli diversi oppure premere «confermo tutto invariato». ${publicOrigin}${supplier.path}`;
  return `https://wa.me/${phone}?text=${encodeURIComponent(text)}`;
}

function ChangeLine({ change }: { change: Change }) {
  const impact = change.impatto_annuo ? Number(change.impatto_annuo) : null;
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
      </div>
    </div>
  );
}

function SupplierLine({ supplier, deadline }: { supplier: SupplierRow; deadline?: string | null }) {
  const url = whatsAppUrl(supplier, deadline);
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

export default function PriceListChanges() {
  const [data, setData] = useState<Overview | null>(null);
  const [error, setError] = useState('');

  useEffect(() => {
    fetchWithAuth(`${API_BASE}/supplier-price-links/overview`)
      .then(async res => {
        if (!res.ok) throw new Error((await res.json().catch(() => null))?.detail || 'Errore nel caricamento');
        setData(await res.json());
      })
      .catch(err => setError(err.message || 'Errore nel caricamento'));
  }, []);

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

      {sospese.length > 0 && (
        <div style={{ ...card, borderColor: 'var(--warn)' }}>
          <h3 style={{ margin: 0 }}>Sospese: servono il tuo via libera</h3>
          <div style={muted}>Non entrano nel listino finché l'ufficio non le guarda.</div>
          {sospese.map(change => <ChangeLine key={change.id} change={change} />)}
        </div>
      )}

      <div style={card}>
        <h3 style={{ margin: 0 }}>Aumenti in arrivo</h3>
        <div style={muted}>In alto quelli che costano di più, calcolati sugli acquisti degli ultimi 12 mesi.</div>
        {aumenti.length === 0
          ? <div style={{ ...row, ...muted }}>Nessun aumento programmato.</div>
          : aumenti.map(change => <ChangeLine key={change.id} change={change} />)}
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
    </div>
  );
}
