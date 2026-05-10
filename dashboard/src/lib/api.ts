import axios from 'axios'
import type {
  Member,
  ModAction,
  RuleKey,
  TimelineEvent,
  OwnerGroup,
  OwnerMetrics,
  OwnerSubscriptionRequest,
  AutomationTask,
  DashboardStats,
  GroupSettings,
  ModerationLogEntry,
  WarningEntry,
  TaskCatalogItem,
  NotificationReport,
  AccessGateInfo,
  PromotionCode,
} from '../lib/types'

function resolveApiBaseUrl() {
  const configuredBaseUrl = import.meta.env.VITE_API_URL
  const { protocol, hostname, port, origin } = window.location

  if (configuredBaseUrl) {
    try {
      const parsed = new URL(configuredBaseUrl, origin)
      const configuredHost = parsed.hostname
      const pageIsLocalhost = hostname === 'localhost' || hostname === '127.0.0.1'
      const apiIsLocalhost = configuredHost === 'localhost' || configuredHost === '127.0.0.1'

      if (!apiIsLocalhost || pageIsLocalhost) {
        return parsed.toString().replace(/\/$/, '')
      }
    } catch {
      return configuredBaseUrl
    }
  }
  if (port === '5173' || port === '5174') {
    return `${protocol}//${hostname}:8000`
  }

  return origin
}

const api = axios.create({
  baseURL: resolveApiBaseUrl(),
})

const AUTH_API_PREFIX = '/api/auth'
const ADMIN_API_PREFIX = '/api/admin'
const OWNER_API_PREFIX = '/webapp/owner'

api.interceptors.request.use((config) => {
  const token = localStorage.getItem('auth_token')
  if (token) {
    config.headers.Authorization = `Bearer ${token}`
  }
  return config
})

api.interceptors.response.use(
  (response) => response,
  (err) => {
    if (err.response?.status === 401) {
      localStorage.removeItem('auth_token')
      localStorage.removeItem('auth_user')
      window.location.href = '/dashboard/login'
    }
    return Promise.reject(err)
  },
)

// ─── Auth ────────────────────────────────────────────────────────────────────

export async function login(email: string, password: string) {
  const { data } = await api.post('/auth/email/login', { email, password })
  return data
}

export async function telegramLogin(payload: Record<string, unknown>) {
  const { data } = await api.post('/auth/telegram/login', payload)
  return data
}

export async function fetchCurrentUser(token?: string) {
  const headers = token ? { Authorization: `Bearer ${token}` } : undefined
  const { data } = await api.get(`${AUTH_API_PREFIX}/me`, { headers })
  return data
}

// ─── Groups ──────────────────────────────────────────────────────────────────

export async function fetchGroups(): Promise<{ id: number; title: string; tg_group_id: number }[]> {
  const { data } = await api.get('/groups')
  return data
}

// ─── Group Overview ──────────────────────────────────────────────────────────

export async function fetchGroupOverview(groupId: number) {
  const { data } = await api.get(`${ADMIN_API_PREFIX}/groups/${groupId}/overview`)
  return data
}

export async function fetchGroupSettings(groupId: number): Promise<GroupSettings> {
  const { data } = await api.get<GroupSettings>(`${ADMIN_API_PREFIX}/groups/${groupId}/settings`)
  return data
}

export async function updateGroupSettings(groupId: number, settings: Record<string, boolean | number | string>) {
  const { data } = await api.patch(`${ADMIN_API_PREFIX}/groups/${groupId}/settings`, { settings })
  return data
}

export async function fetchAccessGate(groupId: number): Promise<AccessGateInfo> {
  const { data } = await api.get<AccessGateInfo>(`${ADMIN_API_PREFIX}/groups/${groupId}/access-gate`)
  return data
}

export async function updateAccessGate(groupId: number, requiredGroupTgIds: number[]) {
  const { data } = await api.patch(`${ADMIN_API_PREFIX}/groups/${groupId}/access-gate`, { required_group_tg_ids: requiredGroupTgIds })
  return data
}

// ─── Moderation ──────────────────────────────────────────────────────────────

