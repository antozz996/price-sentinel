export const SUPPLIER_UNIT_OPTIONS = [
  ['KG', 'Chilogrammi (KG)'],
  ['G', 'Grammi (G)'],
  ['L', 'Litri (L)'],
  ['CL', 'Centilitri (CL)'],
  ['ML', 'Millilitri (ML)'],
  ['PZ', 'Pezzi (PZ)'],
  ['BT', 'Bottiglie (BT)'],
  ['CF', 'Confezioni (CF)'],
  ['CT', 'Cartoni (CT)'],
  ['SC', 'Sacchi (SC)'],
  ['BX', 'Box (BX)'],
  ['CONF', 'Confezione generica (CONF)'],
] as const;

export const normalizeSupplierUnit = (value?: string | null) => {
  const normalized = (value || '').trim().toUpperCase();
  return SUPPLIER_UNIT_OPTIONS.some(([code]) => code === normalized) ? normalized : '';
};
