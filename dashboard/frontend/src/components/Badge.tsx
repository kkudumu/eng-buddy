import styles from './Badge.module.css'

interface BadgeProps {
  text: string
  color?: 'pink' | 'mint' | 'blue' | 'coral' | 'muted'
}

export function Badge({ text, color = 'muted' }: BadgeProps) {
  return <span className={`${styles.badge} ${styles[color]}`}>{text}</span>
}