export async function fetchModerationLogs(groupId: number, limit = 50): Promise<ModerationLogEntry[]> {
  const { data } = await api.get<ModerationLogEntry[]>(`${ADMIN_API_PREFIX}/groups/${groupId}/logs`, { params: { limit } })
  return data
}

export async function performModerationAction(groupId: number, payload: {
  user_id: number
  action: ModAction
  reason?: string
  count?: number
}) {
  const { data } = await api.post(`${ADMIN_API_PREFIX}/groups/${groupId}/moderation/actions`, payload)
  return data
}

export async function fetchWarnings(groupId: number): Promise<WarningEntry[]> {
  const { data } = await api.get<WarningEntry[]>(`${ADMIN_API_PREFIX}/groups/${groupId}/moderation/warnings`)
  return data
}

export async function addWarning(groupId: number, payload: { user_id: number; reason?: string; count?: number }) {
  const { data } = await api.post(`${ADMIN_API_PREFIX}/groups/${groupId}/moderation/warnings`, payload)
  return data
}

export async function clearWarnings(groupId: number, userId: number) {
  const { data } = await api.delete(`${ADMIN_API_PREFIX}/groups/${groupId}/moderation/warnings/${userId}`)
  return data
}

// ─── Members ─────────────────────────────────────────────────────────────────

export async function fetchMembers(groupId: number, q?: string): Promise<Member[]> {
  const { data } = await api.get<Member[]>(`${ADMIN_API_PREFIX}/groups/${groupId}/members`, { params: q ? { q } : undefined })
  return data
}

export async function searchMembers(groupId: number, query: string, limit = 50): Promise<Member[]> {
  const { data } = await api.get<Member[]>(`${ADMIN_API_PREFIX}/groups/${groupId}/member-search`, { params: { q: query, limit } })
  return data
}

export async function setMemberRole(groupId: number, userId: number, role: string) {
  const { data } = await api.post(`${ADMIN_API_PREFIX}/groups/${groupId}/members/${userId}/role`, { role })
  return data
}

// ─── Rules ───────────────────────────────────────────────────────────────────

export async function toggleRule(groupId: number, ruleKey: RuleKey, enabled: boolean) {
  const { data } = await api.patch(`${ADMIN_API_PREFIX}/groups/${groupId}/settings`, {
    settings: { [`${ruleKey}_enabled`]: enabled },
  })
  return data
}

export async function updateRuleConfig(groupId: number, ruleKey: RuleKey, config: Record<string, boolean | number | string>) {
  const { data } = await api.patch(`${ADMIN_API_PREFIX}/groups/${groupId}/settings`, { settings: config })
  return data
}

// ─── Activity ────────────────────────────────────────────────────────────────

export async function fetchActivity(groupId: number, limit = 50): Promise<TimelineEvent[]> {
  const logs = await fetchModerationLogs(groupId, limit)
  return logs.map((log, i) => ({
    id: log.id || i,
    type: log.action === 'lead_captured' ? 'report' : log.action === 'warn' ? 'moderation' : 'system',
    title: log.action,
    subtitle: log.reason || '',
    timestamp: log.created_at ? new Date(log.created_at).toLocaleString() : '',
    severity: getSeverity(log.action),
  }))
}

function getSeverity(action: string): TimelineEvent['severity'] {
  switch (action) {
    case 'approve': return 'info'
    case 'warn': return 'warn'
    case 'mute': return 'mute'
    case 'ban': return 'ban'
    case 'lead_captured': return 'info'
    default: return 'info'
  }
}

// ─── Notification Reports ────────────────────────────────────────────────────

export async function fetchNotificationReports(groupId: number): Promise<NotificationReport[]> {
  const { data } = await api.get<NotificationReport[]>(`${ADMIN_API_PREFIX}/groups/${groupId}/notification-reports`)
  return data
}

export async function replyToNotificationReport(groupId: number, logId: number, text: string) {
  const { data } = await api.post(`${ADMIN_API_PREFIX}/groups/${groupId}/notification-reports/${logId}/reply`, { text })
  return data
}

// ─── Tasks / Automation ──────────────────────────────────────────────────────

export async function fetchTaskCatalog(): Promise<TaskCatalogItem[]> {
  const { data } = await api.get<TaskCatalogItem[]>(`${ADMIN_API_PREFIX}/tasks/catalog`)
  return data
}

