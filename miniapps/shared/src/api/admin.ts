import { apiClient } from './base'
import type {
  AccessGateInfo,
  AutomationTask,
  GroupOverview,
  GroupSettings,
  ModerationLogEntry,
  NotificationReport,
  ScheduledMessage,
  TaskCatalogItem,
  WarningEntry,
  AgentNotificationsResponse,
  AIModerationSettings,
  AIModerationEvent,
  GroupSubscriptionSettings,
  SubscriptionPlan,
  GroupSubscriber,
  PaymentRecord,
  SubscriptionUser,
} from '../types'

const ADMIN_API_PREFIX = '/api/admin'

export async function fetchGroupOverview(groupId: number) {
  return apiClient.get<GroupOverview>(`${ADMIN_API_PREFIX}/groups/${groupId}/overview`)
}

export async function fetchGroupSettings(groupId: number) {
  return apiClient.get<GroupSettings>(`${ADMIN_API_PREFIX}/groups/${groupId}/settings`)
}

export async function fetchAIModerationSettings(groupId: number) {
  return apiClient.get<{ group_id: number; settings: AIModerationSettings }>(`${ADMIN_API_PREFIX}/groups/${groupId}/moderation/ai-settings`)
}

export async function updateAIModerationSettings(groupId: number, settings: Partial<AIModerationSettings>) {
  return apiClient.patch(`${ADMIN_API_PREFIX}/groups/${groupId}/moderation/ai-settings`, settings)
}

export async function fetchAIModerationEvents(groupId: number, limit = 100) {
  return apiClient.get<AIModerationEvent[]>(`${ADMIN_API_PREFIX}/groups/${groupId}/moderation/ai-events`, { limit })
}

export async function fetchGroupSubscriptionSettings(groupId: number) {
  return apiClient.get<GroupSubscriptionSettings>(`/api/groups/${groupId}/subscriptions/settings`)
}

export async function updateGroupSubscriptionSettings(groupId: number, settings: Partial<GroupSubscriptionSettings>) {
  return apiClient.put(`/api/groups/${groupId}/subscriptions/settings`, settings)
}

export async function fetchSubscriptionPlans(groupId: number) {
  return apiClient.get<SubscriptionPlan[]>(`/api/groups/${groupId}/subscriptions/plans`)
}

export async function createSubscriptionPlan(groupId: number, plan: Omit<SubscriptionPlan, 'id'>) {
  return apiClient.post(`/api/groups/${groupId}/subscriptions/plans`, plan)
}

export async function updateSubscriptionPlan(groupId: number, planId: number, plan: Partial<SubscriptionPlan>) {
  return apiClient.put(`/api/groups/${groupId}/subscriptions/plans/${planId}`, plan)
}

export async function fetchGroupSubscribers(groupId: number) {
  return apiClient.get<GroupSubscriber[]>(`/api/groups/${groupId}/subscriptions/subscribers`)
}

export async function fetchGroupPayments(groupId: number) {
  return apiClient.get<PaymentRecord[]>(`/api/groups/${groupId}/subscriptions/payments`)
}

export async function markPaymentPaid(groupId: number, paymentId: number, reference?: string) {
  return apiClient.post(`/api/groups/${groupId}/subscriptions/payments/${paymentId}/mark-paid`, { reference })
}

export async function updateGroupSettings(groupId: number, settings: Record<string, boolean | number | string>) {
  return apiClient.patch(`${ADMIN_API_PREFIX}/groups/${groupId}/settings`, { settings })
}

export async function fetchAccessGate(groupId: number) {
  return apiClient.get<AccessGateInfo>(`${ADMIN_API_PREFIX}/groups/${groupId}/access-gate`)
}

export async function updateAccessGate(groupId: number, requiredGroupTgIds: number[]) {
  return apiClient.patch(`${ADMIN_API_PREFIX}/groups/${groupId}/access-gate`, { required_group_tg_ids: requiredGroupTgIds })
}

export async function fetchModerationLogs(groupId: number, limit = 50) {
  return apiClient.get<ModerationLogEntry[]>(`${ADMIN_API_PREFIX}/groups/${groupId}/logs`, { limit })
}

export async function fetchWarnings(groupId: number) {
  return apiClient.get<WarningEntry[]>(`${ADMIN_API_PREFIX}/groups/${groupId}/moderation/warnings`)
}

export async function addWarning(groupId: number, payload: { user_id: number; reason?: string; count?: number }) {
  return apiClient.post(`${ADMIN_API_PREFIX}/groups/${groupId}/moderation/warnings`, payload)
}

