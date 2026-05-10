import type { CSSProperties, ReactNode } from 'react'

import { contentMaxWidth, radius, spacing, typeScale, uiVars } from '../../../../shared/ui-system/tokens'

const panelBaseStyle: CSSProperties = {
  background: uiVars.surface,
  border: `1px solid ${uiVars.border}`,
  borderRadius: radius.lg,
  boxShadow: uiVars.shadow,
}

function buttonVariantStyle(variant: ButtonVariant): CSSProperties {
  if (variant === 'outline') {
    return {
      background: uiVars.surfaceStrong,
      color: uiVars.text,
      border: `1px solid ${uiVars.borderStrong}`,
    }
  }

  if (variant === 'ghost') {
    return {
      background: 'transparent',
      color: uiVars.primary,
      border: '1px solid transparent',
    }
  }

  if (variant === 'destructive') {
    return {
      background: uiVars.dangerSoft,
      color: uiVars.danger,
      border: `1px solid color-mix(in srgb, ${uiVars.danger} 22%, transparent)`,
    }
  }

  return {
    background: uiVars.primary,
    color: uiVars.primaryText,
    border: `1px solid ${uiVars.primary}`,
  }
}

function overlayStyle(dimmed = true): CSSProperties {
  return {
    position: 'fixed',
    inset: 0,
    background: dimmed ? 'rgba(20, 33, 61, 0.22)' : 'transparent',
    backdropFilter: 'blur(10px)',
    zIndex: 1000,
  }
}

export type ButtonVariant = 'default' | 'outline' | 'ghost' | 'destructive'

export function Button({
  children,
  variant = 'default',
  size = 'md',
  style,
  ...props
}: React.ButtonHTMLAttributes<HTMLButtonElement> & {
  variant?: ButtonVariant
  size?: 'sm' | 'md' | 'lg'
}) {
  const sizes = {
    sm: { minHeight: 32, padding: '0 10px', fontSize: 13 },
    md: { minHeight: 42, padding: '0 14px', fontSize: typeScale.subhead },
    lg: { minHeight: 50, padding: '0 20px', fontSize: 16 },
  }
  const sizeStyle = sizes[size]

  return (
    <button
      {...props}
      style={{
        borderRadius: radius.md,
        fontWeight: 700,
        lineHeight: '18px',
        cursor: props.disabled ? 'not-allowed' : 'pointer',
        transition: 'opacity 0.16s ease, background 0.16s ease, border-color 0.16s ease',
        opacity: props.disabled ? 0.55 : 1,
        display: 'inline-flex',
        alignItems: 'center',
        justifyContent: 'center',
        gap: spacing.xs,
        ...sizeStyle,
        ...buttonVariantStyle(variant),
        ...style,
      }}
    >
      {children}
    </button>
  )
}

export function Card({
  children,
  style,
  padded = true,
  title,
  subtitle,
}: {
  children: ReactNode
  style?: CSSProperties
  padded?: boolean
  title?: string
  subtitle?: string
}) {
  return (
    <section style={{ ...panelBaseStyle, padding: padded ? spacing.lg : 0, ...style }}>
      {title ? (
        <div style={{ padding: padded ? `0 0 ${spacing.lg}px 0` : spacing.lg, borderBottom: subtitle ? 'none' : `1px solid ${uiVars.border}` }}>
          <div style={{ fontSize: 16, fontWeight: 800 }}>{title}</div>
          {subtitle ? <div style={{ fontSize: 13, color: uiVars.textMuted, marginTop: 4 }}>{subtitle}</div> : null}
        </div>
      ) : null}
      <div style={{ marginTop: title ? spacing.lg : 0 }}>
        {children}
      </div>
    </section>
  )
}

export function LoadingState() {
  return (
    <div style={{ padding: spacing.xl, textAlign: 'center', color: uiVars.textMuted }}>
      <div className="pulse" style={{ width: 40, height: 40, borderRadius: 20, background: uiVars.primarySoft, margin: '0 auto 12px' }} />
      Loading...
    </div>
  )
}

export function SectionHeader({
  eyebrow: _eyebrow,
  title,
  subtitle,
  actions,
}: {
  eyebrow?: string
  title: ReactNode
  subtitle?: ReactNode
  actions?: ReactNode
}) {
  return (
    <div style={{ display: 'flex', alignItems: 'flex-start', justifyContent: 'space-between', gap: spacing.lg }}>
      <div style={{ minWidth: 0, flex: 1 }}>
        <div style={{ fontSize: 22, lineHeight: '28px', fontWeight: 800, color: uiVars.text }}>{title}</div>
        {subtitle ? (
          <div style={{ marginTop: spacing.xs, fontSize: typeScale.body, lineHeight: '20px', color: uiVars.textMuted }}>
            {subtitle}
          </div>
        ) : null}
      </div>
      {actions ? <div style={{ display: 'flex', gap: spacing.sm, flexWrap: 'wrap', justifyContent: 'flex-end' }}>{actions}</div> : null}
    </div>
  )
}

