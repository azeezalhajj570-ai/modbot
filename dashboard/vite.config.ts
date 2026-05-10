import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig({
  plugins: [react()],
  base: '/dashboard/',
  build: {
    outDir: '../bot/dashboard/browser',
    emptyOutDir: true,
  },
  server: {
    port: 5174,
    fs: {
      allow: ['..'],
    },
  },
})
