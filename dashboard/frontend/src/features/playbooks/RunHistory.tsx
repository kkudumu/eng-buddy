import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { fetchPlaybookHistory } from '../../api/client'
import { Badge } from '../../components/Badge'
import type { PlaybookRun } from '../../api/types'
import styles from './RunHistory.module.css'

interface Props {
  playbookId: string
}

export function RunHistory({ playbookId }: Props) {
  const [expandedRun, setExpandedRun] = useState<string | null>(null)

  const { data, isLoading } = useQuery({
    queryKey: ['playbook-history', playbookId],
    queryFn: () => fetchPlaybookHistory(playbookId),
  })

  if (isLoading) return <div className={styles.loading}>Loading history...</div>

  const runs = data?.runs ?? []
  if (runs.length === 0) return <div className={styles.empty}>No execution history</div>

  const statusColor = (status: PlaybookRun['status']): 'mint' | 'coral' | 'pink' | 'muted' => {
    switch (status) {
      case 'success': return 'mint'
      case 'failed': return 'coral'
      case 'partial': return 'pink'
      default: return 'muted'
    }
  }

  return (
    <div className={styles.container}>
      {runs.map((run) => (
        <div key={run.id} className={styles.run}>
          <button
            className={styles.runHeader}
            onClick={() => setExpandedRun(expandedRun === run.id ? null : run.id)}
          >
            <Badge text={run.status} color={statusColor(run.status)} />
            <span className={styles.date}>{new Date(run.started_at).toLocaleString()}</span>
            <span className={styles.stepCount}>{run.steps.length} steps</span>
            <span className={styles.chevron}>{expandedRun === run.id ? '\u25BC' : '\u25B6'}</span>
          </button>

          {expandedRun === run.id && (
            <div className={styles.steps}>
              {run.steps.map((step, i) => (
                <div key={i} className={styles.step}>
                  <span className={styles.stepNum}>{step.number}.</span>
                  <span className={styles.stepDesc}>{step.description}</span>
                  <span className={styles.stepTool}>{step.tool}</span>
                  <Badge text={step.status} color={statusColor(step.status as PlaybookRun['status'])} />
                  {step.duration_ms != null && (
                    <span className={styles.duration}>{(step.duration_ms / 1000).toFixed(1)}s</span>
                  )}
                </div>
              ))}
            </div>
          )}
        </div>
      ))}
    </div>
  )
}
