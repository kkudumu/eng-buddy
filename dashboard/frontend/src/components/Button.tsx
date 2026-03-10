import styles from './Button.module.css'

interface ButtonProps {
  label: string
  onClick: () => void
  variant?: 'primary' | 'ghost' | 'mint' | 'coral'
  disabled?: boolean
}

export function Button({ label, onClick, variant = 'primary', disabled = false }: ButtonProps) {
  return (
    <button
      className={`${styles.button} ${styles[variant]}`}
      onClick={onClick}
      disabled={disabled}
    >
      {label}
    </button>
  )
}
