import { useState, useEffect, useRef } from 'react'
import { fetchChatHistory, postRefine } from '../../api/client'
import type { ChatMessage } from '../../api/types'
import styles from './RefineChat.module.css'

interface RefineChatProps {
  entityType: 'cards' | 'tasks'
  entityId: number
}

export function RefineChat({ entityType, entityId }: RefineChatProps) {
  const [messages, setMessages] = useState<ChatMessage[]>([])
  const [input, setInput] = useState('')
  const [loading, setLoading] = useState(false)
  const [loaded, setLoaded] = useState(false)
  const inputRef = useRef<HTMLTextAreaElement>(null)
  useEffect(() => {
    if (loaded) return
    fetchChatHistory(entityType, entityId)
      .then((res) => { setMessages(res.messages); setLoaded(true) })
      .catch(() => setLoaded(true))
  }, [entityType, entityId, loaded])
  const handleSend = async () => {
    const text = input.trim()
    if (!text || loading) return
    setInput('')
    const userMsg: ChatMessage = { id: Date.now(), role: 'user', content: text, created_at: new Date().toISOString() }
    setMessages((prev) => [...prev, userMsg])
    setLoading(true)
    try {
      const history = messages.map((m) => ({ role: m.role, content: m.content }))
      const res = await postRefine(entityType, entityId, text, history)
      const assistantMsg: ChatMessage = { id: Date.now() + 1, role: 'assistant', content: res.response, created_at: new Date().toISOString() }
      setMessages((prev) => [...prev, assistantMsg])
    } catch {
      const errMsg: ChatMessage = { id: Date.now() + 1, role: 'assistant', content: 'Error: could not refine', created_at: new Date().toISOString() }
      setMessages((prev) => [...prev, errMsg])
    } finally {
      setLoading(false)
      inputRef.current?.focus()
    }
  }
  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault()
      handleSend()
    }
  }
  return (
    <div className={styles.chat}>
      <div className={styles.history}>
        {messages.map((m) => (
          <div key={m.id} className={`${styles.message} ${styles[m.role]}`}>
            <span className={styles.label}>{m.role === 'user' ? 'YOU' : 'BUDDY'}</span>
            <span>{m.content}</span>
          </div>
        ))}
        {loading && <div className={styles.message}><span className={styles.label}>BUDDY</span> thinking...</div>}
      </div>
      <div className={styles.inputArea}>
        <textarea ref={inputRef} value={input} onChange={(e) => setInput(e.target.value)}
          onKeyDown={handleKeyDown} placeholder="Refine this card..." rows={2} disabled={loading} />
        <button onClick={handleSend} disabled={loading || !input.trim()}>Send</button>
      </div>
    </div>
  )
}
