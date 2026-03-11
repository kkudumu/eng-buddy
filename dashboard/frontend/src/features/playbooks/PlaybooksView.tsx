import { useState } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { fetchPlaybooks, fetchPlaybookDrafts, executePlaybook } from '../../api/client'
import { useToastStore } from '../../stores/toast'
import styles from './PlaybooksView.module.css'

interface PlaybookStep {
  summary: string
  tool: string
}

interface PlaybookDraft {
  id: string
  name: string
  trigger: string
  confidence: number
  steps: PlaybookStep[]
}

interface PlaybookItem extends PlaybookDraft {
  executions: number
}

export function PlaybooksView() {
  const queryClient = useQueryClient()
  const addToast = useToastStore((s) => s.addToast)
  const [approvalText, setApprovalText] = useState<Record<string, string>>({})

  const { data: draftsData, isLoading: draftsLoading } = useQuery({
    queryKey: ['playbook-drafts'],
    queryFn: fetchPlaybookDrafts,
  })

  const { data: playbooksData, isLoading: playbooksLoading } = useQuery({
    queryKey: ['playbooks'],
    queryFn: fetchPlaybooks,
  })

  const drafts = (draftsData?.drafts ?? []) as PlaybookDraft[]
  const playbooks = (playbooksData?.playbooks ?? []) as PlaybookItem[]

  const handleExecute = async (playbookId: string) => {
    const approval = approvalText[playbookId] || 'approved'
    try {
      await executePlaybook(playbookId, {}, approval)
      queryClient.invalidateQueries({ queryKey: ['playbooks'] })
      addToast(`Playbook ${playbookId} executed`, 'success')
    } catch {
      addToast(`Failed to execute playbook ${playbookId}`, 'error')
    }
  }

  if (draftsLoading || playbooksLoading) return <div className={styles.loading}>Loading playbooks...</div>

  return (
    <div className={styles.container}>
      <h2 className={styles.heading}>Playbooks</h2>

      {drafts.length > 0 && (
        <section className={styles.section}>
          <h3 className={styles.subheading}>Drafts ({drafts.length})</h3>
          {drafts.map((d) => (
            <div key={d.id} className={styles.card}>
              <div className={styles.cardHeader}>
                <span className={styles.name}>{d.name}</span>
                <span className={styles.confidence}>{Math.round(d.confidence * 100)}%</span>
              </div>
              <div className={styles.trigger}>Trigger: {d.trigger}</div>
              <div className={styles.steps}>
                {d.steps.map((s, i) => (
                  <div key={i} className={styles.step}>
                    <span className={styles.stepNum}>{i + 1}.</span>
                    <span>{s.summary}</span>
                    <span className={styles.tool}>{s.tool}</span>
                  </div>
                ))}
              </div>
            </div>
          ))}
        </section>
      )}

      <section className={styles.section}>
        <h3 className={styles.subheading}>Approved ({playbooks.length})</h3>
        {playbooks.length === 0 && <div className={styles.empty}>No approved playbooks</div>}
        {playbooks.map((p) => (
          <div key={p.id} className={styles.card}>
            <div className={styles.cardHeader}>
              <span className={styles.name}>{p.name}</span>
              <span className={styles.executions}>{p.executions} runs</span>
            </div>
            <div className={styles.trigger}>Trigger: {p.trigger}</div>
            <div className={styles.steps}>
              {p.steps.map((s, i) => (
                <div key={i} className={styles.step}>
                  <span className={styles.stepNum}>{i + 1}.</span>
                  <span>{s.summary}</span>
                  <span className={styles.tool}>{s.tool}</span>
                </div>
              ))}
            </div>
            <div className={styles.executeRow}>
              <input
                type="text" placeholder="Approval text..."
                value={approvalText[p.id] || ''}
                onChange={(e) => setApprovalText({ ...approvalText, [p.id]: e.target.value })}
                className={styles.approvalInput}
              />
              <button onClick={() => handleExecute(p.id)} className={styles.executeBtn}>Execute</button>
            </div>
          </div>
        ))}
      </section>
    </div>
  )
}
