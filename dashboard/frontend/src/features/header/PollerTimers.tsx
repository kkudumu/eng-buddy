import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { fetchPollers, syncPoller } from '../../api/client'
import { usePollerCountdown } from '../../hooks/usePollerCountdown'
import styles from './PollerTimers.module.css'

export function PollerTimers() {
  const queryClient = useQueryClient()
  const { data } = useQuery({
    queryKey: ['pollers'],
    queryFn: fetchPollers,
    refetchInterval: 30_000,
  })
  const pollers = data?.pollers ?? []
  const countdowns = usePollerCountdown(pollers)
  const sync = useMutation({
    mutationFn: (id: string) => syncPoller(id),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['pollers'] }),
  })
  const formatCountdown = (seconds: number | null | undefined): string => {
    if (seconds == null) return '--'
    const m = Math.floor(seconds / 60)
    const s = seconds % 60
    return m > 0 ? `${m}m ${s}s` : `${s}s`
  }
  return (
    <div className={styles.timers} aria-live="polite">
      {pollers.map((p) => (
        <button
          key={p.id}
          className={`${styles.badge} ${styles[p.health] ?? ''}`}
          onClick={() => sync.mutate(p.id)}
          title={`Click to sync ${p.label} now`}
          disabled={sync.isPending}
        >
          {p.label} {formatCountdown(countdowns.get(p.id))}
        </button>
      ))}
    </div>
  )
}
