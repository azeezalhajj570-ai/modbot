export interface ManagedGroup {
  id: number
  title: string
  tg_group_id: number
  role: string
}

export interface SubscriptionInfo {
  plan: string
  status: string
  expires_at: string | null
}

export interface SubscriptionUser {
  tg_user_id: number
  username: string | null
  full_name: string | null
  plan: string
  status: string
  bot_kind: string | null
  expires_at: string | null
  created_at: string | null
}

export interface PlanLimits {
  max_groups: number
  max_scheduled_messages: number
  max_automation_tasks: number
  max_moderation_actions_per_day: number
}

export interface MiniappIdentity {
  user: {
    id: number
    username: string | null
    first_name: string | null
    last_name: string | null
    language_code: string
  }
  is_bot_owner: boolean
  groups: ManagedGroup[]
  subscription?: SubscriptionInfo
  plan_limits?: PlanLimits
}

export interface GroupOverview {
  group: {
    id: number
    title: string
    tg_group_id: number
  }
  stats: {
    configured_settings: number
    enabled_plugins: number
    total_warnings: number
    total_leads: number
    active_moderators: number
    members_count?: number
    messages_count?: number
    spam_detected?: number
    messages_deleted?: number
    member_growth?: Record<string, number>
    message_activity?: Record<string, number>
  }
  recent_actions: ModerationLogEntry[]
  recent_events?: DashboardModerationEvent[]
}

export interface DashboardModerationEvent {
  id: number
  category: string
  text_preview?: string | null
  username?: string | null
  confidence: number
  action_taken: string
  created_at: string
}

export interface GroupSettings {
  group_id: number
  settings: Record<string, boolean | number | string>
}

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

export interface AccessGateInfo {
  group_id?: number
  required_group_tg_ids: number[]
  candidates?: {
    id?: number
    title?: string
    tg_group_id?: number
    role?: string
    member_count?: number
  }[]
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

export interface AutomationTask {
  assignment_id: string
  task_key: string
  executor_type: 'agent' | 'bot'
  enabled: boolean
  conditions: Record<string, unknown>
  config: Record<string, unknown>
  agent_id?: number | null
  group_id?: number
  group_ids?: number[]
  group_tg_ids?: number[]
  group_titles?: string[]
}

export interface ScheduledMessage {
  id: string
  group_id: number
  text: string
  send_at: string
  cron?: string
  delete_after_seconds: number | null
}

export interface Agent {
  id: number
  group_id: number
  telegram_user_id?: number
  phone_number?: string
  external_account_id: string
  status: 'active' | 'pending' | 'failed'
  auth_state: 'active' | 'pending_code' | 'pending_2fa' | 'failed'
  metadata?: Record<string, unknown>
  max_actions_per_hour?: number | null
  min_delay_seconds?: number | null
  cooldown_minutes?: number | null
  safety_mode_enabled?: boolean
  safety_mode_until?: string | null
}

export interface AgentJobRecord {
  id: number
  agent_id: number
  job_type: string
  job_payload?: Record<string, unknown>
  status: string
  created_at?: string
}

export interface AgentManagedGroup {
  id?: number
  title?: string
  tg_group_id?: number
  member_count?: number
  messages_count?: number
}

export interface AgentGroupMember {
  user_id: number
  username?: string | null
  full_name?: string | null
  role?: string
  message_count?: number
}

export interface AgentGroupMembersPage {
  members: AgentGroupMember[]
  total: number
  page: number
  page_size: number
}

export interface AgentGroupMemberMessage {
  message_id: number
  text?: string | null
  date?: string | null
  message_type?: string | null
  username?: string | null
  full_name?: string | null
}

export interface AgentGroupMemberMessagesPage {
  messages: AgentGroupMemberMessage[]
  total: number
  page: number
  page_size: number
}

export interface AgentGroupScrapeResult {
  success_count: number
  error_count: number
  total_scraped: number
  messages_count?: number
  messages_total_scraped?: number
}

export interface AgentNotification {
  id: number
  agent_id: number
  group_id: number
  kind: string
  title: string
  body: string
  payload?: Record<string, unknown>
  is_seen: boolean
  created_at?: string | null
}

export interface AgentNotificationsResponse {
  items: AgentNotification[]
  unseen_count: number
}

// AI Moderation
export interface AIModerationSettings {
  enabled: boolean
  safe_mode: boolean
  dry_run: boolean
  default_action: string
  review_threshold: number
  auto_delete_threshold: number
  mute_threshold: number
  ban_threshold: number
  action_for_arabic_ads?: string
  action_for_investment_scam?: string
  action_for_crypto_scam?: string
  action_for_phishing_link?: string
  action_for_link_spam?: string
  action_for_repeated_promo?: string
  allowlisted_domains: string[]
  blocked_domains: string[]
  allowlisted_user_ids: number[]
  muted_duration_seconds: number
}

export interface AIModerationEvent {
  id: number
  message_id: number
  user_id: number | null
  username?: string | null
  text_preview?: string | null
  category: string
  confidence: number
  reason?: string | null
  matched_signals: string[]
  recommended_action: string
  action_taken: string
  dry_run: boolean
  status: string
  error_message?: string | null
  created_at: string
}

// Group Subscriptions
export interface GroupSubscriptionSettings {
  enabled: boolean
  payment_mode: string
  default_currency: string
  auto_approve_manual_payments: boolean
  auto_remove_expired: boolean
  expiry_action: string
  grace_period_days: number
  reminder_days_before_expiry: number
  invite_link_expire_seconds: number
  invite_link_member_limit: number
  payment_instructions?: string | null
}

export interface SubscriptionPlan {
  id: number
  name: string
  description?: string | null
  price_amount: number
  currency: string
  duration_days: number
  enabled: boolean
}

export interface GroupSubscriber {
  id: number
  user_id: number
  username?: string | null
  full_name?: string | null
  status: string
  plan_id?: number | null
  starts_at?: string | null
  expires_at?: string | null
}

export interface PaymentRecord {
  id: number
  user_id: number
  plan_id?: number | null
  provider: string
  amount: number
  currency: string
  status: string
  provider_reference?: string | null
  created_at: string
}

export interface AgentLead {
  id: number
  agent_id: number
  group_id: number
  tg_user_id?: number | null
  username?: string | null
  first_name?: string | null
  last_name?: string | null
  source_group_tg_id?: number | null
  source_group_title?: string | null
  source_message_id?: number | null
  message_text?: string | null
  lead_label?: string | null
  status: 'new' | 'contacted' | 'interested' | 'converted' | 'junk' | 'dismissed'
  assigned_to?: number | null
  contact_info?: string | null
  notes?: string | null
  confidence: number
  last_contacted_at?: string | null
  converted_at?: string | null
  captured_at?: string | null
  created_at?: string | null
  updated_at?: string | null
}

export interface AgentLeadPage {
  items: AgentLead[]
  total: number
  page: number
  page_size: number
  total_pages: number
}

export interface AgentLeadStats {
  total: number
  by_status: Record<string, number>
}

export interface AgentAnalytics {
  agent: Agent
  leads: AgentLeadStats
  jobs: {
    total: number
    completed: number
    failed: number
    pending: number
  }
  notifications: {
    unseen: number
  }
  safety: {
    max_actions_per_hour?: number | null
    min_delay_seconds?: number | null
    cooldown_minutes?: number | null
    safety_mode_enabled?: boolean
    safety_mode_until?: string | null
  }
}
