import { useUIStore } from '../../stores/ui'
import type { CardCounts, CardSource } from '../../api/types'
import styles from './Sidebar.module.css'

interface SidebarProps {
  counts: CardCounts
  sourceCounts: Record<string, number>
}

const sources: { key: CardSource; label: string }[] = [
  { key: 'all', label: 'All' },
  { key: 'gmail', label: 'Gmail' },
  { key: 'slack', label: 'Slack' },
  { key: 'jira', label: 'Jira' },
  { key: 'freshservice', label: 'Freshservice' },
  { key: 'calendar', label: 'Calendar' },
  { key: 'tasks', label: 'Tasks' },
]

export function Sidebar({ counts, sourceCounts }: SidebarProps) {
  const activeSource = useUIStore((s) => s.activeSource)
  const setActiveSource = useUIStore((s) => s.setActiveSource)

  const getCount = (key: CardSource): number => {
    if (key === 'all') return counts.pending
    return sourceCounts[key] ?? 0
  }

  return (
    <nav className={styles.sidebar}>
      {sources.map(({ key, label }) => (
        <button
          key={key}
          className={`${styles.item} ${activeSource === key ? styles.active : ''}`}
          onClick={() => setActiveSource(key)}
        >
          <span>{label}</span>
          {getCount(key) > 0 && <span className={styles.count}>{getCount(key)}</span>}
        </button>
      ))}
    </nav>
  )
}
