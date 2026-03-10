import styles from './StatsBar.module.css'

interface StatsBarProps {
  needsAction: number
  autoResolved: number
  draftAcceptRate: number
  timeSavedMinutes: number
}

function formatTime(minutes: number): string {
  const h = Math.floor(minutes / 60)
  const m = minutes % 60
  return `${h}h ${m}m`
}

export function StatsBar({ needsAction, autoResolved, draftAcceptRate, timeSavedMinutes }: StatsBarProps) {
  return (
    <div className={styles.bar}>
      <div className={styles.stat}>
        <div className={styles.value}>{needsAction}</div>
        <div className={styles.label}>Needs Action</div>
      </div>
      <div className={styles.stat}>
        <div className={styles.value}>{autoResolved}</div>
        <div className={styles.label}>Auto-Resolved</div>
      </div>
      <div className={styles.stat}>
        <div className={styles.value}>{draftAcceptRate}%</div>
        <div className={styles.label}>Draft Accept Rate</div>
      </div>
      <div className={styles.stat}>
        <div className={styles.value}>{formatTime(timeSavedMinutes)}</div>
        <div className={styles.label}>Time Saved</div>
      </div>
    </div>
  )
}
