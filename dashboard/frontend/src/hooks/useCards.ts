import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { fetchCards, performCardAction } from '../api/client'
import type { CardSource } from '../api/types'

export function useCards(source: CardSource) {
  return useQuery({
    queryKey: ['cards', source],
    queryFn: () => fetchCards(source),
  })
}

export function useCardAction() {
  const queryClient = useQueryClient()

  return useMutation({
    mutationFn: ({ cardId, action, body }: { cardId: number; action: string; body?: Record<string, unknown> }) =>
      performCardAction(cardId, action, body),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['cards'] })
    },
  })
}
