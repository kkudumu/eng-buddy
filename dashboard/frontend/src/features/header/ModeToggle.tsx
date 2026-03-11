import { useUIStore } from '../../stores/ui'
import { useUpdateSettings } from '../../hooks/useSettings'

export function ModeToggle() {
  const mode = useUIStore((s) => s.mode)
  const toggleMode = useUIStore((s) => s.toggleMode)
  const update = useUpdateSettings()
  const handleClick = () => {
    const nextMode = mode === 'dark' ? 'light' : 'dark'
    toggleMode()
    update.mutate({ mode: nextMode })
  }
  return (
    <button onClick={handleClick} aria-label="Toggle light and dark mode" type="button">
      {mode === 'dark' ? '\u263E' : '\u2600'}
    </button>
  )
}
