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
}

export const API_BASE = '/api/v1';

// Funzione base per gestire le chiamate per bypassare Axios temporaneamente
export async function fetchWithAuth(url: string, options: RequestInit = {}) {
  const token = localStorage.getItem('token');
  
  const headers: Record<string, string> = {
    'Content-Type': 'application/json',
    'bypass-tunnel-reminder': 'true', // Essenziale per Localtunnel
    ...(options.headers as Record<string, string> || {}),
  };

  if (token) {
    headers['Authorization'] = `Bearer ${token}`;
  }

  const response = await fetch(`${API_BASE}${url}`, {
    ...options,
    headers,
  });

  if (!response.ok) {
    throw new Error(`API Error: ${response.status} ${response.statusText}`);
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
