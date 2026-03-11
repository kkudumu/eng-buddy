import { useQuery, useQueryClient } from '@tanstack/react-query'
import { fetchJiraSprint, fetchCards } from '../../api/client'
import styles from './JiraSprintView.module.css'

const STATUS_GROUPS = {
  'To Do': ['to do', 'open', 'new', 'backlog'],
  'In Progress': ['in progress', 'in review', 'in development'],
  'Done': ['done', 'closed', 'resolved', 'complete'],
}

function getGroup(status: string): string {
  const lower = status.toLowerCase()
  for (const [group, statuses] of Object.entries(STATUS_GROUPS)) {
    if (statuses.some((s) => lower.includes(s))) return group
  }
  return 'To Do'
}

export function JiraSprintView() {
  const queryClient = useQueryClient()
  const { data: sprint, isLoading: sprintLoading } = useQuery({
    queryKey: ['jira-sprint'],
    queryFn: () => fetchJiraSprint(),
  })
  const { data: _cardsData } = useQuery({
    queryKey: ['cards', 'jira'],
    queryFn: () => fetchCards('jira'),
  })

  const issues = sprint?.issues ?? []
  const grouped = { 'To Do': [] as typeof issues, 'In Progress': [] as typeof issues, 'Done': [] as typeof issues }
  for (const issue of issues) {
    const group = getGroup(issue.status)
    ;(grouped[group as keyof typeof grouped] ?? grouped['To Do']).push(issue)
  }

  const handleRefresh = () => {
    fetchJiraSprint(true).then(() => queryClient.invalidateQueries({ queryKey: ['jira-sprint'] }))
  }

  if (sprintLoading) return <div className={styles.loading}>Loading sprint...</div>

  return (
    <div className={styles.container}>
      <div className={styles.headerRow}>
        <h2 className={styles.heading}>Jira Sprint</h2>
        <button onClick={handleRefresh} className={styles.refresh}>Refresh</button>
      </div>
      <div className={styles.board}>
        {Object.entries(grouped).map(([group, items]) => (
          <div key={group} className={styles.column}>
            <h3 className={styles.columnTitle}>{group} ({items.length})</h3>
            {items.map((issue) => (
              <div key={issue.key} className={styles.issue}>
                <div className={styles.issueKey}>{issue.key}</div>
                <div className={styles.issueSummary}>{issue.summary}</div>
                <div className={styles.issueMeta}>
                  <span>{issue.assignee}</span>
                  <span className={styles.priority}>{issue.priority}</span>
                </div>
              </div>
            ))}
          </div>
        ))}
      </div>
    </div>
  )
}
