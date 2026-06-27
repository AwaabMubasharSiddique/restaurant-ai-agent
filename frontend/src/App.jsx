import { useEffect, useRef, useState } from 'react'
import ChatWindow from './components/ChatWindow.jsx'
import { ApiError, sendMessage } from './api.js'

// Bump this when the stored shape changes so old/incoherent transcripts are dropped.
const TRANSCRIPT_KEY = 'transcript_v2'

function genId() {
  if (typeof crypto !== 'undefined' && crypto.randomUUID) return crypto.randomUUID()
  return `${Date.now()}-${Math.random().toString(16).slice(2)}`
}

function loadSessionId() {
  const existing = localStorage.getItem('session_id')
  if (existing) return existing
  const id = genId()
  localStorage.setItem('session_id', id)
  return id
}

const GREETING = {
  id: 'greeting',
  role: 'assistant',
  text:
    "Hi! 👋 Welcome to The Olive Branch. I can help with reservations, our menu, " +
    'hours & location, or placing an order. What can I do for you?',
}

function loadMessages() {
  try {
    const saved = JSON.parse(localStorage.getItem(TRANSCRIPT_KEY) || 'null')
    if (Array.isArray(saved) && saved.length) {
      // Drop a trailing user message that never got a reply (e.g. a refresh
      // mid-send), so we never restore an orphaned message with no response.
      const trimmed = saved[saved.length - 1]?.role === 'user' ? saved.slice(0, -1) : saved
      return trimmed.length ? trimmed : [GREETING]
    }
  } catch {
    /* ignore corrupt transcript */
  }
  return [GREETING]
}

function errorText(err) {
  if (err instanceof ApiError) {
    if (err.status === 429) {
      const wait = err.retryAfter ? `about ${err.retryAfter}s` : 'a moment'
      return `We're getting a lot of messages right now — please try again in ${wait}.`
    }
    if (err.status === 401) {
      return "This chat session isn't authorized. Please refresh the page."
    }
  }
  return "Sorry — I'm having trouble reaching the restaurant right now. Please try again in a moment."
}

export default function App() {
  const [messages, setMessages] = useState(loadMessages)
  const [loading, setLoading] = useState(false)
  const [connected, setConnected] = useState(true)
  const [awaitingHuman, setAwaitingHuman] = useState(false)
  const sessionId = useRef(loadSessionId())

  // Persist the transcript faithfully so a reload restores a coherent conversation
  // (a failed turn keeps its error reply + Retry button rather than leaving an
  // orphaned user message). Errors self-clear on the next send.
  useEffect(() => {
    localStorage.setItem(TRANSCRIPT_KEY, JSON.stringify(messages))
  }, [messages])

  function startNewConversation() {
    const id = genId()
    sessionId.current = id
    localStorage.setItem('session_id', id)
    localStorage.removeItem(TRANSCRIPT_KEY)
    setMessages([GREETING])
    setAwaitingHuman(false)
    setConnected(true)
  }

  async function handleSend(text) {
    // Drop any prior error bubble, then add the user's message.
    setMessages((prev) => [...prev.filter((m) => !m.error), { id: genId(), role: 'user', text }])
    setLoading(true)

    try {
      const data = await sendMessage(text, sessionId.current)
      if (data.session_id) {
        sessionId.current = data.session_id
        localStorage.setItem('session_id', data.session_id)
      }
      setConnected(true)
      if (data.needs_human) setAwaitingHuman(true)
      setMessages((prev) => [
        ...prev,
        {
          id: genId(),
          role: 'assistant',
          text: data.response,
          needsHuman: data.needs_human,
        },
      ])
    } catch (err) {
      if (!(err instanceof ApiError) || err.status === 0 || err.status >= 500) {
        setConnected(false)
      }
      setMessages((prev) => [
        ...prev,
        { id: genId(), role: 'assistant', text: errorText(err), error: true, retryText: text },
      ])
    } finally {
      setLoading(false)
    }
  }

  return (
    <ChatWindow
      messages={messages}
      loading={loading}
      connected={connected}
      awaitingHuman={awaitingHuman}
      onSend={handleSend}
      onRetry={handleSend}
      onNewConversation={startNewConversation}
    />
  )
}
