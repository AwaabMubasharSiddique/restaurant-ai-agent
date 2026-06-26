import MessageList from './MessageList.jsx'
import ChatInput from './ChatInput.jsx'

export default function ChatWindow({ messages, loading, onSend }) {
  return (
    <div className="chat-app">
      <header className="chat-header">
        <div className="brand">
          <span className="logo" aria-hidden="true">🫒</span>
          <div className="brand-text">
            <h1>The Olive Branch</h1>
            <p>Customer Service Assistant</p>
          </div>
        </div>
        <span className="status">
          <span className="status-dot" /> Online
        </span>
      </header>

      <MessageList messages={messages} loading={loading} />
      <ChatInput onSend={onSend} disabled={loading} />
    </div>
  )
}