export function Input(props: React.InputHTMLAttributes<HTMLInputElement>) {
  return (
    <input
      {...props}
      style={{
        width: '100%',
        minHeight: 44,
        borderRadius: radius.md,
        border: `1px solid ${uiVars.borderStrong}`,
        padding: '0 14px',
        background: uiVars.surfaceStrong,
        color: uiVars.text,
        boxShadow: 'inset 0 1px 0 rgba(255,255,255,0.72)',
        ...props.style,
      }}
    />
  )
}

export function Select({
  children,
  uiSize,
  ...props
}: React.SelectHTMLAttributes<HTMLSelectElement> & { children: ReactNode; uiSize?: 'sm' | 'default' }) {
  return (
    <select
      {...props}
      style={{
        width: '100%',
        minHeight: uiSize === 'sm' ? 32 : 44,
        borderRadius: radius.md,
        border: `1px solid ${uiVars.border}`,
        padding: uiSize === 'sm' ? '0 8px' : '0 14px',
        fontSize: uiSize === 'sm' ? 13 : 15,
        background: uiVars.surfaceStrong,
        color: uiVars.text,
        boxShadow: 'inset 0 1px 0 rgba(255,255,255,0.72)',
        ...props.style,
      }}
    >
      {children}
    </select>
  )
}

export function Textarea(props: React.TextareaHTMLAttributes<HTMLTextAreaElement>) {
  return (
    <textarea
      {...props}
      style={{
        width: '100%',
        minHeight: 120,
        borderRadius: radius.md,
        border: `1px solid ${uiVars.borderStrong}`,
        padding: 14,
        background: uiVars.surfaceStrong,
        color: uiVars.text,
        resize: 'vertical',
        boxShadow: 'inset 0 1px 0 rgba(255,255,255,0.72)',
        ...props.style,
      }}
    />
  )
}

export function Field({
  label,
  hint,
  children,
}: {
  label: string
  hint?: string
  children: ReactNode
}) {
  return (
    <label style={{ display: 'grid', gap: 8 }}>
        <div>
        <div style={{ fontSize: typeScale.body, lineHeight: '18px', fontWeight: 700, color: uiVars.textMuted }}>
          {label}
        </div>
        {hint ? <div style={{ marginTop: 4, fontSize: typeScale.caption, lineHeight: '16px', color: uiVars.textSubtle }}>{hint}</div> : null}
      </div>
      {children}
    </label>
  )
}

export function FieldRow({
  children,
  columns = 2,
}: {
  children: ReactNode
  columns?: 1 | 2 | 3
}) {
  return (
    <div
      style={{
        display: 'grid',
        gridTemplateColumns: `repeat(${columns}, minmax(0, 1fr))`,
        gap: spacing.md,
      }}
    >
      {children}
    </div>
  )
}

export function Badge({
  children,
  tone = 'default',
}: {
  children: ReactNode
  tone?: 'default' | 'success' | 'warning' | 'destructive' | 'info' | 'neutral'
}) {
  const tones: Record<string, CSSProperties> = {
    default: { background: uiVars.primarySoft, color: uiVars.primary },
    success: { background: uiVars.successSoft, color: uiVars.success },
    warning: { background: uiVars.warningSoft, color: uiVars.warning },
    destructive: { background: uiVars.dangerSoft, color: uiVars.danger },
    info: { background: uiVars.primarySoft, color: uiVars.primary },
    neutral: { background: uiVars.bgMuted, color: uiVars.textMuted },
  }

  return (
    <span
      style={{
        display: 'inline-flex',
        alignItems: 'center',
        gap: 6,
        border: `1px solid ${uiVars.border}`,
        borderRadius: radius.sm,
        padding: '4px 8px',
        fontSize: typeScale.caption,
        lineHeight: '16px',
        fontWeight: 800,
        ...tones[tone],
      }}
    >
      {children}
    </span>
  )
}

