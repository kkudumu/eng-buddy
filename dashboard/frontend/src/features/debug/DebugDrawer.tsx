import { useDebugStore } from '../../stores/debug'
import { sendDebugToClaude } from '../../api/client'
import { useToastStore } from '../../stores/toast'
import styles from './DebugDrawer.module.css'

export function DebugDrawer() {
  const { entries, isOpen, toggle, clear, markSent } = useDebugStore()
  const addToast = useToastStore((s) => s.addToast)
  const handleSendToClaude = async (entry: typeof entries[0]) => {
    try {
      await sendDebugToClaude(entry.message, entry.level, 'REACT', entry.details)
      markSent(entry.id)
      addToast('Sent to Claude', 'success')
    } catch {
      addToast('Failed to send to Claude', 'error')
    }
  }
  return (
    <>
      <button className={styles.toggle} onClick={toggle}>
        {isOpen ? 'CLOSE DEBUG' : `DEBUG (${entries.length})`}
      </button>
      {isOpen && (
        <div className={styles.drawer}>
          <div className={styles.header}>
            <span>Debug Log ({entries.length})</span>
            <button onClick={clear}>Clear All</button>
          </div>
          <div className={styles.entries}>
            {entries.map((e) => (
              <div key={e.id} className={`${styles.entry} ${styles[e.level]}`}>
                <span className={styles.badge}>{e.level.toUpperCase()}</span>
                <span className={styles.message}>{e.message}</span>
                <span className={styles.time}>{new Date(e.timestamp).toLocaleTimeString()}</span>
                {e.level === 'error' && !e.sentToClaude && (
                  <button onClick={() => handleSendToClaude(e)} className={styles.sendBtn}>Send to Claude</button>
                )}
                {e.sentToClaude && <span className={styles.sent}>sent</span>}
              </div>
            ))}
          </div>
        </div>
      )}
    </>
  )
}
