import type { ReactNode } from 'react'

import { spacing, uiVars } from '../../../shared/ui-system/tokens'
import { useI18n } from './i18n'
import { EmptyState, PageFrame, SectionHeader } from '../components/ui/primitives'

export function PageShell({
  titleKey,
  title,
  descriptionKey,
  description,
  actions,
  children,
  loading,
}: {
  titleKey?: string
  title?: string
  descriptionKey?: string
  description?: string
  actions?: ReactNode
  children: ReactNode
  loading?: boolean
}) {
  const { t } = useI18n()
  const resolvedTitle = titleKey ? t(titleKey) : (title || '')
  const resolvedDesc = descriptionKey ? t(descriptionKey) : description

  return (
    <div style={{ flex: 1, overflowY: 'auto', padding: spacing.xl }}>
      <PageFrame>
        <div
          style={{
            background: uiVars.bgMuted,
            border: `1px solid ${uiVars.border}`,
            borderRadius: 12,
            padding: spacing.xl,
            boxShadow: uiVars.shadow,
          }}
        >
          <SectionHeader title={resolvedTitle} subtitle={resolvedDesc} actions={actions} />
        </div>
        {loading ? (
          <EmptyState title={t('loading')} subtitle="" />
        ) : (
          children
        )}
      </PageFrame>
    </div>
  )
}
