import { describe, it, expect } from 'vitest'
import { render, screen } from '@testing-library/react'
import { Badge } from '../Badge'

describe('Badge', () => {
  it('renders text', () => {
    render(<Badge text="API" />)
    expect(screen.getByText('API')).toBeInTheDocument()
  })

  it('applies color variant', () => {
    render(<Badge text="MCP" color="mint" />)
    const badge = screen.getByText('MCP')
    expect(badge.className).toContain('mint')
  })
})
