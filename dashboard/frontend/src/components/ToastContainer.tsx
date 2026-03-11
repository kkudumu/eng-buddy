import { useToastStore } from '../stores/toast'
import styles from './ToastContainer.module.css'

export function ToastContainer() {
  const toasts = useToastStore((s) => s.toasts)
  const removeToast = useToastStore((s) => s.removeToast)
  if (toasts.length === 0) return null
  return (
    <div className={styles.container}>
      {toasts.map((t) => (
        <div key={t.id} className={`${styles.toast} ${styles[t.level]}`}>
          <span>{t.message}</span>
          <button onClick={() => removeToast(t.id)} className={styles.close}>&times;</button>
        </div>
      ))}
    </div>
  )
}
