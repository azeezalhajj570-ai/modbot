import { useState } from 'react'

import { ActionBar, Badge, Button, Card, Field, FieldRow, Input, ListItem, Select, Sheet, Textarea } from '../components/ui/primitives'
import { PageShell } from '../lib/page-shell'
import { useI18n } from '../lib/i18n'

const TASKS = [
  { id: 'task-1', taskType: 'broadcast', executor: 'Agent 7', source: 'Invest Community', status: 'active' },
  { id: 'task-2', taskType: 'auto_reply', executor: 'Bot', source: 'Trading AR', status: 'draft' },
]

export default function AutomationPage() {
  const { t } = useI18n()
  const [open, setOpen] = useState(false)

  return (
    <PageShell eyebrow="Automation" titleKey="page.automation" descriptionKey="page.automation.desc" actions={<Button onClick={() => setOpen(true)}>New task</Button>}>
      <div style={{ display: 'grid', gap: 16 }}>
        {TASKS.map((task) => (
          <Card key={task.id}>
            <ListItem
              title={task.executor}
              subtitle={`${task.source} · ${task.taskType}`}
              meta={<><Badge tone="info">{task.taskType}</Badge><Badge tone={task.status === 'active' ? 'success' : 'warning'}>{task.status}</Badge></>}
              actions={<><Button variant="outline" onClick={() => setOpen(true)}>Edit</Button><Button variant="destructive">Delete</Button></>}
            />
          </Card>
        ))}
      </div>
      <Sheet
        open={open}
        title="Automation task"
        description="Use the same structured fields and action order as the compact Mini App task flow, with added desktop detail."
        onClose={() => setOpen(false)}
        footer={<ActionBar secondary={<Button variant="outline" onClick={() => setOpen(false)}>Cancel</Button>} primary={<Button onClick={() => setOpen(false)}>Save task</Button>} />}
      >
        <FieldRow>
          <Field label="Task ID"><Input placeholder="task-101" /></Field>
          <Field label="Task type">
            <Select defaultValue="broadcast">
              <option value="broadcast">Broadcast</option>
              <option value="message_forward">Message forward</option>
              <option value="auto_reply">Auto reply</option>
              <option value="lead_notify">Lead notify</option>
            </Select>
          </Field>
        </FieldRow>
        <FieldRow>
          <Field label="Executor"><Input placeholder="Agent 7" /></Field>
          <Field label="Source group"><Input placeholder="Invest Community" /></Field>
        </FieldRow>
        <Field label="Message template"><Textarea placeholder="Message template" /></Field>
      </Sheet>
    </PageShell>
  )
}
