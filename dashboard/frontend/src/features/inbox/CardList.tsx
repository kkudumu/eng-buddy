import { useCards } from '../../hooks/useCards'
import { useUIStore } from '../../stores/ui'
import { CardItem } from './CardItem'
import styles from './CardList.module.css'

export function CardList() {
  const activeSource = useUIStore((s) => s.activeSource)
  const { data, isLoading } = useCards(activeSource)

  if (isLoading) {
    return (
      <div className={styles.list} data-testid="card-list-loading">
        {[1, 2, 3].map((i) => (
          <div key={i} className={`skeleton ${styles.skeletonCard}`} />
        ))}
      </div>
    )
  }

  const cards = data?.cards ?? []

  if (cards.length === 0) {
    return <div className={styles.empty}>No cards right now. All clear!</div>
  }

  return (
    <div className={styles.list}>
      {cards.map((card, index) => (
        <CardItem
          key={card.id}
          card={card}
          style={{
            animation: `fadeUp 0.3s ease-out both`,
            animationDelay: `${index * 50}ms`,
          }}
        />
      ))}
    </div>
  )
}
