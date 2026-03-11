import { useEffect, useRef } from 'react'
import { useQuery } from '@tanstack/react-query'
import { fetchBriefing } from '../../api/client'
import styles from './BriefingModal.module.css'

interface BriefingModalProps {
  open: boolean
  onClose: () => void
}

const loadColors: Record<string, string> = {
  low: 'var(--fresh)',
  medium: 'var(--needs-response)',
  high: 'var(--gmail)',
}

export function BriefingModal({ open, onClose }: BriefingModalProps) {
  const overlayRef = useRef<HTMLDivElement>(null)

  const { data, isLoading } = useQuery({
    queryKey: ['briefing'],
    queryFn: fetchBriefing,
    enabled: open,
  })

  useEffect(() => {
    if (!open) return
    const handleKey = (e: KeyboardEvent) => { if (e.key === 'Escape') onClose() }
    window.addEventListener('keydown', handleKey)
    return () => window.removeEventListener('keydown', handleKey)
  }, [open, onClose])

  const handleOverlayClick = (e: React.MouseEvent) => {
    if (e.target === overlayRef.current) onClose()
  }

  if (!open) return null

  return (
    <div className={styles.overlay} ref={overlayRef} onClick={handleOverlayClick}>
      <div className={styles.modal}>
        <div className={styles.header}>
          <h2 className={styles.title}>Morning Briefing</h2>
          <button onClick={onClose} className={styles.close}>&times;</button>
        </div>
        {isLoading ? (
          <div className={styles.loading}>Loading briefing...</div>
        ) : data ? (
          <div className={styles.content}>
            <div className={styles.loadIndicator} style={{ borderColor: loadColors[data.cognitive_load] || 'var(--muted)' }}>
              Cognitive Load: <strong>{data.cognitive_load.toUpperCase()}</strong>
            </div>

            {data.meetings.length > 0 && (
              <section className={styles.section}>
                <h3>Meetings</h3>
                {data.meetings.map((m, i) => (
                  <div key={i} className={styles.meeting}>
                    <span className={styles.meetingTime}>{m.time}</span>
                    <span>{m.title}</span>
                    {m.hangout_link && <a href={m.hangout_link} target="_blank" rel="noopener noreferrer" className={styles.joinLink}>Join</a>}
                  </div>
                ))}
              </section>
            )}

            {data.needs_response.length > 0 && (
              <section className={styles.section}>
                <h3>Needs Response</h3>
                {data.needs_response.map((item, i) => (
                  <div key={i} className={styles.responseItem}>
                    <span>{item.summary}</span>
                    <span className={styles.source}>{item.source}</span>
                    {item.has_draft && <span className={styles.draftBadge}>draft</span>}
                  </div>
                ))}
              </section>
            )}

            {data.alerts.length > 0 && (
              <section className={styles.section}>
                <h3>Alerts</h3>
                {data.alerts.map((a, i) => (
                  <div key={i} className={styles.alert}>
                    <span className={styles.alertType}>{a.type}</span>
                    <span>{a.message}</span>
                  </div>
                ))}
              </section>
            )}

            <div className={styles.stats}>
              <span>Drafts sent: {data.stats.drafts_sent}</span>
              <span>Triaged: {data.stats.triaged}</span>
              <span>Time saved: {data.stats.time_saved_minutes}m</span>
            </div>

            {data.pep_talk && <div className={styles.pepTalk}>{data.pep_talk}</div>}
          </div>
        ) : (
          <div className={styles.loading}>No briefing data</div>
        )}
      </div>
    </div>
  )
}
