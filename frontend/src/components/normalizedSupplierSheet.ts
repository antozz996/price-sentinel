/** ID-based review of supplier offers against the normalized category Sheet. */
const TABS = ['FOOD', 'BEVERAGE', 'FRUTTA E VERDURA', 'MATERIALI'] as const;
const HEADERS = ['ID_PRODOTTO', 'PRODOTTO', 'SOTTOCATEGORIA', 'ID_FORNITORE', 'FORNITORE', 'DICITURA_FORNITORE', 'MARCA', 'QUANTITA_CONFEZIONE', 'UNITA_MISURA', 'PREZZO_CONFEZIONE_EUR', 'DATA_PREZZO', 'NOTE'];
const SUPPLIER_HEADERS = ['ID_FORNITORE', 'FORNITORE', 'PARTITA_IVA', 'FOOD', 'BEVERAGE', 'FRUTTA_E_VERDURA', 'MATERIALI', 'NOTE'];
const normalize = (value: unknown) => String(value ?? '').normalize('NFD').replace(/[\u0300-\u036f]/g, '').toLocaleLowerCase().replace(/[^a-z0-9]+/g, ' ').trim().replace(/\s+/g, ' ');
const cellText = (value: unknown) => String(value ?? '').trim();
const quote = (tab: string) => "'" + tab.replace(/'/g, "''") + "'";

export type SheetOfferTarget = {
  item_id: number; product: string; sku: string; status: 'ready' | 'already' | 'blocked' | 'not_trattato' | 'written';
  reason: string; tab?: string; cell?: string; current: string; offered: string; unit: string;
  mode?: 'update' | 'append'; row?: number; supplierId?: string; snapshot?: string[]; nextRow?: string[];
};
type Offer = { id: number; sku_interno: string; descrizione: string; prezzo_inviato?: string | null; unita_inviata?: string | null; brand_inviata?: string | null; dicitura_inviata?: string | null; quantita_inviata?: string | null; nota_fornitore?: string | null; non_trattato?: boolean };
type Request = { supplier_name: string; validita_inviata_da?: string | null; items: Offer[] };
type Fetcher = (url: string, token: string, init?: RequestInit) => Promise<any>;

async function snapshot(root: string, token: string, fetcher: Fetcher) {
  const meta = await fetcher(root + '?fields=' + encodeURIComponent('sheets.properties(sheetId,title)'), token);
  const ids = new Map<string, number>((meta.sheets || []).map((sheet: any) => [sheet.properties.title, sheet.properties.sheetId]));
  for (const name of [...TABS, 'FORNITORI']) if (!ids.has(name)) throw new Error(`Nel nuovo Sheet manca la scheda ${name}.`);
  const params = new URLSearchParams();
  for (const name of TABS) params.append('ranges', `${quote(name)}!A1:L5000`);
  params.append('ranges', "'FORNITORI'!A1:H5000");
  params.set('valueRenderOption', 'FORMULA');
  const read = await fetcher(root + '/values:batchGet?' + params, token);
  if (read.valueRanges?.length !== 5) throw new Error('Lettura incompleta del nuovo Sheet.');
  const tabs = new Map<string, string[][]>();
  [...TABS, 'FORNITORI'].forEach((name, i) => tabs.set(name, (read.valueRanges[i].values || []).map((row: unknown[]) => Array.from({ length: name === 'FORNITORI' ? 8 : 12 }, (_, col) => cellText(row[col])))));
  for (const name of TABS) if ((tabs.get(name)?.length || 0) >= 5000) throw new Error(`La scheda ${name} raggiunge il limite di lettura: nessuna modifica è consentita.`);
  for (const name of TABS) if (HEADERS.some((header, col) => tabs.get(name)?.[0]?.[col] !== header)) throw new Error(`Intestazioni diverse dal nuovo formato nella scheda ${name}.`);
  if (SUPPLIER_HEADERS.some((header, col) => tabs.get('FORNITORI')?.[0]?.[col] !== header)) throw new Error('Intestazioni diverse dal nuovo formato nella scheda FORNITORI.');
  return { tabs, ids };
}

export async function prepareNormalizedSheet(root: string, token: string, request: Request, fetcher: Fetcher): Promise<SheetOfferTarget[]> {
  const { tabs } = await snapshot(root, token, fetcher);
  const suppliers = (tabs.get('FORNITORI') || []).slice(1).filter(row => normalize(row[1]) === normalize(request.supplier_name));
  if (suppliers.length !== 1 || !suppliers[0][0]) throw new Error('Il fornitore non ha una corrispondenza univoca per nome e ID nella scheda FORNITORI. Completa il registro prima di aggiornare le offerte.');
  const supplierId = suppliers[0][0];
  return request.items.map(item => {
    const base = { item_id: item.id, product: item.descrizione, sku: item.sku_interno, current: '', offered: item.prezzo_inviato || '', unit: item.unita_inviata || '' };
    if (item.non_trattato) return { ...base, status: 'not_trattato', reason: 'Il fornitore non tratta questo prodotto.' };
    if (!item.prezzo_inviato || !item.unita_inviata || !item.brand_inviata || !item.dicitura_inviata || !item.quantita_inviata || !request.validita_inviata_da) return { ...base, status: 'blocked', reason: 'Risposta incompleta: servono dicitura, marca, quantità, unità, prezzo e data.' };
    const productRows: Array<{ tab: string; row: number; cells: string[] }> = [];
    const matchingRows: typeof productRows = [];
    for (const tab of TABS) (tabs.get(tab) || []).slice(1).forEach((cells, index) => {
      if (cells[0] === item.sku_interno) {
        const entry = { tab, row: index + 2, cells };
        productRows.push(entry);
        if (cells[3] === supplierId) matchingRows.push(entry);
      }
    });
    if (matchingRows.length > 1 || new Set(productRows.map(row => row.tab)).size > 1 || new Set(productRows.map(row => normalize(row.cells[1]) + '|' + normalize(row.cells[2]))).size > 1) return { ...base, status: 'blocked', reason: 'ID prodotto ambiguo o presente in più categorie: verifica manuale.' };
    if (!productRows.length) return { ...base, status: 'blocked', reason: 'ID prodotto assente dal nuovo Sheet: aggiungi prima il prodotto al catalogo.' };
    const existing = matchingRows[0];
    const tab = productRows[0].tab;
    const sectorColumn: Record<string, number> = { FOOD: 3, BEVERAGE: 4, 'FRUTTA E VERDURA': 5, MATERIALI: 6 };
    if (normalize(suppliers[0][sectorColumn[tab]]) !== 'si') return { ...base, status: 'blocked', reason: `Il fornitore non è abilitato per ${tab} nel registro FORNITORI.` };
    const sourceNote = (existing?.cells[11] || productRows[0].cells[11] || '').replace(/\s*\|\s*Conferma fornitore Price Sentinel(?:\s*\|\s*Risposta fornitore:.*)?$/, '');
    const confirmation = 'Conferma fornitore Price Sentinel';
    const nextNote = `${sourceNote}${sourceNote ? ' | ' : ''}${confirmation}${item.nota_fornitore ? ` | Risposta fornitore: ${item.nota_fornitore}` : ''}`;
    const values = [item.dicitura_inviata, item.brand_inviata, item.quantita_inviata, item.unita_inviata, item.prezzo_inviato, request.validita_inviata_da, nextNote];
    if (existing && existing.cells.slice(5).some(cell => cell.startsWith('='))) return { ...base, status: 'blocked', reason: 'La riga contiene una formula nelle colonne offerta; non la sovrascrivo.' };
    const nextRow = existing ? [...existing.cells.slice(0, 5), ...values] : [item.sku_interno, productRows[0].cells[1], productRows[0].cells[2], supplierId, suppliers[0][1], ...values];
    const snapshotRow = existing?.cells || productRows[0].cells;
    const already = Boolean(existing && nextRow.every((value, col) => cellText(value) === cellText(snapshotRow[col])));
    return { ...base, status: already ? 'already' : 'ready', reason: already ? 'Offerta già presente.' : existing ? 'Riga identificata per ID prodotto e fornitore.' : 'Nuova riga per questo fornitore.', tab, cell: existing ? `${quote(tab)}!F${existing.row}:L${existing.row}` : `${quote(tab)}!nuova riga`, current: existing?.cells[9] || '', mode: existing ? 'update' : 'append', row: existing?.row, supplierId, snapshot: snapshotRow, nextRow };
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
  const sectorColumn: Record<string, number> = { FOOD: 3, BEVERAGE: 4, 'FRUTTA E VERDURA': 5, MATERIALI: 6 };
  for (const target of ready) {
    if (!target.tab || !target.nextRow || target.supplierId !== supplier[0][0]) throw new Error('Anteprima incompleta; prepara una nuova anteprima.');
    if (normalize(supplier[0][sectorColumn[target.tab]]) !== 'si') throw new Error('L’abilitazione del fornitore è cambiata; prepara una nuova anteprima.');
    const rows = tabs.get(target.tab) || [];
    const matches = rows.slice(1).filter(row => row[0] === target.sku && row[3] === target.supplierId);
    if (target.mode === 'update') {
      const live = rows[(target.row || 0) - 1];
      if (matches.length !== 1 || !live || live.some((value, col) => value !== target.snapshot?.[col])) throw new Error(`La riga ${target.cell} è cambiata: prepara una nuova anteprima.`);
    } else if (matches.length || !rows.some(row => row[0] === target.sku && row.every((value, col) => value === target.snapshot?.[col]))) throw new Error(`Il prodotto ${target.sku} è cambiato: prepara una nuova anteprima.`);
  }
  const requests = ready.map(target => {
    const sheetId = ids.get(target.tab!)!;
    const next = target.nextRow!;
    if (target.mode === 'append') return { appendCells: { sheetId, rows: [{ values: next.map((value, col) => gridValue(value, col === 7 || col === 9)) }], fields: 'userEnteredValue' } };
    return { updateCells: { range: { sheetId, startRowIndex: target.row! - 1, endRowIndex: target.row, startColumnIndex: 5, endColumnIndex: 12 }, rows: [{ values: next.slice(5).map((value, col) => gridValue(value, col === 2 || col === 4)) }], fields: 'userEnteredValue' } };
  });
  if (!requests.length) return;
  await fetcher(root + ':batchUpdate', token, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ requests }) });
}
