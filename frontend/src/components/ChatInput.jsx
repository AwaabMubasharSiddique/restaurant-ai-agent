import { useState } from 'react'

export default function ChatInput({ onSend, disabled }) {
  const [value, setValue] = useState('')

  function submit(event) {
    event.preventDefault()
    const text = value.trim()
    if (!text || disabled) return
    onSend(text)
    setValue('')
  }

  return (
    <form className="chat-input" onSubmit={submit}>
      <input
        type="text"
        placeholder="Ask about reservations, the menu, hours…"
        value={value}
        onChange={(e) => setValue(e.target.value)}
        disabled={disabled}
        autoFocus
      />
      <button type="submit" disabled={disabled || !value.trim()}>
        Send
      </button>
    </form>
  )
}
