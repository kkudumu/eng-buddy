import { useUIStore } from '../../stores/ui'
import { useUpdateSettings } from '../../hooks/useSettings'

export function NotificationToggle() {
  const enabled = useUIStore((s) => s.macosNotifications)
  const setEnabled = useUIStore((s) => s.setMacosNotifications)
  const update = useUpdateSettings()
  const handleChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    setEnabled(e.target.checked)
    update.mutate({ macos_notifications: e.target.checked })
  }
  return (
    <label style={{ display: 'flex', alignItems: 'center', gap: '4px', fontSize: '0.7rem', color: 'var(--muted)' }}>
      <input type="checkbox" checked={enabled} onChange={handleChange} />
      Notify
    </label>
  )
}
