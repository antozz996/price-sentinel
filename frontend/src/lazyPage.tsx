import { Component, lazy, type ComponentType, type ErrorInfo, type ReactNode } from 'react';

const RELOAD_KEY = 'ps_reload_after_update';
const TAB_KEY = 'ps_active_tab';
const RELOAD_GUARD_MS = 30_000;

function readStorage(key: string): string | null {
  try {
    return sessionStorage.getItem(key);
  } catch {
    return null;
  }
}

function writeStorage(key: string, value: string): void {
  try {
    sessionStorage.setItem(key, value);
  } catch {
    // Without storage the guard below cannot work, so no automatic reload happens.
  }
}

function reloadedMoments(): boolean {
  return Date.now() - Number(readStorage(RELOAD_KEY) || 0) < RELOAD_GUARD_MS;
}

export function rememberActiveTab(tab: string): void {
  writeStorage(TAB_KEY, tab);
}

/** After an automatic reload, return to the section the user was opening. */
export function restoreTabAfterUpdate(): string | null {
  return reloadedMoments() ? readStorage(TAB_KEY) : null;
}

/**
 * A new release removes the files of the previous one, so a tab left open fails
 * when it opens a section. Reload once to pick up the new release. A second
 * failure, or no connection, reaches PageErrorBoundary instead of looping.
 */
export function lazyPage<T extends ComponentType<any>>(importer: () => Promise<{ default: T }>) {
  return lazy(() =>
    importer().catch((error: unknown) => {
      if (!navigator.onLine || reloadedMoments()) throw error;
      writeStorage(RELOAD_KEY, String(Date.now()));
      if (!reloadedMoments()) throw error;
      window.location.reload();
      return new Promise<never>(() => {});
    }),
  );
}

interface PageErrorBoundaryProps {
  children: ReactNode;
}

export class PageErrorBoundary extends Component<PageErrorBoundaryProps, { failed: boolean }> {
  state = { failed: false };

  static getDerivedStateFromError() {
    return { failed: true };
  }

  componentDidCatch(error: Error, info: ErrorInfo) {
    console.error('Errore di caricamento della sezione', error, info.componentStack);
  }

  render() {
    if (!this.state.failed) return this.props.children;
    return (
      <div role="alert" style={{ padding: '48px 24px', textAlign: 'center', color: 'var(--text-secondary, #cbd5e1)' }}>
        <h3 style={{ margin: '0 0 8px', color: 'white' }}>Impossibile aprire questa sezione</h3>
        <p style={{ margin: '0 0 16px' }}>Controlla la connessione e ricarica la pagina.</p>
        <button type="button" className="btn" onClick={() => window.location.reload()}>
          Ricarica la pagina
        </button>
      </div>
    );
  }
}
