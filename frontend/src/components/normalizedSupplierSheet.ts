/** ID-based review of supplier offers against the normalized category Sheet. */
const TABS = ['FOOD', 'BEVERAGE', 'FRUTTA E VERDURA', 'MATERIALI'] as const;
const HEADERS = ['ID_PRODOTTO', 'PRODOTTO', 'SOTTOCATEGORIA', 'ID_FORNITORE', 'FORNITORE', 'DICITURA_FORNITORE', 'MARCA', 'QUANTITA_CONFEZIONE', 'UNITA_MISURA', 'PREZZO_CONFEZIONE_EUR', 'DATA_PREZZO', 'NOTE'];
const OFFER_HEADER = 'ID_OFFERTA';
const SUPPLIER_HEADERS = ['ID_FORNITORE', 'FORNITORE', 'PARTITA_IVA', 'FOOD', 'BEVERAGE', 'FRUTTA_E_VERDURA', 'MATERIALI', 'NOTE'];
const normalize = (value: unknown) => String(value ?? '').normalize('NFD').replace(/[\u0300-\u036f]/g, '').toLocaleLowerCase().replace(/[^a-z0-9]+/g, ' ').trim().replace(/\s+/g, ' ');
const cellText = (value: unknown) => String(value ?? '').trim();
const quote = (tab: string) => "'" + tab.replace(/'/g, "''") + "'";

export type SheetOfferTarget = {
  item_id: number; offer_id: string; product: string; sku: string; status: 'ready' | 'already' | 'blocked' | 'not_trattato' | 'written';
  reason: string; tab?: string; cell?: string; current: string; offered: string; unit: string;
  mode?: 'update' | 'append'; row?: number; supplierId?: string; snapshot?: string[]; nextRow?: string[];
};
type SubmittedOffer = { id_offerta: string; prezzo: string; unita_misura: string; marca: string; dicitura_fornitore: string; quantita_confezione: string; nota?: string | null };
type Offer = { id: number; sku_interno: string; descrizione: string; prezzo_inviato?: string | null; unita_inviata?: string | null; brand_inviata?: string | null; dicitura_inviata?: string | null; quantita_inviata?: string | null; nota_fornitore?: string | null; non_trattato?: boolean; offerte_inviate?: SubmittedOffer[] };
type Request = { supplier_name: string; validita_inviata_da?: string | null; items: Offer[] };
type Fetcher = (url: string, token: string, init?: RequestInit) => Promise<any>;

async function snapshot(root: string, token: string, fetcher: Fetcher) {
  const meta = await fetcher(root + '?fields=' + encodeURIComponent('sheets.properties(sheetId,title)'), token);
  const ids = new Map<string, number>((meta.sheets || []).map((sheet: any) => [sheet.properties.title, sheet.properties.sheetId]));
  for (const name of [...TABS, 'FORNITORI']) if (!ids.has(name)) throw new Error(`Nel nuovo Sheet manca la scheda ${name}.`);
  const params = new URLSearchParams();
  for (const name of TABS) params.append('ranges', `${quote(name)}!A1:M5000`);
  params.append('ranges', "'FORNITORI'!A1:H5000");
  params.set('valueRenderOption', 'FORMULA');
  const read = await fetcher(root + '/values:batchGet?' + params, token);
  if (read.valueRanges?.length !== 5) throw new Error('Lettura incompleta del nuovo Sheet.');
  const tabs = new Map<string, string[][]>();
  [...TABS, 'FORNITORI'].forEach((name, i) => tabs.set(name, (read.valueRanges[i].values || []).map((row: unknown[]) => Array.from({ length: name === 'FORNITORI' ? 8 : 13 }, (_, col) => cellText(row[col])))));
  for (const name of TABS) if ((tabs.get(name)?.length || 0) >= 5000) throw new Error(`La scheda ${name} raggiunge il limite di lettura: nessuna modifica è consentita.`);
  for (const name of TABS) if (HEADERS.some((header, col) => tabs.get(name)?.[0]?.[col] !== header) || !['', OFFER_HEADER].includes(tabs.get(name)?.[0]?.[12] || '')) throw new Error(`Intestazioni diverse dal nuovo formato nella scheda ${name}.`);
  if (SUPPLIER_HEADERS.some((header, col) => tabs.get('FORNITORI')?.[0]?.[col] !== header)) throw new Error('Intestazioni diverse dal nuovo formato nella scheda FORNITORI.');
  return { tabs, ids };
}

export async function prepareNormalizedSheet(root: string, token: string, request: Request, fetcher: Fetcher): Promise<SheetOfferTarget[]> {
  const { tabs } = await snapshot(root, token, fetcher);
  const suppliers = (tabs.get('FORNITORI') || []).slice(1).filter(row => normalize(row[1]) === normalize(request.supplier_name));
  if (suppliers.length !== 1 || !suppliers[0][0]) throw new Error('Il fornitore non ha una corrispondenza univoca per nome e ID nella scheda FORNITORI. Completa il registro prima di aggiornare le offerte.');
  const supplierId = suppliers[0][0];
  return request.items.flatMap<SheetOfferTarget>(item => {
    const offers: SubmittedOffer[] = item.offerte_inviate?.length ? item.offerte_inviate : item.non_trattato ? [] : [{ id_offerta: '', prezzo: item.prezzo_inviato || '', unita_misura: item.unita_inviata || '', marca: item.brand_inviata || '', dicitura_fornitore: item.dicitura_inviata || '', quantita_confezione: item.quantita_inviata || '', nota: item.nota_fornitore }];
    if (item.non_trattato) return [{ item_id: item.id, offer_id: '', product: item.descrizione, sku: item.sku_interno, current: '', offered: '', unit: '', status: 'not_trattato' as const, reason: 'Il fornitore non tratta questo prodotto.' }];
    return offers.map((offer, offerIndex) => {
    const base = { item_id: item.id, offer_id: offer.id_offerta, product: item.descrizione, sku: item.sku_interno, current: '', offered: offer.prezzo, unit: offer.unita_misura };
    if (!offer.prezzo || !offer.unita_misura || !offer.marca || !offer.dicitura_fornitore || !offer.quantita_confezione || !request.validita_inviata_da) return { ...base, status: 'blocked' as const, reason: 'Risposta incompleta: servono dicitura, marca, quantità, unità, prezzo e data.' };
    const productRows: Array<{ tab: string; row: number; cells: string[] }> = [];
    const matchingRows: typeof productRows = [];
    for (const tab of TABS) (tabs.get(tab) || []).slice(1).forEach((cells, index) => {
      if (cells[0] === item.sku_interno) {
        const entry = { tab, row: index + 2, cells };
        productRows.push(entry);
        if (cells[3] === supplierId) matchingRows.push(entry);
      }
    });
    if (new Set(productRows.map(row => row.tab)).size > 1 || new Set(productRows.map(row => normalize(row.cells[1]) + '|' + normalize(row.cells[2]))).size > 1) return { ...base, status: 'blocked' as const, reason: 'ID prodotto ambiguo o presente in più categorie: verifica manuale.' };
    if (!productRows.length) return { ...base, status: 'blocked' as const, reason: 'ID prodotto assente dal nuovo Sheet: aggiungi prima il prodotto al catalogo.' };
    const exact = offer.id_offerta ? matchingRows.filter(row => row.cells[12] === offer.id_offerta) : [];
    const legacy = matchingRows.filter(row => !row.cells[12]);
    const matchingLegacy = legacy.filter(row => {
      if (!offer.id_offerta && legacy.length === 1) return true;
      const emptyOffer = row.cells.slice(5, 9).every(value => !value);
      if (emptyOffer) return offerIndex === 0;
      return normalize(row.cells[5]) === normalize(offer.dicitura_fornitore)
        && normalize(row.cells[6]) === normalize(offer.marca)
        && Number(row.cells[7].replace(',', '.')) === Number(offer.quantita_confezione.replace(',', '.'))
        && normalize(row.cells[8]) === normalize(offer.unita_misura);
    });
    if (exact.length > 1 || matchingLegacy.length > 1 || (!offer.id_offerta && matchingRows.length > 1)) return { ...base, status: 'blocked' as const, reason: 'Più righe candidabili per la stessa offerta: verifica gli ID offerta.' };
    const existing = exact[0] || matchingLegacy[0];
    const foreignOffer = offer.id_offerta && [...TABS].some(name => (tabs.get(name) || []).slice(1).some(row => row[12] === offer.id_offerta && (row[0] !== item.sku_interno || row[3] !== supplierId)));
    if (foreignOffer) return { ...base, status: 'blocked' as const, reason: 'ID offerta già usato per un altro prodotto o fornitore.' };
    const tab = productRows[0].tab;
    const sectorColumn: Record<string, number> = { FOOD: 3, BEVERAGE: 4, 'FRUTTA E VERDURA': 5, MATERIALI: 6 };
    if (normalize(suppliers[0][sectorColumn[tab]]) !== 'si') return { ...base, status: 'blocked' as const, reason: `Il fornitore non è abilitato per ${tab} nel registro FORNITORI.` };
    const sourceNote = (existing?.cells[11] || productRows[0].cells[11] || '').replace(/\s*\|\s*Conferma fornitore Price Sentinel(?:\s*\|\s*Risposta fornitore:.*)?$/, '');
    const confirmation = 'Conferma fornitore Price Sentinel';
    const nextNote = `${sourceNote}${sourceNote ? ' | ' : ''}${confirmation}${offer.nota ? ` | Risposta fornitore: ${offer.nota}` : ''}`;
    const values = [offer.dicitura_fornitore, offer.marca, offer.quantita_confezione, offer.unita_misura, offer.prezzo, request.validita_inviata_da, nextNote, offer.id_offerta];
    if (existing && existing.cells.slice(5).some(cell => cell.startsWith('='))) return { ...base, status: 'blocked' as const, reason: 'La riga contiene una formula nelle colonne offerta; non la sovrascrivo.' };
    const nextRow = existing ? [...existing.cells.slice(0, 5), ...values] : [item.sku_interno, productRows[0].cells[1], productRows[0].cells[2], supplierId, suppliers[0][1], ...values];
    const snapshotRow = existing?.cells || productRows[0].cells;
    const already = Boolean(existing && nextRow.every((value, col) => cellText(value) === cellText(snapshotRow[col])));
    return { ...base, status: already ? 'already' as const : 'ready' as const, reason: already ? 'Offerta già presente.' : existing ? 'Riga identificata per ID offerta.' : 'Nuova riga per questa marca o formato.', tab, cell: existing ? `${quote(tab)}!F${existing.row}:${offer.id_offerta ? 'M' : 'L'}${existing.row}` : `${quote(tab)}!nuova riga`, current: existing?.cells[9] || '', mode: existing ? 'update' as const : 'append' as const, row: existing?.row, supplierId, snapshot: snapshotRow, nextRow };
    });
  });
}

function gridValue(value: string, numeric: boolean) {
  return { userEnteredValue: numeric ? { numberValue: Number(value) } : { stringValue: value } };
}

export async function writeNormalizedSheet(root: string, token: string, request: Request, targets: SheetOfferTarget[], fetcher: Fetcher): Promise<void> {
  const ready = targets.filter(target => target.status === 'ready');
  const { tabs, ids } = await snapshot(root, token, fetcher);
  const supplier = (tabs.get('FORNITORI') || []).slice(1).filter(row => normalize(row[1]) === normalize(request.supplier_name));
  if (supplier.length !== 1 || !supplier[0][0]) throw new Error('Il registro fornitori è cambiato; prepara una nuova anteprima.');
  const offerIds = ready.map(target => target.offer_id).filter(Boolean);
  if (new Set(offerIds).size !== offerIds.length) throw new Error('ID offerta duplicato nella proposta: correggi il modulo prima di scrivere.');
  const sectorColumn: Record<string, number> = { FOOD: 3, BEVERAGE: 4, 'FRUTTA E VERDURA': 5, MATERIALI: 6 };
  for (const target of ready) {
    if (!target.tab || !target.nextRow || target.supplierId !== supplier[0][0]) throw new Error('Anteprima incompleta; prepara una nuova anteprima.');
    if (normalize(supplier[0][sectorColumn[target.tab]]) !== 'si') throw new Error('L’abilitazione del fornitore è cambiata; prepara una nuova anteprima.');
    const rows = tabs.get(target.tab) || [];
    const matches = rows.slice(1).filter(row => row[0] === target.sku && row[3] === target.supplierId);
    if (target.mode === 'update') {
      const live = rows[(target.row || 0) - 1];
      if (!live || live[0] !== target.sku || live[3] !== target.supplierId || live.some((value, col) => value !== target.snapshot?.[col])) throw new Error(`La riga ${target.cell} è cambiata: prepara una nuova anteprima.`);
      if (target.offer_id && matches.some(row => row[12] === target.offer_id && row !== live)) throw new Error(`ID offerta duplicato per ${target.sku}.`);
    } else if ((target.offer_id ? matches.some(row => row[12] === target.offer_id) : matches.length > 0) || !rows.some(row => row[0] === target.sku && row.every((value, col) => value === target.snapshot?.[col]))) throw new Error(`Il prodotto ${target.sku} è cambiato: prepara una nuova anteprima.`);
  }
  const headerRequests = [...new Set(ready.filter(target => target.offer_id).map(target => target.tab!))].filter(tab => !tabs.get(tab)?.[0]?.[12]).map(tab => ({ updateCells: { range: { sheetId: ids.get(tab)!, startRowIndex: 0, endRowIndex: 1, startColumnIndex: 12, endColumnIndex: 13 }, rows: [{ values: [gridValue(OFFER_HEADER, false)] }], fields: 'userEnteredValue' } }));
  const requests = ready.map(target => {
    const sheetId = ids.get(target.tab!)!;
    const next = target.nextRow!;
    if (target.mode === 'append') return { appendCells: { sheetId, rows: [{ values: next.slice(0, target.offer_id ? 13 : 12).map((value, col) => gridValue(value, col === 7 || col === 9)) }], fields: 'userEnteredValue' } };
    return { updateCells: { range: { sheetId, startRowIndex: target.row! - 1, endRowIndex: target.row, startColumnIndex: 5, endColumnIndex: target.offer_id ? 13 : 12 }, rows: [{ values: next.slice(5, target.offer_id ? 13 : 12).map((value, col) => gridValue(value, col === 2 || col === 4)) }], fields: 'userEnteredValue' } };
  });
  if (!requests.length) return;
  await fetcher(root + ':batchUpdate', token, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ requests: [...headerRequests, ...requests] }) });
}
