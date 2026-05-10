import { useEffect, useMemo, useState } from 'react'

import { Badge, Button, Card, Dialog, EmptyState, Field, FieldRow, InlineMessage, Input, ListItem, Select, Textarea } from '../components/ui/primitives'
import { PageShell } from '../lib/page-shell'
import {
  createScheduledMessage,
  deleteScheduledMessage,
  fetchAccessGate,
  fetchScheduledMessages,
  updateAccessGate,
  updateScheduledMessage,
  type ScheduledMessage,
} from '../lib/api'
import { useDashboardGroups } from '../lib/use-dashboard-groups'
import { useI18n } from '../lib/i18n'

export default function SettingsPage() {
  const { t } = useI18n()
  const { groups, currentGroup, currentGroupId, setCurrentGroupId, loading: groupsLoading, error: groupsError } = useDashboardGroups()
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [feedback, setFeedback] = useState('')
  const [requiredGroupIds, setRequiredGroupIds] = useState<number[]>([])
  const [requiredGroupsQuery, setRequiredGroupsQuery] = useState('')
  const [requiredGroupCandidates, setRequiredGroupCandidates] = useState<Array<{ tg_group_id?: number; title?: string; role?: string }>>([])
  const [savingGate, setSavingGate] = useState(false)
  const [scheduledMessages, setScheduledMessages] = useState<ScheduledMessage[]>([])
  const [editorOpen, setEditorOpen] = useState(false)
  const [editingMessage, setEditingMessage] = useState<ScheduledMessage | null>(null)
  const [messageText, setMessageText] = useState('')
  const [messageSchedule, setMessageSchedule] = useState('+1h')
  const [messageDeleteAfter, setMessageDeleteAfter] = useState('0')
  const [savingMessage, setSavingMessage] = useState(false)

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
        const [gate, messages] = await Promise.all([
          fetchAccessGate(currentGroupId),
          fetchScheduledMessages(currentGroupId),
        ])
        if (cancelled) return

        setRequiredGroupIds(gate.required_group_tg_ids)
        setRequiredGroupCandidates(gate.candidates ?? [])
        setScheduledMessages(messages)
      } catch {
        if (!cancelled) setError('Unable to load group settings right now.')
      } finally {
        if (!cancelled) setLoading(false)
      }
    })()

    return () => { cancelled = true }
  }, [currentGroupId, groupsLoading])

  const selectedRequiredGroups = useMemo(() => {
    const selectedIds = new Set(requiredGroupIds)
    return requiredGroupCandidates.filter((candidate) => {
      const tgGroupId = Number(candidate.tg_group_id)
      return tgGroupId && selectedIds.has(tgGroupId)
    })
  }, [requiredGroupCandidates, requiredGroupIds])

  const requiredGroupSuggestions = useMemo(() => {
    const selectedIds = new Set(requiredGroupIds)
    const query = requiredGroupsQuery.trim().toLowerCase()

    return requiredGroupCandidates.filter((candidate) => {
      const tgGroupId = Number(candidate.tg_group_id)
      if (!tgGroupId || selectedIds.has(tgGroupId)) return false
      if (!query) return true

      return [candidate.title || '', candidate.role || '', String(candidate.tg_group_id || '')]
        .some((value) => value.toLowerCase().includes(query))
    })
  }, [requiredGroupCandidates, requiredGroupIds, requiredGroupsQuery])

  function openCreateDialog() {
    setEditingMessage(null)
    setMessageText('')
    setMessageSchedule('+1h')
    setMessageDeleteAfter('0')
    setEditorOpen(true)
  }

  function openEditDialog(message: ScheduledMessage) {
    setEditingMessage(message)
    setMessageText(message.text)
    setMessageSchedule(message.schedule)
    setMessageDeleteAfter(String(message.delete_after_seconds ?? 0))
    setEditorOpen(true)
  }

  async function handleSaveAccessGate() {
    if (currentGroupId == null) return

    setSavingGate(true)
    setError('')
    setFeedback('')
    try {
      const updated = await updateAccessGate(currentGroupId, requiredGroupIds)
      setRequiredGroupIds(updated.required_group_tg_ids)
      setRequiredGroupCandidates(updated.candidates ?? [])
      setFeedback('Required groups updated.')
    } catch {
      setError('Unable to save required groups right now.')
    } finally {
      setSavingGate(false)
    }
  }

  async function handleSaveScheduledMessage() {
    if (currentGroupId == null) return

    const deleteAfter = Number(messageDeleteAfter)
    if (!messageText.trim()) {
      setError('Scheduled message text is required.')
      return
    }
    if (!messageSchedule.trim()) {
      setError('Schedule is required.')
      return
    }
    if (!Number.isFinite(deleteAfter) || deleteAfter < 0) {
      setError('Delete after seconds must be 0 or a positive number.')
      return
    }

    setSavingMessage(true)
    setError('')
    setFeedback('')
    try {
      if (editingMessage) {
        const response = await updateScheduledMessage(currentGroupId, editingMessage.id, {
          text: messageText.trim(),
          schedule: messageSchedule.trim(),
          delete_after_seconds: deleteAfter || undefined,
        })
        setScheduledMessages((current) => current.map((item) => item.id === editingMessage.id ? response.scheduled_message : item))
      } else {
        const response = await createScheduledMessage(currentGroupId, {
          text: messageText.trim(),
          schedule: messageSchedule.trim(),
          delete_after_seconds: deleteAfter || undefined,
        })
        setScheduledMessages((current) => [response.scheduled_message, ...current])
      }
      setEditorOpen(false)
      setFeedback('Scheduled messages updated.')
    } catch {
      setError('Unable to save the scheduled message.')
    } finally {
      setSavingMessage(false)
    }
  }

  async function handleDeleteScheduledMessage(message: ScheduledMessage) {
    if (currentGroupId == null) return
    setError('')
    setFeedback('')
    try {
      await deleteScheduledMessage(currentGroupId, message.id)
      setScheduledMessages((current) => current.filter((item) => item.id !== message.id))
      setFeedback('Scheduled message deleted.')
    } catch {
      setError('Unable to delete the scheduled message.')
    }
  }

  function addRequiredGroup(tgGroupId: number) {
    setRequiredGroupIds((current) => current.includes(tgGroupId) ? current : [...current, tgGroupId])
    setRequiredGroupsQuery('')
  }

  function removeRequiredGroup(tgGroupId: number) {
    setRequiredGroupIds((current) => current.filter((id) => id !== tgGroupId))
  }

  return (
    <PageShell
      eyebrow="Settings"
      titleKey="page.settings"
      descriptionKey="page.settings.desc"
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
      {currentGroup ? <InlineMessage tone="neutral">Editing settings for {currentGroup.title}.</InlineMessage> : null}
      {error ? <InlineMessage tone="danger">{error}</InlineMessage> : null}
      {feedback ? <InlineMessage tone="success">{feedback}</InlineMessage> : null}

      <Card>
        <div style={{ fontSize: 18, fontWeight: 800, marginBottom: 12 }}>Required groups</div>
        <Field label="Select groups" hint="Search managed groups by name, role, or Telegram ID and add multiple requirements.">
          <Input
            value={requiredGroupsQuery}
            onChange={(event) => setRequiredGroupsQuery(event.target.value)}
            placeholder="Search groups"
          />
        </Field>
        {selectedRequiredGroups.length > 0 ? (
          <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap', marginTop: 12 }}>
            {selectedRequiredGroups.map((candidate) => (
              <button
                key={candidate.tg_group_id}
                onClick={() => removeRequiredGroup(Number(candidate.tg_group_id))}
                style={{ border: 'none', background: 'transparent', padding: 0, cursor: 'pointer' }}
              >
                <Badge tone="neutral">
                  {candidate.title ?? candidate.tg_group_id} {candidate.role ? `· ${candidate.role}` : ''} ×
                </Badge>
              </button>
            ))}
          </div>
        ) : null}
        {requiredGroupSuggestions.length > 0 ? (
          <div style={{ display: 'grid', gap: 8, marginTop: 12 }}>
            {requiredGroupSuggestions.slice(0, 8).map((candidate) => (
              <button
                key={candidate.tg_group_id}
                onClick={() => addRequiredGroup(Number(candidate.tg_group_id))}
                style={{
                  display: 'flex',
                  justifyContent: 'space-between',
                  alignItems: 'center',
                  gap: 12,
                  border: '1px solid var(--ui-border)',
                  borderRadius: 10,
                  background: 'var(--ui-surface-alt)',
                  padding: '10px 12px',
                  textAlign: 'left',
                  cursor: 'pointer',
                }}
              >
                <span style={{ fontSize: 14, fontWeight: 700 }}>{candidate.title ?? candidate.tg_group_id}</span>
                <span style={{ fontSize: 12, color: 'var(--ui-text-muted)' }}>
                  {candidate.role ? `${candidate.role} · ` : ''}{candidate.tg_group_id}
                </span>
              </button>
            ))}
          </div>
        ) : null}
        <div style={{ marginTop: 12 }}><Button onClick={() => void handleSaveAccessGate()} disabled={savingGate || currentGroupId == null}>{savingGate ? 'Saving…' : 'Save required groups'}</Button></div>
      </Card>

      <Card>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', gap: 12, marginBottom: 12, flexWrap: 'wrap' }}>
          <div>
            <div style={{ fontSize: 18, fontWeight: 800 }}>Scheduled messages</div>
            <div style={{ marginTop: 4, fontSize: 14, color: 'var(--ui-text-muted)' }}>Create recurring or one-off reminders for the selected group.</div>
          </div>
          <Button onClick={openCreateDialog} disabled={currentGroupId == null}>New scheduled message</Button>
        </div>
        {scheduledMessages.length > 0 ? (
          <div style={{ display: 'grid' }}>
            {scheduledMessages.map((message) => (
              <ListItem
                key={message.id}
                title={message.text}
                subtitle={`Schedule: ${message.schedule} · Next send: ${new Date(message.send_at).toLocaleString()}`}
                meta={<Badge tone="info">{message.delete_after_seconds ? `Delete after ${message.delete_after_seconds}s` : 'Keep message'}</Badge>}
                actions={(
                  <>
                    <Button variant="outline" onClick={() => openEditDialog(message)}>Edit</Button>
                    <Button variant="destructive" onClick={() => void handleDeleteScheduledMessage(message)}>Delete</Button>
                  </>
                )}
              />
            ))}
          </div>
        ) : (
          <EmptyState title="No scheduled messages" subtitle="Use the group scheduler for recurring reminders, announcements, and cleanup-friendly notices." action={<Button onClick={openCreateDialog} disabled={currentGroupId == null}>Create one</Button>} />
        )}
      </Card>

      <Dialog
        open={editorOpen}
        title={editingMessage ? 'Edit scheduled message' : 'Create scheduled message'}
        description="The scheduler accepts relative times like +10m or cron expressions like */15 * * * *."
        onClose={() => setEditorOpen(false)}
      >
        <Field label="Message text">
          <Textarea value={messageText} onChange={(event) => setMessageText(event.target.value)} placeholder="Deploy reminder" />
        </Field>
        <FieldRow>
          <Field label="Schedule" hint="Examples: +10m, +1h, 0 9 * * *">
            <Input value={messageSchedule} onChange={(event) => setMessageSchedule(event.target.value)} />
          </Field>
          <Field label="Delete after seconds" hint="Use 0 to keep the message after sending.">
            <Input type="number" min={0} value={messageDeleteAfter} onChange={(event) => setMessageDeleteAfter(event.target.value)} />
          </Field>
        </FieldRow>
        <div style={{ display: 'flex', justifyContent: 'flex-end', gap: 8 }}>
          <Button variant="outline" onClick={() => setEditorOpen(false)}>Cancel</Button>
          <Button onClick={() => void handleSaveScheduledMessage()} disabled={savingMessage}>{savingMessage ? 'Saving…' : editingMessage ? 'Save changes' : 'Create message'}</Button>
        </div>
      </Dialog>
    </PageShell>
  )
}
