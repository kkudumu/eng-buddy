import { useState, useEffect } from 'react'
import type { Poller } from '../api/types'

export function usePollerCountdown(pollers: Poller[]): Map<string, number | null> {
  const [countdowns, setCountdowns] = useState<Map<string, number | null>>(new Map())
  useEffect(() => {
    const calc = () => {
      const now = Date.now()
      const next = new Map<string, number | null>()
      for (const p of pollers) {
        if (!p.next_run_at) { next.set(p.id, null); continue }
        const target = new Date(p.next_run_at).getTime()
        let diff = Math.round((target - now) / 1000)
        if (diff < 0 && p.interval_seconds > 0) {
          const cycles = Math.ceil(Math.abs(diff) / p.interval_seconds)
          diff += cycles * p.interval_seconds
        }
        next.set(p.id, Math.max(0, diff))
      }
      setCountdowns(next)
    }
    calc()
    const id = setInterval(calc, 1000)
    return () => clearInterval(id)
  }, [pollers])
  return countdowns
}
