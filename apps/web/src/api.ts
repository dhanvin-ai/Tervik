export async function request<T>(path: string, options: RequestInit = {}): Promise<T> {
  const session = sessionStorage.getItem('tervik_session');
  const token = session || sessionStorage.getItem('tervik_admin_token');
  const headers = new Headers(options.headers);
  if (options.body) headers.set('Content-Type', 'application/json');
  if (token) headers.set('Authorization', `Bearer ${token}`);
  let response: Response;
  try {
    response = await fetch(path, { ...options, headers });
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
    if (response.status === 401 || response.status === 403) {
      message = sessionStorage.getItem('tervik_session')
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
