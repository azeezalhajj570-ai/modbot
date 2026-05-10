import { useMemo, useState } from 'react'

import { ActionBar, Badge, Button, Card, Field, Input, Select, Sheet, Table } from '../components/ui/primitives'
import { PageShell } from '../lib/page-shell'
import { useI18n } from '../lib/i18n'

const MEMBERS = [
  { name: 'Ali Hassan', username: '@ali_h', role: 'owner', joinedAt: '2026-01-01' },
  { name: 'Mona Saleh', username: '@mona_s', role: 'admin', joinedAt: '2026-01-14' },
  { name: 'Fahad Omar', username: '@fahad_o', role: 'member', joinedAt: '2026-02-03' },
  { name: 'Sara Noor', username: '@sara_n', role: 'banned', joinedAt: '2026-02-19' },
]

export default function MembersPage() {
  const { t } = useI18n()
  const [query, setQuery] = useState('')
  const [filter, setFilter] = useState('all')
  const [sheetOpen, setSheetOpen] = useState(false)

  const rows = useMemo(() => {
    return MEMBERS.filter((member) => {
      const matchesQuery =
        !query ||
        member.name.toLowerCase().includes(query.toLowerCase()) ||
        member.username.toLowerCase().includes(query.toLowerCase())
      const matchesFilter = filter === 'all' ? true : member.role === filter
      return matchesQuery && matchesFilter
    }).map((member) => [
      member.name,
      member.username,
      <Badge tone={member.role === 'banned' ? 'destructive' : member.role === 'admin' || member.role === 'owner' ? 'warning' : 'default'}>
        {member.role}
      </Badge>,
      member.joinedAt,
      <div style={{ display: 'flex', gap: 8 }}>
        <Button variant="outline">Warn</Button>
        <Button variant="outline">Mute</Button>
        <Button variant="destructive">Ban</Button>
      </div>,
    ])
  }, [filter, query])

  return (
    <PageShell eyebrow="Members" titleKey="page.members" descriptionKey="page.members.desc" actions={<Button onClick={() => setSheetOpen(true)}>Bulk actions</Button>}>
      <div style={{ display: 'grid', gridTemplateColumns: '1fr 180px', gap: 12 }}>
        <Input placeholder="Search members" value={query} onChange={(e) => setQuery(e.target.value)} />
        <Select value={filter} onChange={(e) => setFilter(e.target.value)}>
          <option value="all">All</option>
          <option value="admin">Admins</option>
          <option value="banned">Banned</option>
        </Select>
      </div>
      <Card>
        <Table columns={['Name', 'Username', 'Role', 'Joined', 'Actions']} rows={rows} />
      </Card>
      <Sheet
        open={sheetOpen}
        title="Bulk member action"
        description="Bulk member flows use the same action order and confirmation-ready structure as the rest of the product."
        onClose={() => setSheetOpen(false)}
        footer={<ActionBar secondary={<Button variant="outline" onClick={() => setSheetOpen(false)}>Cancel</Button>} primary={<Button onClick={() => setSheetOpen(false)}>Apply action</Button>} />}
      >
        <Field label="Members" hint="Paste member IDs or usernames.">
          <Input placeholder="@ali_h, @mona_s" />
        </Field>
        <Field label="Action">
          <Select defaultValue="warn">
            <option value="warn">Warn</option>
            <option value="mute">Mute</option>
            <option value="ban">Ban</option>
          </Select>
        </Field>
      </Sheet>
    </PageShell>
  )
}
