import { ChibiMascot } from '../../components/ChibiMascot'
import type { MascotMood } from '../../components/ChibiMascot'
import styles from './Header.module.css'

interface HeaderProps {
  pendingCount: number
  isLoading: boolean
}

function getMood(pendingCount: number, isLoading: boolean): MascotMood {
  if (isLoading) return 'thinking'
  if (pendingCount === 0) return 'happy'
  if (pendingCount > 10) return 'sleepy'
  return 'happy'
}

export function Header({ pendingCount, isLoading }: HeaderProps) {
  return (
    <header className={styles.header}>
      <div className={styles.titleGroup}>
        <ChibiMascot mood={getMood(pendingCount, isLoading)} size={40} />
        <span className={styles.title}>ENG-BUDDY</span>
      </div>
    </header>
  )
}
