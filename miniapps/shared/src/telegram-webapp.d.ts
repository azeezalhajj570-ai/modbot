export {}

declare global {
  interface TelegramWebAppHapticFeedback {
    notificationOccurred(type: 'error' | 'success' | 'warning'): void
  }

  interface TelegramWebApp {
    initData?: string
    ready?: () => void
    expand?: () => void
    HapticFeedback?: TelegramWebAppHapticFeedback
  }

  interface Window {
    Telegram?: {
      WebApp?: TelegramWebApp
    }
  }
}
