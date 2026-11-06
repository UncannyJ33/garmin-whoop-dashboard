/**
 * PulseEngine wordmark — SVG text-based logo.
 * "PULSE" in DM Sans 600 brand blue + "ENGINE" in DM Sans 300 text-secondary + 2px brand accent line.
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
      {/* "PULSE" — weight 600, brand blue */}
      <text
        x="0"
        y="18"
        fontFamily="DM Sans, system-ui, sans-serif"
        fontSize="16"
        fontWeight="600"
        fill="var(--brand)"
        letterSpacing="0.03em"
      >
        PULSE
      </text>

      {/* 2px × 16px accent line between words */}
      <rect x="58" y="4" width="2" height="16" fill="var(--brand)" rx="1" />

      {/* "ENGINE" — weight 300, text-secondary */}
      <text
        x="64"
        y="18"
        fontFamily="DM Sans, system-ui, sans-serif"
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
