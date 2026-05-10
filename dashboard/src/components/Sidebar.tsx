import { NavLink, useNavigate } from 'react-router-dom'
import { Cpu, Crown, HelpCircle, LayoutDashboard, LogOut, ScrollText, Settings, ShieldAlert, Ticket, Users } from 'lucide-react'

import { radius, spacing, uiVars } from '../../../shared/ui-system/tokens'
import { clearAuth, getStoredUser } from '../lib/auth'
import { useI18n } from '../lib/i18n'

const NAV = [
  { to: '/', label: 'nav.workspace', icon: LayoutDashboard },
  { to: '/members', label: 'nav.members', icon: Users },
  { to: '/rules', label: 'nav.rules', icon: ShieldAlert },
  { to: '/activity', label: 'nav.activity', icon: ScrollText },
  { to: '/automation', label: 'nav.automation', icon: Cpu },
  { to: '/faq', label: 'nav.faq', icon: HelpCircle },
  { to: '/summaries', label: 'nav.summaries', icon: ScrollText },
  { to: '/subscriptions', label: 'nav.subscriptions', icon: Ticket },
  { to: '/owner', label: 'nav.owner', icon: Crown },
  { to: '/settings', label: 'nav.settings', icon: Settings },
]

export default function Sidebar({ onNavClick }: { onNavClick?: () => void }) {
  const navigate = useNavigate()
  const user = getStoredUser()
  const { t, lang, setLang } = useI18n()

  function handleLogout() {
    clearAuth()
    navigate('/login')
  }

  return (
    <aside
      style={{
        width: 252,
        display: 'flex',
        flexDirection: 'column',
        padding: `${spacing.lg}px 0`,
        borderRight: `1px solid ${uiVars.border}`,
        background: uiVars.surface,
        height: '100%',
      }}
    >
      <div
        style={{
          flex: 1,
          display: 'flex',
          flexDirection: 'column',
          overflow: 'hidden',
        }}
      >
        {/* Language toggle for sidebar */}
        <div style={{ padding: `0 ${spacing.lg}px ${spacing.sm}px`, display: 'flex', justifyContent: 'flex-end' }}>
          <button className="lang-toggle" onClick={() => setLang(lang === 'en' ? 'ar' : 'en')}>
            {t('lang.switch')}
          </button>
        </div>

        <div style={{ padding: `${spacing.xl}px ${spacing.lg}px`, borderBottom: `1px solid ${uiVars.border}` }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
            <div style={{ width: 36, height: 36, borderRadius: radius.md, background: uiVars.primary, color: uiVars.primaryText, display: 'grid', placeItems: 'center' }}>
              <svg width="14" height="14" viewBox="0 0 24 24" fill="white"><path d="M12 0C5.37 0 0 5.37 0 12s5.37 12 12 12 12-5.37 12-12S18.63 0 12 0zm5.94 8.19l-2.02 9.52c-.15.68-.54.84-1.08.52l-3-2.21-1.45 1.4c-.16.16-.3.3-.61.3l.21-3.04 5.53-5c.24-.21-.05-.33-.37-.12L6.26 14.5l-2.95-.92c-.64-.2-.65-.64.14-.95l11.56-4.46c.53-.19.99.13.93.02z"/></svg>
            </div>
            <div>
              <div style={{ fontSize: 17, fontWeight: 800, color: uiVars.text }}>{t('app.name')}</div>
              <div style={{ fontSize: 13, color: uiVars.textMuted }}>{t('app.desc')}</div>
            </div>
          </div>
        </div>

        <nav style={{ flex: 1, padding: `${spacing.sm}px`, overflowY: 'auto', display: 'grid', gap: 2 }}>
          {NAV.map(({ to, label, icon: Icon }) => (
            <NavLink
              key={to}
              to={to}
              end={to === '/'}
              onClick={onNavClick}
              style={({ isActive }) => ({
                display: 'flex',
                alignItems: 'center',
                gap: 10,
                padding: '10px 12px',
                borderRadius: radius.md,
                color: isActive ? uiVars.text : uiVars.textMuted,
                background: isActive ? uiVars.bgMuted : 'transparent',
                border: `1px solid ${isActive ? uiVars.borderStrong : 'transparent'}`,
                fontWeight: isActive ? 700 : 600,
              })}
            >
              <Icon size={15} />
              {t(label)}
            </NavLink>
          ))}
        </nav>

        <div style={{ padding: `${spacing.lg}px`, borderTop: `1px solid ${uiVars.border}` }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: 10 }}>
            <div style={{ width: 32, height: 32, borderRadius: radius.md, background: uiVars.bgMuted, color: uiVars.primary, display: 'grid', placeItems: 'center', fontSize: 12, fontWeight: 800 }}>
              {user?.username?.[0]?.toUpperCase() ?? 'U'}
            </div>
            <div style={{ minWidth: 0 }}>
              <div style={{ fontSize: 13, fontWeight: 800 }}>{user?.username ?? 'User'}</div>
              <div style={{ fontSize: 12, color: uiVars.textMuted }}>{user?.role ?? 'admin'}</div>
            </div>
          </div>
          <button onClick={handleLogout} style={{ background: 'none', border: 'none', padding: 0, display: 'flex', alignItems: 'center', gap: 8, color: uiVars.textMuted, cursor: 'pointer', fontWeight: 700 }}>
            <LogOut size={13} />
            {t('sidebar.logout')}
          </button>
        </div>
      </div>
    </aside>
  )
}
