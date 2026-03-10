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

async function request<T>(path: string, options?: RequestInit): Promise<T> {
  let res: Response
  try {
    res = await fetch(`${BASE_URL}${path}`, {
      credentials: 'same-origin',
      headers: {
        'Content-Type': 'application/json',
        'ngrok-skip-browser-warning': 'true',
      },
      ...options,
    })
  } catch (err) {
    // TypeError = network failure (offline, DNS, etc.) — not an HTTP error
    if (err instanceof TypeError) {
      window.dispatchEvent(new Event('api-offline'))
    }
    throw err
  }

  // Successful network contact — device is online
  window.dispatchEvent(new Event('api-online'))

  if (!res.ok) {
    let message = `HTTP ${res.status}`
    try {
      const body = (await res.json()) as { detail?: string }
      if (body.detail) message = body.detail
    } catch {
      // ignore parse error
    }
    throw new ApiError(res.status, message)
  }

  return res.json() as Promise<T>
}

export const api = {
  get: <T>(path: string) => request<T>(path),
  post: <T>(path: string, body?: unknown) =>
    request<T>(path, { method: 'POST', body: body ? JSON.stringify(body) : undefined }),
}
