export default function Message({ role, text, needsHuman, error }) {
  const isUser = role === 'user'
  return (
    <div className={`message ${isUser ? 'user' : 'assistant'}`}>
      {!isUser && (
        <div className="avatar" aria-hidden="true">🫒</div>
      )}
      <div className="bubble-wrap">
        <div className={`bubble ${error ? 'error' : ''}`}>{text}</div>
        {needsHuman && (
          <div className="handoff-note">
            👤 A team member will follow up with you shortly.
          </div>
        )}
      </div>
    </div>
  )
}
