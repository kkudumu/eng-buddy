import { describe, it, expect } from 'vitest'
import { render, screen } from '@testing-library/react'
import { StatsBar } from '../StatsBar'

describe('StatsBar', () => {
  it('renders all stat values', () => {
    render(
      <StatsBar
        needsAction={12}
        autoResolved={34}
        draftAcceptRate={87}
        timeSavedMinutes={120}
      />,
    )
    expect(screen.getByText('12')).toBeInTheDocument()
    expect(screen.getByText('34')).toBeInTheDocument()
    expect(screen.getByText('87%')).toBeInTheDocument()
    expect(screen.getByText('2h 0m')).toBeInTheDocument()
  })

  it('renders stat labels', () => {
    render(
      <StatsBar needsAction={0} autoResolved={0} draftAcceptRate={0} timeSavedMinutes={0} />,
    )
    expect(screen.getByText('Needs Action')).toBeInTheDocument()
    expect(screen.getByText('Auto-Resolved')).toBeInTheDocument()
    expect(screen.getByText('Draft Accept Rate')).toBeInTheDocument()
    expect(screen.getByText('Time Saved')).toBeInTheDocument()
  })
})
