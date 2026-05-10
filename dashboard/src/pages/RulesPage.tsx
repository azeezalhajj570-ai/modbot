import { useEffect, useMemo, useState } from 'react'

import { Button, Card, Field, FieldRow, InlineMessage, Input, Select, ToggleRow } from '../components/ui/primitives'
import { PageShell } from '../lib/page-shell'
import { fetchGroupSettings, updateGroupSettings } from '../lib/api'
import { useDashboardGroups } from '../lib/use-dashboard-groups'
import { useI18n } from '../lib/i18n'

type ModerationToggleKey = 'anti_spam' | 'anti_ads' | 'anti_spam_mute' | 'anti_ads_mute'
type ModerationLimitKey = 'anti_spam_mute_limit' | 'anti_ads_mute_limit' | 'warn_remove_limit'

const TOGGLE_DEFINITIONS: Array<{
  key: ModerationToggleKey
  title: string
  description: string
  defaultValue: boolean
}> = [
  {
    key: 'anti_spam',
    title: 'Spam detection',
    description: 'Deletes spammy messages using the existing moderation classifier and warning flow.',
    defaultValue: true,
  },
  {
    key: 'anti_ads',
    title: 'Ads detection',
    description: 'Removes advertising messages so the group can enforce anti-promo policy from the dashboard.',
    defaultValue: true,
  },
  {
    key: 'anti_spam_mute',
    title: 'Mute spam senders',
    description: 'Restricts members automatically after they cross the spam threshold.',
    defaultValue: false,
  },
  {
    key: 'anti_ads_mute',
    title: 'Mute ad senders',
    description: 'Restricts members who keep posting ads after the configured threshold.',
    defaultValue: false,
  },
]

const LIMIT_DEFINITIONS: Array<{
  key: ModerationLimitKey
  label: string
  hint: string
  defaultValue: number
}> = [
  {
    key: 'anti_spam_mute_limit',
    label: 'Spam mute limit',
    hint: 'How many spam violations trigger a mute.',
    defaultValue: 1,
  },
  {
    key: 'anti_ads_mute_limit',
    label: 'Ads mute limit',
    hint: 'How many ad removals trigger a mute.',
    defaultValue: 1,
  },
  {
    key: 'warn_remove_limit',
    label: 'Warn remove limit',
    hint: 'How many warnings are allowed before auto-removal.',
    defaultValue: 5,
  },
]

