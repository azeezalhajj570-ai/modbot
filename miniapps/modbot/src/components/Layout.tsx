import React from 'react'
import { clsx, type ClassValue } from 'clsx'
import { twMerge } from 'tailwind-merge'
import { useLang } from './LanguageContext'
import type { SubscriptionInfo, PlanLimits } from '@miniapp/shared'

function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs))
}

interface LayoutProps {
  children: React.ReactNode
  activeTab: string
  onTabChange: (tab: string) => void
  onRefresh?: () => void
  subscription?: SubscriptionInfo
  planLimits?: PlanLimits
}

const TAB_IDS = ['dashboard', 'moderation', 'tasks', 'events'] as const

function tabIcon(id: string): string {
  const icons: Record<string, string> = {
    dashboard: 'dashboard',
    moderation: 'gpp_maybe',
    tasks: 'assignment',
    events: 'notification_important',
  }
  return icons[id] || 'help'
}

export const Layout: React.FC<LayoutProps> = ({ children, activeTab, onTabChange, onRefresh, subscription, planLimits }) => {
  const { t, dir, toggleLang, lang } = useLang()

  const openDashboard = () => {
    const url = window.location.origin.replace('/webapp/modbot', '') + '/dashboard'
    try {
      const tg = (window as any).Telegram?.WebApp
      if (tg?.openLink) {
        tg.openLink(url)
        return
      }
    } catch {}
    window.open(url, '_blank')
  }

  return (
    <div dir={dir} className="bg-background text-on-surface min-h-screen" style={{ fontFamily: lang === 'ar' ? "'Noto Kufi Arabic', sans-serif" : 'inherit' }}>
      <header className="fixed top-0 left-0 w-full z-50 bg-white border-b border-slate-100 shadow-[0_2px_8px_rgba(0,0,0,0.05)] h-14 px-4 flex justify-between items-center">
        <div className="flex items-center gap-3">
          <div className="w-8 h-8 rounded-full bg-primary-container flex items-center justify-center text-on-primary font-bold overflow-hidden">
            <span className="material-symbols-outlined text-white">gavel</span>
          </div>
          <div>
            <h1 className="text-lg font-bold text-slate-900 font-headline-md leading-tight">{t('app.title')}</h1>
            {subscription && (
              <span className={`text-[10px] font-semibold px-1.5 py-0.5 rounded-full ${subscription.plan === 'free' ? 'bg-amber-100 text-amber-700' : subscription.plan === 'pro' ? 'bg-blue-100 text-blue-700' : 'bg-purple-100 text-purple-700'}`}>
                {subscription.plan.toUpperCase()}
              </span>
            )}
          </div>
        </div>
        <div className="flex items-center gap-2">
          {subscription?.plan === 'free' && (
            <button onClick={openDashboard} className="px-3 py-1.5 rounded-lg bg-primary text-white text-xs font-semibold hover:bg-primary/90 transition-colors">
              <span className="material-symbols-outlined text-sm align-middle mr-1">upgrade</span>
              Upgrade
            </button>
          )}
          {onRefresh && (
            <button onClick={onRefresh} title="Refresh data" className="p-2 rounded-full hover:bg-slate-50 transition-colors active:opacity-70">
              <span className="material-symbols-outlined text-primary">refresh</span>
            </button>
          )}
          <button onClick={toggleLang} title={lang === 'en' ? 'العربية' : 'English'} className="p-2 rounded-full hover:bg-slate-50 transition-colors active:opacity-70 text-sm font-medium text-primary">
            {lang === 'en' ? 'AR' : 'EN'}
          </button>
          <button onClick={openDashboard} title={t('header.open_browser')} className="p-2 rounded-full hover:bg-slate-50 transition-colors active:opacity-70">
            <span className="material-symbols-outlined text-primary">open_in_browser</span>
          </button>
        </div>
      </header>

      <main className="mt-20 px-4 max-w-5xl mx-auto space-y-gutter pb-24">
        {children}
      </main>

      <nav className="fixed bottom-0 left-0 w-full z-50 bg-white/95 backdrop-blur-md border-t border-slate-100 flex justify-around items-center h-16 px-2">
        {TAB_IDS.map(id => (
          <TabButton
            key={id}
            active={activeTab === id}
            icon={tabIcon(id)}
            label={t(`tab.${id}`)}
            onClick={() => onTabChange(id)}
          />
        ))}
      </nav>
    </div>
  )
}

const TabButton: React.FC<{ active: boolean; icon: string; label: string; onClick: () => void }> = ({
  active, icon, label, onClick,
}) => (
  <button
    onClick={onClick}
    className={cn(
      "flex flex-col items-center justify-center py-2 flex-1 transition-all active:scale-95",
      active ? "text-primary" : "text-slate-400"
    )}
  >
    <span className="material-symbols-outlined" style={{ fontVariationSettings: active ? "'FILL' 1" : "'FILL' 0" }}>
      {icon}
    </span>
    <span className="text-[10px] font-medium mt-1">{label}</span>
  </button>
)
