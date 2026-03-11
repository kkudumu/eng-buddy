import { useState, useRef, useCallback } from 'react'
import { postRestart, fetchHealth, fetchRestartStatus } from '../../api/client'

type Phase = 'idle' | 'restarting' | 'syncing' | 'complete' | 'failed' | 'timeout'

const LABELS: Record<Phase, string> = {
  idle: 'RESTART',
  restarting: 'RESTARTING...',
  syncing: 'SYNCING DATA...',
  complete: 'RESTART',
  failed: 'RESTART FAILED',
  timeout: 'RESTART TIMEOUT',
}

export function RestartButton() {
  const [phase, setPhase] = useState<Phase>('idle')
  const timerRef = useRef<ReturnType<typeof setTimeout>>()
  const handleClick = useCallback(async () => {
    if (phase === 'restarting' || phase === 'syncing') return
    setPhase('restarting')
    try {
      await postRestart()
    } catch {
      setPhase('failed')
      return
    }
    const deadline = Date.now() + 120_000
    const pollHealth = async (): Promise<boolean> => {
      while (Date.now() < deadline) {
        try {
          await fetchHealth()
          return true
        } catch {
          await new Promise((r) => { timerRef.current = setTimeout(r, 500) })
        }
      }
      return false
    }
    const healthy = await pollHealth()
    if (!healthy) { setPhase('timeout'); return }
    setPhase('syncing')
    const pollStatus = async () => {
      while (Date.now() < deadline) {
        try {
          const status = await fetchRestartStatus()
          if (status.phase === 'complete' || status.phase === 'idle') {
            setPhase('complete')
            setTimeout(() => setPhase('idle'), 2000)
            return
          }
        } catch { /* server still coming up */ }
        await new Promise((r) => { timerRef.current = setTimeout(r, 500) })
      }
      setPhase('timeout')
    }
    await pollStatus()
  }, [phase])
  const busy = phase === 'restarting' || phase === 'syncing'
  return (
    <button onClick={handleClick} disabled={busy} aria-label="Restart dashboard">
      {LABELS[phase]}
    </button>
  )
}
