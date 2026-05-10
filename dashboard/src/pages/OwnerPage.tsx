import { useState } from 'react'

import { Badge, Button, Card, ContentGrid, EmptyState, MetricCard, Table } from '../components/ui/primitives'
import { PageShell } from '../lib/page-shell'
import { getStoredUser } from '../lib/auth'
import { useI18n } from '../lib/i18n'

const GROUPS = [
  ['Invest Community', <Badge tone="success">92</Badge>, '1842', <Badge tone="success">active</Badge>, ''],
  ['Trading AR', <Badge tone="warning">74</Badge>, '934', <Badge tone="warning">pending</Badge>, <div style={{ display: 'flex', gap: 8 }}><Button>Approve</Button><Button variant="outline">Decline</Button></div>],
  ['Alpha Signals', <Badge tone="warning">68</Badge>, '2231', <Badge>none</Badge>, ''],
  ['Owner Lab', <Badge tone="success">88</Badge>, '1474', <Badge tone="success">active</Badge>, ''],
]

export default function OwnerPage() {
  const { t } = useI18n()
  const [page, setPage] = useState(1)
  const user = getStoredUser()

  if (user?.role !== 'owner') {
    return (
      <PageShell eyebrow="Owner" titleKey="page.owner" descriptionKey="page.owner.desc">
        <EmptyState title="Access denied" subtitle="This area is available to owner accounts only." />
      </PageShell>
    )
  }

  return (
    <PageShell eyebrow="Owner" titleKey="page.owner" descriptionKey="page.owner.desc">
      <ContentGrid columns="repeat(auto-fit, minmax(220px, 1fr))">
        <MetricCard label="Total groups" value="4" hint="Tracked workspaces" />
        <MetricCard label="Total members" value="6481" hint="Across all groups" />
        <MetricCard label="Active subs" value="2" hint="Approved access" />
        <MetricCard label="Pending requests" value="1" hint="Awaiting review" />
      </ContentGrid>
      <Card>
        <Table columns={['Name', 'Health', 'Members', 'Subscription', 'Actions']} rows={GROUPS.slice((page - 1) * 2, page * 2)} />
        <div style={{ display: 'flex', justifyContent: 'space-between', marginTop: 12 }}>
          <Button variant="outline" disabled={page === 1} onClick={() => setPage((current) => Math.max(1, current - 1))}>Prev</Button>
          <Button variant="outline" disabled={page >= 2} onClick={() => setPage((current) => current + 1)}>Next</Button>
        </div>
      </Card>
    </PageShell>
  )
}
