import { useEffect, useRef } from 'react'
import Message from './Message.jsx'

export default function MessageList({ messages, loading }) {
  const bottomRef = useRef(null)

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages, loading])

  return (
    <div className="message-list">
      {messages.map((message, index) => (
        <Message key={index} {...message} />
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
