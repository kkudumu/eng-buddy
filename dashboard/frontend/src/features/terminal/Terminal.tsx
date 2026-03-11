import { useEffect, useRef } from 'react'
import { Terminal as XTerm } from 'xterm'
import { FitAddon } from '@xterm/addon-fit'
import 'xterm/css/xterm.css'
import styles from './Terminal.module.css'

interface TerminalProps {
  cardId: number
  decisionEventId: number
  onClose: () => void
}

export function Terminal({ cardId, decisionEventId, onClose }: TerminalProps) {
  const containerRef = useRef<HTMLDivElement>(null)
  const termRef = useRef<XTerm | null>(null)
  const wsRef = useRef<WebSocket | null>(null)
  useEffect(() => {
    if (!containerRef.current) return
    const term = new XTerm({
      theme: { background: '#000000', foreground: '#ffffff', cursor: '#ffffff' },
      fontFamily: 'JetBrains Mono, monospace',
      fontSize: 13,
      scrollback: 5000,
      cursorBlink: true,
    })
    const fitAddon = new FitAddon()
    term.loadAddon(fitAddon)
    term.open(containerRef.current)
    fitAddon.fit()
    termRef.current = term
    const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:'
    const url = `${protocol}//${window.location.host}/ws/execute/${cardId}?decision_event_id=${decisionEventId}`
    const ws = new WebSocket(url)
    wsRef.current = ws
    ws.onmessage = (e) => term.write(e.data)
    ws.onclose = () => onClose()
    ws.onerror = () => onClose()
    term.onData((data) => {
      if (ws.readyState === WebSocket.OPEN) ws.send(data)
    })
    const observer = new ResizeObserver(() => fitAddon.fit())
    observer.observe(containerRef.current)
    return () => {
      observer.disconnect()
      ws.close()
      term.dispose()
    }
  }, [cardId, decisionEventId, onClose])
  return <div ref={containerRef} className={styles.container} />
}
