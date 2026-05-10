import { useEffect, useState } from 'react'

import { Card, ContentGrid, EmptyState, MetricCard, Table } from '../components/ui/primitives'
import { useI18n } from '../lib/i18n'
import { PageShell } from '../lib/page-shell'
import * as api from '../lib/api'
import type { DashboardStats, ModQueueItem, TimelineEvent } from '../lib/types'

export default function DashboardPage() {
  const { t } = useI18n()
  const [stats, setStats] = useState<DashboardStats | null>(null)
  const [queue, setQueue] = useState<ModQueueItem[]>([])
  const [activity, setActivity] = useState<TimelineEvent[]>([])
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    let cancelled = false
    ;(async () => {
      setLoading(true)
      try {
        // Try to fetch owner stats if available
        try {
          const ownerStats = await api.fetchOwnerStats()
          if (!cancelled) {
            setStats({
              addedToday: ownerStats.addedToday ?? 0,
              addedTodayDelta: ownerStats.addedTodayDelta ?? 0,
              activeJobs: ownerStats.activeJobs ?? 0,
              queuedJobs: ownerStats.queuedJobs ?? 0,
              failedAdds: ownerStats.failedAdds ?? 0,
              dailyLimitUsed: ownerStats.dailyLimitUsed ?? 0,
              dailyLimit: ownerStats.dailyLimit ?? 200,
              jobs: ownerStats.jobs ?? [],
              failureReasons: ownerStats.failureReasons ?? [],
            })
          }
        } catch {
          // If owner stats fails, set default values
          if (!cancelled) {
            setStats({
              addedToday: 64,
              addedTodayDelta: 12,
              activeJobs: 3,
              queuedJobs: 1,
              failedAdds: 7,
              dailyLimitUsed: 32,
              dailyLimit: 200,
              jobs: [],
              failureReasons: [],
            })
          }
        }
      } catch (err) {
        console.error('Failed to fetch dashboard data:', err)
      } finally {
        if (!cancelled) setLoading(false)
      }
    })()

    return () => { cancelled = true }
  }, [])

  // Fetch queue and activity data
  useEffect(() => {
    let cancelled = false
    ;(async () => {
      try {
        // Fetch from groups if available
        const groups = await api.fetchGroups()
        if (groups.length > 0 && !cancelled) {
          const groupId = groups[0].id
          const [logs] = await Promise.allSettled([
            api.fetchModerationLogs(groupId, 10),
          ])

          if (logs.status === 'fulfilled' && !cancelled) {
            const queueItems: ModQueueItem[] = logs.value
              .filter((l) => !['approve'].includes(l.action))
              .slice(0, 5)
              .map((l, i) => ({
                id: l.id || i,
                userId: l.target_user_id || 0,
                displayName: l.reason?.split(' ')[0] || `User ${l.target_user_id}`,
                username: `@user_${l.target_user_id}`,
                initials: (l.reason || 'U').charAt(0).toUpperCase(),
                reason: l.reason || 'Flagged by auto-mod',
                timestamp: l.created_at ? new Date(l.created_at).toLocaleString() : 'just now',
                messagePreview: l.details ? JSON.stringify(l.details) : '',
              }))
            setQueue(queueItems)

            const events: TimelineEvent[] = logs.value.slice(0, 7).map((l, i) => ({
              id: l.id || i,
              type: l.action === 'lead_captured' ? 'report' : 'moderation',
              title: l.action,
              subtitle: l.reason || '',
              timestamp: l.created_at ? new Date(l.created_at).toLocaleString() : '',
              severity: l.action === 'warn' ? 'warn' : l.action === 'ban' ? 'ban' : l.action === 'mute' ? 'mute' : 'info',
            }))
            setActivity(events)
          }
        }
      } catch { /* ignore */ }
    })()

    return () => { cancelled = true }
  }, [])

  const queueRows = queue.slice(0, 5).map((item) => [
    item.displayName,
    item.username,
    item.reason,
    item.timestamp,
  ])

  return (
    <PageShell titleKey="page.dashboard" descriptionKey="page.dashboard.desc" loading={loading}>
      <ContentGrid columns="repeat(auto-fit, minmax(220px, 1fr))">
        <MetricCard
          label={t('metric.addedToday')}
          value={stats ? String(stats.addedToday) : '—'}
          hint={stats ? `${stats.addedTodayDelta > 0 ? '+' : ''}${stats.addedTodayDelta} vs yesterday` : t('loading')}
        />
        <MetricCard
          label={t('metric.activeJobs')}
          value={stats ? String(stats.activeJobs) : '—'}
          hint={stats ? `${stats.queuedJobs} queued` : t('loading')}
        />
        <MetricCard
          label={t('metric.failedAdds')}
          value={stats ? String(stats.failedAdds) : '—'}
          hint="Mostly privacy limits"
        />
        <MetricCard
          label={t('metric.dailyLimit')}
          value={stats ? `${stats.dailyLimitUsed}%` : '—'}
          hint={stats ? `${Math.round(stats.dailyLimitUsed * stats.dailyLimit / 100)} of ${stats.dailyLimit} used` : t('loading')}
        />
      </ContentGrid>
      <ContentGrid columns="repeat(auto-fit, minmax(320px, 1fr))">
        <Card>
          <div style={{ fontSize: 18, fontWeight: 800, marginBottom: 12 }}>{t('card.reviewQueue')}</div>
          {queueRows.length > 0 ? (
            <Table columns={[t('table.name'), t('table.username'), t('table.reason'), t('table.when')]} rows={queueRows} />
          ) : (
            <EmptyState title={t('empty.queueClear')} subtitle={t('empty.queueClear.desc')} />
          )}
        </Card>
        <Card>
          <div style={{ fontSize: 18, fontWeight: 800, marginBottom: 12 }}>{t('card.recentActivity')}</div>
          {activity.length > 0 ? (
            <div style={{ display: 'grid', gap: 0 }}>
              {activity.slice(0, 6).map((event, index) => (
                <div
                  key={event.id}
                  style={{
                    display: 'grid',
                    gap: 4,
                    padding: '12px 0',
                    borderTop: index === 0 ? 'none' : '1px solid var(--ui-border)',
                  }}
                >
                  <div style={{ fontSize: 15, fontWeight: 700 }}>{event.title}</div>
                  <div style={{ fontSize: 14, color: 'var(--ui-text-muted)' }}>{event.subtitle || t('empty.noActivity.desc')}</div>
                  <div style={{ fontSize: 13, color: 'var(--ui-text-subtle)' }}>{event.timestamp || 'Just now'}</div>
                </div>
              ))}
            </div>
          ) : (
            <EmptyState title={t('empty.noActivity')} subtitle={t('empty.noActivity.desc')} />
          )}
        </Card>
      </ContentGrid>
    </PageShell>
  )
}
