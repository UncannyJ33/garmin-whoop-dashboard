/** @type {import('tailwindcss').Config} */
export default {
  content: ['./index.html', './src/**/*.{js,ts,jsx,tsx}'],
  darkMode: 'class',
  theme: {
    extend: {
      colors: {
        surface: {
          DEFAULT: 'var(--color-surface)',
          raised: 'var(--color-surface-raised)',
          overlay: 'var(--color-surface-overlay)',
          border: 'var(--color-surface-border)',
        },
        good: {
          DEFAULT: '#22c55e',
          muted: '#16a34a',
          bg: 'rgba(34,197,94,0.12)',
        },
        moderate: {
          DEFAULT: '#f59e0b',
          muted: '#d97706',
          bg: 'rgba(245,158,11,0.12)',
        },
        poor: {
          DEFAULT: '#ef4444',
          muted: '#dc2626',
          bg: 'rgba(239,68,68,0.12)',
        },
        brand: {
          DEFAULT: '#818cf8',
          muted: '#6366f1',
          bg: 'rgba(129,140,248,0.12)',
        },
        // Chart colors
        chart: {
          blue: '#60a5fa',
          orange: '#fb923c',
          purple: '#c084fc',
          teal: '#2dd4bf',
          slate: '#94a3b8',
        },
      },
      fontFamily: {
        sans: ['Inter var', 'Inter', 'system-ui', 'sans-serif'],
        mono: ['JetBrains Mono', 'ui-monospace', 'monospace'],
      },
      fontSize: {
        '2xs': ['0.625rem', { lineHeight: '1rem' }],
      },
      keyframes: {
        shimmer: {
          '0%': { backgroundPosition: '-200% 0' },
          '100%': { backgroundPosition: '200% 0' },
        },
        'fade-in': {
          from: { opacity: '0', transform: 'translateY(4px)' },
          to: { opacity: '1', transform: 'translateY(0)' },
        },
      },
      animation: {
        shimmer: 'shimmer 1.8s ease-in-out infinite',
        'fade-in': 'fade-in 0.2s ease-out',
      },
    },
  },
  plugins: [],
}
