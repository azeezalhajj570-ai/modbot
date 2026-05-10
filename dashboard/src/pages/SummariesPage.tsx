import { useEffect, useState } from 'react'

import { Badge, Button, Card, EmptyState, Field, InlineMessage, Input, ListItem, Select, ToggleRow } from '../components/ui/primitives'
import { PageShell } from '../lib/page-shell'
import { fetchSummaries, fetchSummarySettings, updateSummarySettings } from '../lib/api'
import { useDashboardGroups } from '../lib/use-dashboard-groups'
import { useI18n } from '../lib/i18n'

export default function SummariesPage() {
  const { t } = useI18n()
  const { groups, currentGroup, currentGroupId, setCurrentGroupId, loading: groupsLoading, error: groupsError } = useDashboardGroups()
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [feedback, setFeedback] = useState('')
  const [settings, setSettings] = useState<any>(null)
  const [summaries, setSummaries] = useState<any[]>([])
  const [expandedIds, setExpandedIds] = useState<Set<number>>(new Set())
  const [savingSettings, setSavingSettings] = useState(false)

  useEffect(() => {
    if (currentGroupId == null) {
      setLoading(groupsLoading)
      return
    }

    let cancelled = false
    ;(async () => {
      setLoading(true)
      setError('')
      setFeedback('')
      try {
        const [summarySettings, summaryList] = await Promise.all([
          fetchSummarySettings(currentGroupId),
          fetchSummaries(currentGroupId),
        ])
        if (cancelled) return

        setSettings(summarySettings)
        setSummaries(summaryList)
      } catch {
        if (!cancelled) setError('Unable to load summaries right now.')
      } finally {
        if (!cancelled) setLoading(false)
      }
    })()

    return () => { cancelled = true }
  }, [currentGroupId, groupsLoading])

  function toggleExpanded(id: number) {
    setExpandedIds((current) => {
      const next = new Set(current)
      if (next.has(id)) next.delete(id)
      else next.add(id)
      return next
    })
  }

  async function handleSaveSettings() {
    if (currentGroupId == null || settings == null) return

    setSavingSettings(true)
    setError('')
    setFeedback('')
    try {
      const updated = await updateSummarySettings(currentGroupId, settings)
      setSettings(updated)
      setFeedback('Summary settings saved.')
    } catch {
      setError('Unable to save summary settings.')
    } finally {
      setSavingSettings(false)
    }
  }

  return (
    <PageShell
      eyebrow="Summaries"
      titleKey="page.summaries"
      descriptionKey="page.summaries.desc"
      loading={loading}
      actions={(
        <div style={{ minWidth: 240 }}>
          <Select value={currentGroupId ?? ''} onChange={(event) => setCurrentGroupId(Number(event.target.value) || null)} disabled={groupsLoading || groups.length === 0}>
            {groups.length === 0 ? <option value="">No managed groups</option> : null}
            {groups.map((group) => (
              <option key={group.id} value={group.id}>{group.title}</option>
            ))}
          </Select>
        </div>
      )}
    >
      {groupsError ? <InlineMessage tone="danger">{groupsError}</InlineMessage> : null}
      {currentGroup ? <InlineMessage tone="neutral">Viewing summaries for {currentGroup.title}.</InlineMessage> : null}
      {error ? <InlineMessage tone="danger">{error}</InlineMessage> : null}
      {feedback ? <InlineMessage tone="success">{feedback}</InlineMessage> : null}

      {settings ? (
        <Card title="Summary settings" subtitle="Configure summary delivery preferences.">
          <ToggleRow
            title="Enable summaries"
            subtitle="Toggle daily summary generation for this group."
            checked={settings.enabled}
            disabled={currentGroupId == null}
            onCheckedChange={(checked) => setSettings((current) => current ? { ...current, enabled: checked } : null)}
          />
          <div style={{ marginTop: 16 }}>
            <Field label="Delivery mode" hint="How summaries are delivered to admins.">
              <Select
                value={settings.delivery_mode}
                onChange={(event) => setSettings((current) => current ? { ...current, delivery_mode: event.target.value } : null)}
              >
                <option value="private">Private message</option>
                <option value="group">Group message</option>
                <option value="both">Both</option>
              </Select>
            </Field>
          </div>
          <div style={{ marginTop: 16 }}>
            <Field label="Delivery time" hint="Time of day for summary delivery (UTC).">
              <Input
                type="time"
                value={settings.delivery_time}
                onChange={(event) => setSettings((current) => current ? { ...current, delivery_time: event.target.value } : null)}
              />
            </Field>
          </div>
          <div style={{ marginTop: 16 }}>
            <Button onClick={() => void handleSaveSettings()} disabled={savingSettings || currentGroupId == null}>
              {savingSettings ? 'Saving…' : 'Save settings'}
            </Button>
          </div>
        </Card>
      ) : null}

      <Card title="Daily summaries" subtitle="Generated summaries for this group.">
        {summaries.length > 0 ? (
          <div style={{ display: 'grid' }}>
            {summaries.map((summary) => (
              <div key={summary.id}>
                <ListItem
                  title={summary.date}
                  subtitle={`${summary.total_messages} messages · ${summary.active_users} active users · ${summary.links_count} links`}
                  actions={(
                    <Button variant="outline" onClick={() => toggleExpanded(summary.id)}>
                      {expandedIds.has(summary.id) ? 'Collapse' : 'Expand'}
                    </Button>
                  )}
                />
                {expandedIds.has(summary.id) ? (
                  <div style={{ padding: '8px 0 16px 18px', fontSize: 14, color: 'var(--ui-text-muted)', lineHeight: '20px', whiteSpace: 'pre-wrap' }}>
                    {summary.summary_text}
                  </div>
                ) : null}
              </div>
            ))}
          </div>
        ) : (
          <EmptyState title="No summaries yet" subtitle="Daily summaries will appear here once generated." />
        )}
      </Card>
    </PageShell>
  )
}
