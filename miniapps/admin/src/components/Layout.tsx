import React from 'react'
import { clsx, type ClassValue } from 'clsx'
import { twMerge } from 'tailwind-merge'

function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs))
}

interface LayoutProps {
  children: React.ReactNode
  activeTab: string
  onTabChange: (tab: string) => void
  title: string
  dashboardUrl: string
}

export const Layout: React.FC<LayoutProps> = ({ children, activeTab, onTabChange, title, dashboardUrl }) => {
  const openDashboard = () => {
    const url = dashboardUrl || 'https://modboard.hamedco.com/dashboard'
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
    <div className="bg-background text-on-surface min-h-screen">
      <header className="fixed top-0 left-0 w-full z-50 bg-white border-b border-slate-100 shadow-[0_2px_8px_rgba(0,0,0,0.05)] h-14 px-4 flex justify-between items-center">
        <div className="flex items-center gap-3">
          <div className="w-8 h-8 rounded-full bg-primary-container flex items-center justify-center text-on-primary font-bold overflow-hidden">
            <span className="material-symbols-outlined text-white">admin_panel_settings</span>
          </div>
          <h1 className="text-lg font-bold text-slate-900 font-headline-md">{title}</h1>
        </div>
        <div className="flex items-center gap-2">
          <button onClick={openDashboard} title="Open browser dashboard" className="p-2 rounded-full hover:bg-slate-50 transition-colors active:opacity-70">
            <span className="material-symbols-outlined text-primary">open_in_browser</span>
          </button>
          <button className="p-2 rounded-full hover:bg-slate-50 transition-colors active:opacity-70">
            <span className="material-symbols-outlined text-slate-500">notifications</span>
          </button>
        </div>
      </header>

      <main className="mt-20 px-4 max-w-5xl mx-auto space-y-gutter pb-24">
        {children}
      </main>

      <nav className="fixed bottom-0 left-0 w-full z-50 bg-white/95 backdrop-blur-md border-t border-slate-100 flex justify-around items-center h-16 px-2">
        <TabButton 
          active={activeTab === 'dashboard'} 
          icon="dashboard" 
          label="Dashboard" 
          onClick={() => onTabChange('dashboard')} 
        />
        <TabButton 
          active={activeTab === 'events'} 
          icon="event_note" 
          label="Events" 
          onClick={() => onTabChange('events')} 
        />
        <TabButton 
          active={activeTab === 'moderation'} 
          icon="security" 
          label="Moderation" 
          onClick={() => onTabChange('moderation')} 
        />
        <TabButton 
          active={activeTab === 'subscriptions'} 
          icon="payments" 
          label="Paid Access" 
          onClick={() => onTabChange('subscriptions')} 
        />
        <TabButton 
          active={activeTab === 'settings'} 
          icon="settings" 
          label="Settings" 
          onClick={() => onTabChange('settings')} 
        />
      </nav>
    </div>
  )
}

const TabButton: React.FC<{ active: boolean; icon: string; label: string; onClick: () => void }> = ({
  active,
  icon,
  label,
  onClick,
}) => (
  <button
    onClick={onClick}
    className={cn(
      "flex flex-col items-center justify-center py-2 flex-1 transition-all active:scale-95",
      active ? "text-primary" : "text-slate-400"
    )}
  >
    <span className={cn("material-symbols-outlined", active && "fill-current")} style={{ fontVariationSettings: active ? "'FILL' 1" : "'FILL' 0" }}>
      {icon}
    </span>
    <span className="font-['Inter'] text-[10px] font-medium mt-1">{label}</span>
  </button>
)
