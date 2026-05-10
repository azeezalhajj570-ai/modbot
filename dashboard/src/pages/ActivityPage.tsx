import { useMemo, useState } from 'react'

import { Button, Card, Field, ListItem, Sheet, Tabs, Textarea } from '../components/ui/primitives'
import { PageShell } from '../lib/page-shell'
import { useI18n } from '../lib/i18n'

const EVENTS = [
  { type: 'moderation', title: 'User warned', subtitle: '@market_bot · repeated links', timestamp: '3m ago', color: '#f59e0b' },
  { type: 'moderation', title: 'User muted', subtitle: '@spam_acc · suspicious invite', timestamp: '8m ago', color: '#ef4444' },
  { type: 'system', title: 'Preset changed', subtitle: 'Protection preset switched to Balanced', timestamp: '14m ago', color: '#3b82f6' },
  { type: 'report', title: 'Report received', subtitle: 'Member flagged an offensive message', timestamp: '33m ago', color: '#f59e0b' },
]

export default function ActivityPage() {
  const { t } = useI18n()
  const [tab, setTab] = useState('all')
  const [sheetOpen, setSheetOpen] = useState(false)
  const [reply, setReply] = useState('')

  const filtered = useMemo(() => EVENTS.filter((event) => (tab === 'all' ? true : event.type === tab)), [tab])

  return (
    <PageShell eyebrow="Activity" titleKey="page.activity" descriptionKey="page.activity.desc">
      <Tabs value={tab} onChange={setTab} items={[{ value: 'all', label: 'All' }, { value: 'moderation', label: 'Moderation' }, { value: 'system', label: 'System' }, { value: 'report', label: 'Reports' }]} />
      <Card>
        <div style={{ display: 'grid' }}>
          {filtered.map((event) => (
            <ListItem
              key={`${event.type}-${event.title}`}
              markerColor={event.color}
              title={event.title}
              subtitle={event.subtitle}
              meta={<span style={{ fontSize: 12, color: 'var(--ui-text-muted)', fontWeight: 700 }}>{event.timestamp}</span>}
              actions={event.type === 'report' ? <Button variant="outline" onClick={() => setSheetOpen(true)}>Reply</Button> : undefined}
            />
          ))}
        </div>
      </Card>
      <Sheet
        open={sheetOpen}
        title="Reply to report"
        description="Responses follow the same side-panel editing model used for other workspace actions."
        onClose={() => setSheetOpen(false)}
        footer={
          <div style={{ display: 'flex', justifyContent: 'space-between', gap: 12 }}>
            <Button variant="outline" onClick={() => setSheetOpen(false)}>Cancel</Button>
            <Button onClick={() => setSheetOpen(false)}>Send reply</Button>
          </div>
        }
      >
        <Field label="Reply" hint="Replies are sent through the same structured moderation flow.">
          <Textarea placeholder="Write your reply" value={reply} onChange={(event) => setReply(event.target.value)} />
        </Field>
      </Sheet>
    </PageShell>
  )
}
