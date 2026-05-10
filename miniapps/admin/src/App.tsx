import React, { useEffect, useState } from 'react'
import { 
  adminApi, 
  useMiniappSession,
  type ManagedGroup,
  type AIModerationSettings,
  type AIModerationEvent,
  type GroupSubscriptionSettings,
  type SubscriptionPlan,
  type GroupSubscriber,
  type PaymentRecord,
  type GroupOverview
} from '@miniapp/shared'

import { Layout } from './components/Layout'
import { GroupSelector } from './components/GroupSelector'
import { DashboardPage } from './pages/DashboardPage'
import { ModerationPage } from './pages/ModerationPage'
import { EventsPage } from './pages/EventsPage'
import { SubscriptionsPage } from './pages/SubscriptionsPage'

const ADMIN_TABS = ['dashboard', 'moderation', 'events', 'subscriptions', 'settings'] as const
type AdminTab = typeof ADMIN_TABS[number]

function isAdminTab(value: string): value is AdminTab {
  return (ADMIN_TABS as readonly string[]).includes(value)
}

function resolveInitialTab(): AdminTab {
  const params = new URLSearchParams(window.location.search)
  const queryTab = params.get('tab')?.trim().toLowerCase()
  if (queryTab && isAdminTab(queryTab)) {
    return queryTab
  }

  const hashTab = window.location.hash.replace(/^#\/?/, '').split('/')[0]?.trim().toLowerCase()
  if (hashTab && isAdminTab(hashTab)) {
    return hashTab
  }

  const pathTab = window.location.pathname.split('/').filter(Boolean).pop()?.trim().toLowerCase()
  if (pathTab && pathTab !== 'admin' && isAdminTab(pathTab)) {
    return pathTab
  }

  return 'dashboard'
}

const App: React.FC = () => {
  const session = useMiniappSession()
  const { groups } = session
  const [activeTab, setActiveTab] = useState<AdminTab>(() => resolveInitialTab())
  const [selectedGroup, setSelectedGroup] = useState<ManagedGroup | null>(null)
  
  // Data States
  const [aiSettings, setAiSettings] = useState<AIModerationSettings | null>(null)
  const [aiEvents, setAiEvents] = useState<AIModerationEvent[]>([])
  const [overview, setOverview] = useState<GroupOverview | null>(null)
  
  const [subSettings, setSubSettings] = useState<GroupSubscriptionSettings | null>(null)
  const [subPlans, setSubPlans] = useState<SubscriptionPlan[]>([])
  const [subscribers, setSubscribers] = useState<GroupSubscriber[]>([])
  const [payments, setPayments] = useState<PaymentRecord[]>([])

  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    if (groups.length === 0) {
      setSelectedGroup(null)
      return
    }
    if (!selectedGroup || !groups.some(group => group.id === selectedGroup.id)) {
      setSelectedGroup(groups[0])
    }
  }, [groups, selectedGroup])

  useEffect(() => {
    const syncTabFromLocation = () => setActiveTab(resolveInitialTab())
    window.addEventListener('popstate', syncTabFromLocation)
    window.addEventListener('hashchange', syncTabFromLocation)
    return () => {
      window.removeEventListener('popstate', syncTabFromLocation)
      window.removeEventListener('hashchange', syncTabFromLocation)
    }
  }, [])

  useEffect(() => {
    if (selectedGroup) {
      void refreshData()
    }
  }, [selectedGroup])

  const refreshData = async () => {
    if (!session.identity || !selectedGroup) return
    setLoading(true)
    setError(null)
    try {
      const [aiSettingsRes, aiEventsRes, overviewRes] = await Promise.all([
        adminApi.fetchAIModerationSettings(selectedGroup.id),
        adminApi.fetchAIModerationEvents(selectedGroup.id),
        adminApi.fetchGroupOverview(selectedGroup.id)
      ])
      
      setAiSettings(aiSettingsRes.settings)
      setAiEvents(aiEventsRes)
      setOverview(overviewRes)

      const subscriptionResults = await Promise.allSettled([
        adminApi.fetchGroupSubscriptionSettings(selectedGroup.id),
        adminApi.fetchSubscriptionPlans(selectedGroup.id),
        adminApi.fetchGroupSubscribers(selectedGroup.id),
        adminApi.fetchGroupPayments(selectedGroup.id)
      ])

      if (subscriptionResults[0].status === 'fulfilled') {
        setSubSettings(subscriptionResults[0].value as GroupSubscriptionSettings)
      }
      if (subscriptionResults[1].status === 'fulfilled') {
        setSubPlans(subscriptionResults[1].value as SubscriptionPlan[])
      }
      if (subscriptionResults[2].status === 'fulfilled') {
        setSubscribers(subscriptionResults[2].value as GroupSubscriber[])
      }
      if (subscriptionResults[3].status === 'fulfilled') {
        setPayments(subscriptionResults[3].value as PaymentRecord[])
      }

    } catch (err) {
      console.error("Failed to fetch data:", err)
      setError(err instanceof Error ? err.message : 'Failed to load admin data')
    } finally {
      setLoading(false)
    }
  }

  const handleUpdateSettings = async (updates: Partial<AIModerationSettings>) => {
    if (!selectedGroup || !aiSettings) return
    setAiSettings({ ...aiSettings, ...updates })
    try {
      await adminApi.updateAIModerationSettings(selectedGroup.id, updates)
    } catch (err) {
      void refreshData()
    }
  }

  const [actionLoading, setActionLoading] = useState<number | null>(null)

  const handleEventAction = async (eventId: number, action: string) => {
    if (!selectedGroup) return
    const event = aiEvents.find(e => e.id === eventId)
    if (!event || !event.user_id) return

    if (action === 'delete') {
      setAiEvents(prev => prev.filter(e => e.id !== eventId))
      return
    }

    setActionLoading(eventId)
    try {
      await adminApi.performModerationAction(selectedGroup.id, {
        user_id: event.user_id,
        action: action as 'approve' | 'warn' | 'mute' | 'ban',
      })
      setAiEvents(prev => prev.filter(e => e.id !== eventId))
    } catch (err) {
      console.error('Failed to perform moderation action:', err)
    } finally {
      setActionLoading(null)
    }
  }

  const handleMarkPaid = async (paymentId: number) => {
    if (!selectedGroup) return
    try {
      await adminApi.markPaymentPaid(selectedGroup.id, paymentId)
      void refreshData()
    } catch (err) {
      console.error("Failed to mark paid:", err)
    }
  }

  function handleTabChange(tab: string) {
    const nextTab = isAdminTab(tab) ? tab : 'dashboard'
    setActiveTab(nextTab)
    const nextUrl = `${window.location.pathname}${window.location.search}#/${nextTab}`
    window.history.replaceState({}, '', nextUrl)
  }

  if (session.loading) {
    return (
      <div className="flex items-center justify-center min-h-screen p-10 text-center">
        <div className="space-y-4">
          <div className="mx-auto w-12 h-12 rounded-full border-4 border-primary/20 border-t-primary animate-spin"></div>
          <h2 className="text-xl font-bold">Loading Admin</h2>
          <p className="text-on-secondary-container">Preparing your moderation dashboard.</p>
        </div>
      </div>
    )
  }

  if (!session.identity) {
    return (
      <div className="flex items-center justify-center min-h-screen p-10 text-center">
        <div className="space-y-4">
          <span className="material-symbols-outlined text-6xl text-primary/20">lock</span>
          <h2 className="text-xl font-bold">Authentication Required</h2>
          <p className="text-on-secondary-container">{session.error || 'Open this WebApp from Telegram to continue.'}</p>
        </div>
      </div>
    )
  }

  if (!selectedGroup) {
    return (
      <div className="flex items-center justify-center min-h-screen p-10 text-center">
        <div className="space-y-4">
          <span className="material-symbols-outlined text-6xl text-primary/20">group_off</span>
          <h2 className="text-xl font-bold">No Groups Found</h2>
          <p className="text-on-secondary-container">You need to be an admin to use this dashboard.</p>
        </div>
      </div>
    )
  }

  return (
    <Layout 
      activeTab={activeTab} 
      onTabChange={handleTabChange}
      title="Admin Dashboard"
      dashboardUrl={`${window.location.origin.replace('/webapp/admin', '')}/dashboard`}
    >
      <GroupSelector 
        groups={groups} 
        selectedGroup={selectedGroup} 
        onSelect={setSelectedGroup} 
      />

      {error && (
        <div className="rounded-xl bg-red-50 border border-red-100 p-4 text-sm text-red-700">
          {error}
        </div>
      )}

      {activeTab === 'dashboard' && (
        <DashboardPage 
          safetyScore={85}
          stats={{
            scanned: overview?.stats?.messages_count ?? 0,
            spam: overview?.stats?.spam_detected ?? 0,
            activeMembers: overview?.stats?.members_count ?? 0,
            deleted: overview?.stats?.messages_deleted ?? 0
          }}
          recentEvents={overview?.recent_events ?? []}
          loading={loading}
        />
      )}

      {activeTab === 'moderation' && (
        aiSettings ? (
          <ModerationPage
            settings={aiSettings}
            onUpdate={handleUpdateSettings}
          />
        ) : (
          <div className="bg-white rounded-xl p-10 text-center space-y-4 shadow-[0_4px_20px_rgba(15,23,42,0.05)]">
            <span className="material-symbols-outlined text-6xl text-primary/20">security</span>
            <h2 className="text-xl font-bold">Loading Moderation</h2>
            <p className="text-on-secondary-container">Moderation settings will appear here once loaded.</p>
          </div>
        )
      )}

      {activeTab === 'events' && (
        <EventsPage 
          events={aiEvents} 
          onAction={handleEventAction}
          actionLoading={actionLoading}
        />
      )}

      {activeTab === 'subscriptions' && (
        <SubscriptionsPage 
          plans={subPlans}
          subscribers={subscribers}
          payments={payments}
          onMarkPaid={handleMarkPaid}
        />
      )}

      {activeTab === 'settings' && (
        <div className="bg-white rounded-xl p-10 text-center space-y-4 shadow-[0_4px_20px_rgba(15,23,42,0.05)]">
          <span className="material-symbols-outlined text-6xl text-primary/20">settings_applications</span>
          <h2 className="text-xl font-bold">Bot Settings</h2>
          <p className="text-on-secondary-container">Configure general bot behavior and permissions.</p>
        </div>
      )}

      {loading && (
        <div className="fixed inset-0 bg-white/20 backdrop-blur-[1px] flex items-center justify-center z-[100]">
          <div className="w-12 h-12 rounded-full border-4 border-primary/20 border-t-primary animate-spin"></div>
        </div>
      )}
    </Layout>
  )
}

export default App
