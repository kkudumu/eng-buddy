import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { fetchLearningsSummary, fetchLearningsEvents } from '../../api/client'
import styles from './LearningsView.module.css'

export function LearningsView() {
  const [range, setRange] = useState<'day' | 'week'>('day')
  const [date, setDate] = useState(new Date().toISOString().split('T')[0])

  const { data: summary, isLoading: summaryLoading } = useQuery({
    queryKey: ['learnings-summary', range, date],
    queryFn: () => fetchLearningsSummary(range, date),
  })

  const { data: events } = useQuery({
    queryKey: ['learnings-events', range, date],
    queryFn: () => fetchLearningsEvents(range, date),
  })

  const summaryData = summary as Record<string, unknown> | undefined
  const eventsData = (events as { events?: unknown[] })?.events ?? []

  return (
    <div className={styles.container}>
      <h2 className={styles.heading}>Learnings</h2>
      <div className={styles.controls}>
        <button className={`${styles.toggle} ${range === 'day' ? styles.active : ''}`} onClick={() => setRange('day')}>Day</button>
        <button className={`${styles.toggle} ${range === 'week' ? styles.active : ''}`} onClick={() => setRange('week')}>Week</button>
        <input type="date" value={date} onChange={(e) => setDate(e.target.value)} className={styles.datePicker} />
      </div>
      {summaryLoading ? (
        <div className={styles.loading}>Loading...</div>
      ) : (
        <>
          {summaryData && (
            <div className={styles.summary}>
              {Object.entries(summaryData).map(([key, value]) => (
                <div key={key} className={styles.summaryItem}>
                  <span className={styles.summaryLabel}>{key}</span>
                  <span className={styles.summaryValue}>{typeof value === 'object' ? JSON.stringify(value) : String(value)}</span>
                </div>
              ))}
            </div>
          )}
          {eventsData.length > 0 && (
            <div className={styles.events}>
              <h3 className={styles.subheading}>Recent Events</h3>
              {eventsData.map((event, i) => {
                const e = event as Record<string, unknown>
                return (
                  <div key={i} className={styles.event}>
                    <span className={styles.eventTitle}>{String(e.title ?? e.summary ?? 'Event')}</span>
                    {e.category && <span className={styles.eventCategory}>{String(e.category)}</span>}
                  </div>
                )
              })}
            </div>
          )}
        </>
      )}
    </div>
  )
}
