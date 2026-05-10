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
  base: '/webapp/modbot/',
  build: {
    outDir: '../../bot/dashboard/frontend/modbot',
    emptyOutDir: true,
  },
  server: {
    port: 5177,
    host: '0.0.0.0',
    allowedHosts: ['mod.hamedco.com'],
    fs: {
      allow: ['..'],
    },
  },
})
