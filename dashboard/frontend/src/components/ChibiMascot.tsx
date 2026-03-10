export type MascotMood = 'happy' | 'thinking' | 'sleepy' | 'excited'

interface ChibiMascotProps {
  mood: MascotMood
  size?: number
}

const faces: Record<MascotMood, { eyes: string; mouth: string; extras?: string }> = {
  happy: { eyes: '\u25cf  \u25cf', mouth: '\u03c9' },
  thinking: { eyes: '\u25cf  \u25d0', mouth: '\u03c9', extras: '?' },
  sleepy: { eyes: '\u2212  \u2212', mouth: '\u03c9', extras: 'z' },
  excited: { eyes: '\u2727  \u2727', mouth: '\u03c9', extras: '!' },
}

export function ChibiMascot({ mood, size = 48 }: ChibiMascotProps) {
  const face = faces[mood]

  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 64 64"
      aria-label={`mascot-${mood}`}
      style={mood === 'excited' ? { animation: 'bounce 0.6s ease-in-out infinite' } : undefined}
    >
      {/* Ears */}
      <polygon points="12,22 8,4 24,16" fill="#f4a8c8" opacity="0.8" />
      <polygon points="52,22 56,4 40,16" fill="#f4a8c8" opacity="0.8" />
      {/* Inner ears */}
      <polygon points="14,20 11,8 22,16" fill="#ff9b87" opacity="0.5" />
      <polygon points="50,20 53,8 42,16" fill="#ff9b87" opacity="0.5" />
      {/* Head */}
      <ellipse cx="32" cy="36" rx="22" ry="20" fill="#241832" stroke="#f4a8c8" strokeWidth="1.5" />
      {/* Eyes */}
      <text x="32" y="34" textAnchor="middle" fill="#f0e6ff" fontSize="8" fontFamily="monospace">
        {face.eyes}
      </text>
      {/* Mouth */}
      <text x="32" y="44" textAnchor="middle" fill="#f4a8c8" fontSize="10" fontFamily="monospace">
        {face.mouth}
      </text>
      {/* Extras */}
      {face.extras && (
        <text x="54" y="16" fill="#9ac4ff" fontSize="10" fontFamily="monospace" opacity="0.7">
          {face.extras}
        </text>
      )}
    </svg>
  )
}
