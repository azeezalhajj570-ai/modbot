export type JobStatus = 'running' | 'done' | 'failed' | 'queued'
export type MemberStatus = 'pending' | 'added' | 'failed'
export type ModAction = 'approve' | 'warn' | 'mute' | 'ban'
export type RuleKey =
  | 'anti_spam'
  | 'bot_install'
  | 'link_blocking'
  | 'flood_protection'
  | 'banned_words'
  | 'welcome_message'
  | 'auto_reply'
  | 'lead_capture'

export interface Workspace {
  id: number
  name: string
  username: string
  memberCount: number
  healthScore: number
  isOwner: boolean
}

export interface ModQueueItem {
  id: number
  userId: number
  displayName: string
  username: string
  initials: string
  reason: string
  timestamp: string
  messagePreview: string
}

export interface TimelineEvent {
  id: number
  type: 'moderation' | 'system' | 'report'
  title: string
  subtitle: string
  timestamp: string
  severity?: 'warn' | 'mute' | 'ban' | 'info'
}

export interface Rule {
  key: RuleKey
  label: string
  description: string
  enabled: boolean
  actionOnly?: boolean
}

export interface Member {
  id: number
  displayName: string
  username: string
  initials: string
  role: 'member' | 'admin' | 'owner'
  joinedAt: string
}

export interface AutomationTask {
  id: string
  taskType: 'message_forward' | 'auto_reply' | 'lead_notify' | 'broadcast'
  executorType: 'agent' | 'bot'
  agentOrBot: string
  sourceGroup: string
  replyMode: 'direct' | 'thread' | 'private'
  destination: string
  suggestedPrivateReply: string
  deliveryMode: 'immediate' | 'delayed' | 'scheduled'
  deleteAfterSeconds: number
  keyword: string
  messageTemplate: string
}

export interface OwnerGroup {
  id: number
  name: string
  username: string
  memberCount: number
  healthScore: number
  subscriptionStatus: 'active' | 'pending' | 'none'
}

export interface OwnerMetrics {
  totalGroups: number
  totalMembers: number
  activeSubscriptions: number
  pendingRequests: number
}

export interface DashboardStats {
  addedToday: number
  addedTodayDelta: number
  activeJobs: number
  queuedJobs: number
  failedAdds: number
  dailyLimitUsed: number
  dailyLimit: number
  jobs: any[]
  failureReasons: { name: string; value: number }[]
  linked_agents?: number
  pending_agent_jobs?: number
  active_subscriptions?: number
  pending_requests?: number
}

// ─── Backend API response types ──────────────────────────────────────────────

export interface ModerationLogEntry {
  id?: number
  action: string
  target_user_id?: number
  moderator_id?: number
  reason?: string
  details?: Record<string, unknown>
  created_at?: string
}

export interface WarningEntry {
  user_id: number
  reason?: string
  count: number
  issued_by?: number
  created_at?: string
}

export interface GroupSettings {
  group_id: number
  settings: Record<string, boolean | number | string>
}

export interface NotificationReport {
  id: number
  group_id: number
  user_id: number
  reason?: string
  message_text?: string
  rendered_text?: string
  destination?: string
  delivery_mode?: string
  source_chat_id?: number
  source_group_title?: string
  source_message_id?: number
  source_user_id?: number
  task_key?: string
  assignment_id?: string
  created_at?: string
}

export interface TaskCatalogItem {
  key: string
  title: string
  description: string
  executor_types: string[]
  conditions_schema?: Record<string, unknown>
  config_schema?: Record<string, unknown>
}

export interface AccessGateInfo {
  group_id?: number
  required_group_tg_ids: number[]
  candidates?: { id?: number; title?: string; tg_group_id?: number; role?: string; member_count?: number }[]
}

export interface OwnerSubscriptionRequest {
  id: number
  fullName: string
  username?: string
  tgUserId: number
  message?: string
  status: 'pending' | 'approved' | 'declined' | 'cancelled'
  plan?: 'pro' | 'business'
  expires_at?: string
  createdAt: string
}

export interface PromotionCode {
  id: number
  code: string
  plan: 'pro' | 'business'
  duration_days: number
  max_uses?: number
  used_count: number
  is_active: boolean
  expiry_date?: string
  created_at: string
}
