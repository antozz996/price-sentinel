export interface Anomalia {
  id: number;
  riga_fattura_id: number;
  delta_prezzo: number;
  delta_totale: number;
  prezzo_listino_snapshot: number;
  prezzo_fatturato_snapshot: number;
  stato_validazione: string;
  nota_manager?: string;
  created_at: string;
  fornitore_id?: number;
  codice_fornitore?: string;
  quantita?: number;
  descrizione_orig?: string;
  sku_interno?: string;
  fornitore_nome?: string;
}

export const API_BASE = '/api/v1';

export function getHeaders(customHeaders: Record<string, string> = {}): Record<string, string> {
  const token = localStorage.getItem('token');
  const headers: Record<string, string> = {
    'Content-Type': 'application/json',
    ...customHeaders,
  };

  if (token) {
    headers['Authorization'] = `Bearer ${token}`;
  }

  // bypass-tunnel-reminder strictly in DEV mode
  if ((import.meta as any).env?.DEV) {
    headers['bypass-tunnel-reminder'] = 'true';
  }

  return headers;
}

function formatApiErrorDetail(value: unknown): string {
  if (typeof value === 'string') return value;
  if (Array.isArray(value)) {
    const messages = value.map(item => {
      if (item && typeof item === 'object') {
        const entry = item as Record<string, unknown>;
        const message = entry.msg ?? entry.message ?? entry.detail;
        const location = Array.isArray(entry.loc) ? entry.loc.filter(Boolean).join('.') : '';
        if (typeof message === 'string') return location ? `${location}: ${message}` : message;
      }
      return formatApiErrorDetail(item);
    }).filter(Boolean);
    return messages.join('; ');
  }
  if (value && typeof value === 'object') {
    const entry = value as Record<string, unknown>;
    for (const key of ['message', 'detail', 'error', 'msg']) {
      if (entry[key] !== undefined && entry[key] !== value) {
        const message = formatApiErrorDetail(entry[key]);
        if (message) return message;
      }
    }
    try {
      return JSON.stringify(value);
    } catch {
      return 'Errore API con dettagli non leggibili.';
    }
  }
  return value == null ? '' : String(value);
}

// Funzione base per gestire le chiamate per bypassare Axios temporaneamente
export async function fetchWithAuth(url: string, options: RequestInit = {}) {
  const headers = getHeaders(options.headers as Record<string, string>);

  const response = await fetch(`${API_BASE}${url}`, {
    ...options,
    headers,
  });

  if (response.status === 401) {
    localStorage.removeItem('token');
    window.dispatchEvent(new Event('unauthorized'));
    throw new Error(`Sessione scaduta o non autorizzata (401)`);
  }

  if (!response.ok) {
    let detail = '';
    try {
      const payload = await response.json();
      detail = formatApiErrorDetail(payload?.detail ?? payload?.error);
    } catch {
      detail = '';
    }
    throw new Error(
      detail || `API Error: ${response.status} ${response.statusText}`,
    );
  }

  if (response.status === 204) {
    return null;
  }

  return response.json();
}

export const AnomalieAPI = {
  // Lista tutte le anomalie (es: per il manager della p.iva collegata)
  list: async (stato?: string): Promise<Anomalia[]> => {
    const query = stato ? `?stato=${stato}` : '';
    return fetchWithAuth(`/anomalie/${query}`);
  },

  // Azione da parte del Manager
  azioneManager: async (id: number, azione: 'segnala' | 'accetta' | 'proponi_aggiornamento' | 'parcheggia', nota?: string) => {
    return fetchWithAuth(`/anomalie/${id}/azione`, {
      method: 'POST',
      body: JSON.stringify({ azione, nota })
    });
  }
};
