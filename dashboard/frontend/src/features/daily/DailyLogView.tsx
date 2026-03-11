import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { fetchDailyLogs, fetchDailyLog } from '../../api/client'
import styles from './DailyLogView.module.css'

export function DailyLogView() {
  const [selectedDate, setSelectedDate] = useState<string | null>(null)
  const { data: logsData, isLoading: logsLoading } = useQuery({
    queryKey: ['daily-logs'],
    queryFn: fetchDailyLogs,
  })
  const { data: logContent } = useQuery({
    queryKey: ['daily-log', selectedDate],
    queryFn: () => fetchDailyLog(selectedDate!),
    enabled: !!selectedDate,
  })

  const dates = logsData?.logs ?? []

  if (logsLoading) return <div className={styles.loading}>Loading logs...</div>

  return (
    <div className={styles.container}>
      <h2 className={styles.heading}>Daily Log</h2>
      <div className={styles.layout}>
        <div className={styles.dateList}>
          {dates.map((date) => (
            <button
              key={date}
              className={`${styles.dateBtn} ${date === selectedDate ? styles.selected : ''}`}
              onClick={() => setSelectedDate(date)}
            >
              {date}
            </button>
          ))}
          {dates.length === 0 && <div className={styles.empty}>No logs yet</div>}
        </div>
        <div className={styles.content}>
          {selectedDate && logContent ? (
            <>
              <h3 className={styles.dateHeading}>{logContent.date}</h3>
              {logContent.stats && (
                <div className={styles.stats}>
                  {Object.entries(logContent.stats).map(([k, v]) => (
                    <span key={k} className={styles.stat}>{k}: {String(v)}</span>
                  ))}
                </div>
              )}
              <pre className={styles.logContent}>{logContent.content}</pre>
            </>
          ) : (
            <div className={styles.placeholder}>Select a date to view log</div>
          )}
        </div>
      </div>
    </div>
  )
}
