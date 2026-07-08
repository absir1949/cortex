/** @type {import('tailwindcss').Config} */
export default {
  content: ['./index.html', './src/**/*.{ts,tsx}'],
  theme: {
    extend: {
      colors: {
        bg: '#f8f7f2',
        panel: '#ffffff',
        border: '#dedbd2',
        text: '#20211f',
        muted: '#6c6f6b',
        accent: '#3f5f84',
        accentAlt: '#8a563d',
        danger: '#b24a3c',
      },
    },
  },
  plugins: [],
}