export async function fetchTasks(groupId: number): Promise<AutomationTask[]> {
  const { data } = await api.get<AutomationTask[]>(`${ADMIN_API_PREFIX}/groups/${groupId}/tasks`)
  return data
}

export async function createTask(groupId: number, payload: {
  assignment_id?: string
  task_key: string
  executor_type: string
  enabled?: boolean
  conditions?: Record<string, unknown>
  config?: Record<string, unknown>
  agent_id?: number
}) {
  const { data } = await api.post(`${ADMIN_API_PREFIX}/groups/${groupId}/tasks`, payload)
  return data
}

export async function updateTask(groupId: number, assignmentId: string, payload: Record<string, unknown>) {
  const { data } = await api.patch(`${ADMIN_API_PREFIX}/groups/${groupId}/tasks/${assignmentId}`, payload)
  return data
}

export async function deleteTask(groupId: number, assignmentId: string) {
  const { data } = await api.delete(`${ADMIN_API_PREFIX}/groups/${groupId}/tasks/${assignmentId}`)
  return data
}

// ─── Scheduled Messages ──────────────────────────────────────────────────────

export interface ScheduledMessage {
  id: string
  group_id: number
  text: string
  schedule: string
  send_at: string
  delete_after_seconds: number | null
}

export async function fetchScheduledMessages(groupId: number): Promise<ScheduledMessage[]> {
  const { data } = await api.get<ScheduledMessage[]>(`${ADMIN_API_PREFIX}/groups/${groupId}/scheduled-messages`)
  return data
}

export async function createScheduledMessage(groupId: number, payload: {
  text: string
  schedule: string
  delete_after_seconds?: number
}) {
  const { data } = await api.post(`${ADMIN_API_PREFIX}/groups/${groupId}/scheduled-messages`, payload)
  return data
}

export async function updateScheduledMessage(groupId: number, entryId: string, payload: Record<string, unknown>) {
  const { data } = await api.patch(`${ADMIN_API_PREFIX}/groups/${groupId}/scheduled-messages/${entryId}`, payload)
  return data
}

export async function deleteScheduledMessage(groupId: number, entryId: string) {
  const { data } = await api.delete(`${ADMIN_API_PREFIX}/groups/${groupId}/scheduled-messages/${entryId}`)
  return data
}

// ─── FAQ ──────────────────────────────────────────────────────────────────────

export async function fetchFAQSettings(groupId: number): Promise<any> {
  const { data } = await api.get(`${ADMIN_API_PREFIX}/groups/${groupId}/faq/settings`)
  return data
}

export async function updateFAQSettings(groupId: number, settings: any): Promise<any> {
  const { data } = await api.put(`${ADMIN_API_PREFIX}/groups/${groupId}/faq/settings`, settings)
  return data
}

export async function fetchFAQEntries(groupId: number): Promise<any[]> {
  const { data } = await api.get<any[]>(`${ADMIN_API_PREFIX}/groups/${groupId}/faq/entries`)
  return data
}

export async function deleteFAQEntry(groupId: number, entryId: number): Promise<void> {
  await api.delete(`${ADMIN_API_PREFIX}/groups/${groupId}/faq/entries/${entryId}`)
}

export async function fetchUnansweredQuestions(groupId: number): Promise<any[]> {
  const { data } = await api.get<any[]>(`${ADMIN_API_PREFIX}/groups/${groupId}/faq/unanswered`)
  return data
}

export async function convertUnansweredToFAQ(groupId: number, questionId: number, answer: string): Promise<any> {
  const { data } = await api.post(`${ADMIN_API_PREFIX}/groups/${groupId}/faq/unanswered/${questionId}/convert`, { answer })
  return data
}

export async function testFAQMatch(groupId: number, question: string): Promise<any> {
  const { data } = await api.post(`/api/groups/${groupId}/faq/test-match`, { question })
  return data
}

export async function aiAnalyzeGroupMessages(groupId: number, maxMessages = 1000): Promise<any> {
  const { data } = await api.post(`/api/groups/${groupId}/faq/ai-analyze`, undefined, {
    params: { max_messages: maxMessages },
  })
  return data
}

