import { apiClient } from './base'
import type {
  Agent,
  AgentAnalytics,
  AgentGroupMember,
  AgentGroupMemberMessagesPage,
  AgentGroupMembersPage,
  AgentLead,
  AgentLeadPage,
  AgentLeadStats,
  AgentNotificationsResponse,
  AgentGroupScrapeResult,
  AgentJobRecord,
  AgentManagedGroup,
  AutomationTask,
  TaskCatalogItem,
} from '../types'

const AGENTS_API_PREFIX = '/api/agents'

export async function fetchAgents(_groupId?: number | null) {
  return apiClient.get<Agent[]>(AGENTS_API_PREFIX)
}

export async function linkAgent(groupId: number | null | undefined, payload: {
  external_account_id?: string
  name?: string
  phone_number?: string
  telegram_user_id?: number
  metadata?: Record<string, unknown>
}) {
  return apiClient.post(`${AGENTS_API_PREFIX}/link`, { ...(groupId ? { group_id: groupId } : {}), ...payload })
}

export async function startAgentAuth(groupId: number | null, phoneNumber: string, agentId?: number | null) {
  return apiClient.post(`${AGENTS_API_PREFIX}/auth/start`, {
    ...(groupId ? { group_id: groupId } : {}),
    ...(agentId ? { agent_id: agentId } : {}),
    phone_number: phoneNumber,
  })
}

export async function submitAgentCode(agentId: number, code: string) {
  return apiClient.post(`${AGENTS_API_PREFIX}/${agentId}/auth/code`, { code })
}

export async function submitAgentPassword(agentId: number, password: string) {
  return apiClient.post(`${AGENTS_API_PREFIX}/${agentId}/auth/password`, { password })
}

export async function updateAgent(agentId: number, payload: {
  external_account_id?: string
  name?: string
  phone_number?: string
  telegram_user_id?: number
  metadata?: Record<string, unknown>
}) {
  return apiClient.patch(`${AGENTS_API_PREFIX}/${agentId}`, payload)
}

export async function deleteAgent(agentId: number) {
  return apiClient.delete(`${AGENTS_API_PREFIX}/${agentId}`)
}

export async function fetchAgentJobs(agentId: number) {
  return apiClient.get<AgentJobRecord[]>(`${AGENTS_API_PREFIX}/${agentId}/jobs`)
}

export async function fetchAgentNotifications(agentId: number, limit = 50) {
  return apiClient.get<AgentNotificationsResponse>(`${AGENTS_API_PREFIX}/${agentId}/notifications`, { limit })
}

export async function markAgentNotificationsSeen(agentId: number) {
  return apiClient.post(`${AGENTS_API_PREFIX}/${agentId}/notifications/mark-seen`)
}

export async function createAgentJob(agentId: number, jobType: string, jobPayload: Record<string, unknown>) {
  return apiClient.post(`${AGENTS_API_PREFIX}/${agentId}/jobs`, { job_type: jobType, job_payload: jobPayload })
}

export async function syncAgentWorkspace(agentId: number) {
  return apiClient.post(`${AGENTS_API_PREFIX}/${agentId}/sync-workspace`)
}

export async function fetchAgentGroups(agentId: number, query?: string) {
  return apiClient.get<AgentManagedGroup[]>(`${AGENTS_API_PREFIX}/${agentId}/groups`, { q: query })
}

export async function searchAgentGroupMembers(agentId: number, tgGroupId: number, query?: string, limit = 20) {
  return apiClient.get<AgentGroupMember[]>(`${AGENTS_API_PREFIX}/${agentId}/member-search`, {
    tg_group_id: tgGroupId,
    q: query,
    limit,
  })
}

export async function fetchAgentGroupMembers(agentId: number, tgGroupId: number, query?: string, page = 1, pageSize = 10) {
  return apiClient.get<AgentGroupMembersPage>(`${AGENTS_API_PREFIX}/${agentId}/groups/${tgGroupId}/members`, {
    q: query,
    page,
    page_size: pageSize,
  })
}

export async function fetchAgentGroupMemberMessages(agentId: number, tgGroupId: number, userId: number, page = 1, pageSize = 25) {
  return apiClient.get<AgentGroupMemberMessagesPage>(
    `${AGENTS_API_PREFIX}/${agentId}/groups/${tgGroupId}/members/${userId}/messages`,
    {
      page,
      page_size: pageSize,
    },
  )
}

