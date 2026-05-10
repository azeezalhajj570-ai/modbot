import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import { resolve } from 'path'

export default defineConfig({
  plugins: [react()],
  define: {
    'import.meta.env.VITE_APP_BOUNDARY': JSON.stringify('admin'),
  },
  resolve: {
    alias: {
      '@miniapp/shared': resolve(__dirname, '../shared/src'),
    },
  },
  base: '/webapp/admin/',
  build: {
    outDir: '../../bot/dashboard/frontend/admin',
    emptyOutDir: true,
  },
  server: {
    port: 5173,
    fs: {
      allow: ['..'],
    },
  },
})
