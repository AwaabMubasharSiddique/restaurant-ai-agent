const API_URL = import.meta.env.VITE_API_URL || 'http://localhost:8000'
const TIMEOUT_MS = 25000

export class ApiError extends Error {
  constructor(message, { status = 0, retryAfter = null } = {}) {
    super(message)
    this.name = 'ApiError'
    this.status = status
    this.retryAfter = retryAfter
  }
}

export async function sendMessage(message, sessionId) {
  const controller = new AbortController()
  const timer = setTimeout(() => controller.abort(), TIMEOUT_MS)

  let response
  try {
    response = await fetch(`${API_URL}/chat`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ message, session_id: sessionId }),
      signal: controller.signal,
    })
  } catch (err) {
    // network failure or our own timeout abort — both look like "can't reach it"
    throw new ApiError(err.name === 'AbortError' ? 'timeout' : 'network', { status: 0 })
  } finally {
    clearTimeout(timer)
  }

  if (!response.ok) {
    let detail = ''
    try {
      detail = (await response.json())?.detail || ''
    } catch {
      /* non-JSON body */
    }
    const retryAfter = Number(response.headers.get('Retry-After')) || null
    throw new ApiError(detail || `status ${response.status}`, {
      status: response.status,
      retryAfter,
    })
  }

  return response.json()
}
