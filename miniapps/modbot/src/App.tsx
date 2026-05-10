import React, { useEffect, useState } from 'react'
import {
  adminApi,
  useMiniappSession,
  type ManagedGroup,
  type AIModerationSettings,
  type AIModerationEvent,
  type GroupOverview,
  type AutomationTask,
  type ScheduledMessage,
  type GroupSettings,
  type AccessGateInfo,
  type ModerationLogEntry,
} from '@miniapp/shared'

import { Layout } from './components/Layout'
import { GroupSelector } from './components/GroupSelector'
import { ToastProvider, useToast } from './components/Toast'
import { LanguageProvider, useLang } from './components/LanguageContext'
import { DashboardPage } from './pages/DashboardPage'
import { TasksPage } from './pages/TasksPage'
import { EventsPage } from './pages/EventsPage'
import { ModerationPage } from './pages/ModerationPage'

const MODBOT_TABS = ['dashboard', 'moderation', 'tasks', 'events'] as const
type ModbotTab = typeof MODBOT_TABS[number]

function isModbotTab(value: string): value is ModbotTab {
  return (MODBOT_TABS as readonly string[]).includes(value)
}

function resolveInitialTab(): ModbotTab {
  const params = new URLSearchParams(window.location.search)
  const queryTab = params.get('tab')?.trim().toLowerCase()
  if (queryTab && isModbotTab(queryTab)) return queryTab

  const hashTab = window.location.hash.replace(/^#\/?/, '').split('/')[0]?.trim().toLowerCase()
  if (hashTab && isModbotTab(hashTab)) return hashTab

  const pathTab = window.location.pathname.split('/').filter(Boolean).pop()?.trim().toLowerCase()
  if (pathTab && pathTab !== 'modbot' && isModbotTab(pathTab)) return pathTab

  return 'dashboard'
}

const App: React.FC = () => (
  <LanguageProvider>
    <ToastProvider>
      <AppInner />
    </ToastProvider>
  </LanguageProvider>
)

const AppInner: React.FC = () => {
  const { showToast } = useToast()
  const { t, dir, toggleLang, lang } = useLang()
  const session = useMiniappSession()
  const { groups, refreshSession } = session
  const [activeTab, setActiveTab] = useState<ModbotTab>(() => resolveInitialTab())
  const [selectedGroup, setSelectedGroup] = useState<ManagedGroup | null>(null)

  const [overview, setOverview] = useState<GroupOverview | null>(null)
  const [aiSettings, setAiSettings] = useState<AIModerationSettings | null>(null)
  const [aiEvents, setAiEvents] = useState<AIModerationEvent[]>([])
  const [modLogs, setModLogs] = useState<ModerationLogEntry[]>([])
  const [tasks, setTasks] = useState<AutomationTask[]>([])
  const [scheduledMessages, setScheduledMessages] = useState<ScheduledMessage[]>([])
  const [groupSettings, setGroupSettings] = useState<GroupSettings | null>(null)
  const [accessGate, setAccessGate] = useState<AccessGateInfo | null>(null)
  const [welcomeSettings, setWelcomeSettings] = useState<GroupSettings | null>(null)
  const [adsSettings, setAdsSettings] = useState<GroupSettings | null>(null)

  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    if (groups.length === 0) {
      setSelectedGroup(null)
      return
    }
    if (!selectedGroup || !groups.some(g => g.id === selectedGroup.id)) {
      setSelectedGroup(groups[0])
    }
  }, [groups, selectedGroup])

  useEffect(() => {
    const syncTab = () => setActiveTab(resolveInitialTab())
    window.addEventListener('popstate', syncTab)
    window.addEventListener('hashchange', syncTab)
    return () => {
      window.removeEventListener('popstate', syncTab)
      window.removeEventListener('hashchange', syncTab)
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
      const [overviewRes, aiSettingsRes, aiEventsRes, logsRes, tasksRes, schedRes, settingsRes] = await Promise.all([
        adminApi.fetchGroupOverview(selectedGroup.id),
        adminApi.fetchAIModerationSettings(selectedGroup.id),
        adminApi.fetchAIModerationEvents(selectedGroup.id),
        adminApi.fetchModerationLogs(selectedGroup.id),
        adminApi.fetchTasks(selectedGroup.id),
        adminApi.fetchScheduledMessages(selectedGroup.id),
        adminApi.fetchGroupSettings(selectedGroup.id),
      ])

      setOverview(overviewRes)
      setAiSettings(aiSettingsRes.settings)
      setAiEvents(aiEventsRes)
      setModLogs(logsRes)
      setTasks(tasksRes)
      setScheduledMessages(schedRes)
      setGroupSettings(settingsRes)

      const [gateRes] = await Promise.allSettled([
        adminApi.fetchAccessGate(selectedGroup.id),
      ])
      if (gateRes.status === 'fulfilled') {
        setAccessGate(gateRes.value)
      }
    } catch (err) {
      console.error('Failed to fetch modbot data:', err)
      setError(err instanceof Error ? err.message : 'Failed to load moderation data')
    } finally {
      setLoading(false)
    }
  }

  const toastSuccess = (msg: string) => showToast(msg, 'success')
  const toastError = (msg: string) => showToast(msg, 'error')

  const handleUpdateAiSettings = async (updates: Partial<AIModerationSettings>) => {
    if (!selectedGroup || !aiSettings) return
    setAiSettings({ ...aiSettings, ...updates })
    try {
      await adminApi.updateAIModerationSettings(selectedGroup.id, updates)
      toastSuccess('AI settings saved')
    } catch (err) {
      toastError('Failed to save AI settings')
      void refreshData()
    }
  }

  const handleUpdateGroupSettings = async (updates: Record<string, boolean | number | string>) => {
    if (!selectedGroup || !groupSettings) return
    setGroupSettings({ ...groupSettings, settings: { ...groupSettings.settings, ...updates } })
    try {
      await adminApi.updateGroupSettings(selectedGroup.id, updates)
      toastSuccess('Group settings saved')
    } catch (err) {
      toastError('Failed to save group settings')
      void refreshData()
    }
  }

  const handleUpdateAccessGate = async (requiredGroupTgIds: number[]) => {
    if (!selectedGroup) return
    try {
      await adminApi.updateAccessGate(selectedGroup.id, requiredGroupTgIds)
      toastSuccess('Access gate updated')
      void refreshData()
    } catch (err) {
      toastError('Failed to update access gate')
    }
  }

  const handleCreateTask = async (payload: {
    task_key: string
    enabled?: boolean
    conditions?: Record<string, unknown>
    config?: Record<string, unknown>
  }) => {
    if (!selectedGroup) return
    try {
      await adminApi.createTask(selectedGroup.id, { ...payload, executor_type: 'bot' })
      toastSuccess('Task created')
      void refreshData()
    } catch (err) {
      toastError('Failed to create task')
    }
  }

  const handleUpdateTask = async (assignmentId: string, payload: Record<string, unknown>) => {
    if (!selectedGroup) return
    try {
      await adminApi.updateTask(selectedGroup.id, assignmentId, payload)
      setTasks(prev => prev.map(t => t.assignment_id === assignmentId ? { ...t, ...payload } : t))
      toastSuccess('Task updated')
    } catch (err) {
      toastError('Failed to update task')
      void refreshData()
    }
  }

  const handleDeleteTask = async (assignmentId: string) => {
    if (!selectedGroup) return
    try {
      await adminApi.deleteTask(selectedGroup.id, assignmentId)
      setTasks(prev => prev.filter(t => t.assignment_id !== assignmentId))
      toastSuccess('Task deleted')
    } catch (err) {
      toastError('Failed to delete task')
    }
  }

  const handleCreateScheduledMessage = async (payload: {
    text: string
    schedule: string
    delete_after_seconds?: number
  }) => {
    if (!selectedGroup) return
    try {
      await adminApi.createScheduledMessage(selectedGroup.id, payload)
      toastSuccess('Scheduled message created')
      void refreshData()
    } catch (err) {
      toastError('Failed to create scheduled message')
    }
  }

  const handleUpdateScheduledMessage = async (entryId: string, payload: Record<string, unknown>) => {
    if (!selectedGroup) return
    try {
      const res: any = await adminApi.updateScheduledMessage(selectedGroup.id, entryId, payload)
      if (res && res.scheduled_message) {
        setScheduledMessages(prev => prev.map(m => m.id === entryId ? { ...m, ...res.scheduled_message } : m))
      } else {
        setScheduledMessages(prev => prev.map(m => m.id === entryId ? { ...m, ...payload } : m))
      }
      toastSuccess('Scheduled message updated')
    } catch (err) {
      toastError('Failed to update scheduled message')
      void refreshData()
    }
  }

  const handleDeleteScheduledMessage = async (entryId: string) => {
    if (!selectedGroup) return
    try {
      await adminApi.deleteScheduledMessage(selectedGroup.id, entryId)
      setScheduledMessages(prev => prev.filter(m => m.id !== entryId))
      toastSuccess('Scheduled message cancelled')
    } catch (err) {
      toastError('Failed to cancel scheduled message')
    }
  }

  const handleSendNowScheduledMessage = async (entryId: string) => {
    if (!selectedGroup) return
    try {
      await adminApi.sendScheduledMessageNow(selectedGroup.id, entryId)
      toastSuccess('Message sent')
    } catch (err) {
      toastError('Failed to send message now')
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
      toastSuccess(`User ${action === 'approve' ? 'approved' : action + 'ed'}`)
    } catch (err) {
      toastError('Failed to perform action')
    } finally {
      setActionLoading(null)
    }
  }

  function handleTabChange(tab: string) {
    const nextTab = isModbotTab(tab) ? tab : 'dashboard'
    setActiveTab(nextTab)
    const nextUrl = `${window.location.pathname}${window.location.search}#/${nextTab}`
    window.history.replaceState({}, '', nextUrl)
  }

  const rootDir = dir

  if (session.loading) {
    return (
      <div dir={rootDir} className="flex items-center justify-center min-h-screen p-10 text-center" style={{ fontFamily: lang === 'ar' ? "'Noto Kufi Arabic', sans-serif" : 'inherit' }}>
        <div className="space-y-4">
          <div className="mx-auto w-12 h-12 rounded-full border-4 border-primary/20 border-t-primary animate-spin"></div>
          <h2 className="text-xl font-bold">{t('loading.sessions')}</h2>
          <p className="text-on-secondary-container">{t('loading.prep')}</p>
        </div>
      </div>
    )
  }

  if (!session.identity) {
    return (
      <div dir={rootDir} className="flex items-center justify-center min-h-screen p-10 text-center" style={{ fontFamily: lang === 'ar' ? "'Noto Kufi Arabic', sans-serif" : 'inherit' }}>
        <div className="space-y-4">
          <span className="material-symbols-outlined text-6xl text-primary/20">lock</span>
          <h2 className="text-xl font-bold">{t('auth.required')}</h2>
          <p className="text-on-secondary-container">{session.error || t('auth.desc')}</p>
        </div>
      </div>
    )
  }

  if (!selectedGroup) {
    return (
      <div dir={rootDir} className="flex items-center justify-center min-h-screen p-10 text-center" style={{ fontFamily: lang === 'ar' ? "'Noto Kufi Arabic', sans-serif" : 'inherit' }}>
        <div className="space-y-4">
          <span className="material-symbols-outlined text-6xl text-primary/20">group_off</span>
          <h2 className="text-xl font-bold">{t('no_group.title')}</h2>
          <p className="text-on-secondary-container">{t('no_group.desc')}</p>
        </div>
      </div>
    )
  }

  return (
    <Layout
      activeTab={activeTab}
      onTabChange={handleTabChange}
      onRefresh={() => { void refreshSession(); void refreshData(); }}
      subscription={session.identity?.subscription}
      planLimits={session.identity?.plan_limits}
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
          overview={overview}
          modLogs={modLogs}
          settings={aiSettings}
          loading={loading}
          is_bot_owner={session.identity?.is_bot_owner}
        />
      )}

      {activeTab === 'tasks' && (
        <TasksPage
          tasks={tasks}
          scheduledMessages={scheduledMessages}
          onCreateTask={handleCreateTask}
          onUpdateTask={handleUpdateTask}
          onDeleteTask={handleDeleteTask}
          onCreateScheduledMessage={handleCreateScheduledMessage}
          onUpdateScheduledMessage={handleUpdateScheduledMessage}
          onDeleteScheduledMessage={handleDeleteScheduledMessage}
          onSendNowScheduledMessage={handleSendNowScheduledMessage}
          loading={loading}
        />
      )}

      {activeTab === 'events' && (
        <EventsPage
          events={aiEvents}
          onAction={handleEventAction}
          actionLoading={actionLoading}
          loading={loading}
        />
      )}

      {activeTab === 'moderation' && (
        <ModerationPage
          groupId={selectedGroup.id}
          settings={aiSettings}
          onUpdateAiSettings={handleUpdateAiSettings}
          groupSettings={groupSettings}
          onUpdateGroupSettings={handleUpdateGroupSettings}
          accessGate={accessGate}
          onUpdateAccessGate={handleUpdateAccessGate}
          loading={loading}
        />
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
