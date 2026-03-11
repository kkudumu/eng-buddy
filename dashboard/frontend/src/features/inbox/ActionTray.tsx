import type { Card } from '../../api/types'
import { useCardDecision } from '../../hooks/useCardDecision'
import { InlineConfirm } from './InlineConfirm'
import { openSession } from '../../api/client'
import { useToastStore } from '../../stores/toast'
import styles from './ActionTray.module.css'

interface ActionTrayProps {
  card: Card
  onApprove: () => void
}

export function ActionTray({ card, onApprove }: ActionTrayProps) {
  const decision = useCardDecision()
  const addToast = useToastStore((s) => s.addToast)
  const handleHold = (rationale: string) => {
    decision.mutate({ cardId: card.id, action: 'hold', decision: 'rejected', rationale, followUp: { endpoint: 'hold' } })
  }
  const handleClose = (rationale: string) => {
    decision.mutate({ cardId: card.id, action: 'close', decision: 'approved', rationale, followUp: { endpoint: 'close', body: { note: rationale } } })
  }
  const handleJira = (rationale: string) => {
    decision.mutate({ cardId: card.id, action: 'write-jira', decision: 'approved', rationale, followUp: { endpoint: 'write-jira', body: { note: rationale } } })
  }
  const handleDailyLog = (rationale: string) => {
    decision.mutate({ cardId: card.id, action: 'daily-log', decision: 'approved', rationale, followUp: { endpoint: 'daily-log', body: { note: rationale } } })
  }
  const handleSendDraft = (channel: 'send-slack' | 'send-email') => {
    decision.mutate({ cardId: card.id, action: channel, decision: 'approved', followUp: { endpoint: channel } })
  }
  const handleOpenSession = async () => {
    try {
      await openSession('cards', card.id)
      addToast(`Session opened for card #${card.id}`, 'success')
    } catch {
      addToast(`Failed to open session for card #${card.id}`, 'error')
    }
  }
  return (
    <div className={styles.tray}>
      <button onClick={onApprove}>Approve</button>
      <InlineConfirm label="Hold" onConfirm={handleHold} />
      <InlineConfirm label="Close" onConfirm={handleClose} />
      <InlineConfirm label="Jira" onConfirm={handleJira} />
      <InlineConfirm label="Daily Log" onConfirm={handleDailyLog} showRationale={false} />
      {card.source === 'slack' && card.draft_response && (
        <button onClick={() => handleSendDraft('send-slack')}>Send Draft</button>
      )}
      {card.source === 'gmail' && card.draft_response && (
        <button onClick={() => handleSendDraft('send-email')}>Send Draft</button>
      )}
      <button onClick={handleOpenSession}>Open Session</button>
    </div>
  )
}
