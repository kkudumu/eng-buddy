import { useUIStore } from '../../stores/ui'
import { useUpdateSettings } from '../../hooks/useSettings'
import type { ThemeName } from '../../stores/ui'

const themes: { value: ThemeName; label: string }[] = [
  { value: 'neon-dreams', label: 'Neon Dreams' },
  { value: 'midnight-ops', label: 'Midnight Ops' },
  { value: 'soft-kitty', label: 'Soft Kitty' },
]

export function ThemePicker() {
  const theme = useUIStore((s) => s.theme)
  const setTheme = useUIStore((s) => s.setTheme)
  const update = useUpdateSettings()
  const handleChange = (e: React.ChangeEvent<HTMLSelectElement>) => {
    const value = e.target.value as ThemeName
    setTheme(value)
    update.mutate({ theme: value })
  }
  return (
    <select value={theme} onChange={handleChange} aria-label="Theme">
      {themes.map((t) => (
        <option key={t.value} value={t.value}>{t.label}</option>
      ))}
    </select>
  )
}
