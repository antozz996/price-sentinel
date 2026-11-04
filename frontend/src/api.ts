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

const REFRESH_TOKEN_KEY = 'refresh_token';

/** Save the tokens returned by login, refresh or a password change. */
export function storeSession(data: { access_token: string; refresh_token?: string | null }): void {
  localStorage.setItem('token', data.access_token);
  if (data.refresh_token) localStorage.setItem(REFRESH_TOKEN_KEY, data.refresh_token);
}

export function clearSession(): void {
  localStorage.removeItem('token');
  localStorage.removeItem(REFRESH_TOKEN_KEY);
}

/** End the session on the server too. Local tokens are removed even when offline. */
export async function logoutSession(): Promise<void> {
  const token = localStorage.getItem('token');
  const refreshToken = localStorage.getItem(REFRESH_TOKEN_KEY);
  clearSession();
  if (!token && !refreshToken) return;
  try {
    await fetch(`${API_BASE}/auth/logout`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        ...(token ? { Authorization: `Bearer ${token}` } : {}),
      },
      body: JSON.stringify({ refresh_token: refreshToken }),
    });
  } catch {
    // Without network the refresh token cannot be revoked, but it is gone from this browser.
  }
}

/**
 * Keep the session alive without storing the user's password.
 * The 7-day limit lives in the refresh token, so a tab left idle or offline
 * for more than 30 minutes recovers on its next request.
 */
export function refreshAuthSession(force = false): Promise<boolean> {
  const token = localStorage.getItem('token');
  const refreshToken = localStorage.getItem(REFRESH_TOKEN_KEY);
  if (!token && !refreshToken) return Promise.resolve(false);

  // Refresh only in the last 15 minutes of the 30-minute JWT lifetime.
  // A five-minute caller interval leaves ample margin without API noise.
  if (!force && token && tokenSecondsRemaining(token) > 15 * 60) return Promise.resolve(true);
  if (sessionRefreshInFlight) return sessionRefreshInFlight;

  sessionRefreshInFlight = fetch(`${API_BASE}/auth/refresh`, {
    method: 'POST',
    headers: refreshToken
      ? { 'Content-Type': 'application/json' }
      : { Authorization: `Bearer ${token}` },
    body: refreshToken ? JSON.stringify({ refresh_token: refreshToken }) : undefined,
  })
    .then(async response => {
      if (!response.ok) {
        if (response.status === 401) {
          clearSession();
          window.dispatchEvent(new Event('unauthorized'));
        }
        return false;
      }
      const data = await response.json();
      if (!data?.access_token) return false;
      storeSession(data);
      return true;
    })
    .catch(() => false)
    .finally(() => {
      sessionRefreshInFlight = null;
    });

  return sessionRefreshInFlight;
}

/**
 * Most screens call fetch directly with getHeaders(), so an expired access token
 * is recovered here once for all of them: renew, then repeat the same request.
 */
function installSessionRecovery(): void {
  if (typeof window === 'undefined') return;
  const nativeFetch = window.fetch.bind(window);

  window.fetch = async (input: RequestInfo | URL, init?: RequestInit): Promise<Response> => {
    const response = await nativeFetch(input, init);
    if (response.status !== 401 || typeof input !== 'string') return response;
    if (!input.startsWith(API_BASE) || input.startsWith(`${API_BASE}/auth/`)) return response;

    const headers = new Headers(init?.headers);
    if (!headers.has('Authorization') || !localStorage.getItem(REFRESH_TOKEN_KEY)) return response;

    if (!(await refreshAuthSession(true))) {
      // The refresh token survives only a network failure: that must not end the session.
      if (localStorage.getItem(REFRESH_TOKEN_KEY)) throw new TypeError('Connessione non disponibile');
      return response;
    }
    headers.set('Authorization', `Bearer ${localStorage.getItem('token')}`);
    return nativeFetch(input, { ...init, headers });
  };
}

installSessionRecovery();

// Any screen can end the session on a final 401: the refresh token must go with it.
if (typeof window !== 'undefined') {
  window.addEventListener('unauthorized', () => localStorage.removeItem(REFRESH_TOKEN_KEY));
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
