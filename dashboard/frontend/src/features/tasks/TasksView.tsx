import { useQuery } from '@tanstack/react-query'
import { fetchTasks, postDecision, performCardAction, openSession } from '../../api/client'
import { useToastStore } from '../../stores/toast'
import { useState } from 'react'
import { RefineChat } from '../refine/RefineChat'
import styles from './TasksView.module.css'

export function TasksView() {
  const { data, isLoading } = useQuery({ queryKey: ['tasks'], queryFn: fetchTasks })
  const addToast = useToastStore((s) => s.addToast)
  const [refiningTask, setRefiningTask] = useState<number | null>(null)

  const tasks = (data?.tasks ?? []).filter(
    (t) => !['completed', 'closed', 'done', 'cancelled'].includes(t.status.toLowerCase())
  )

  const handleAction = async (taskNumber: number, action: string, endpoint: string) => {
    try {
      const result = await postDecision('tasks', taskNumber, action, 'approved')
      await performCardAction(taskNumber, endpoint, { decision_event_id: result.decision_event_id })
      addToast(`Task #${taskNumber}: ${action} done`, 'success')
    } catch {
      addToast(`Failed: ${action} on task #${taskNumber}`, 'error')
    }
  }

  const handleOpenSession = async (taskNumber: number) => {
    try {
      await openSession('tasks', taskNumber)
      addToast(`Session opened for task #${taskNumber}`, 'success')
    } catch {
      addToast(`Failed to open session for task #${taskNumber}`, 'error')
    }
  }

  if (isLoading) return <div className={styles.loading}>Loading tasks...</div>

  return (
    <div className={styles.container}>
      <h2 className={styles.heading}>Tasks ({tasks.length})</h2>
      {tasks.length === 0 && <div className={styles.empty}>No active tasks</div>}
      {tasks.map((task) => (
        <div key={task.number} className={styles.card}>
          <div className={styles.header}>
            <span className={styles.number}>#{task.number}</span>
            <span className={styles.title}>{task.title}</span>
            <span className={`${styles.badge} ${styles[task.priority?.toLowerCase()] ?? ''}`}>{task.priority}</span>
            <span className={styles.status}>{task.status}</span>
          </div>
          {task.description && <div className={styles.description}>{task.description}</div>}
          {task.jira_keys && task.jira_keys.length > 0 && (
            <div className={styles.jiraKeys}>Jira: {task.jira_keys.join(', ')}</div>
          )}
          <div className={styles.actions}>
            <button onClick={() => handleAction(task.number, 'close', 'close')}>Close</button>
            <button onClick={() => handleAction(task.number, 'write-jira', 'write-jira')}>Write Jira</button>
            <button onClick={() => handleAction(task.number, 'daily-log', 'daily-log')}>Daily Log</button>
            <button onClick={() => handleOpenSession(task.number)}>Open Session</button>
            <button onClick={() => setRefiningTask(refiningTask === task.number ? null : task.number)}>
              {refiningTask === task.number ? 'Hide Chat' : 'Refine'}
            </button>
          </div>
          {refiningTask === task.number && (
            <RefineChat entityType="tasks" entityId={task.number} />
          )}
        </div>
      ))}
    </div>
  )
}
