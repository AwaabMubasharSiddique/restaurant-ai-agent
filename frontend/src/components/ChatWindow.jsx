import MessageList from './MessageList.jsx'
import ChatInput from './ChatInput.jsx'

export default function ChatWindow({
  messages,
  loading,
  connected,
  awaitingHuman,
  onSend,
  onRetry,
  onNewConversation,
}) {
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
        <div className="header-actions">
          <span className={`status ${connected ? '' : 'offline'}`}>
            <span className="status-dot" /> {connected ? 'Online' : 'Reconnecting…'}
          </span>
          <button type="button" className="new-chat" onClick={onNewConversation}>
            New chat
          </button>
        </div>
      </header>

      {awaitingHuman && (
        <div className="handoff-banner" role="status">
          👤 A team member has been looped in and will follow up with you shortly.
        </div>
      )}

      <MessageList messages={messages} loading={loading} onRetry={onRetry} />
      <ChatInput onSend={onSend} disabled={loading} />
    </div>
  )
}
