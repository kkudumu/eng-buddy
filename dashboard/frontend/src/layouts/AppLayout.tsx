import { Outlet } from 'react-router-dom'
import { useState, useCallback, useEffect } from 'react'
import { useQueryClient } from '@tanstack/react-query'
import { useSSE } from '../hooks/useSSE'
import type { SSEEvent } from '../hooks/useSSE'
import { useDebugStore } from '../stores/debug'
import { useSettings } from '../hooks/useSettings'
import { Header } from '../features/inbox/Header'
import { Sidebar } from '../features/inbox/Sidebar'
import { ToastContainer } from '../components/ToastContainer'
import { DebugDrawer } from '../features/debug/DebugDrawer'
import { BriefingModal } from '../features/briefing/BriefingModal'
import styles from './AppLayout.module.css'

const particles = ['\u273f', '\u22c6', '\u2661', '\u2727', '\u273f', '\u22c6', '\u2661', '\u2727']

export function AppLayout() {
  useSettings()  // hydrates theme/mode from server on mount
  const queryClient = useQueryClient()
  const [briefingOpen, setBriefingOpen] = useState(false)

  const handleSSE = useCallback(
    (_event: SSEEvent) => {
      queryClient.invalidateQueries({ queryKey: ['cards'] })
    },
    [queryClient],
  )

  useSSE(handleSSE)

  useEffect(() => {
    const addEntry = useDebugStore.getState().addEntry
    const handleError = (event: ErrorEvent) => {
      addEntry('error', event.message, { filename: event.filename, lineno: event.lineno })
    }
    const handleRejection = (event: PromiseRejectionEvent) => {
      addEntry('error', `Unhandled rejection: ${event.reason}`)
    }
    window.addEventListener('error', handleError)
    window.addEventListener('unhandledrejection', handleRejection)
    return () => {
      window.removeEventListener('error', handleError)
      window.removeEventListener('unhandledrejection', handleRejection)
    }
  }, [])

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

      <Header pendingCount={0} isLoading={false} onBriefingClick={() => setBriefingOpen(true)} />

      <div className={styles.body}>
        <Sidebar />
        <div className={styles.content}>
          <Outlet />
        </div>
      </div>

      <DebugDrawer />
      <BriefingModal open={briefingOpen} onClose={() => setBriefingOpen(false)} />
      <ToastContainer />
    </div>
  )
}
