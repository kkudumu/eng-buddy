import { describe, it, expect } from 'vitest'
import { render, screen } from '@testing-library/react'
import { ChibiMascot } from '../ChibiMascot'

describe('ChibiMascot', () => {
  it('renders with happy mood', () => {
    render(<ChibiMascot mood="happy" />)
    expect(screen.getByLabelText('mascot-happy')).toBeInTheDocument()
  })

  it('renders with thinking mood', () => {
    render(<ChibiMascot mood="thinking" />)
    expect(screen.getByLabelText('mascot-thinking')).toBeInTheDocument()
  })

  it('renders with sleepy mood', () => {
    render(<ChibiMascot mood="sleepy" />)
    expect(screen.getByLabelText('mascot-sleepy')).toBeInTheDocument()
  })

  it('renders with excited mood', () => {
    render(<ChibiMascot mood="excited" />)
    expect(screen.getByLabelText('mascot-excited')).toBeInTheDocument()
  })
})
