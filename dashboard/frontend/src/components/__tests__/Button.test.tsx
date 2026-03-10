import { describe, it, expect, vi } from 'vitest'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { Button } from '../Button'

describe('Button', () => {
  it('renders with label', () => {
    render(<Button label="Approve" onClick={() => {}} />)
    expect(screen.getByText('Approve')).toBeInTheDocument()
  })

  it('calls onClick when clicked', async () => {
    const onClick = vi.fn()
    render(<Button label="Approve" onClick={onClick} />)
    await userEvent.click(screen.getByText('Approve'))
    expect(onClick).toHaveBeenCalledOnce()
  })

  it('renders ghost variant', () => {
    render(<Button label="Cancel" variant="ghost" onClick={() => {}} />)
    const btn = screen.getByText('Cancel')
    expect(btn.className).toContain('ghost')
  })

  it('is disabled when disabled prop is true', () => {
    render(<Button label="Send" disabled onClick={() => {}} />)
    expect(screen.getByText('Send')).toBeDisabled()
  })
})
