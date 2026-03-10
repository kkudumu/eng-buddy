import { describe, it, expect, beforeEach } from 'vitest'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { Sidebar } from '../Sidebar'
import { useUIStore } from '../../../stores/ui'

beforeEach(() => {
  useUIStore.setState({ activeSource: 'all' })
})

const mockCounts = { pending: 5, held: 2, approved: 3, completed: 10, failed: 1 }
const mockSourceCounts: Record<string, number> = {
  gmail: 3,
  slack: 2,
  jira: 4,
  freshservice: 1,
  calendar: 2,
}

describe('Sidebar', () => {
  it('renders all source filters', () => {
    render(<Sidebar counts={mockCounts} sourceCounts={mockSourceCounts} />)
    expect(screen.getByText('All')).toBeInTheDocument()
    expect(screen.getByText('Gmail')).toBeInTheDocument()
    expect(screen.getByText('Slack')).toBeInTheDocument()
    expect(screen.getByText('Jira')).toBeInTheDocument()
  })

  it('shows count badges', () => {
    render(<Sidebar counts={mockCounts} sourceCounts={mockSourceCounts} />)
    expect(screen.getByText('3')).toBeInTheDocument() // gmail
  })

  it('highlights active source', () => {
    useUIStore.setState({ activeSource: 'gmail' })
    render(<Sidebar counts={mockCounts} sourceCounts={mockSourceCounts} />)
    const gmailItem = screen.getByText('Gmail').closest('button')
    expect(gmailItem?.className).toContain('active')
  })

  it('changes active source on click', async () => {
    render(<Sidebar counts={mockCounts} sourceCounts={mockSourceCounts} />)
    await userEvent.click(screen.getByText('Slack'))
    expect(useUIStore.getState().activeSource).toBe('slack')
  })
})
