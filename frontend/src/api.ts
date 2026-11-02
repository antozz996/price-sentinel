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

const configuredApiBase = ((import.meta as any).env?.VITE_API_BASE as string | undefined)?.trim();

// Same-origin is the safe default for local and staging. Production hosting
// may set VITE_API_BASE to the reviewed public API origin at build time.
export const API_BASE = (configuredApiBase || '/api/v1').replace(/\/+$/, '');

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

let sessionRefreshInFlight: Promise<boolean> | null = null;

function tokenSecondsRemaining(token: string): number {
  try {
    const encoded = token.split('.')[1].replace(/-/g, '+').replace(/_/g, '/');
    const padded = encoded.padEnd(Math.ceil(encoded.length / 4) * 4, '=');
    const payload = JSON.parse(atob(padded));
    return typeof payload.exp === 'number' ? payload.exp - Date.now() / 1000 : 0;
  } catch {
    return 0;
  }
}

/** Keep an actively used session alive without storing the user's password. */
export function refreshAuthSession(): Promise<boolean> {
  const token = localStorage.getItem('token');
  if (!token) return Promise.resolve(false);

  // Refresh only in the last 15 minutes of the 30-minute JWT lifetime.
  // A five-minute caller interval leaves ample margin without API noise.
  if (tokenSecondsRemaining(token) > 15 * 60) return Promise.resolve(true);
  if (sessionRefreshInFlight) return sessionRefreshInFlight;

  sessionRefreshInFlight = fetch(`${API_BASE}/auth/refresh`, {
    method: 'POST',
    headers: { Authorization: `Bearer ${token}` },
  })
    .then(async response => {
      if (!response.ok) {
        if (response.status === 401) {
          localStorage.removeItem('token');
          window.dispatchEvent(new Event('unauthorized'));
        }
        return false;
      }
      const data = await response.json();
      if (!data?.access_token) return false;
      localStorage.setItem('token', data.access_token);
      return true;
    })
    .catch(() => false)
    .finally(() => {
      sessionRefreshInFlight = null;
    });

  return sessionRefreshInFlight;
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
  if (typeof FormData !== 'undefined' && options.body instanceof FormData) {
    delete headers['Content-Type'];
  }

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
