import { useUIStore } from '../../stores/ui'
import { useUpdateSettings } from '../../hooks/useSettings'
import type { TerminalName } from '../../stores/ui'

const terminals: TerminalName[] = ['Terminal', 'Warp', 'iTerm', 'Alacritty', 'kitty']

export function TerminalPicker() {
  const terminal = useUIStore((s) => s.terminal)
  const setTerminal = useUIStore((s) => s.setTerminal)
  const update = useUpdateSettings()
  const handleChange = (e: React.ChangeEvent<HTMLSelectElement>) => {
    const value = e.target.value as TerminalName
    setTerminal(value)
    update.mutate({ terminal: value })
  }
  return (
    <select value={terminal} onChange={handleChange} aria-label="Terminal">
      {terminals.map((t) => (
        <option key={t} value={t}>{t}</option>
      ))}
    </select>
  )
}
