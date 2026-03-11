import { useNavigate, useLocation } from 'react-router-dom'
import { useUIStore } from '../../stores/ui'
import type { CardCounts, CardSource } from '../../api/types'
import styles from './Sidebar.module.css'

interface SidebarProps {
  counts?: CardCounts
  sourceCounts?: Record<string, number>
}

const navItems: { path: string; label: string }[] = [
  { path: '/app/inbox', label: 'Inbox' },
  { path: '/app/tasks', label: 'Tasks' },
  { path: '/app/jira', label: 'Jira Sprint' },
  { path: '/app/calendar', label: 'Calendar' },
  { path: '/app/daily', label: 'Daily Log' },
  { path: '/app/learnings', label: 'Learnings' },
  { path: '/app/knowledge', label: 'Knowledge' },
  { path: '/app/suggestions', label: 'Suggestions' },
  { path: '/app/playbooks', label: 'Playbooks' },
]

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
  const navigate = useNavigate()
  const location = useLocation()
  const activeSource = useUIStore((s) => s.activeSource)
  const setActiveSource = useUIStore((s) => s.setActiveSource)

  const isInbox = location.pathname.startsWith('/app/inbox') || location.pathname === '/app'

  const getCount = (key: CardSource): number => {
    if (key === 'all') return counts?.pending ?? 0
    return sourceCounts?.[key] ?? 0
  }

  return (
    <nav className={styles.sidebar}>
      <div className={styles.navSection}>
        {navItems.map(({ path, label }) => (
          <button
            key={path}
            className={`${styles.navItem} ${location.pathname.startsWith(path) ? styles.navActive : ''}`}
            onClick={() => navigate(path)}
          >
            {label}
          </button>
        ))}
      </div>

      {isInbox && (
        <>
          <div className={styles.divider} />
          <div className={styles.filterLabel}>Filter by source</div>
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
        </>
      )}
    </nav>
  )
}
