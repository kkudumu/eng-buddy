import { ChibiMascot } from '../../components/ChibiMascot'
import type { MascotMood } from '../../components/ChibiMascot'
import { ThemePicker } from '../header/ThemePicker'
import { ModeToggle } from '../header/ModeToggle'
import { TerminalPicker } from '../header/TerminalPicker'
import { RestartButton } from '../header/RestartButton'
import { PollerTimers } from '../header/PollerTimers'
import { NotificationToggle } from '../header/NotificationToggle'
import { useSettings } from '../../hooks/useSettings'
import styles from './Header.module.css'

interface HeaderProps {
  pendingCount: number
  isLoading: boolean
  onBriefingClick?: () => void
}

function getMood(pendingCount: number, isLoading: boolean): MascotMood {
  if (isLoading) return 'thinking'
  if (pendingCount === 0) return 'happy'
  if (pendingCount > 10) return 'sleepy'
  return 'happy'
}

export function Header({ pendingCount, isLoading, onBriefingClick }: HeaderProps) {
  useSettings()
  return (
    <header className={styles.header}>
      <div className={styles.titleGroup}>
        <ChibiMascot mood={getMood(pendingCount, isLoading)} size={40} />
        <span className={styles.title}>ENG-BUDDY</span>
        {onBriefingClick && (
          <button onClick={onBriefingClick} className={styles.briefingBtn}>Briefing</button>
        )}
      </div>
      <PollerTimers />
      <div className={styles.controls}>
        <ThemePicker />
        <ModeToggle />
        <TerminalPicker />
        <NotificationToggle />
        <RestartButton />
      </div>
    </header>
  )
}
