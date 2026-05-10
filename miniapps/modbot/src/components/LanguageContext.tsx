import React, { createContext, useContext, useState, useCallback } from 'react'
import type { Lang } from '../i18n'
import { t as _t, dir as _dir, LANGUAGES } from '../i18n'

interface LanguageContextValue {
  lang: Lang
  setLang: (l: Lang) => void
  t: (key: string, params?: Record<string, string | number>) => string
  dir: 'ltr' | 'rtl'
  toggleLang: () => void
}

const LanguageContext = createContext<LanguageContextValue>({
  lang: 'en',
  setLang: () => {},
  t: (k: string) => k,
  dir: 'ltr',
  toggleLang: () => {},
})

export const useLang = () => useContext(LanguageContext)

function detectLang(): Lang {
  try {
    const params = new URLSearchParams(window.location.search)
    const query = params.get('lang')
    if (query === 'ar' || query === 'en') return query
    const tg = (window as any).Telegram?.WebApp
    if (tg?.initDataUnsafe?.user?.language_code?.startsWith('ar')) return 'ar'
    if (navigator.language?.startsWith('ar')) return 'ar'
  } catch {}
  return 'en'
}

export const LanguageProvider: React.FC<{ children: React.ReactNode }> = ({ children }) => {
  const [lang, setLangState] = useState<Lang>(() => detectLang())

  const setLang = useCallback((l: Lang) => {
    setLangState(l)
    try {
      const url = new URL(window.location.href)
      url.searchParams.set('lang', l)
      window.history.replaceState({}, '', url.toString())
    } catch {}
  }, [])

  const toggleLang = useCallback(() => {
    setLang(lang === 'en' ? 'ar' : 'en')
  }, [lang, setLang])

  const translate = useCallback(
    (key: string, params?: Record<string, string | number>) => _t(lang, key, params),
    [lang],
  )

  return (
    <LanguageContext.Provider value={{ lang, setLang, t: translate, dir: _dir(lang), toggleLang }}>
      {children}
    </LanguageContext.Provider>
  )
}

export { LANGUAGES }
