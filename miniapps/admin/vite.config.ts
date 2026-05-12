import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import { resolve } from 'path'
import { fileURLToPath } from 'url'

const __dirname = fileURLToPath(new URL('.', import.meta.url))

export default defineConfig({
  plugins: [react()],
  define: {
    'import.meta.env.VITE_APP_BOUNDARY': JSON.stringify('admin'),
  },
  resolve: {
    alias: {
      '@miniapp/shared': resolve(__dirname, '../../miniapp-shared/src'),
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
