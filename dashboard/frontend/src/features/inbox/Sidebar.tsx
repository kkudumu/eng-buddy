import { NavLink } from 'react-router-dom'
import styles from './Sidebar.module.css'

const navItems = [
  { to: '/app/inbox', label: 'Inbox' },
  { to: '/app/tasks', label: 'Tasks' },
  { to: '/app/jira', label: 'Jira' },
  { to: '/app/calendar', label: 'Calendar' },
  { to: '/app/daily', label: 'Daily' },
  { to: '/app/learnings', label: 'Learnings' },
  { to: '/app/knowledge', label: 'Knowledge' },
  { to: '/app/suggestions', label: 'Suggestions' },
  { to: '/app/playbooks', label: 'Playbooks' },
]

export function Sidebar() {
  return (
    <nav className={styles.sidebar}>
      {navItems.map(({ to, label }) => (
        <NavLink
          key={to}
          to={to}
          className={({ isActive }) => `${styles.item} ${isActive ? styles.active : ''}`}
        >
          <span>{label}</span>
        </NavLink>
      ))}
    </nav>
  )
}
