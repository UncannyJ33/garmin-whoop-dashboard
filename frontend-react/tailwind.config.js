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
        // Status palette
        excellent: {
          DEFAULT: 'var(--status-excellent)',    // #5dcaa5
          muted: 'var(--status-excellent-muted)',
        },
        caution: {
          DEFAULT: 'var(--status-caution)',      // #ef9f27
          muted: 'var(--status-caution-muted)',
        },
        alert: {
          DEFAULT: 'var(--status-alert)',        // #e8775a
          dark: 'var(--status-alert-dark)',
          muted: 'var(--status-alert-muted)',
        },
        // Data visualization
        'data-primary':   'var(--data-primary)',
        'data-secondary': 'var(--data-secondary)',
        'data-tertiary':  'var(--data-tertiary)',
        'data-anomaly':   'var(--data-anomaly)',
        // Sleep stages
        sleep: {
          deep:  '#4a3d8f',
          light: '#6b7a99',
          rem:   '#8b5fbf',
          awake: '#4a4a50',
        },

        // ── Backwards-compat tokens (used by unrewritten pages) ──────────
        surface: {
          DEFAULT: 'var(--color-surface)',
          raised:  'var(--color-surface-raised)',
          overlay: 'var(--color-surface-overlay)',
          border:  'var(--color-surface-border)',
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
        brand: {
          DEFAULT: 'var(--status-excellent)',
          muted:   'var(--status-good)',
          bg:      'var(--status-excellent-muted)',
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
        sans: ['Geist', 'system-ui', 'sans-serif'],
        mono: ['Geist Mono', 'ui-monospace', 'monospace'],
      },

      fontSize: {
        '2xs': ['0.625rem', { lineHeight: '1rem' }],
      },

      borderRadius: {
        card:     '12px',
        'card-lg':'16px',
      },

      keyframes: {
        shimmer: {
          '0%':   { backgroundPosition: '-200% 0' },
          '100%': { backgroundPosition: '200% 0' },
        },
        'fade-in': {
          from: { opacity: '0', transform: 'translateY(4px)' },
          to:   { opacity: '1', transform: 'translateY(0)' },
        },
      },

      animation: {
        shimmer:  'shimmer 1.8s ease-in-out infinite',
        'fade-in':'fade-in 0.2s ease-out',
      },
    },
  },
  plugins: [],
}
