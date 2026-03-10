import { describe, it, expect } from 'vitest'
import { render, screen } from '@testing-library/react'
import { CardItem } from '../CardItem'
import type { Card } from '../../../api/types'

const mockCard: Card = {
  id: 1,
  source: 'gmail',
  classification: 'high',
  status: 'pending',
  section: 'needs_action',
  summary: 'RE: Q3 Budget Review - needs approval by Friday',
  context_notes: 'From: cfo@company.com',
  timestamp: '2026-03-10T09:00:00Z',
  proposed_actions: [
    { type: 'send-email', draft: 'Thanks for sharing. I will review and approve by EOD Thursday.' },
  ],
  draft_response: 'Thanks for sharing. I will review and approve by EOD Thursday.',
}

describe('CardItem', () => {
  it('renders card summary', () => {
    render(<CardItem card={mockCard} />)
    expect(screen.getByText(/Q3 Budget Review/)).toBeInTheDocument()
  })

  it('renders source badge', () => {
    render(<CardItem card={mockCard} />)
    expect(screen.getByText('gmail')).toBeInTheDocument()
  })

  it('renders timestamp', () => {
    render(<CardItem card={mockCard} />)
    // Timezone-agnostic: just check that some time string is rendered in the meta span
    const expected = new Date('2026-03-10T09:00:00Z').toLocaleTimeString([], { hour: 'numeric', minute: '2-digit' })
    expect(screen.getByText(expected)).toBeInTheDocument()
  })

  it('shows draft when present', () => {
    render(<CardItem card={mockCard} />)
    expect(screen.getByText(/I will review and approve/)).toBeInTheDocument()
  })

  it('applies source-specific glow class', () => {
    const { container } = render(<CardItem card={mockCard} />)
    const cardEl = container.firstChild as HTMLElement
    expect(cardEl.className).toContain('gmail')
  })
})