export async function clearWarnings(groupId: number, userId: number) {
  return apiClient.delete(`${ADMIN_API_PREFIX}/groups/${groupId}/moderation/warnings/${userId}`)
}

export async function performModerationAction(groupId: number, payload: {
  user_id: number
  action: 'approve' | 'warn' | 'mute' | 'ban'
  reason?: string
  count?: number
}) {
  return apiClient.post(`${ADMIN_API_PREFIX}/groups/${groupId}/moderation/actions`, payload)
}

export interface RestrictedUser {
  user_id: number
  type: 'mute' | 'ban'
  reason: string | null
  created_at: string
  details: Record<string, unknown>
}

export async function fetchRestrictedUsers(groupId: number) {
  return apiClient.get<RestrictedUser[]>(`${ADMIN_API_PREFIX}/groups/${groupId}/moderation/restricted`)
}

export async function fetchNotificationReports(groupId: number) {
  return apiClient.get<NotificationReport[]>(`${ADMIN_API_PREFIX}/groups/${groupId}/notification-reports`)
}

export async function replyToNotificationReport(groupId: number, logId: number, text: string) {
  return apiClient.post(`${ADMIN_API_PREFIX}/groups/${groupId}/notification-reports/${logId}/reply`, { text })
}

export async function fetchTaskCatalog() {
  return apiClient.get<TaskCatalogItem[]>(`${ADMIN_API_PREFIX}/tasks/catalog`)
}

export async function fetchTasks(groupId: number) {
  return apiClient.get<AutomationTask[]>(`${ADMIN_API_PREFIX}/groups/${groupId}/tasks`)
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
  return apiClient.post(`${ADMIN_API_PREFIX}/groups/${groupId}/tasks`, payload)
}

export async function updateTask(groupId: number, assignmentId: string, payload: Record<string, unknown>) {
  return apiClient.patch(`${ADMIN_API_PREFIX}/groups/${groupId}/tasks/${assignmentId}`, payload)
}

export async function deleteTask(groupId: number, assignmentId: string) {
  return apiClient.delete(`${ADMIN_API_PREFIX}/groups/${groupId}/tasks/${assignmentId}`)
}

export async function fetchScheduledMessages(groupId: number) {
  return apiClient.get<ScheduledMessage[]>(`${ADMIN_API_PREFIX}/groups/${groupId}/scheduled-messages`)
}

export async function createScheduledMessage(groupId: number, payload: {
  text: string
  schedule: string
  delete_after_seconds?: number
}) {
  return apiClient.post(`${ADMIN_API_PREFIX}/groups/${groupId}/scheduled-messages`, payload)
}

export async function updateScheduledMessage(groupId: number, entryId: string, payload: Record<string, unknown>) {
  return apiClient.patch(`${ADMIN_API_PREFIX}/groups/${groupId}/scheduled-messages/${entryId}`, payload)
}

export async function deleteScheduledMessage(groupId: number, entryId: string) {
  return apiClient.delete(`${ADMIN_API_PREFIX}/groups/${groupId}/scheduled-messages/${entryId}`)
}

export async function sendScheduledMessageNow(groupId: number, entryId: string) {
  return apiClient.post(`${ADMIN_API_PREFIX}/groups/${groupId}/scheduled-messages/${entryId}/send-now`)
}

export async function fetchNotifications(groupId: number, limit = 50) {
  return apiClient.get<AgentNotificationsResponse>(`${ADMIN_API_PREFIX}/groups/${groupId}/notifications`, { limit })
}

export async function markNotificationsSeen(groupId: number) {
  return apiClient.post(`${ADMIN_API_PREFIX}/groups/${groupId}/notifications/mark-seen`)
}

export async function fetchSubscriptions(botKind?: string) {
  return apiClient.get<SubscriptionUser[]>(`${ADMIN_API_PREFIX}/subscriptions`, botKind ? { bot_kind: botKind } : {})
}

export async function setUserPlan(tgUserId: number, plan: string, botKind?: string) {
  return apiClient.put<SubscriptionUser>(`${ADMIN_API_PREFIX}/subscriptions/${tgUserId}`, { plan, bot_kind: botKind || undefined })
}

export async function cancelSubscription(tgUserId: number, botKind?: string) {
  return apiClient.delete(`${ADMIN_API_PREFIX}/subscriptions/${tgUserId}`, botKind ? { bot_kind: botKind } : {})
}
