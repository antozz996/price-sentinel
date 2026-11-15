import { API_BASE, getHeaders } from './api';

/** One point of /intelligence/price-trends: a single invoice line of that SKU. */
export interface PriceTrendPoint {
  data: string;
  riga_id?: number;
  tipo_documento?: string;
  /** Credit note (TD04/TD08): a return, never a purchase price. */
  is_reso: boolean;
  /** Net price per invoice unit, as printed on the invoice. */
  prezzo_fattura: number;
  unita_fattura: string;
  /** Net price converted to the supplier's price-list unit; null when the conversion is not reliable. */
  prezzo_pagato: number | null;
  unita_confronto: string | null;
  confrontabile: boolean;
  quantita: number;
  quantita_confronto?: number | null;
  fornitore_id: number;
  fornitore: string;
  location: string;
  /** Price list of the same supplier valid on the document date, in unita_confronto. */
  prezzo_contratto: number | null;
  fattura_id?: number | null;
  numero_documento?: string | null;
}

export interface PriceTrendSupplier {
  fornitore_id: number;
  fornitore: string | null;
  prezzo_contratto_corrente: number | null;
  unita_contratto: string | null;
}

export interface PriceTrendSeries {
  sku_interno: string;
  prodotto_nome: string;
  /** Set only when the series has a single supplier. */
  prezzo_contratto_corrente: number | null;
  unita_contratto_corrente?: string | null;
  fornitori?: PriceTrendSupplier[];
  history: PriceTrendPoint[];
}

/** Points that can be drawn on the price line: converted purchases, not returns. */
export function isLinePoint(point: PriceTrendPoint): boolean {
  return point.confrontabile && !point.is_reso && point.prezzo_pagato !== null;
}

const euro = new Intl.NumberFormat('it-IT', { minimumFractionDigits: 2, maximumFractionDigits: 4 });

export function formatEuro(value: number | null | undefined): string {
  return value === null || value === undefined ? '-' : `€ ${euro.format(value)}`;
}

/** "€ 0,8307 / Pz" when converted, otherwise the invoice price in its own unit. */
export function pointPriceLabel(point: PriceTrendPoint): string {
  if (point.confrontabile && point.prezzo_pagato !== null) {
    return `${formatEuro(point.prezzo_pagato)} / ${point.unita_confronto || 'n.d.'}`;
  }
  return `${formatEuro(point.prezzo_fattura)} / ${point.unita_fattura} (unità di fattura, non convertibile)`;
}

/** Download an authenticated file: window.open cannot send the Authorization header. */
export async function downloadWithAuth(path: string, filename: string): Promise<void> {
  const response = await fetch(`${API_BASE}${path}`, { headers: getHeaders() });
  if (!response.ok) {
    let detail = '';
    try {
      const payload = await response.json();
      detail = typeof payload?.detail === 'string' ? payload.detail : '';
    } catch {
      detail = '';
    }
    throw new Error(detail || `Errore ${response.status}`);
  }
  const url = window.URL.createObjectURL(await response.blob());
  const link = document.createElement('a');
  link.href = url;
  link.download = filename;
  document.body.appendChild(link);
  link.click();
  link.remove();
  window.URL.revokeObjectURL(url);
}