export async function scrapeAgentGroupMembers(
  agentId: number,
  tgGroupId: number,
  options?: {
    limit?: number
    message_limit?: number
    max_age_days?: number
  },
) {
  return apiClient.post<AgentGroupScrapeResult>(
    `${AGENTS_API_PREFIX}/${agentId}/groups/${tgGroupId}/scrape-members`,
    undefined,
    options,
  )
}

export async function fetchTaskCatalog() {
  return apiClient.get<TaskCatalogItem[]>('/webapp/tasks/catalog')
}

export async function fetchGroupTasks(groupId: number) {
  return apiClient.get<AutomationTask[]>(`/webapp/groups/${groupId}/tasks`)
}

export async function createGroupTask(groupId: number, payload: {
  assignment_id?: string
  task_key: string
  executor_type: string
  enabled?: boolean
  conditions?: Record<string, unknown>
  config?: Record<string, unknown>
  agent_id?: number
  group_ids?: number[]
  group_tg_ids?: number[]
  group_titles?: string[]
}) {
  return apiClient.post(`/webapp/groups/${groupId}/tasks`, payload)
}

export async function updateGroupTask(groupId: number, assignmentId: string, payload: {
  assignment_id?: string
  task_key: string
  executor_type: string
  enabled?: boolean
  conditions?: Record<string, unknown>
  config?: Record<string, unknown>
  agent_id?: number
  group_ids?: number[]
  group_tg_ids?: number[]
  group_titles?: string[]
}) {
  return apiClient.patch(`/webapp/groups/${groupId}/tasks/${assignmentId}`, payload)
}

export async function deleteGroupTask(groupId: number, assignmentId: string) {
  return apiClient.delete(`/webapp/groups/${groupId}/tasks/${assignmentId}`)
}

export async function fetchSubscriptionStatus() {
  return apiClient.get<{ status: 'active' | 'inactive'; plan: 'pro' | 'business' | null; expires_at: string | null }>(`${AGENTS_API_PREFIX}/subscription/status`)
}

export async function redeemPromoCode(code: string) {
  return apiClient.post<{ success: boolean; status: string; plan: 'pro' | 'business' | null; expires_at: string | null; message: string }>(`${AGENTS_API_PREFIX}/subscription/redeem`, { code })
}

export async function createSubscriptionCheckout(plan: 'pro' | 'business', successUrl: string, cancelUrl: string) {
  return apiClient.post<{ url: string; session_id: string }>(`${AGENTS_API_PREFIX}/subscription/checkout/stripe`, {
    plan,
    success_url: successUrl,
    cancel_url: cancelUrl,
  })
}

export async function updateAgentSafety(agentId: number, payload: {
  max_actions_per_hour?: number
  min_delay_seconds?: number
  cooldown_minutes?: number
  safety_mode_enabled?: boolean
  safety_mode_hours?: number
}) {
  return apiClient.patch(`${AGENTS_API_PREFIX}/${agentId}/safety`, payload)
}

export async function fetchAgentLeads(agentId: number, options?: {
  status?: string
  lead_label?: string
  page?: number
  page_size?: number
}) {
  return apiClient.get<AgentLeadPage>(`${AGENTS_API_PREFIX}/${agentId}/leads`, options)
}

export async function fetchAgentLeadStats(agentId: number) {
  return apiClient.get<AgentLeadStats>(`${AGENTS_API_PREFIX}/${agentId}/leads/stats`)
}

export async function updateAgentLead(agentId: number, leadId: number, payload: {
  status?: string
  assigned_to?: number
  contact_info?: string
  notes?: string
  lead_label?: string
  confidence?: number
}) {
  return apiClient.patch(`${AGENTS_API_PREFIX}/${agentId}/leads/${leadId}`, payload)
}

export async function deleteAgentLead(agentId: number, leadId: number) {
  return apiClient.delete(`${AGENTS_API_PREFIX}/${agentId}/leads/${leadId}`)
}

export async function fetchAgentAnalytics(agentId: number) {
  return apiClient.get<AgentAnalytics>(`${AGENTS_API_PREFIX}/${agentId}/analytics`)
}
