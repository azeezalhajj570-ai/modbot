import type { CSSProperties, ReactNode } from 'react'

const designStyles = `
  @import url('https://fonts.googleapis.com/css2?family=Lora:ital,wght@0,400;0,500;0,600;1,400&family=DM+Sans:wght@300;400;500;600&family=DM+Mono:wght@400;500&display=swap');

  :root {
    --miniapp-bg: #f5f0e8;
    --miniapp-bg-warm: #ede8df;
    --miniapp-bg-deep: #e5dfd4;
    --miniapp-surface: #faf7f2;
    --miniapp-border: #ddd6c9;
    --miniapp-border-soft: #e8e2d8;
    --miniapp-coral: #c96442;
    --miniapp-coral-dim: rgba(201,100,66,0.10);
    --miniapp-sage: #5a7a5a;
    --miniapp-sage-dim: rgba(90,122,90,0.12);
    --miniapp-sage-border: rgba(90,122,90,0.22);
    --miniapp-clay: #9c4a35;
    --miniapp-clay-dim: rgba(156,74,53,0.10);
    --miniapp-clay-border: rgba(156,74,53,0.22);
    --miniapp-slate: #4a6080;
    --miniapp-slate-dim: rgba(74,96,128,0.10);
    --miniapp-slate-border: rgba(74,96,128,0.22);
    --miniapp-ochre: #8a6b2a;
    --miniapp-ochre-dim: rgba(138,107,42,0.10);
    --miniapp-ochre-border: rgba(138,107,42,0.22);
    --miniapp-text-primary: #1a1612;
    --miniapp-text-secondary: #5a5248;
    --miniapp-text-muted: #7d746a;
    --miniapp-radius: 16px;
    --miniapp-radius-sm: 10px;
    --miniapp-radius-xs: 6px;
    --miniapp-shadow-sm: 0 1px 3px rgba(60,40,20,0.07), 0 1px 2px rgba(60,40,20,0.05);
    --miniapp-shadow-lg: 0 12px 40px rgba(60,40,20,0.12), 0 4px 12px rgba(60,40,20,0.06);
    --miniapp-serif: 'Lora', Georgia, serif;
    --miniapp-sans: 'DM Sans', sans-serif;
    --miniapp-mono: 'DM Mono', monospace;
  }

  body {
    margin: 0;
    background: var(--miniapp-bg);
    color: var(--miniapp-text-primary);
    font-family: var(--miniapp-sans);
  }
`

const frameStyle: CSSProperties = {
  minHeight: '100dvh',
  background: 'var(--miniapp-bg)',
  color: 'var(--miniapp-text-primary)',
  fontFamily: 'var(--miniapp-sans)',
  overflowX: 'hidden',
  position: 'relative',
}

const noiseStyle: CSSProperties = {
  position: 'fixed',
  inset: 0,
  pointerEvents: 'none',
  zIndex: 0,
  opacity: 0.028,
  backgroundImage:
    "url(\"data:image/svg+xml,%3Csvg viewBox='0 0 256 256' xmlns='http://www.w3.org/2000/svg'%3E%3Cfilter id='noise'%3E%3CfeTurbulence type='fractalNoise' baseFrequency='0.9' numOctaves='4' stitchTiles='stitch'/%3E%3C/filter%3E%3Crect width='100%25' height='100%25' filter='url(%23noise)'/%3E%3C/svg%3E\")",
  backgroundSize: '128px 128px',
}

const shellStyle: CSSProperties = {
  maxWidth: 860,
  margin: '0 auto',
  position: 'relative',
  zIndex: 1,
}

const headerStyle: CSSProperties = {
  position: 'sticky',
  top: 0,
  zIndex: 100,
  background: 'rgba(245,240,232,0.92)',
  backdropFilter: 'blur(24px) saturate(180%)',
  borderBottom: '1px solid var(--miniapp-border-soft)',
  padding: '14px 20px',
  display: 'flex',
  alignItems: 'center',
  justifyContent: 'space-between',
  gap: 16,
}

const mainStyle: CSSProperties = {
  padding: '20px 20px 110px',
  position: 'relative',
  zIndex: 1,
  display: 'grid',
  gap: 16,
}

const navTabsStyle: CSSProperties = {
  padding: '12px 20px 0',
  display: 'flex',
  gap: 2,
  overflowX: 'auto',
  scrollbarWidth: 'none',
  borderBottom: '1px solid var(--miniapp-border-soft)',
}

const surfaceStyle: CSSProperties = {
  background: 'var(--miniapp-surface)',
  border: '1px solid var(--miniapp-border-soft)',
  borderRadius: 'var(--miniapp-radius)',
  boxShadow: 'var(--miniapp-shadow-sm)',
  overflow: 'hidden',
}

