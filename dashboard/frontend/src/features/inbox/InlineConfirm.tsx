import { useState } from 'react'

interface InlineConfirmProps {
  label: string
  onConfirm: (rationale: string) => void
  showRationale?: boolean
  disabled?: boolean
}

export function InlineConfirm({ label, onConfirm, showRationale = true, disabled }: InlineConfirmProps) {
  const [confirming, setConfirming] = useState(false)
  const [rationale, setRationale] = useState('')
  if (!confirming) {
    return <button onClick={() => setConfirming(true)} disabled={disabled}>{label}</button>
  }
  return (
    <span style={{ display: 'inline-flex', gap: '4px', alignItems: 'center' }}>
      {showRationale && (
        <input type="text" placeholder="reason (optional)" value={rationale}
          onChange={(e) => setRationale(e.target.value)} style={{ fontSize: '0.75rem', width: '120px' }} />
      )}
      <button onClick={() => { onConfirm(rationale); setConfirming(false); setRationale('') }}>Confirm</button>
      <button onClick={() => { setConfirming(false); setRationale('') }}>Cancel</button>
    </span>
  )
}
