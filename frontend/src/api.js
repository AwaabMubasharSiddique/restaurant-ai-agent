const API_URL = import.meta.env.VITE_API_URL || 'http://localhost:8000'

export async function sendMessage(message, sessionId) {
  const response = await fetch(`${API_URL}/chat`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ message, session_id: sessionId }),
  })

  if (!response.ok) {
    throw new Error(`Server responded with ${response.status}`)
  }
  return response.json()
}
