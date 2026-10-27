import assert from 'node:assert/strict';
import { prepareNormalizedSheet, writeNormalizedSheet } from '../src/components/normalizedSupplierSheet.ts';

const headers = ['ID_PRODOTTO', 'PRODOTTO', 'SOTTOCATEGORIA', 'ID_FORNITORE', 'FORNITORE', 'DICITURA_FORNITORE', 'MARCA', 'QUANTITA_CONFEZIONE', 'UNITA_MISURA', 'PREZZO_CONFEZIONE_EUR', 'DATA_PREZZO', 'NOTE'];
const supplierHeaders = ['ID_FORNITORE', 'FORNITORE', 'PARTITA_IVA', 'FOOD', 'BEVERAGE', 'FRUTTA_E_VERDURA', 'MATERIALI', 'NOTE'];
const food = [headers, ['P-001', 'GELATO', 'Varie', 'F-01', 'Fornitore CI', 'Gelato 2,5 kg', 'Marca CI', '2.5', 'KG', '15', '2026-10-01', '']];
const tabs = [food, [headers], [headers], [headers], [supplierHeaders, ['F-01', 'Fornitore CI', '', 'SI', '', '', '', '']]];
let written;
const fetcher = async (url, _token, init) => {
  if (url.endsWith(':batchUpdate')) { written = JSON.parse(init.body); return {}; }
  if (url.includes('values:batchGet')) return { valueRanges: tabs.map(values => ({ values })) };
  return { sheets: ['FOOD', 'BEVERAGE', 'FRUTTA E VERDURA', 'MATERIALI', 'FORNITORI'].map((title, sheetId) => ({ properties: { title, sheetId } })) };
};
const request = { supplier_name: 'Fornitore CI', validita_inviata_da: '2026-10-27', items: [{ id: 1, sku_interno: 'P-001', descrizione: 'GELATO', prezzo_inviato: '18.0000', unita_inviata: 'KG', brand_inviata: 'Marca CI', dicitura_inviata: 'Gelato 2,8 kg', quantita_inviata: '2.800', nota_fornitore: '' }] };
const root = 'https://sheets.googleapis.com/v4/spreadsheets/synthetic';
const preview = await prepareNormalizedSheet(root, 'synthetic-token', request, fetcher);
assert.equal(preview[0].status, 'ready');
assert.equal(preview[0].cell, "'FOOD'!F2:L2");
await writeNormalizedSheet(root, 'synthetic-token', request, preview, fetcher);
assert.equal(written.requests.length, 1);
assert.equal(written.requests[0].updateCells.rows[0].values[2].userEnteredValue.numberValue, 2.8);
food.push(['P-002', 'ACQUA', 'Varie', 'F-02', 'Altro fornitore', 'Acqua', 'Altra marca', '1', 'L', '2', '2026-10-01', 'Origine FOOD!3']);
const newQuote = { ...request, items: [{ ...request.items[0], id: 2, sku_interno: 'P-002', descrizione: 'ACQUA' }] };
const appendPreview = await prepareNormalizedSheet(root, 'synthetic-token', newQuote, fetcher);
assert.equal(appendPreview[0].mode, 'append');
await writeNormalizedSheet(root, 'synthetic-token', newQuote, appendPreview, fetcher);
assert.equal(written.requests[0].appendCells.rows[0].values[3].userEnteredValue.stringValue, 'F-01');
assert.equal(written.requests[0].appendCells.rows[0].values[11].userEnteredValue.stringValue, 'Origine FOOD!3 | Conferma fornitore Price Sentinel');
food[1][9] = '16';
await assert.rejects(() => writeNormalizedSheet(root, 'synthetic-token', request, preview, fetcher), /cambiata/);
console.log('PASS: normalized Sheet preview, package write and concurrent-change block');
