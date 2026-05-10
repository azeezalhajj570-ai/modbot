import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'

import { init } from '@telegram-apps/sdk'
import { AppRoot } from '@telegram-apps/telegram-ui'
import '@telegram-apps/telegram-ui/dist/styles.css'
import './index.css'

import App from './App'

try {
  if (window.Telegram?.WebApp) {
    void init()
  }
} catch (error) {
  console.warn('Telegram Mini App SDK init skipped:', error)
}

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <AppRoot>
      <App />
    </AppRoot>
  </StrictMode>,
)
