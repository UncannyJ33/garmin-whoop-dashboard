/** @type {import('tailwindcss').Config} */
export default {
  content: ['./index.html', './src/**/*.{js,ts,jsx,tsx}'],
  darkMode: 'class',
  theme: {
    extend: {
      colors: {
        // ── New design system tokens ─────────────────────────────────────
        base: 'var(--bg-primary)',
        card: {
          DEFAULT: 'var(--bg-card)',
          elevated: 'var(--bg-card-elevated)',
        },
        // Brand — distinct identity color, not a status indicator
        brand: {
          DEFAULT: 'var(--brand)',
          muted:   'var(--brand-muted)',
          border:  'var(--brand-border)',
        },
        // Status palette
        excellent: {
          DEFAULT: 'var(--status-excellent)',
          muted: 'var(--status-excellent-muted)',
        },
        caution: {
          DEFAULT: 'var(--status-caution)',
          muted: 'var(--status-caution-muted)',
        },
        alert: {
          DEFAULT: 'var(--status-alert)',
          dark: 'var(--status-alert-dark)',
          muted: 'var(--status-alert-muted)',
        },
        // Data visualization
        'data-primary':   'var(--data-primary)',
        'data-secondary': 'var(--data-secondary)',
        'data-tertiary':  'var(--data-tertiary)',
        'data-anomaly':   'var(--data-anomaly)',
        // Sleep stages — cohesive with overall palette
        sleep: {
          deep:  '#1e7a5a',
          light: '#3d6b9e',
          rem:   '#7a5ea0',
          awake: '#3d3d3d',
        },

        // ── Backwards-compat tokens (used by unrewritten pages) ──────────
        surface: {
          DEFAULT: 'var(--color-surface)',
          raised:  'var(--color-surface-raised)',
          overlay: 'var(--color-surface-overlay)',
          border:  'var(--color-surface-border)',
          card:    'var(--color-surface-raised)',
        },
        good: {
          DEFAULT: 'var(--status-excellent)',
          muted:   'var(--status-good)',
          bg:      'var(--status-excellent-muted)',
        },
        moderate: {
          DEFAULT: 'var(--status-caution)',
          muted:   '#ba7517',
          bg:      'var(--status-caution-muted)',
        },
        poor: {
          DEFAULT: 'var(--status-alert)',
          muted:   'var(--status-alert-dark)',
          bg:      'var(--status-alert-muted)',
        },
        // Chart colors (backwards compat)
        chart: {
          blue:   '#60a5fa',
          orange: '#ef9f27',
          purple: '#8b5fbf',
          teal:   'var(--status-excellent)',
          slate:  'rgba(255,255,255,0.30)',
        },
      },

      fontFamily: {
        sans:    ['DM Sans', 'system-ui', 'sans-serif'],
        mono:    ['IBM Plex Mono', 'ui-monospace', 'monospace'],
        display: ['Barlow Condensed', 'system-ui', 'sans-serif'],
      },

      fontSize: {
        '2xs': ['0.625rem', { lineHeight: '1rem' }],
      },

      borderRadius: {
        card:      '12px',
        'card-lg': '16px',
        'card-hero': '18px',
      },

      keyframes: {
        shimmer: {
          '0%':   { backgroundPosition: '-200% 0' },
          '100%': { backgroundPosition: '200% 0' },
        },
        'fade-in': {
          from: { opacity: '0', transform: 'translateY(32px)' },
          to:   { opacity: '1', transform: 'translateY(0)' },
        },
      },

      animation: {
        shimmer:  'shimmer 1.8s ease-in-out infinite',
        'fade-in':'fade-in 0.35s ease-out both',
      },
    },
  },
  plugins: [],
}