export function ToggleRow({
  title,
  subtitle,
  defaultChecked,
  checked,
  onCheckedChange,
  action,
  disabled,
}: {
  title: ReactNode
  subtitle: ReactNode
  defaultChecked?: boolean
  checked?: boolean
  onCheckedChange?: (checked: boolean) => void
  action?: ReactNode
  disabled?: boolean
}) {
  return (
    <div
      style={{
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'space-between',
        gap: spacing.md,
        padding: '14px 16px',
        borderRadius: radius.md,
        border: `1px solid ${uiVars.border}`,
        background: uiVars.surfaceAlt,
      }}
    >
      <div style={{ minWidth: 0, flex: 1 }}>
        <div style={{ fontSize: typeScale.subhead, lineHeight: '20px', fontWeight: 800 }}>{title}</div>
        <div style={{ marginTop: 4, fontSize: typeScale.body, lineHeight: '20px', color: uiVars.textMuted }}>{subtitle}</div>
      </div>
      <div style={{ display: 'flex', alignItems: 'center', gap: spacing.sm }}>
        {action}
        <input
          type="checkbox"
          defaultChecked={defaultChecked}
          checked={checked}
          disabled={disabled}
          onChange={(event) => onCheckedChange?.(event.target.checked)}
          style={{ width: 18, height: 18, accentColor: 'var(--ui-primary)' }}
        />
      </div>
    </div>
  )
}

export function MetricCard({
  label,
  value,
  hint,
  icon,
}: {
  label: string
  value: string
  hint: string
  icon?: ReactNode
}) {
  return (
    <Card style={{ display: 'grid', gap: spacing.sm }}>
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: spacing.md }}>
        <div style={{ fontSize: typeScale.body, lineHeight: '18px', fontWeight: 700, color: uiVars.textMuted }}>
          {label}
        </div>
        {icon ? <div style={{ color: uiVars.primary }}>{icon}</div> : null}
      </div>
      <div style={{ fontSize: 30, lineHeight: '34px', fontWeight: 800, color: uiVars.text }}>{value}</div>
      <div style={{ fontSize: typeScale.caption, lineHeight: '16px', color: uiVars.textSubtle }}>{hint}</div>
    </Card>
  )
}

export function EmptyState({
  title,
  subtitle,
  action,
}: {
  title: string
  subtitle: string
  action?: ReactNode
}) {
  return (
    <Card
      style={{
        display: 'grid',
        justifyItems: 'start',
        gap: spacing.sm,
        background: uiVars.surfaceAlt,
      }}
    >
      <div style={{ fontSize: 18, lineHeight: '24px', fontWeight: 800 }}>{title}</div>
      <div style={{ maxWidth: 520, fontSize: typeScale.body, lineHeight: '20px', color: uiVars.textMuted }}>{subtitle}</div>
      {action}
    </Card>
  )
}

export function InlineMessage({
  tone = 'neutral',
  children,
}: {
  tone?: 'neutral' | 'success' | 'warning' | 'danger'
  children: ReactNode
}) {
  const toneStyle: Record<string, CSSProperties> = {
    neutral: { background: uiVars.bgMuted, color: uiVars.textMuted },
    success: { background: uiVars.successSoft, color: uiVars.success },
    warning: { background: uiVars.warningSoft, color: uiVars.warning },
    danger: { background: uiVars.dangerSoft, color: uiVars.danger },
  }

  return (
    <div style={{ padding: '12px 14px', borderRadius: radius.md, fontSize: typeScale.body, lineHeight: '20px', ...toneStyle[tone] }}>
      {children}
    </div>
  )
}

export function ActionBar({
  primary,
  secondary,
}: {
  primary?: ReactNode
  secondary?: ReactNode
}) {
  return (
    <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', gap: spacing.sm, flexWrap: 'wrap' }}>
      <div style={{ display: 'flex', gap: spacing.sm, flexWrap: 'wrap' }}>{secondary}</div>
      <div style={{ display: 'flex', gap: spacing.sm, flexWrap: 'wrap' }}>{primary}</div>
    </div>
  )
}

