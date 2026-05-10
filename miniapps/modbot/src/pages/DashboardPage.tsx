import React, { useEffect, useState } from 'react'
import type { GroupOverview, AIModerationSettings, ModerationLogEntry, SubscriptionUser } from '@miniapp/shared'
import { adminApi } from '@miniapp/shared'
import { ConfirmModal } from '../components/ConfirmModal'
import { useLang } from '../components/LanguageContext'

function fmtDate(raw: string): string {
  try {
    const d = new Date(raw)
    if (isNaN(d.getTime())) return raw
    return d.toLocaleDateString(undefined, { weekday: 'short', month: 'short', day: 'numeric' })
  } catch { return raw }
}

interface DashboardPageProps {
  overview: GroupOverview | null
  modLogs: ModerationLogEntry[]
  settings: AIModerationSettings | null
  loading?: boolean
  is_bot_owner?: boolean
}

function formatTime(iso: string): string {
  try {
    const d = new Date(iso + 'Z')
    if (isNaN(d.getTime())) return iso
    return d.toLocaleString(undefined, { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' })
  } catch { return iso }
}

const ACTION_ICONS: Record<string, string> = {
  delete: 'delete',
  warn: 'warning',
  ban: 'block',
  mute: 'volume_off',
  approve: 'check_circle',
  kick: 'logout',
  unrestrict: 'lock_open',
}

export const DashboardPage: React.FC<DashboardPageProps> = ({ overview, modLogs, loading, is_bot_owner }) => {
  const { t, lang } = useLang()
  const stats = overview?.stats
  const safetyScore = stats ? Math.min(100, Math.round(
    ((stats.messages_count ?? 0) > 0
      ? (1 - ((stats.spam_detected ?? 0) / Math.max(stats.messages_count ?? 1, 1))) * 100
      : 85)
  )) : 0
  const memberGrowth = stats?.member_growth as Record<string, number> | undefined
  const messageActivity = stats?.message_activity as Record<string, number> | undefined

  return (
    <div className="space-y-stack-lg" style={{ fontFamily: lang === 'ar' ? "'Noto Kufi Arabic', sans-serif" : 'inherit' }}>
      <div className="flex flex-col gap-2">
        <h2 className="text-headline-xl font-headline-xl text-primary">{t('dashboard.title')}</h2>
        <p className="text-body-md font-body-md text-on-secondary-container">{t('dashboard.subtitle')}</p>
      </div>

      {/* Health Score + Key Metrics */}
      <div className="grid grid-cols-1 md:grid-cols-12 gap-gutter">
        <div className="md:col-span-5 bg-white rounded-xl shadow-[0_4px_20px_rgba(15,23,42,0.05)] p-stack-md flex flex-col items-center justify-center text-center space-y-stack-md">
          <div className="relative w-48 h-48 flex items-center justify-center">
            <div
              className="absolute inset-0 rounded-full safety-gauge rotate-[-45deg]"
              style={{
                background: `conic-gradient(from 180deg, #006193 0%, #006193 ${safetyScore}%, #e2e7ff ${safetyScore}%, #e2e7ff 100%)`,
              }}
            ></div>
            <div className="flex flex-col items-center">
              <span className="text-headline-xl font-headline-xl text-primary">{safetyScore}</span>
              <span className="text-label-md font-label-md text-on-secondary-container">{t('dashboard.health')}</span>
            </div>
          </div>
          <div className="space-y-base">
            <h3 className="text-headline-md font-headline-md">
              {safetyScore >= 80 ? t('dashboard.healthy') : safetyScore >= 50 ? t('dashboard.needs_attention') : t('dashboard.at_risk')}
            </h3>
            <p className="text-body-md font-body-md text-on-secondary-container px-4">
              {t('dashboard.threats', { count: stats?.spam_detected ?? 0, deleted: stats?.messages_deleted ?? 0, warnings: stats?.total_warnings ?? 0 })}
            </p>
          </div>
        </div>

        <div className="md:col-span-7 grid grid-cols-1 gap-4">
          <MiniStatCard icon="qr_code_scanner" label={t('dashboard.msgs_tracked')} value={stats?.messages_count ?? 0} iconBg="bg-primary-fixed" iconColor="text-primary" />
          <MiniStatCard icon="gpp_maybe" label={t('dashboard.spam_detected')} value={stats?.spam_detected ?? 0} iconBg="bg-error-container" iconColor="text-error" />
          <MiniStatCard icon="delete_sweep" label={t('dashboard.msgs_deleted')} value={stats?.messages_deleted ?? 0} iconBg="bg-secondary-fixed-dim" iconColor="text-secondary" />
          <MiniStatCard icon="group" label={t('dashboard.active_members')} value={stats?.members_count ?? 0} iconBg="bg-secondary-fixed" iconColor="text-secondary" />
        </div>
      </div>

      {/* Member Activity + Message Activity */}
      <div className="grid grid-cols-1 md:grid-cols-2 gap-gutter">
        <div className="bg-white rounded-xl shadow-[0_4px_20px_rgba(15,23,42,0.05)] p-stack-md">
          <h3 className="text-headline-md font-headline-md mb-stack-md">{t('dashboard.member_activity')}</h3>
          {memberGrowth && Object.keys(memberGrowth).length > 0 ? (
            <div className="space-y-2">
              {Object.entries(memberGrowth).slice(-7).map(([date, count]) => (
                <div key={date} className="flex items-center gap-3">
                  <span className="text-label-sm text-on-surface-variant w-20 flex-shrink-0">
                    {fmtDate(date)}
                  </span>
                  <div className="flex-1 h-6 bg-slate-50 rounded-full overflow-hidden">
                    <div
                      className="h-full bg-primary-fixed rounded-full transition-all"
                      style={{ width: `${Math.min(100, (count / Math.max(...Object.values(memberGrowth), 1)) * 100)}%` }}
                    />
                  </div>
                  <span className="text-label-sm font-medium text-on-surface w-10 text-right">{count}</span>
                </div>
              ))}
              <p className="text-label-sm text-on-secondary-container pt-2">
                {t('dashboard.total_members', { count: Object.values(memberGrowth).reduce((a, b) => a + b, 0) })}
              </p>
            </div>
          ) : (
            <p className="text-body-md text-on-secondary-container text-center py-6">{t('dashboard.no_member_data')}</p>
          )}
        </div>

        <div className="bg-white rounded-xl shadow-[0_4px_20px_rgba(15,23,42,0.05)] p-stack-md">
          <h3 className="text-headline-md font-headline-md mb-stack-md">{t('dashboard.msg_activity')}</h3>
          {messageActivity && Object.keys(messageActivity).length > 0 ? (
            <div className="space-y-2">
              {Object.entries(messageActivity).slice(-7).map(([date, count]) => (
                <div key={date} className="flex items-center gap-3">
                  <span className="text-label-sm text-on-surface-variant w-20 flex-shrink-0">
                    {fmtDate(date)}
                  </span>
                  <div className="flex-1 h-6 bg-slate-50 rounded-full overflow-hidden">
                    <div
                      className="h-full bg-primary/10 rounded-full transition-all"
                      style={{ width: `${Math.min(100, (count / Math.max(...Object.values(messageActivity), 1)) * 100)}%` }}
                    />
                  </div>
                  <span className="text-label-sm font-medium text-on-surface w-10 text-right">{count}</span>
                </div>
              ))}
              <p className="text-label-sm text-on-secondary-container pt-2">
                {t('dashboard.total_msgs', { count: Object.values(messageActivity).reduce((a, b) => a + b, 0) })}
              </p>
            </div>
          ) : (
            <p className="text-body-md text-on-secondary-container text-center py-6">{t('dashboard.no_msg_data')}</p>
          )}
        </div>
      </div>

      {/* Additional Stats */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
        <StatCard label={t('dashboard.moderators')} value={stats?.active_moderators ?? 0} icon="badge" />
        <StatCard label={t('dashboard.warnings')} value={stats?.total_warnings ?? 0} icon="warning" />
        <StatCard label={t('dashboard.plugins')} value={stats?.enabled_plugins ?? 0} icon="extension" />
        <StatCard label={t('dashboard.settings_conf')} value={stats?.configured_settings ?? 0} icon="settings" />
      </div>

      {/* Recent Moderation Actions */}
      <div className="bg-white rounded-xl shadow-[0_4px_20px_rgba(15,23,42,0.05)] p-stack-md">
        <div className="flex items-center justify-between mb-stack-md">
          <h3 className="text-headline-md font-headline-md">{t('dashboard.recent_actions')}</h3>
          {loading && <span className="material-symbols-outlined animate-spin text-primary">progress_activity</span>}
        </div>
        {!modLogs || modLogs.length === 0 ? (
          <p className="text-body-md text-on-secondary-container text-center py-8">
            {loading ? t('dashboard.loading_logs') : t('dashboard.no_actions')}
          </p>
        ) : (
          <div className="space-y-stack-sm">
            {modLogs.slice(0, 10).map((entry, idx) => (
              <div
                key={entry.id ?? idx}
                className="flex items-start gap-stack-md p-stack-md rounded-lg border border-outline-variant bg-surface-container-low"
              >
                <div className="flex-shrink-0 w-10 h-10 rounded-full bg-error-container flex items-center justify-center">
                  <span className="material-symbols-outlined text-error text-lg">
                    {ACTION_ICONS[entry.action] || 'report'}
                  </span>
                </div>
                <div className="flex-1 min-w-0">
                  <div className="flex items-center gap-2 flex-wrap">
                    <span className="text-label-md font-label-md capitalize">{entry.action}</span>
                    {entry.reason && (
                      <span className="text-label-sm text-on-secondary-container">— {entry.reason}</span>
                    )}
                  </div>
                  {entry.details && Object.keys(entry.details).length > 0 && (
                    <p className="text-body-md font-body-md text-on-secondary-container mt-1 truncate max-w-md">
                      {JSON.stringify(entry.details)}
                    </p>
                  )}
                  {entry.created_at && (
                    <p className="text-label-sm text-on-secondary-container mt-1 opacity-60">
                      {formatTime(entry.created_at)}
                    </p>
                  )}
                </div>
              </div>
            ))}
          </div>
        )}
      </div>

      {/* Subscription Management (owner only) */}
      {is_bot_owner && <SubscriptionManager lang={lang} />}
    </div>
  )
}

const MiniStatCard: React.FC<{ icon: string; label: string; value: number; iconBg: string; iconColor: string }> = ({
  icon, label, value, iconBg, iconColor,
}) => (
  <div className="bg-white rounded-xl p-6 shadow-[0_4px_20px_rgba(15,23,42,0.05)] flex justify-between items-center">
    <div>
      <p className="text-label-md text-on-secondary-container mb-1">{label}</p>
      <p className="text-headline-lg font-bold">{(value ?? 0).toLocaleString()}</p>
    </div>
    <span className={`material-symbols-outlined ${iconColor} p-3 ${iconBg} rounded-xl`}>{icon}</span>
  </div>
)

const StatCard: React.FC<{ label: string; value: number; icon: string }> = ({ label, value, icon }) => (
  <div className="bg-white rounded-xl p-4 shadow-[0_4px_20px_rgba(15,23,42,0.05)] flex flex-col items-center text-center gap-2">
    <span className="material-symbols-outlined text-primary/60">{icon}</span>
    <p className="text-headline-lg font-bold">{value ?? 0}</p>
    <p className="text-label-sm text-on-secondary-container">{label}</p>
  </div>
)

const PLAN_OPTIONS = ['free', 'pro', 'business'] as const

const planBadge = (plan: string): string => {
  if (plan === 'free') return 'bg-amber-100 text-amber-700'
  if (plan === 'pro') return 'bg-blue-100 text-blue-700'
  return 'bg-purple-100 text-purple-700'
}

const SubscriptionManager: React.FC<{ lang: string }> = ({ lang }) => {
  const [subs, setSubs] = useState<SubscriptionUser[]>([])
  const [loading, setLoading] = useState(true)
  const [updating, setUpdating] = useState<number | null>(null)
  const [cancelTarget, setCancelTarget] = useState<SubscriptionUser | null>(null)
  const [subBotKind, setSubBotKind] = useState<string | undefined>(undefined)

  const refresh = (bk?: string) => {
    setLoading(true)
    adminApi.fetchSubscriptions(bk).then(setSubs).finally(() => setLoading(false))
  }
  useEffect(() => { refresh(subBotKind) }, [subBotKind])

  const changePlan = async (tgUserId: number, plan: string) => {
    setUpdating(tgUserId)
    try {
      const updated = await adminApi.setUserPlan(tgUserId, plan, subBotKind)
      setSubs(prev => prev.map(s => s.tg_user_id === tgUserId ? updated : s))
    } finally {
      setUpdating(null)
    }
  }

  const cancelUser = async () => {
    if (!cancelTarget) return
    setUpdating(cancelTarget.tg_user_id)
    try {
      await adminApi.cancelSubscription(cancelTarget.tg_user_id, subBotKind)
      setSubs(prev => prev.filter(s => s.tg_user_id !== cancelTarget.tg_user_id))
    } finally {
      setUpdating(null)
      setCancelTarget(null)
    }
  }

  const labels: Record<string, string> = lang === 'ar' ? {
    title: 'إدارة الاشتراكات',
    user: 'المستخدم',
    plan: 'الخطة',
    status: 'الحالة',
    actions: 'الإجراءات',
    loading: 'جاري التحميل...',
    noUsers: 'لا يوجد مستخدمين',
  } : {
    title: 'Subscriptions',
    user: 'User',
    plan: 'Plan',
    status: 'Status',
    actions: 'Actions',
    loading: 'Loading...',
    noUsers: 'No users found',
  }

  return (
    <div className="bg-white rounded-xl shadow-[0_4px_20px_rgba(15,23,42,0.05)] p-stack-md" style={{ fontFamily: lang === 'ar' ? "'Noto Kufi Arabic', sans-serif" : 'inherit' }}>
      <h3 className="text-headline-md font-headline-md mb-stack-md">{labels.title}</h3>
      <div className="flex items-center gap-2 mb-stack-sm">
        <select
          value={subBotKind ?? ''}
          onChange={(e) => setSubBotKind(e.target.value || undefined)}
          className="px-2 py-1 rounded-lg border border-slate-200 bg-white text-xs font-medium"
        >
          <option value="">All</option>
          <option value="admin">Modbot</option>
          <option value="agents">Madarbot</option>
        </select>
      </div>
      {loading ? (
        <p className="text-body-md text-on-secondary-container text-center py-4">{labels.loading}</p>
      ) : subs.length === 0 ? (
        <p className="text-body-md text-on-secondary-container text-center py-4">{labels.noUsers}</p>
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="text-label-sm text-on-surface-variant border-b border-slate-100">
                  <th className="text-left py-2 px-3">{labels.user}</th>
                  <th className="text-left py-2 px-3">{labels.plan}</th>
                  <th className="text-center py-2 px-3">{labels.actions}</th>
              </tr>
            </thead>
            <tbody>
              {subs.map(s => (
                <tr key={s.tg_user_id} className="border-b border-slate-50 hover:bg-slate-50/50">
                  <td className="py-3 px-3">
                    <div>
                      <p className="font-medium text-on-surface">{s.full_name || s.username || `ID ${s.tg_user_id}`}</p>
                      {s.username && <p className="text-xs text-on-surface-variant">@{s.username}</p>}
                    </div>
                  </td>
                  <td className="py-3 px-3">
                    <span className={`text-[10px] font-semibold px-1.5 py-0.5 rounded-full ${planBadge(s.plan)}`}>
                      {s.plan.toUpperCase()}
                    </span>
                  </td>
                  <td className="py-3 px-3 text-center">
                    <div className="flex items-center justify-center gap-1">
                      <select
                        value={s.plan}
                        disabled={updating === s.tg_user_id}
                        onChange={(e) => changePlan(s.tg_user_id, e.target.value)}
                        className="px-2 py-1 rounded-lg border border-slate-200 bg-white text-xs font-medium text-on-surface focus:outline-none focus:ring-2 focus:ring-primary/20 disabled:opacity-50"
                      >
                        {PLAN_OPTIONS.map(p => (
                          <option key={p} value={p}>{p.toUpperCase()}</option>
                        ))}
                      </select>
                      <button
                        onClick={() => setCancelTarget(s)}
                        disabled={updating === s.tg_user_id}
                        className="px-2 py-1 rounded-lg text-xs font-medium text-red-600 bg-red-50 hover:bg-red-100 transition-colors disabled:opacity-50"
                      >
                        <span className="material-symbols-outlined text-sm align-middle">cancel</span>
                      </button>
                      {updating === s.tg_user_id && (
                        <span className="material-symbols-outlined animate-spin text-primary text-sm">progress_activity</span>
                      )}
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      {cancelTarget && (
        <ConfirmModal
          open={true}
          title={lang === 'ar' ? 'إلغاء الاشتراك' : 'Cancel Subscription'}
          message={lang === 'ar'
            ? `هل أنت متأكد من إلغاء اشتراك ${cancelTarget.full_name || cancelTarget.username || `ID ${cancelTarget.tg_user_id}`}؟`
            : `Are you sure you want to cancel the subscription for ${cancelTarget.full_name || cancelTarget.username || `ID ${cancelTarget.tg_user_id}`}?`
          }
          confirmLabel={lang === 'ar' ? 'إلغاء' : 'Cancel'}
          danger
          onConfirm={cancelUser}
          onCancel={() => setCancelTarget(null)}
        />
      )}
    </div>
  )
}
