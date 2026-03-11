import { useState } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { fetchPlaybooks, fetchPlaybookDrafts, executePlaybook } from '../../api/client'
import { useToastStore } from '../../stores/toast'
import { DraftEditor } from './DraftEditor'
import { RunHistory } from './RunHistory'
import styles from './PlaybooksView.module.css'

type Tab = 'drafts' | 'published' | 'history'

interface PlaybookStep { summary: string; tool: string }
interface PlaybookDraft { id: string; name: string; trigger: string; confidence: number; steps: PlaybookStep[] }
interface PlaybookItem extends PlaybookDraft { executions: number }

export function PlaybooksView() {
  const queryClient = useQueryClient()
  const addToast = useToastStore((s) => s.addToast)
  const [tab, setTab] = useState<Tab>('drafts')
  const [expandedDraft, setExpandedDraft] = useState<string | null>(null)
  const [historyPlaybook, setHistoryPlaybook] = useState<string | null>(null)
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

      <div className={styles.tabs}>
        <button className={`${styles.tab} ${tab === 'drafts' ? styles.tabActive : ''}`} onClick={() => setTab('drafts')}>
          Drafts ({drafts.length})
        </button>
        <button className={`${styles.tab} ${tab === 'published' ? styles.tabActive : ''}`} onClick={() => setTab('published')}>
          Published ({playbooks.length})
        </button>
        <button className={`${styles.tab} ${tab === 'history' ? styles.tabActive : ''}`} onClick={() => setTab('history')}>
          History
        </button>
      </div>

      {tab === 'drafts' && (
        <section className={styles.section}>
          {drafts.length === 0 && <div className={styles.empty}>No drafts</div>}
          {drafts.map((d) => (
            <div key={d.id}>
              {expandedDraft === d.id ? (
                <DraftEditor draftId={d.id} onClose={() => setExpandedDraft(null)} />
              ) : (
                <div className={styles.card} onClick={() => setExpandedDraft(d.id)}>
                  <div className={styles.cardHeader}>
                    <span className={styles.name}>{d.name}</span>
                    <span className={styles.confidence}>{Math.round(d.confidence * 100)}%</span>
                  </div>
                  <div className={styles.trigger}>Trigger: {d.trigger}</div>
                  <div className={styles.meta}>{d.steps.length} steps</div>
                </div>
              )}
            </div>
          ))}
        </section>
      )}

      {tab === 'published' && (
        <section className={styles.section}>
          {playbooks.length === 0 && <div className={styles.empty}>No published playbooks</div>}
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
                <button onClick={() => { setHistoryPlaybook(p.id); setTab('history') }} className={styles.historyBtn}>History</button>
              </div>
            </div>
          ))}
        </section>
      )}

      {tab === 'history' && (
        <section className={styles.section}>
          {historyPlaybook ? (
            <>
              <div className={styles.historyHeader}>
                <span>History for: {playbooks.find(p => p.id === historyPlaybook)?.name ?? historyPlaybook}</span>
                <button onClick={() => setHistoryPlaybook(null)} className={styles.clearBtn}>Show all</button>
              </div>
              <RunHistory playbookId={historyPlaybook} />
            </>
          ) : playbooks.length === 0 ? (
            <div className={styles.empty}>No playbooks with history</div>
          ) : (
            playbooks.map((p) => (
              <div key={p.id} className={styles.historySection}>
                <h4 className={styles.historyTitle}>{p.name}</h4>
                <RunHistory playbookId={p.id} />
              </div>
            ))
          )}
        </section>
      )}
    </div>
  )
}
