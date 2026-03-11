import { useEffect } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { fetchSettings, updateSettings } from '../api/client'
import { useUIStore } from '../stores/ui'
import type { SettingsResponse } from '../api/types'

export function useSettings() {
  const hydrateSettings = useUIStore((s) => s.hydrateSettings)
  const query = useQuery({
    queryKey: ['settings'],
    queryFn: fetchSettings,
    staleTime: 60_000,
  })
  useEffect(() => {
    if (query.data) hydrateSettings(query.data)
  }, [query.data, hydrateSettings])
  return query
}

export function useUpdateSettings() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (body: Partial<SettingsResponse>) => updateSettings(body),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['settings'] }),
  })
}
