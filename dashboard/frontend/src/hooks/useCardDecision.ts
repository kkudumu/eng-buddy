import { useMutation, useQueryClient } from '@tanstack/react-query'
import { postDecision, performCardAction } from '../api/client'
import { useToastStore } from '../stores/toast'

interface DecisionAction {
  cardId: number
  action: string
  decision: 'approved' | 'rejected' | 'refined'
  rationale?: string
  followUp?: { endpoint: string; body?: Record<string, unknown> }
}

export function useCardDecision() {
  const queryClient = useQueryClient()
  const addToast = useToastStore((s) => s.addToast)
  return useMutation({
    mutationFn: async ({ cardId, action, decision, rationale, followUp }: DecisionAction) => {
      const result = await postDecision('cards', cardId, action, decision, rationale)
      if (followUp) {
        const body = { ...followUp.body, decision_event_id: result.decision_event_id }
        await performCardAction(cardId, followUp.endpoint, body)
      }
      return result
    },
    onSuccess: (_data, vars) => {
      queryClient.invalidateQueries({ queryKey: ['cards'] })
      addToast(`Card #${vars.cardId}: ${vars.action} ${vars.decision}`, 'success')
    },
    onError: (_err, vars) => {
      addToast(`Failed to ${vars.action} card #${vars.cardId}`, 'error')
    },
  })
}
