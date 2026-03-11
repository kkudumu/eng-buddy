import { Outlet } from 'react-router-dom'
import { useCallback } from 'react'
import { useQueryClient } from '@tanstack/react-query'
import { useSSE } from '../hooks/useSSE'
import type { SSEEvent } from '../hooks/useSSE'
import { Header } from '../features/inbox/Header'
import { Sidebar } from '../features/inbox/Sidebar'
import styles from './AppLayout.module.css'

const particles = ['\u273f', '\u22c6', '\u2661', '\u2727', '\u273f', '\u22c6', '\u2661', '\u2727']

export function AppLayout() {
  const queryClient = useQueryClient()

  const handleSSE = useCallback(
    (_event: SSEEvent) => {
      queryClient.invalidateQueries({ queryKey: ['cards'] })
    },
    [queryClient],
  )

  useSSE(handleSSE)

  return (
    <div className={styles.layout}>
      <div className={styles.particles}>
        {particles.map((p, i) => (
          <span
            key={i}
            className={styles.particle}
            style={{
              left: `${10 + i * 12}%`,
              top: `${20 + (i % 3) * 25}%`,
              animationDelay: `${i * 1.2}s`,
              animationDuration: `${6 + (i % 4) * 2}s`,
            }}
          >
            {p}
          </span>
        ))}
      </div>

      <Header pendingCount={0} isLoading={false} />

      <div className={styles.body}>
        <Sidebar />
        <div className={styles.content}>
          <Outlet />
        </div>
      </div>
    </div>
  )
}
