import { describe, it, expect } from 'vitest'
import { render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { Sidebar } from '../Sidebar'

function renderSidebar(initialPath = '/app/inbox') {
  return render(
    <MemoryRouter initialEntries={[initialPath]}>
      <Sidebar />
    </MemoryRouter>,
  )
}

describe('Sidebar', () => {
  it('renders all nav items', () => {
    renderSidebar()
    expect(screen.getByText('Inbox')).toBeInTheDocument()
    expect(screen.getByText('Tasks')).toBeInTheDocument()
    expect(screen.getByText('Jira')).toBeInTheDocument()
    expect(screen.getByText('Calendar')).toBeInTheDocument()
    expect(screen.getByText('Daily')).toBeInTheDocument()
    expect(screen.getByText('Learnings')).toBeInTheDocument()
    expect(screen.getByText('Knowledge')).toBeInTheDocument()
    expect(screen.getByText('Suggestions')).toBeInTheDocument()
    expect(screen.getByText('Playbooks')).toBeInTheDocument()
  })

  it('renders nav items as links', () => {
    renderSidebar()
    const inboxLink = screen.getByText('Inbox').closest('a')
    expect(inboxLink).toBeInTheDocument()
    expect(inboxLink).toHaveAttribute('href', '/app/inbox')
  })

  it('highlights active nav item', () => {
    renderSidebar('/app/tasks')
    const tasksLink = screen.getByText('Tasks').closest('a')
    expect(tasksLink?.className).toContain('active')
  })

  it('does not highlight inactive nav items', () => {
    renderSidebar('/app/inbox')
    const tasksLink = screen.getByText('Tasks').closest('a')
    expect(tasksLink?.className).not.toContain('active')
  })
})