const inputStyle: CSSProperties = {
  width: '100%',
  background: 'var(--miniapp-bg)',
  border: '1px solid var(--miniapp-border-soft)',
  borderRadius: 'var(--miniapp-radius-sm)',
  padding: '11px 12px',
  fontFamily: 'var(--miniapp-sans)',
  fontSize: 13,
  color: 'var(--miniapp-text-primary)',
  outline: 'none',
  boxSizing: 'border-box',
}

export type AppShellNavTab = {
  id: string
  label: string
  active?: boolean
  onClick: () => void
}

export function AppShell({
  title,
  subtitle,
  actions,
  navTabs,
  children,
}: {
  title: string
  subtitle: ReactNode
  actions?: ReactNode
  navTabs?: AppShellNavTab[]
  children: ReactNode
}) {
  return (
    <div style={frameStyle}>
      <style>{designStyles}</style>
      <div style={noiseStyle} />
      <div style={shellStyle}>
        <header style={headerStyle}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 11 }}>
            <div
              style={{
                width: 36,
                height: 36,
                background: 'var(--miniapp-coral)',
                borderRadius: 11,
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'center',
                color: '#fff',
                boxShadow: '0 2px 8px rgba(201,100,66,0.30)',
                flexShrink: 0,
              }}
            >
              <svg width="18" height="18" viewBox="0 0 24 24" fill="none">
                <path d="M12 4l7 3v5c0 4.5-3 8.5-7 10-4-1.5-7-5.5-7-10V7l7-3z" stroke="currentColor" strokeWidth="1.7" />
              </svg>
            </div>
            <div style={{ minWidth: 0 }}>
              <div style={{ fontFamily: 'var(--miniapp-serif)', fontSize: 18, fontWeight: 500, lineHeight: 1.1 }}>{title}</div>
              <div style={{ marginTop: 6, color: 'var(--miniapp-text-muted)', fontSize: 12.5, lineHeight: '16px' }}>{subtitle}</div>
            </div>
          </div>
          <div style={{ display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap', justifyContent: 'flex-end' }}>
            {actions}
          </div>
        </header>
        {navTabs?.length ? (
          <div style={navTabsStyle}>
            {navTabs.map((tab) => (
              <button
                key={tab.id}
                type="button"
                onClick={tab.onClick}
                style={{
                  position: 'relative',
                  padding: '8px 14px 11px',
                  fontSize: 13,
                  fontWeight: 500,
                  color: tab.active ? 'var(--miniapp-coral)' : 'var(--miniapp-text-muted)',
                  cursor: 'pointer',
                  whiteSpace: 'nowrap',
                  borderRadius: 'var(--miniapp-radius-xs) var(--miniapp-radius-xs) 0 0',
                  transition: 'color .2s',
                  background: 'none',
                  border: 'none',
                  fontFamily: 'var(--miniapp-sans)',
                  borderBottom: tab.active ? '2px solid var(--miniapp-coral)' : '2px solid transparent',
                  flexShrink: 0,
                }}
              >
                {tab.label}
              </button>
            ))}
          </div>
        ) : null}
        <main style={mainStyle}>{children}</main>
      </div>
    </div>
  )
}

export function Card({ title, subtitle, children }: { title: string; subtitle?: string; children: ReactNode }) {
  return (
    <section style={surfaceStyle}>
      <div style={{ padding: 16, display: 'grid', gap: 12 }}>
        <div>
          <div style={{ fontSize: 11, fontWeight: 600, letterSpacing: '.8px', textTransform: 'uppercase', color: 'var(--miniapp-text-muted)' }}>
            Section
          </div>
          <h2 style={{ margin: '4px 0 0', fontFamily: 'var(--miniapp-serif)', fontSize: 18, fontWeight: 500, lineHeight: '24px' }}>{title}</h2>
          {subtitle ? (
            <p style={{ margin: '6px 0 0', color: 'var(--miniapp-text-secondary)', fontSize: 13, lineHeight: '19px' }}>{subtitle}</p>
          ) : null}
        </div>
        {children}
      </div>
    </section>
  )
}

export function Grid({ children }: { children: ReactNode }) {
  return <div style={{ display: 'grid', gap: 16 }}>{children}</div>
}

