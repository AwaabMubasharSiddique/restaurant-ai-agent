import { useEffect, useRef, useState } from 'react'

export default function ChatInput({ onSend, disabled }) {
  const [value, setValue] = useState('')
  const inputRef = useRef(null)

  // Re-focus the input whenever it becomes enabled again (i.e. right after the
  // reply arrives), so the user can keep typing without clicking back in.
  useEffect(() => {
    if (!disabled) inputRef.current?.focus()
  }, [disabled])

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
        ref={inputRef}
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
