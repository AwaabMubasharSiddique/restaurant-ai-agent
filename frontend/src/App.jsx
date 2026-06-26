import { useRef, useState } from 'react'
import ChatWindow from './components/ChatWindow.jsx'
import { sendMessage } from './api.js'

// Persist the session id so a page refresh continues the same conversation.
// crypto.randomUUID only exists in secure contexts (https / localhost); if it's
// unavailable we start with null and adopt the id the server mints on the first
// reply.
function loadSessionId() {
  const existing = localStorage.getItem('session_id')
  if (existing) return existing
  if (typeof crypto !== 'undefined' && crypto.randomUUID) {
    const id = crypto.randomUUID()
    localStorage.setItem('session_id', id)
    return id
  }
  return null
}

const GREETING = {
  role: 'assistant',
  text:
    "Hi! 👋 Welcome to The Olive Branch. I can help with reservations, our menu, " +
    'hours & location, or placing an order. What can I do for you?',
  needsHuman: false,
}

export default function App() {
  const [messages, setMessages] = useState([GREETING])
  const [loading, setLoading] = useState(false)
  const sessionId = useRef(loadSessionId())

  async function handleSend(text) {
    // Optimistically show the user's message.
    setMessages((prev) => [...prev, { role: 'user', text }])
    setLoading(true)

    try {
      const data = await sendMessage(text, sessionId.current)
      // The server may mint a session id on the first turn — adopt it.
      if (data.session_id) {
        sessionId.current = data.session_id
        localStorage.setItem('session_id', data.session_id)
      }
      setMessages((prev) => [
        ...prev,
        {
          role: 'assistant',
          text: data.response,
          intent: data.intent,
          needsHuman: data.needs_human,
        },
      ])
    } catch (err) {
      setMessages((prev) => [
        ...prev,
        {
          role: 'assistant',
          text:
            "Sorry — I'm having trouble reaching the restaurant right now. " +
            'Please try again in a moment.',
          error: true,
        },
      ])
    } finally {
      setLoading(false)
    }
  }

  return <ChatWindow messages={messages} loading={loading} onSend={handleSend} />
}