export async function createFAQEntry(groupId: number, payload: { question: string; answer: string; keywords: string[] }): Promise<any> {
  const { data } = await api.post(`${ADMIN_API_PREFIX}/groups/${groupId}/faq/entries`, payload)
  return data
}

// ─── Summaries ────────────────────────────────────────────────────────────────

export async function fetchSummaries(groupId: number): Promise<any[]> {
  const { data } = await api.get<any[]>(`${ADMIN_API_PREFIX}/groups/${groupId}/summaries`)
  return data
}

export async function fetchSummarySettings(groupId: number): Promise<any> {
  const { data } = await api.get<any>(`${ADMIN_API_PREFIX}/groups/${groupId}/summaries/settings`)
  return data
}

export async function updateSummarySettings(groupId: number, settings: any): Promise<any> {
  const { data } = await api.put(`${ADMIN_API_PREFIX}/groups/${groupId}/summaries/settings`, settings)
  return data
}

// ─── Owner endpoints ─────────────────────────────────────────────────────────

export async function fetchOwnerStats(): Promise<DashboardStats> {
  const { data } = await api.get<DashboardStats>(`${OWNER_API_PREFIX}/stats`)
  return data
}

export async function fetchOwnerGroups(): Promise<OwnerGroup[]> {
  const { data } = await api.get<OwnerGroup[]>(`${OWNER_API_PREFIX}/groups`)
  return data
}

export async function fetchOwnerUsers(): Promise<any[]> {
  const { data } = await api.get<any[]>(`${OWNER_API_PREFIX}/users`)
  return data
}

export async function fetchOwnerGroupDetails(groupId: number) {
  const { data } = await api.get(`${OWNER_API_PREFIX}/groups/${groupId}`)
  return data
}

export async function disableOwnerGroup(groupId: number) {
  const { data } = await api.post(`${OWNER_API_PREFIX}/groups/${groupId}/disable`)
  return data
}

export async function leaveOwnerGroup(groupId: number) {
  const { data } = await api.post(`${OWNER_API_PREFIX}/groups/${groupId}/leave`)
  return data
}

export async function fetchOwnerSubscriptions(): Promise<OwnerSubscriptionRequest[]> {
  const { data } = await api.get<OwnerSubscriptionRequest[]>(`${OWNER_API_PREFIX}/subscriptions`)
  return data
}

export async function updateOwnerSubscription(requestId: number, action: 'approve' | 'decline' | 'cancel', plan?: 'pro' | 'business', response?: string) {
  const { data } = await api.post(`${OWNER_API_PREFIX}/subscriptions/${requestId}`, { action, plan, response })
  return data
}

export async function fetchOwnerPrivateAccessGate() {
  const { data } = await api.get(`${OWNER_API_PREFIX}/private-access-gate`)
  return data
}

export async function updateOwnerPrivateAccessGate(requiredGroupTgIds: number[]) {
  const { data } = await api.patch(`${OWNER_API_PREFIX}/private-access-gate`, { required_group_tg_ids: requiredGroupTgIds })
  return data
}

export async function fetchOwnerAuditLog(limit = 50, offset = 0) {
  const { data } = await api.get(`${OWNER_API_PREFIX}/audit-log`, { params: { limit, offset } })
  return data
}

export async function fetchOwnerPromoCodes(limit = 100): Promise<PromotionCode[]> {
  const { data } = await api.get<PromotionCode[]>(`${OWNER_API_PREFIX}/promo-codes`, { params: { limit } })
  return data
}

export async function createOwnerPromoCode(payload: {
  code: string
  plan: 'pro' | 'business'
  duration_days: number
  max_uses?: number
  expiry_date?: string
  is_active?: boolean
}) {
  const { data } = await api.post(`${OWNER_API_PREFIX}/promo-codes`, payload)
  return data
}

export async function updateOwnerPromoCode(promoCodeId: number, payload: {
  is_active?: boolean
  max_uses?: number
  expiry_date?: string
}) {
  const { data } = await api.patch(`${OWNER_API_PREFIX}/promo-codes/${promoCodeId}`, payload)
  return data
}

export async function deleteOwnerPromoCode(promoCodeId: number) {
  const { data } = await api.delete(`${OWNER_API_PREFIX}/promo-codes/${promoCodeId}`)
  return data
}

export default api
