/**
 * PulseEngine wordmark — SVG text-based logo.
 * "PULSE" in Geist 600 teal + "ENGINE" in Geist 300 text-secondary + 2px teal accent line.
 */

interface PulseLogoProps {
  /** Width in px. Height scales proportionally. Defaults to 140. */
  width?: number
  className?: string
}

export function PulseLogo({ width = 140, className = '' }: PulseLogoProps) {
  // SVG viewBox is 140×24 — scaled by the width prop
  const height = Math.round((width / 140) * 24)

  return (
    <svg
      viewBox="0 0 140 24"
      width={width}
      height={height}
      fill="none"
      xmlns="http://www.w3.org/2000/svg"
      aria-label="PulseEngine"
      className={className}
    >
      {/* "PULSE" — weight 600, teal */}
      <text
        x="0"
        y="18"
        fontFamily="Geist, system-ui, sans-serif"
        fontSize="16"
        fontWeight="600"
        fill="var(--status-excellent)"
        letterSpacing="0.03em"
      >
        PULSE
      </text>

      {/* 2px × 16px accent line between words (spec §5) */}
      <rect x="58" y="4" width="2" height="16" fill="var(--status-excellent)" rx="1" />

      {/* "ENGINE" — weight 300, text-secondary */}
      <text
        x="64"
        y="18"
        fontFamily="Geist, system-ui, sans-serif"
        fontSize="16"
        fontWeight="300"
        fill="var(--text-secondary)"
        letterSpacing="0.03em"
      >
        ENGINE
      </text>
    </svg>
  )
}

/** "PE" monogram — for favicon/compact usage */
export function PulseMonogram({ size = 32 }: { size?: number }) {
  return (
    <svg
      viewBox="0 0 32 32"
      width={size}
      height={size}
      fill="none"
      xmlns="http://www.w3.org/2000/svg"
      aria-label="PE"
    >
      <rect width="32" height="32" rx="6" fill="var(--bg-card)" />
      <text
        x="4"
        y="23"
        fontFamily="Geist, system-ui, sans-serif"
        fontSize="17"
        fontWeight="600"
        fill="var(--status-excellent)"
        letterSpacing="-0.03em"
      >
        PE
      </text>
    </svg>
  )
}
