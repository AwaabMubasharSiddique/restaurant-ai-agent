// Backend base URL comes from an env var (VITE_API_URL), never hard-coded.
const API_URL = import.meta.env.VITE_API_URL || 'http://localhost:8000'

/**
 * Send one message to the backend. We pass session_id so the server can keep
 * per-conversation memory; the first call may send null and the server returns
 * a fresh id to reuse on subsequent calls.
 */
export async function sendMessage(message, sessionId) {
  const response = await fetch(`${API_URL}/chat`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ message, session_id: sessionId }),
  })

  if (!response.ok) {
    throw new Error(`Server responded with ${response.status}`)
  }
  return response.json() // { session_id, response, intent, needs_human }
}
