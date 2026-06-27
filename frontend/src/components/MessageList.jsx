import { useEffect, useLayoutEffect, useRef } from 'react'
import Message from './Message.jsx'

export default function MessageList({ messages, loading, onRetry }) {
  const containerRef = useRef(null)
  const bottomRef = useRef(null)
  const nearBottomRef = useRef(true)

  // Track whether the user is reading at the bottom, so we don't yank them down
  // while they're scrolled up reviewing earlier messages.
  function onScroll() {
    const el = containerRef.current
    if (!el) return
    nearBottomRef.current = el.scrollHeight - el.scrollTop - el.clientHeight < 80
  }

  useLayoutEffect(() => {
    if (nearBottomRef.current) {
      bottomRef.current?.scrollIntoView({ behavior: 'smooth' })
    }
  }, [messages, loading])

  useEffect(() => {
    onScroll()
  }, [])

  return (
    <div
      className="message-list"
      ref={containerRef}
      onScroll={onScroll}
      role="log"
      aria-live="polite"
    >
      {messages.map((message) => (
        <Message key={message.id} {...message} onRetry={onRetry} />
      ))}

      {loading && (
        <div className="message assistant">
          <div className="avatar" aria-hidden="true">🫒</div>
          <div className="bubble typing" aria-label="Assistant is typing">
            <span />
            <span />
            <span />
          </div>
        </div>
      )}

      <div ref={bottomRef} />
    </div>
  )
}
