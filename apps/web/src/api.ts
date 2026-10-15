// Where the Tervik API lives. Empty means the dashboard's own origin: locally the
// dev server forwards /api to it. Set VITE_API_URL when building a dashboard that
// is hosted apart from the API (for example on Vercel, with the API on Railway).
export const API_URL = (import.meta.env.VITE_API_URL || '').trim().replace(/\/+$/, '');

const SESSION_KEY = 'tervik_session';
const GUEST_KEY = 'tervik_guest';

/** The account session: one signed in through Log in or Sign up is kept in this
 * browser until logging out; one pasted into Connection settings lasts for the tab. */
export function getSession() {
  try { return sessionStorage.getItem(SESSION_KEY) || localStorage.getItem(SESSION_KEY) || ''; } catch { return ''; }
}
export function saveSession(token: string, guest = false) {
  try {
    localStorage.setItem(SESSION_KEY, token); sessionStorage.removeItem(SESSION_KEY);
    if (guest) localStorage.setItem(GUEST_KEY, '1'); else localStorage.removeItem(GUEST_KEY);
  } catch { sessionStorage.setItem(SESSION_KEY, token); }
  window.dispatchEvent(new Event('tervik:session'));
}
export function clearSession() {
  try { localStorage.removeItem(SESSION_KEY); localStorage.removeItem(GUEST_KEY); } catch { /* storage blocked */ }
  sessionStorage.removeItem(SESSION_KEY);
}
/** Whether this browser is in a guest workspace rather than signed in to an account. */
export function isGuest() {
  try { return !!getSession() && localStorage.getItem(GUEST_KEY) === '1'; } catch { return false; }
}

let pendingGuest: Promise<boolean> | null = null;
/** Starts a private guest workspace, so a visitor can use the dashboard without
 * signing up. Requests that fail at the same moment share one guest. */
function startGuest() {
  pendingGuest ??= fetch(`${API_URL}/api/auth/guest`, { method: 'POST' })
    .then(response => response.ok ? response.json() : null)
    .then(data => { if (data?.session) saveSession(data.session, true); return !!data?.session; })
    .catch(() => false)
    .finally(() => { pendingGuest = null; });
  return pendingGuest;
}

/** Signs up or logs in, and returns the new session. Errors carry the reason in plain words. */
export async function authenticate(kind: 'signup' | 'login', body: { email: string; password: string; name?: string }): Promise<string> {
  let response: Response;
  try {
    response = await fetch(`${API_URL}/api/auth/${kind}`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) });
  } catch {
    throw new Error('Cannot reach Tervik. Check your connection and try again.');
  }
  const data = await response.json().catch(() => ({}));
  if (response.ok) return data.session as string;
  if (response.status === 401) throw new Error('Wrong email or password.');
  if (response.status === 409) throw new Error('An account with this email already exists. Log in instead.');
  if (response.status === 422) throw new Error(kind === 'signup' ? 'Enter a valid email and a password of at least 8 characters.' : 'Enter your email and password.');
  throw new Error(typeof data.detail === 'string' ? data.detail : `Request failed (${response.status}).`);
}

export async function request<T>(path: string, options: RequestInit = {}, retried = false): Promise<T> {
  const session = getSession();
  const token = session || sessionStorage.getItem('tervik_admin_token');
  const headers = new Headers(options.headers);
  if (options.body) headers.set('Content-Type', 'application/json');
  if (token) headers.set('Authorization', `Bearer ${token}`);
  let response: Response;
  try {
    response = await fetch(API_URL + path, { ...options, headers });
  } catch {
    throw new Error('Cannot reach Tervik. Start the API service and try again.');
  }
  if (!response.ok) {
    let message = `Request failed (${response.status}).`;
    try {
      const body = await response.json();
      if (typeof body.detail === 'string') message = body.detail;
      else if (typeof body.error === 'string') message = body.error;
    } catch { /* Some proxies return a non-JSON error body. */ }
    if (response.status === 401 && !sessionStorage.getItem('tervik_admin_token')) {
      // Not signed in, or a guest session the API no longer knows: carry on in a
      // guest workspace. A signed-in account whose session ended logs in again.
      if (!retried && (!session || isGuest() || getSession() !== session)) {
        if (getSession() !== session || await startGuest()) return request<T>(path, options, true);
      }
      clearSession();
      if (window.location.hash !== '#login') window.location.hash = 'login';
      message = 'Sign in to continue.';
    } else if (response.status === 401 || response.status === 403) {
      message = getSession()
        ? 'Access denied. Check your account access for this project.'
        : 'Access denied. Sign in or add your administrator token in connection settings.';
    } else if (response.status >= 500) {
      message = 'The API service is unavailable. Start it and try again.';
    }
    throw new Error(message);
  }
  return response.json() as Promise<T>;
}

export function query(params: Record<string, string | undefined>) {
  const search = new URLSearchParams();
  Object.entries(params).forEach(([key, value]) => {
    if (value !== undefined && value !== '') search.set(key, value);
  });
  return `?${search}`;
}