export default function RulesPage() {
  const { t } = useI18n()
  const { groups, currentGroup, currentGroupId, setCurrentGroupId, loading: groupsLoading, error: groupsError } = useDashboardGroups()
  const [settings, setSettings] = useState<Record<string, boolean | number | string>>({})
  const [limitDrafts, setLimitDrafts] = useState<Record<ModerationLimitKey, string>>({
    anti_spam_mute_limit: '1',
    anti_ads_mute_limit: '1',
    warn_remove_limit: '5',
  })
  const [loading, setLoading] = useState(true)
  const [savingToggle, setSavingToggle] = useState<ModerationToggleKey | null>(null)
  const [savingLimits, setSavingLimits] = useState(false)
  const [feedback, setFeedback] = useState('')
  const [error, setError] = useState('')

  useEffect(() => {
    if (currentGroupId == null) {
      setSettings({})
      setLoading(groupsLoading)
      return
    }

    let cancelled = false
    ;(async () => {
      setLoading(true)
      setError('')
      setFeedback('')
      try {
        const response = await fetchGroupSettings(currentGroupId)
        if (cancelled) return
        setSettings(response.settings)
      } catch {
        if (!cancelled) setError('Unable to load moderation settings for this group.')
      } finally {
        if (!cancelled) setLoading(false)
      }
    })()

    return () => { cancelled = true }
  }, [currentGroupId, groupsLoading])

  useEffect(() => {
    setLimitDrafts({
      anti_spam_mute_limit: String(readLimit(settings, 'anti_spam_mute_limit', 1)),
      anti_ads_mute_limit: String(readLimit(settings, 'anti_ads_mute_limit', 1)),
      warn_remove_limit: String(readLimit(settings, 'warn_remove_limit', 5)),
    })
  }, [settings])

  const toggleCards = useMemo(
    () => TOGGLE_DEFINITIONS.map((toggle) => ({
      ...toggle,
      checked: readBoolean(settings, toggle.key, toggle.defaultValue),
    })),
    [settings],
  )

  async function handleToggleChange(key: ModerationToggleKey, nextValue: boolean) {
    if (currentGroupId == null) return
    setSavingToggle(key)
    setError('')
    setFeedback('')
    try {
      await updateGroupSettings(currentGroupId, { [key]: nextValue })
      setSettings((current) => ({ ...current, [key]: nextValue }))
      setFeedback('Moderation rules updated.')
    } catch {
      setError('Unable to save moderation changes right now.')
    } finally {
      setSavingToggle(null)
    }
  }

  async function handleSaveLimits() {
    if (currentGroupId == null) return

    const payload = {} as Record<ModerationLimitKey, number>
    for (const item of LIMIT_DEFINITIONS) {
      const parsed = Number(limitDrafts[item.key])
      if (!Number.isInteger(parsed) || parsed < 1) {
        setError(`${item.label} must be a whole number greater than 0.`)
        setFeedback('')
        return
      }
      payload[item.key] = parsed
    }

    setSavingLimits(true)
    setError('')
    setFeedback('')
    try {
      await updateGroupSettings(currentGroupId, payload)
      setSettings((current) => ({ ...current, ...payload }))
      setFeedback('Moderation thresholds saved.')
    } catch {
      setError('Unable to save moderation thresholds right now.')
    } finally {
      setSavingLimits(false)
    }
  }

  return (
    <PageShell
      eyebrow="Rules"
      titleKey="page.rules"
      descriptionKey="page.rules.desc"
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
      {currentGroup ? <InlineMessage tone="neutral">Editing moderation rules for {currentGroup.title}.</InlineMessage> : null}
      {error ? <InlineMessage tone="danger">{error}</InlineMessage> : null}
      {feedback ? <InlineMessage tone="success">{feedback}</InlineMessage> : null}

      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(280px, 1fr))', gap: 16 }}>
        {toggleCards.map((rule) => (
          <Card key={rule.key}>
            <ToggleRow
              title={rule.title}
              subtitle={rule.description}
              checked={rule.checked}
              disabled={savingToggle === rule.key || currentGroupId == null}
              onCheckedChange={(checked) => void handleToggleChange(rule.key, checked)}
              action={savingToggle === rule.key ? <span style={{ fontSize: 12 }}>Saving…</span> : null}
            />
          </Card>
        ))}
      </div>

      <Card>
        <div style={{ fontSize: 18, fontWeight: 800, marginBottom: 12 }}>Moderation thresholds</div>
        <FieldRow columns={3}>
          {LIMIT_DEFINITIONS.map((item) => (
            <Field key={item.key} label={item.label} hint={item.hint}>
              <Input
                type="number"
                min={1}
                value={limitDrafts[item.key]}
                onChange={(event) => setLimitDrafts((current) => ({ ...current, [item.key]: event.target.value }))}
              />
            </Field>
          ))}
        </FieldRow>
        <div style={{ marginTop: 12 }}>
          <Button onClick={() => void handleSaveLimits()} disabled={savingLimits || currentGroupId == null}>
            {savingLimits ? 'Saving…' : 'Save thresholds'}
          </Button>
        </div>
      </Card>
    </PageShell>
  )
}

function readBoolean(
  settings: Record<string, boolean | number | string>,
  key: ModerationToggleKey,
  fallback: boolean,
) {
  const value = settings[key]
  return typeof value === 'boolean' ? value : fallback
}

function readLimit(
  settings: Record<string, boolean | number | string>,
  key: ModerationLimitKey,
  fallback: number,
) {
  const value = settings[key]
  return typeof value === 'number' ? value : fallback
}
