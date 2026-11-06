const BASE_URL = (import.meta.env.VITE_API_URL as string | undefined) ?? ''

export class ApiError extends Error {
  constructor(
    public status: number,
    message: string,
  ) {
    super(message)
    this.name = 'ApiError'
  }
}

/**
 * Normalise a FastAPI `detail` to a string. HTTPException sends a string;
 * 422 validation errors send a list of `{loc, msg, type}` objects.
 */
export function formatDetail(detail: unknown): string | null {
  if (typeof detail === 'string') return detail || null
  if (Array.isArray(detail)) {
    const msgs = detail
      .map((d) =>
        d && typeof d === 'object' && 'msg' in d ? String((d as { msg: unknown }).msg) : null,
      )
      .filter((m): m is string => !!m)
    return msgs.length ? msgs.join('; ') : null
  }
  return null
}

// Module-level token store — set by AuthContext after login.
let _authToken: string | null = null

export function setAuthToken(token: string | null) {
  _authToken = token
}

// Only mark offline after 2 consecutive network-level failures to avoid
// false positives from a single slow/dropped request (e.g. during sync).
let consecutiveFailures = 0

async function request<T>(path: string, options?: RequestInit): Promise<T> {
  // Do NOT set Content-Type for FormData — the browser must set it with the multipart boundary.
  const isFormData = options?.body instanceof FormData
  const headers = new Headers(options?.headers)
  if (!isFormData && !headers.has('Content-Type')) headers.set('Content-Type', 'application/json')
  headers.set('ngrok-skip-browser-warning', 'true')
  if (_authToken) {
    headers.set('Authorization', `Bearer ${_authToken}`)
  }

  let res: Response
  try {
    res = await fetch(`${BASE_URL}${path}`, {
      credentials: 'same-origin',
      ...options,
      headers,
    })
  } catch (err) {
    // TypeError = network failure (offline, DNS, etc.) — not an HTTP error
    if (err instanceof TypeError) {
      consecutiveFailures++
      if (consecutiveFailures >= 2) {
        window.dispatchEvent(new Event('api-offline'))
      }
    }
    throw err
  }

  // Successful network contact — device is online
  consecutiveFailures = 0
  window.dispatchEvent(new Event('api-online'))

  if (res.status === 401) {
    // Notify AuthContext to log out and redirect to /login
    window.dispatchEvent(new Event('auth-error'))
    throw new ApiError(401, 'Session expired. Please sign in again.')
  }

  if (res.status === 204) {
    // 204 has no body. Endpoints that can return it must declare `T | null`.
    return null as T
  }

  if (!res.ok) {
    let message = `HTTP ${res.status}`
    try {
      const body = (await res.json()) as { detail?: unknown }
      const detail = formatDetail(body.detail)
      if (detail) message = detail
    } catch {
      // ignore parse error
    }
    throw new ApiError(res.status, message)
  }

  return res.json() as Promise<T>
}

export const api = {
  get: <T>(path: string, signal?: AbortSignal) => request<T>(path, { signal }),
  post: <T>(path: string, body?: unknown) =>
    request<T>(path, { method: 'POST', body: body !== undefined ? JSON.stringify(body) : undefined }),
  /** Upload multipart/form-data (e.g. CSV file upload). */
  postForm: <T>(path: string, form: FormData) =>
    request<T>(path, { method: 'POST', body: form }),
  delete: <T = void>(path: string) =>
    request<T>(path, { method: 'DELETE' }),
  /** Download a file — returns a Blob (bypasses JSON parsing). */
  download: async (path: string): Promise<Blob> => {
    const headers: Record<string, string> = { 'ngrok-skip-browser-warning': 'true' }
    if (_authToken) headers['Authorization'] = `Bearer ${_authToken}`
    const res = await fetch(`${BASE_URL}${path}`, { credentials: 'same-origin', headers })
    if (!res.ok) throw new ApiError(res.status, `HTTP ${res.status}`)
    return res.blob()
  },
}
