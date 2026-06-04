/** @type {import('tailwindcss').Config} */
export default {
  content: ['./index.html', './src/**/*.{ts,tsx}'],
  theme: {
    extend: {
      colors: {
        bg: '#f4f7f5',
        panel: '#ffffff',
        border: '#dce6dd',
        text: '#17221d',
        muted: '#66756d',
        accent: '#149b68',
        accentAlt: '#315fd6',
        danger: '#c2413a',
      },
    },
  },
  plugins: [],
}
