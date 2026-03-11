import { useState } from 'react'
import type { Card } from '../../api/types'
import { gmailAnalyze } from '../../api/client'
import { useCardDecision } from '../../hooks/useCardDecision'
import { useToastStore } from '../../stores/toast'

interface GmailActionsProps {
  card: Card
}

export function GmailActions({ card }: GmailActionsProps) {
  const [analysis, setAnalysis] = useState<{ labels: string[]; draft: string; reasoning: string } | null>(null)
  const [loading, setLoading] = useState(false)
  const decision = useCardDecision()
  const addToast = useToastStore((s) => s.addToast)

  const handleAnalyze = async () => {
    setLoading(true)
    try {
      const res = await gmailAnalyze(card.id)
      setAnalysis({ labels: res.suggested_labels, draft: res.draft_response, reasoning: res.reasoning })
    } catch {
      addToast('Failed to analyze email', 'error')
    } finally {
      setLoading(false)
    }
  }

  const handleAutoLabel = () => {
    decision.mutate({
      cardId: card.id,
      action: 'gmail-auto-label',
      decision: 'approved',
      followUp: { endpoint: 'gmail-auto-label' },
    })
  }

  const handleArchive = () => {
    decision.mutate({
      cardId: card.id,
      action: 'archive-email',
      decision: 'approved',
      followUp: { endpoint: 'archive-email' },
    })
  }

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: '0.5rem', padding: '0.5rem 0' }}>
      <div style={{ display: 'flex', gap: '0.5rem', flexWrap: 'wrap' }}>
        <button onClick={handleAnalyze} disabled={loading}>
          {loading ? 'Analyzing...' : 'Suggest Labels'}
        </button>
        <button onClick={handleAutoLabel}>Auto Label</button>
        <button onClick={handleArchive}>Archive</button>
      </div>
      {analysis && (
        <div style={{ fontSize: '0.75rem', fontFamily: 'var(--font-mono)', color: 'var(--text)' }}>
          {analysis.labels.length > 0 && (
            <div>Labels: {analysis.labels.join(', ')}</div>
          )}
          {analysis.reasoning && <div style={{ color: 'var(--muted)', marginTop: '0.25rem' }}>{analysis.reasoning}</div>}
          {analysis.draft && (
            <div style={{ marginTop: '0.5rem', padding: '0.5rem', background: 'var(--surface)', borderRadius: 'var(--radius-sm, 4px)' }}>
              <div style={{ fontWeight: 'bold', marginBottom: '0.25rem' }}>Suggested Draft:</div>
              <div style={{ whiteSpace: 'pre-wrap' }}>{analysis.draft}</div>
            </div>
          )}
        </div>
      )}
    </div>
  )
}
