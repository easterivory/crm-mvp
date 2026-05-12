/** @type {import('tailwindcss').Config} */
export default {
  content: ['./index.html', './src/**/*.{js,ts,jsx,tsx}'],
  theme: {
    extend: {
      colors: {
        background: '#0B0F19',
        surface: {
          DEFAULT: '#131826',
          muted: 'rgba(255,255,255,0.03)',
          raised: '#182033',
        },
        primary: {
          DEFAULT: '#8B5CF6',
          50: '#F3E8FF',
          100: '#E9D5FF',
          300: '#C4B5FD',
          400: '#A78BFA',
          500: '#8B5CF6',
          600: '#7C3AED',
          700: '#6D28D9',
        },
        accent: {
          DEFAULT: '#22D3EE',
          300: '#67E8F9',
          400: '#22D3EE',
          500: '#06B6D4',
          600: '#0891B2',
        },
        ink: '#E5E7EB',
      },
      boxShadow: {
        'glow-primary': '0 0 28px rgba(139, 92, 246, 0.35)',
        'glow-accent': '0 0 28px rgba(34, 211, 238, 0.30)',
        'glow-danger': '0 0 28px rgba(248, 113, 113, 0.25)',
        card: '0 18px 60px rgba(0, 0, 0, 0.35)',
      },
      backgroundImage: {
        'neon-radial':
          'radial-gradient(circle at 20% 0%, rgba(139,92,246,0.16), transparent 34%), radial-gradient(circle at 80% 10%, rgba(34,211,238,0.12), transparent 30%)',
      },
    },
  },
  plugins: [],
}
