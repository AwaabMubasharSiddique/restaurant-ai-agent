export default function Message({ role, text, needsHuman, error, retryText, onRetry }) {
  const isUser = role === 'user'
  return (
    <div className={`message ${isUser ? 'user' : 'assistant'}`}>
      {!isUser && (
        <div className="avatar" aria-hidden="true">🫒</div>
      )}
      <div className="bubble-wrap">
        <div className={`bubble ${error ? 'error' : ''}`}>{text}</div>
        {error && retryText && onRetry && (
          <button type="button" className="retry" onClick={() => onRetry(retryText)}>
            ↻ Retry
          </button>
        )}
        {needsHuman && (
          <div className="handoff-note">
            👤 A team member will follow up with you shortly.
          </div>
        )}
      </div>
    </div>
  )
}
