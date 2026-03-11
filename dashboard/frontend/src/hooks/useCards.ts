import { useQuery } from '@tanstack/react-query'
import { fetchCards } from '../api/client'
import type { CardSource } from '../api/types'

export function useCards(source: CardSource) {
  return useQuery({
    queryKey: ['cards', source],
    queryFn: () => fetchCards(source),
  })
}