export function Table({
  columns,
  rows,
}: {
  columns: string[]
  rows: ReactNode[][]
}) {
  return (
    <div style={{ overflowX: 'auto' }}>
      <table style={{ width: '100%', borderCollapse: 'collapse', minWidth: 640 }}>
        <thead>
          <tr>
            {columns.map((column) => (
              <th
                key={column}
                style={{
                  textAlign: 'left',
                  fontSize: typeScale.body,
                  color: uiVars.textMuted,
                  padding: '0 0 12px',
                  fontWeight: 700,
                }}
              >
                {column}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((row, rowIndex) => (
            <tr key={rowIndex}>
              {row.map((cell, cellIndex) => (
                <td
                  key={cellIndex}
                  style={{
                    padding: '14px 0',
                    borderTop: `1px solid ${uiVars.border}`,
                    fontSize: typeScale.body,
                    lineHeight: '20px',
                    verticalAlign: 'top',
                  }}
                >
                  {cell}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

export function ListItem({
  title,
  subtitle,
  meta,
  actions,
  markerColor,
}: {
  title: ReactNode
  subtitle: ReactNode
  meta?: ReactNode
  actions?: ReactNode
  markerColor?: string
}) {
  return (
    <div
      style={{
        display: 'flex',
        alignItems: 'flex-start',
        justifyContent: 'space-between',
        gap: spacing.md,
        padding: `${spacing.md}px 0`,
        borderTop: `1px solid ${uiVars.border}`,
      }}
    >
      <div style={{ display: 'flex', gap: spacing.sm, minWidth: 0, flex: 1 }}>
        <span
          style={{
            width: 10,
            height: 10,
            borderRadius: radius.sm,
            background: markerColor ?? uiVars.primary,
            marginTop: 6,
            flexShrink: 0,
          }}
        />
        <div style={{ minWidth: 0, flex: 1 }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: spacing.sm, flexWrap: 'wrap' }}>
            <div style={{ fontSize: typeScale.subhead, lineHeight: '20px', fontWeight: 800 }}>{title}</div>
            {meta}
          </div>
          <div style={{ marginTop: 4, fontSize: typeScale.body, lineHeight: '20px', color: uiVars.textMuted }}>{subtitle}</div>
        </div>
      </div>
      {actions ? <div style={{ display: 'flex', gap: spacing.sm, flexWrap: 'wrap', justifyContent: 'flex-end' }}>{actions}</div> : null}
    </div>
  )
}

export function Dialog({
  open,
  title,
  description,
  children,
  onClose,
}: {
  open: boolean
  title: string
  description?: string
  children: ReactNode
  onClose: () => void
}) {
  if (!open) return null

  return (
    <div style={{ ...overlayStyle(), display: 'grid', placeItems: 'center', padding: spacing.lg }}>
      <div style={{ ...panelBaseStyle, width: 'min(560px, 100%)', padding: spacing.xl }}>
        <SectionHeader title={title} subtitle={description} actions={<Button variant="ghost" onClick={onClose}>Close</Button>} />
        <div style={{ display: 'grid', gap: spacing.md, marginTop: spacing.lg }}>{children}</div>
      </div>
    </div>
  )
}

export function Sheet({
  open,
  title,
  description,
  children,
  onClose,
  footer,
}: {
  open: boolean
  title: string
  description?: string
  children: ReactNode
  onClose: () => void
  footer?: ReactNode
}) {
  if (!open) return null

  return (
    <div style={overlayStyle()}>
      <div
        style={{
          position: 'absolute',
          top: spacing.lg,
          right: spacing.lg,
          bottom: spacing.lg,
          width: 'min(560px, calc(100vw - 32px))',
          ...panelBaseStyle,
          background: uiVars.surfaceStrong,
          overflow: 'hidden',
          display: 'flex',
          flexDirection: 'column',
        }}
      >
        <div style={{ padding: spacing.xl, borderBottom: `1px solid ${uiVars.border}` }}>
          <SectionHeader title={title} subtitle={description} actions={<Button variant="ghost" onClick={onClose}>Close</Button>} />
        </div>
        <div style={{ flex: 1, overflowY: 'auto', padding: spacing.xl, display: 'grid', gap: spacing.lg }}>{children}</div>
        {footer ? <div style={{ padding: spacing.xl, borderTop: `1px solid ${uiVars.border}` }}>{footer}</div> : null}
      </div>
    </div>
  )
}

export function Tabs({
  value,
  onChange,
  items,
}: {
  value: string
  onChange: (value: string) => void
  items: { value: string; label: string }[]
}) {
  return (
    <div style={{ display: 'flex', gap: spacing.sm, flexWrap: 'wrap' }}>
      {items.map((item) => (
        <Button key={item.value} variant={value === item.value ? 'default' : 'outline'} onClick={() => onChange(item.value)}>
          {item.label}
        </Button>
      ))}
    </div>
  )
}

export function ContentGrid({
  children,
  columns = 'repeat(2, minmax(0, 1fr))',
}: {
  children: ReactNode
  columns?: string
}) {
  return (
    <div style={{ display: 'grid', gridTemplateColumns: columns, gap: spacing.lg }}>
      {children}
    </div>
  )
}

export function PageFrame({ children }: { children: ReactNode }) {
  return <div style={{ width: '100%', maxWidth: contentMaxWidth, margin: '0 auto', display: 'grid', gap: spacing.lg }}>{children}</div>
}
