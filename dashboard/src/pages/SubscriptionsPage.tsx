import { useState } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { Ticket, Users, CheckCircle2, XCircle, Plus, Calendar, Clock, RefreshCw, Trash2 } from 'lucide-react'

import { 
  Badge, 
  Button, 
  Card, 
  ContentGrid, 
  EmptyState, 
  MetricCard, 
  Table, 
  LoadingState,
  Dialog,
  Field,
  Input,
  FieldRow,
  Select,
  ToggleRow
} from '../components/ui/primitives'
import { PageShell } from '../lib/page-shell'
import { getStoredUser } from '../lib/auth'
import { 
  fetchOwnerSubscriptions, 
  updateOwnerSubscription, 
  fetchOwnerPromoCodes, 
  createOwnerPromoCode, 
  updateOwnerPromoCode,
  deleteOwnerPromoCode,
  fetchOwnerStats 
} from '../lib/api'
import { useI18n } from '../lib/i18n'

export default function SubscriptionsPage() {
  const { t } = useI18n()
  const queryClient = useQueryClient()
  const user = getStoredUser()
  const [promoDialogOpen, setPromoDialogOpen] = useState(false)
  const [approvalPlans, setApprovalPlans] = useState<Record<number, 'pro' | 'business'>>({})
  
  // Form state for new promo code
  const [newPromo, setNewPromo] = useState({
    code: '',
    plan: 'pro' as 'pro' | 'business',
    duration_days: 30,
    max_uses: 0,
    is_active: true
  })

  const { data: stats } = useQuery({
    queryKey: ['owner', 'stats'],
    queryFn: fetchOwnerStats,
  })

  const { data: subs, isLoading: subsLoading } = useQuery({
    queryKey: ['owner', 'subscriptions'],
    queryFn: fetchOwnerSubscriptions,
  })

  const { data: promos, isLoading: promosLoading } = useQuery({
    queryKey: ['owner', 'promos'],
    queryFn: () => fetchOwnerPromoCodes(),
  })

  const subMutation = useMutation({
    mutationFn: ({ id, action, plan }: { id: number, action: 'approve' | 'decline', plan?: 'pro' | 'business' }) => 
      updateOwnerSubscription(id, action, plan),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['owner', 'subscriptions'] })
      queryClient.invalidateQueries({ queryKey: ['owner', 'stats'] })
    }
  })

  const createPromoMutation = useMutation({
    mutationFn: (payload: any) => createOwnerPromoCode(payload),
    onSuccess: () => {
      setPromoDialogOpen(false)
      setNewPromo({ code: '', plan: 'pro', duration_days: 30, max_uses: 0, is_active: true })
      queryClient.invalidateQueries({ queryKey: ['owner', 'promos'] })
    }
  })

  const updatePromoMutation = useMutation({
    mutationFn: ({ id, payload }: { id: number, payload: any }) => 
      updateOwnerPromoCode(id, payload),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['owner', 'promos'] })
    }
  })

  const deletePromoMutation = useMutation({
    mutationFn: (id: number) => deleteOwnerPromoCode(id),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['owner', 'promos'] })
    }
  })

  if (user?.role !== 'owner') {
    return (
      <PageShell eyebrow="Owner" titleKey="page.subscriptions" descriptionKey="page.subscriptions.desc">
        <EmptyState title="Access denied" subtitle="This area is available to owner accounts only." />
      </PageShell>
    )
  }

  const subRows = (subs || []).map((sub: any) => [
    <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
      <div style={{ width: 32, height: 32, borderRadius: 8, background: 'var(--ui-bg-muted)', display: 'grid', placeItems: 'center', color: 'var(--ui-primary)' }}>
        <Users size={16} />
      </div>
      <div>
        <div style={{ fontWeight: 700 }}>{sub.full_name || 'Telegram User'}</div>
        <div style={{ fontSize: 12, color: 'var(--ui-text-muted)' }}>@{sub.username || 'no_username'} · {sub.tg_user_id}</div>
      </div>
    </div>,
    <div style={{ maxWidth: 240, fontSize: 13, color: 'var(--ui-text-muted)', fontStyle: sub.message ? 'normal' : 'italic' }}>
      {sub.message || 'No message provided'}
    </div>,
    <Badge tone={
      sub.status === 'approved' ? 'success' : 
      sub.status === 'pending' ? 'warning' : 
      sub.status === 'declined' ? 'destructive' : 'neutral'
    }>
      {sub.status}
    </Badge>,
    <div style={{ fontSize: 12, color: 'var(--ui-text-muted)' }}>
      {new Date(sub.created_at).toLocaleDateString()}
    </div>,
    <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
      {sub.status === 'pending' ? (
        <>
          <div style={{ width: 100 }}>
            <Select 
              uiSize="sm" 
              value={approvalPlans[sub.id] || 'pro'} 
              onChange={(e) => setApprovalPlans({ ...approvalPlans, [sub.id]: e.target.value as any })}
            >
              <option value="pro">Pro</option>
              <option value="business">Business</option>
            </Select>
          </div>
          <Button 
            size="sm" 
            variant="default" 
            onClick={() => subMutation.mutate({ 
              id: sub.id, 
              action: 'approve', 
              plan: approvalPlans[sub.id] || 'pro' 
            })}
            disabled={subMutation.isPending}
          >
            Approve
          </Button>
          <Button 
            size="sm" 
            variant="outline" 
            onClick={() => subMutation.mutate({ id: sub.id, action: 'decline' })}
            disabled={subMutation.isPending}
          >
            Decline
          </Button>
        </>
      ) : (
        <span style={{ fontSize: 12, color: 'var(--ui-text-muted)' }}>
          {sub.status === 'approved' ? `Approved as ${sub.plan || 'pro'}` : 'No actions'}
        </span>
      )}
    </div>
  ])

  const promoRows = (promos || []).map((p: any) => [
    <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
      <div style={{ width: 32, height: 32, borderRadius: 8, background: 'var(--ui-bg-muted)', display: 'grid', placeItems: 'center', color: 'var(--ui-primary)' }}>
        <Ticket size={16} />
      </div>
      <div style={{ fontFamily: 'monospace', fontWeight: 800, fontSize: 14 }}>{p.code}</div>
    </div>,
    <Badge tone={p.plan === 'business' ? 'success' : 'neutral'}>{p.plan}</Badge>,
    <div style={{ fontWeight: 600 }}>{p.duration_days} days</div>,
    <div style={{ fontSize: 13 }}>
      {p.used_count} / {p.max_uses || '∞'}
    </div>,
    <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
      <ToggleRow
        title=""
        subtitle=""
        checked={p.is_active}
        onCheckedChange={(checked) => updatePromoMutation.mutate({ id: p.id, payload: { is_active: checked } })}
        disabled={updatePromoMutation.isPending}
      />
    </div>,
    <div style={{ display: 'flex', gap: 8 }}>
      <Button 
        size="sm" 
        variant="outline" 
        onClick={() => { if(confirm('Are you sure you want to delete this promo code?')) deletePromoMutation.mutate(p.id) }}
        disabled={deletePromoMutation.isPending}
      >
        <Trash2 size={14} />
      </Button>
    </div>
  ])

  return (
    <PageShell 
      eyebrow="Owner" 
      titleKey="page.subscriptions" 
      descriptionKey="page.subscriptions.desc"
    >
      <ContentGrid columns="repeat(auto-fit, minmax(240px, 1fr))">
        <MetricCard 
          label="Active Subs" 
          value={stats?.active_subscriptions?.toString() || '0'} 
          hint="Approved accounts" 
          icon={<CheckCircle2 size={20} />}
        />
        <MetricCard 
          label="Pending Requests" 
          value={stats?.pending_requests?.toString() || '0'} 
          hint="Awaiting review" 
          icon={<Clock size={20} />}
        />
        <MetricCard 
          label="Promo Codes" 
          value={(promos?.length || 0).toString()} 
          hint="Active campaigns" 
          icon={<Ticket size={20} />}
        />
      </ContentGrid>

      <div style={{ display: 'grid', gap: 24 }}>
        <Card title="Subscription Requests" subtitle="Users requesting access to the premium agent features.">
          {subsLoading ? (
            <LoadingState />
          ) : subRows.length > 0 ? (
            <Table 
              columns={['Requester', 'Message', 'Status', 'Requested', 'Actions']} 
              rows={subRows} 
            />
          ) : (
            <EmptyState title="No requests" subtitle="Manual subscription requests will appear here." />
          )}
        </Card>

        <Card 
          title="Promotion Codes" 
          subtitle="Generate codes that users can redeem for trial or paid periods."
        >
          <div style={{ marginBottom: 16, display: 'flex', justifyContent: 'flex-end' }}>
            <Button onClick={() => setPromoDialogOpen(true)}>
              <Plus size={16} style={{ marginRight: 8 }} />
              Create Promo Code
            </Button>
          </div>
          
          {promosLoading ? (
            <LoadingState />
          ) : promoRows.length > 0 ? (
            <Table 
              columns={['Code', 'Plan', 'Duration', 'Usage', 'Active', 'Actions']} 
              rows={promoRows} 
            />
          ) : (
            <EmptyState title="No codes" subtitle="Create your first promotion code to attract users." />
          )}
        </Card>
      </div>

      <Dialog 
        open={promoDialogOpen} 
        onClose={() => setPromoDialogOpen(false)}
        title="Create Promo Code"
        description="This code can be shared with users to grant them a period of premium access."
      >
        <div style={{ display: 'grid', gap: 16 }}>
          <FieldRow>
            <Field label="Code Name" hint="Alphanumeric string (e.g. TRIAL30)">
              <Input 
                value={newPromo.code} 
                onChange={(e) => setNewPromo({ ...newPromo, code: e.target.value.toUpperCase() })} 
                placeholder="SUMMER2026"
              />
            </Field>
            <Field label="Plan" hint="Tier to grant">
              <Select 
                value={newPromo.plan} 
                onChange={(e) => setNewPromo({ ...newPromo, plan: e.target.value as any })}
              >
                <option value="pro">Pro</option>
                <option value="business">Business</option>
              </Select>
            </Field>
          </FieldRow>
          
          <FieldRow>
            <Field label="Duration (Days)" hint="Length of access">
              <Input 
                type="number" 
                value={newPromo.duration_days} 
                onChange={(e) => setNewPromo({ ...newPromo, duration_days: parseInt(e.target.value) || 1 })} 
              />
            </Field>
            <Field label="Max Uses" hint="0 for unlimited">
              <Input 
                type="number" 
                value={newPromo.max_uses} 
                onChange={(e) => setNewPromo({ ...newPromo, max_uses: parseInt(e.target.value) || 0 })} 
              />
            </Field>
          </FieldRow>

          <Button 
            onClick={() => createPromoMutation.mutate({
              ...newPromo,
              max_uses: newPromo.max_uses > 0 ? newPromo.max_uses : undefined
            })}
            disabled={createPromoMutation.isPending || !newPromo.code}
          >
            {createPromoMutation.isPending ? 'Creating...' : 'Create Code'}
          </Button>
        </div>
      </Dialog>
    </PageShell>
  )
}