export function Button({
  children,
  onClick,
  tone = 'primary',
  type = 'button',
  disabled = false,
}: {
  children: ReactNode
  onClick?: () => void
  tone?: 'primary' | 'secondary' | 'danger'
  type?: 'button' | 'submit'
  disabled?: boolean
}) {
  const colors: Record<string, CSSProperties> = {
    primary: {
      background: 'var(--miniapp-coral)',
      color: '#fff',
      border: '1px solid rgba(201,100,66,0.35)',
      boxShadow: '0 2px 8px rgba(201,100,66,0.18)',
    },
    secondary: {
      background: 'var(--miniapp-bg)',
      color: 'var(--miniapp-text-primary)',
      border: '1px solid var(--miniapp-border-soft)',
    },
    danger: {
      background: 'var(--miniapp-clay-dim)',
      color: 'var(--miniapp-clay)',
      border: '1px solid var(--miniapp-clay-border)',
    },
  }

  return (
    <button
      type={type}
      onClick={onClick}
      disabled={disabled}
      style={{
        ...colors[tone],
        borderRadius: 12,
        padding: '10px 14px',
        fontSize: 13,
        lineHeight: '18px',
        fontWeight: 600,
        fontFamily: 'var(--miniapp-sans)',
        opacity: disabled ? 0.6 : 1,
        cursor: disabled ? 'default' : 'pointer',
      }}
    >
      {children}
    </button>
  )
}

export function InputField({
  label,
  value,
  onChange,
  type = 'text',
  placeholder,
  listId,
}: {
  label: string
  value: string
  onChange: (value: string) => void
  type?: string
  placeholder?: string
  listId?: string
}) {
  return (
    <label style={{ display: 'grid', gap: 6 }}>
      <span style={{ fontSize: 11, fontWeight: 600, letterSpacing: '.6px', textTransform: 'uppercase', color: 'var(--miniapp-text-muted)' }}>{label}</span>
      <input
        type={type}
        value={value}
        list={listId}
        placeholder={placeholder}
        onChange={(event) => onChange(event.target.value)}
        style={inputStyle}
      />
    </label>
  )
}

export function TextAreaField({
  label,
  value,
  onChange,
  rows = 4,
  placeholder,
}: {
  label: string
  value: string
  onChange: (value: string) => void
  rows?: number
  placeholder?: string
}) {
  return (
    <label style={{ display: 'grid', gap: 6 }}>
      <span style={{ fontSize: 11, fontWeight: 600, letterSpacing: '.6px', textTransform: 'uppercase', color: 'var(--miniapp-text-muted)' }}>{label}</span>
      <textarea
        rows={rows}
        value={value}
        placeholder={placeholder}
        onChange={(event) => onChange(event.target.value)}
        style={{ ...inputStyle, resize: 'vertical', lineHeight: '20px' }}
      />
    </label>
  )
}

export function SelectField({
  label,
  value,
  onChange,
  children,
}: {
  label: string
  value: string
  onChange: (value: string) => void
  children: ReactNode
}) {
  return (
    <label style={{ display: 'grid', gap: 6 }}>
      <span style={{ fontSize: 11, fontWeight: 600, letterSpacing: '.6px', textTransform: 'uppercase', color: 'var(--miniapp-text-muted)' }}>{label}</span>
      <select
        value={value}
        onChange={(event) => onChange(event.target.value)}
        style={inputStyle}
      >
        {children}
      </select>
    </label>
  )
}

export function Note({ children, tone = 'neutral' }: { children: ReactNode; tone?: 'neutral' | 'warning' }) {
  const toneStyle =
    tone === 'warning'
      ? {
          background: 'var(--miniapp-ochre-dim)',
          border: '1px solid var(--miniapp-ochre-border)',
          color: 'var(--miniapp-ochre)',
        }
      : {
          background: 'var(--miniapp-bg)',
          border: '1px solid var(--miniapp-border-soft)',
          color: 'var(--miniapp-text-secondary)',
        }

  return (
    <div
      style={{
        ...toneStyle,
        borderRadius: 12,
        padding: 12,
        fontSize: 12.5,
        lineHeight: '18px',
      }}
    >
      {children}
    </div>
  )
}

export function LinkRow({
  children,
  active = false,
  onClick,
}: {
  children: ReactNode
  active?: boolean
  onClick: () => void
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      style={{
        width: '100%',
        textAlign: 'left',
        borderRadius: 12,
        border: active ? '1px solid var(--miniapp-coral)' : '1px solid var(--miniapp-border-soft)',
        background: active ? 'var(--miniapp-coral-dim)' : 'var(--miniapp-surface)',
        padding: '13px 14px',
        fontSize: 13,
        lineHeight: '18px',
        color: 'var(--miniapp-text-primary)',
        cursor: 'pointer',
      }}
    >
      {children}
    </button>
  )
}
