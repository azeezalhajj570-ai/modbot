import React, { useState, useEffect } from 'react'
import type { AIModerationSettings, GroupSettings, AccessGateInfo } from '@miniapp/shared'
import { useLang } from '../components/LanguageContext'
import * as adminApi from '@miniapp/shared/api/admin'

interface ModerationPageProps {
  groupId: number
  settings: AIModerationSettings | null
  onUpdateAiSettings: (updates: Partial<AIModerationSettings>) => void
  groupSettings: GroupSettings | null
  onUpdateGroupSettings: (updates: Record<string, boolean | number | string>) => void
  accessGate: AccessGateInfo | null
  onUpdateAccessGate: (requiredGroupTgIds: number[]) => void
  loading?: boolean
}

interface RestrictedUser {
  user_id: number
  type: 'mute' | 'ban'
  reason: string | null
  created_at: string
  details: Record<string, unknown>
}

export const ModerationPage: React.FC<ModerationPageProps> = ({
  groupId, settings, onUpdateAiSettings, groupSettings, onUpdateGroupSettings,
  accessGate, onUpdateAccessGate,
}) => {
  const { t, lang } = useLang()
  const gs = groupSettings?.settings ?? {}
  const [accessGateDirty, setAccessGateDirty] = useState(false)
  const [selectedCandidates, setSelectedCandidates] = useState<number[]>(() => accessGate?.required_group_tg_ids ?? [])
  const [restrictedUsers, setRestrictedUsers] = useState<RestrictedUser[]>([])
  const [restrictedLoading, setRestrictedLoading] = useState(false)

  const [warnAutoMute, setWarnAutoMute] = useState(!!gs.warn_auto_mute)
  const [warnMuteLimit, setWarnMuteLimit] = useState(Number(gs.warn_mute_limit) || 3)
  const [warnAutoBan, setWarnAutoBan] = useState(!!gs.warn_auto_remove)
  const [warnBanLimit, setWarnBanLimit] = useState(Number(gs.warn_remove_limit) || 5)
  const [warnDirty, setWarnDirty] = useState(false)

  const saveWarnLimits = () => {
    onUpdateGroupSettings({
      warn_auto_mute: warnAutoMute,
      warn_mute_limit: warnMuteLimit,
      warn_auto_remove: warnAutoBan,
      warn_remove_limit: warnBanLimit,
    })
    setWarnDirty(false)
  }

  const cancelWarnLimits = () => {
    setWarnAutoMute(!!gs.warn_auto_mute)
    setWarnMuteLimit(Number(gs.warn_mute_limit) || 3)
    setWarnAutoBan(!!gs.warn_auto_remove)
    setWarnBanLimit(Number(gs.warn_remove_limit) || 5)
    setWarnDirty(false)
  }

  const fetchRestricted = async () => {
    setRestrictedLoading(true)
    try {
      const res = await adminApi.fetchRestrictedUsers(groupId)
      setRestrictedUsers(res as RestrictedUser[])
    } catch {
      setRestrictedUsers([])
    }
    setRestrictedLoading(false)
  }

  useEffect(() => {
    fetchRestricted()
  }, [groupId])

  const handleRestrictedAction = async (userId: number, action: 'unmute' | 'unban') => {
    try {
      await adminApi.performModerationAction(groupId, { user_id: userId, action: action === 'unmute' ? 'unmute' : 'unban' } as any)
      fetchRestricted()
    } catch { }
  }

  const toggleCandidate = (tgId: number) => {
    setSelectedCandidates(prev =>
      prev.includes(tgId) ? prev.filter(id => id !== tgId) : [...prev, tgId]
    )
    setAccessGateDirty(true)
  }

  const saveAccessGate = () => {
    onUpdateAccessGate(selectedCandidates)
    setAccessGateDirty(false)
  }

  return (
    <div className="space-y-stack-lg pb-10" style={{ fontFamily: lang === 'ar' ? "'Noto Kufi Arabic', sans-serif" : 'inherit' }}>
      <div className="space-y-stack-sm">
        <h2 className="font-headline-lg text-on-surface">{t('moderation.title')}</h2>
        <p className="font-body-md text-on-surface-variant">{t('moderation.subtitle')}</p>
      </div>

      {/* Category Actions (Ads Links) */}
      {settings && (
        <section className="space-y-stack-md">
          <h3 className="font-label-md text-primary tracking-widest px-1 uppercase">{t('moderation.ads_scam')}</h3>
          <div className="bg-white rounded-xl shadow-[0_4px_20px_rgba(15,23,42,0.05)] overflow-hidden">
            <CategoryActionItem icon="translate" title={t('moderation.arabic_ads')} value={settings.action_for_arabic_ads ?? settings.default_action} onChange={(val) => onUpdateAiSettings({ action_for_arabic_ads: val })} />
            <div className="h-[1px] bg-slate-50 mx-container-padding" />
            <CategoryActionItem icon="savings" title={t('moderation.investment_scam')} value={settings.action_for_investment_scam ?? settings.default_action} onChange={(val) => onUpdateAiSettings({ action_for_investment_scam: val })} />
            <div className="h-[1px] bg-slate-50 mx-container-padding" />
            <CategoryActionItem icon="currency_bitcoin" title={t('moderation.crypto_scam')} value={settings.action_for_crypto_scam ?? settings.default_action} onChange={(val) => onUpdateAiSettings({ action_for_crypto_scam: val })} />
            <div className="h-[1px] bg-slate-50 mx-container-padding" />
            <CategoryActionItem icon="link" title={t('moderation.phishing_links')} value={settings.action_for_phishing_link ?? settings.default_action} onChange={(val) => onUpdateAiSettings({ action_for_phishing_link: val })} />
            <div className="h-[1px] bg-slate-50 mx-container-padding" />
            <CategoryActionItem icon="spam" title={t('moderation.link_spam')} value={settings.action_for_link_spam ?? settings.default_action} onChange={(val) => onUpdateAiSettings({ action_for_link_spam: val })} />
            <div className="h-[1px] bg-slate-50 mx-container-padding" />
            <CategoryActionItem icon="replay" title={t('moderation.repeated_promo')} value={settings.action_for_repeated_promo ?? settings.default_action} onChange={(val) => onUpdateAiSettings({ action_for_repeated_promo: val })} />
          </div>
        </section>
      )}

      {/* Warning Limits */}
      <section className="space-y-stack-md">
        <h3 className="font-label-md text-primary tracking-widest px-1 uppercase">{t('moderation.warn_limits')}</h3>
        <div className="bg-white rounded-xl shadow-[0_4px_20px_rgba(15,23,42,0.05)] overflow-hidden">
          <ToggleItem icon="gavel" title={t('moderation.warn_auto_mute')} description={t('moderation.warn_auto_mute_desc')} checked={warnAutoMute} onChange={(val) => { setWarnAutoMute(val); setWarnDirty(true) }} />
          <div className="h-[1px] bg-slate-50 mx-container-padding" />
          <NumberItem icon="volume_off" title={t('moderation.warn_mute_limit')} description={t('moderation.warn_mute_limit_desc')} value={warnMuteLimit} onChange={(val) => { setWarnMuteLimit(val); setWarnDirty(true) }} suffix={t('moderation.warnings')} />
          <div className="h-[1px] bg-slate-50 mx-container-padding" />
          <ToggleItem icon="block" title={t('moderation.warn_auto_ban')} description={t('moderation.warn_auto_ban_desc')} checked={warnAutoBan} onChange={(val) => { setWarnAutoBan(val); setWarnDirty(true) }} />
          <div className="h-[1px] bg-slate-50 mx-container-padding" />
          <NumberItem icon="person_remove" title={t('moderation.warn_ban_limit')} description={t('moderation.warn_ban_limit_desc')} value={warnBanLimit} onChange={(val) => { setWarnBanLimit(val); setWarnDirty(true) }} suffix={t('moderation.warnings')} />
          {warnDirty && (
            <div className="flex gap-3 p-4 bg-slate-50 border-t border-slate-100">
              <button onClick={saveWarnLimits} className="flex-1 bg-primary text-white py-2.5 rounded-lg font-label-md transition-all active:scale-95 hover:bg-primary/90">
                {t('moderation.save')}
              </button>
              <button onClick={cancelWarnLimits} className="flex-1 bg-slate-200 text-on-surface py-2.5 rounded-lg font-label-md transition-all active:scale-95 hover:bg-slate-300">
                {t('moderation.cancel')}
              </button>
            </div>
          )}
        </div>
      </section>

      {/* Restricted Users */}
      <section className="space-y-stack-md">
        <h3 className="font-label-md text-primary tracking-widest px-1 uppercase">{t('moderation.restricted')}</h3>
        <div className="bg-white rounded-xl shadow-[0_4px_20px_rgba(15,23,42,0.05)] overflow-hidden">
          {restrictedLoading ? (
            <div className="p-6 text-center text-on-surface-variant font-body-md">{t('common.loading')}</div>
          ) : restrictedUsers.length === 0 ? (
            <div className="p-6 text-center text-on-surface-variant font-body-md">{t('moderation.no_restricted')}</div>
          ) : (
            restrictedUsers.map((user, i) => (
              <div key={user.user_id}>
                {i > 0 && <div className="h-[1px] bg-slate-50 mx-container-padding" />}
                <div className="flex items-center justify-between p-4 hover:bg-slate-50 transition-colors">
                  <div className="flex items-center gap-3">
                    <div className={`w-9 h-9 rounded-lg flex items-center justify-center text-white ${user.type === 'mute' ? 'bg-amber-500' : 'bg-red-500'}`}>
                      <span className="material-symbols-outlined text-lg">{user.type === 'mute' ? 'volume_off' : 'block'}</span>
                    </div>
                    <div>
                      <p className="font-headline-md text-on-surface">ID: {user.user_id}</p>
                      <p className="font-body-sm text-on-surface-variant">
                        {user.type === 'mute' ? t('moderation.muted') : t('moderation.banned')}
                        {user.reason ? ` — ${user.reason}` : ''}
                      </p>
                    </div>
                  </div>
                  <div className="flex gap-2">
                    {user.type === 'mute' && (
                      <button onClick={() => handleRestrictedAction(user.user_id, 'unmute')} className="px-3 py-1.5 rounded-lg bg-primary text-white text-sm font-medium hover:bg-primary/90 transition-colors">
                        {t('moderation.unmute')}
                      </button>
                    )}
                    {user.type === 'ban' && (
                      <button onClick={() => handleRestrictedAction(user.user_id, 'unban')} className="px-3 py-1.5 rounded-lg bg-primary text-white text-sm font-medium hover:bg-primary/90 transition-colors">
                        {t('moderation.unban')}
                      </button>
                    )}
                    <button onClick={() => handleRestrictedAction(user.user_id, user.type === 'mute' ? 'unban' : 'unmute')} className={`px-3 py-1.5 rounded-lg text-sm font-medium transition-colors ${user.type === 'mute' ? 'bg-red-500 text-white hover:bg-red-600' : 'bg-amber-500 text-white hover:bg-amber-600'}`}>
                      {user.type === 'mute' ? t('moderation.ban') : t('moderation.mute')}
                    </button>
                  </div>
                </div>
              </div>
            ))
          )}
        </div>
      </section>

      {/* Mute & Ban Settings */}
      <section className="space-y-stack-md">
        <h3 className="font-label-md text-primary tracking-widest px-1 uppercase">{t('moderation.mute_ban')}</h3>
        <div className="bg-white rounded-xl shadow-[0_4px_20px_rgba(15,23,42,0.05)] p-6 space-y-6">
          <DurationItem icon="timer" title={t('moderation.mute_duration')} description={t('moderation.mute_desc')} value={settings?.muted_duration_seconds ?? 3600} onChange={(val) => onUpdateAiSettings({ muted_duration_seconds: val })} suffix={t('moderation.min')} />
          <ToggleItem icon="auto_delete" title={t('moderation.ban_delete')} description={t('moderation.ban_delete_desc')} checked={!!gs.ban_after_delete} onChange={(val) => onUpdateGroupSettings({ ban_after_delete: val })} />
        </div>
      </section>

      {/* Rate Limits */}
      <section className="space-y-stack-md">
        <h3 className="font-label-md text-primary tracking-widest px-1 uppercase">{t('moderation.rate_limits')}</h3>
        <div className="bg-white rounded-xl shadow-[0_4px_20px_rgba(15,23,42,0.05)] overflow-hidden">
          <NumberItem icon="flash_on" title={t('moderation.max_msgs')} description={t('moderation.max_msgs_desc')} value={Number(gs.max_messages_per_minute) || 20} onChange={(val) => onUpdateGroupSettings({ max_messages_per_minute: val })} suffix={t('moderation.msg_min')} />
        </div>
      </section>

      {/* Notifications */}
      <section className="space-y-stack-md">
        <h3 className="font-label-md text-primary tracking-widest px-1 uppercase">{t('moderation.notifications')}</h3>
        <div className="bg-white rounded-xl shadow-[0_4px_20px_rgba(15,23,42,0.05)] overflow-hidden">
          <ToggleItem icon="notifications" title={t('moderation.notify_violations')} description={t('moderation.notify_violations_desc')} checked={!!gs.notify_on_violation} onChange={(val) => onUpdateGroupSettings({ notify_on_violation: val })} />
          <div className="h-[1px] bg-slate-50 mx-container-padding" />
          <ToggleItem icon="campaign" title={t('moderation.notify_join')} description={t('moderation.notify_join_desc')} checked={!!gs.notify_on_join} onChange={(val) => onUpdateGroupSettings({ notify_on_join: val })} />
        </div>
      </section>

      {/* Gated Group Access */}
      <section className="space-y-stack-md">
        <h3 className="font-label-md text-primary tracking-widest px-1 uppercase">{t('moderation.access_gate')}</h3>
        <div className="bg-white rounded-xl shadow-[0_4px_20px_rgba(15,23,42,0.05)] p-6 space-y-5">
          <div className="flex items-start gap-4">
            <div className="w-10 h-10 rounded-lg bg-slate-50 flex items-center justify-center text-slate-500 flex-shrink-0">
              <span className="material-symbols-outlined">lock</span>
            </div>
            <div>
              <p className="font-headline-md text-on-surface">{t('moderation.access_gate_title')}</p>
              <p className="font-body-md text-on-surface-variant mt-1">{t('moderation.access_gate_desc')}</p>
            </div>
          </div>

          <BilingualTextInput
            enValue={String(gs.access_gate_text_en || '')}
            arValue={String(gs.access_gate_text_ar || '')}
            onEnChange={(v) => onUpdateGroupSettings({ access_gate_text_en: v })}
            onArChange={(v) => onUpdateGroupSettings({ access_gate_text_ar: v })}
            enPlaceholder={t('moderation.access_gate_en_placeholder')}
            arPlaceholder={t('moderation.access_gate_ar_placeholder')}
          />

          {accessGate?.candidates && accessGate.candidates.length > 0 ? (
            <div className="space-y-2 max-h-64 overflow-y-auto">
              {accessGate.candidates.map((c) => {
                const isSelected = selectedCandidates.includes(c.tg_group_id!)
                return (
                  <button
                    key={c.tg_group_id}
                    onClick={() => toggleCandidate(c.tg_group_id!)}
                    className={`w-full flex items-center justify-between p-3 rounded-lg border transition-all ${
                      isSelected
                        ? 'bg-primary/5 border-primary/30 text-primary'
                        : 'bg-slate-50 border-slate-100 text-on-surface-variant hover:bg-slate-100'
                    }`}
                  >
                    <div className="flex items-center gap-3">
                      <span className={`material-symbols-outlined ${isSelected ? 'text-primary' : ''}`}>
                        {isSelected ? 'check_circle' : 'group'}
                      </span>
                      <div>
                        <span className="font-body-md">{c.title || `Group #${c.tg_group_id}`}</span>
                        {c.member_count != null && (
                          <span className="text-label-sm text-on-surface-variant ml-2">{t('common.members', { count: c.member_count })}</span>
                        )}
                      </div>
                    </div>
                    <span className={`w-5 h-5 rounded-full border-2 flex items-center justify-center ${
                      isSelected ? 'bg-primary border-primary' : 'border-slate-300'
                    }`}>
                      {isSelected && <span className="w-2 h-2 rounded-full bg-white" />}
                    </span>
                  </button>
                )
              })}
            </div>
          ) : (
            <div className="bg-slate-50 rounded-lg p-6 text-center">
              <span className="material-symbols-outlined text-4xl text-slate-300">lock_open</span>
              <p className="font-body-md text-on-surface-variant mt-2">
                {accessGate ? t('moderation.access_gate_no_groups') : t('moderation.access_gate_loading')}
              </p>
            </div>
          )}

          {accessGateDirty && (
            <div className="flex gap-3">
              <button onClick={() => { setSelectedCandidates(accessGate?.required_group_tg_ids ?? []); setAccessGateDirty(false) }} className="flex-1 bg-slate-100 text-on-surface py-2.5 rounded-lg font-label-md">{t('moderation.cancel')}</button>
              <button onClick={saveAccessGate} className="flex-1 bg-primary text-white py-2.5 rounded-lg font-label-md">{t('moderation.save')}</button>
            </div>
          )}
        </div>
      </section>

      {/* Welcome Messages */}
      <section className="space-y-stack-md">
        <h3 className="font-label-md text-primary tracking-widest px-1 uppercase">{t('moderation.welcome')}</h3>
        <div className="bg-white rounded-xl shadow-[0_4px_20px_rgba(15,23,42,0.05)] p-6 space-y-5">
          <ToggleItem icon="celebration" title={t('moderation.welcome_toggle')} description={t('moderation.welcome_toggle_desc')} checked={!!gs.welcome_enabled} onChange={(val) => onUpdateGroupSettings({ welcome_enabled: val })} />
          <BilingualTextInput
            enValue={String(gs.welcome_text_en || '')}
            arValue={String(gs.welcome_text_ar || '')}
            onEnChange={(v) => onUpdateGroupSettings({ welcome_text_en: v })}
            onArChange={(v) => onUpdateGroupSettings({ welcome_text_ar: v })}
            enPlaceholder={t('moderation.welcome_en_placeholder')}
            arPlaceholder={t('moderation.welcome_ar_placeholder')}
          />
        </div>
      </section>
    </div>
  )
}

const ToggleItem: React.FC<{ icon: string; title: string; description: string; checked: boolean; onChange: (val: boolean) => void }> = ({ icon, title, description, checked, onChange }) => (
  <div className="flex items-center justify-between p-6 hover:bg-slate-50 transition-colors">
    <div className="flex items-center gap-4">
      <div className="w-10 h-10 rounded-lg bg-slate-50 flex items-center justify-center text-slate-500">
        <span className="material-symbols-outlined">{icon}</span>
      </div>
      <div>
        <p className="font-headline-md text-on-surface">{title}</p>
        <p className="font-body-md text-on-surface-variant max-w-[220px] leading-tight">{description}</p>
      </div>
    </div>
    <label className="relative inline-flex items-center cursor-pointer">
      <input type="checkbox" className="sr-only peer" checked={checked} onChange={(e) => onChange(e.target.checked)} />
      <div className="w-11 h-6 bg-slate-200 peer-focus:outline-none rounded-full peer peer-checked:after:-translate-x-full rtl:peer-checked:after:-translate-x-full peer-checked:after:border-white after:content-[''] after:absolute after:top-[2px] after:right-[2px] after:bg-white after:border-gray-300 after:border after:rounded-full after:h-5 after:w-5 after:transition-all peer-checked:bg-primary" />
    </label>
  </div>
)

const ACTIONS = ['delete', 'warn', 'mute', 'ban', 'none'] as const

const CategoryActionItem: React.FC<{ icon: string; title: string; value: string; onChange: (val: string) => void }> = ({ icon, title, value, onChange }) => (
  <div className="flex items-center justify-between p-6 hover:bg-slate-50 transition-colors">
    <div className="flex items-center gap-4">
      <div className="w-10 h-10 rounded-lg bg-slate-50 flex items-center justify-center text-slate-500">
        <span className="material-symbols-outlined">{icon}</span>
      </div>
      <p className="font-headline-md text-on-surface">{title}</p>
    </div>
    <select value={value} onChange={(e) => onChange(e.target.value)} className="px-3 py-1.5 rounded-lg border border-slate-200 bg-white text-sm font-medium text-on-surface focus:outline-none focus:ring-2 focus:ring-primary/20">
      {ACTIONS.map(a => <option key={a} value={a}>{a.charAt(0).toUpperCase() + a.slice(1)}</option>)}
    </select>
  </div>
)

const DurationItem: React.FC<{ icon: string; title: string; description: string; value: number; onChange: (val: number) => void; suffix: string }> = ({ icon, title, description, value, onChange, suffix }) => {
  const [minutes, setMinutes] = useState(Math.round(value / 60))
  return (
    <div className="flex items-center justify-between">
      <div className="flex items-center gap-4">
        <div className="w-10 h-10 rounded-lg bg-slate-50 flex items-center justify-center text-slate-500">
          <span className="material-symbols-outlined">{icon}</span>
        </div>
        <div>
          <p className="font-headline-md text-on-surface">{title}</p>
          <p className="font-body-md text-on-surface-variant">{description}</p>
        </div>
      </div>
      <div className="flex items-center gap-2">
        <input type="number" min="1" max="525600" value={minutes} onChange={(e) => { const m = parseInt(e.target.value) || 1; setMinutes(m); onChange(m * 60) }} className="w-20 px-3 py-1.5 rounded-lg border border-slate-200 bg-white text-sm text-center font-medium text-on-surface focus:outline-none focus:ring-2 focus:ring-primary/20" />
        <span className="text-label-sm text-on-surface-variant">{suffix}</span>
      </div>
    </div>
  )
}

const BilingualTextInput: React.FC<{
  enValue: string; arValue: string
  onEnChange: (v: string) => void; onArChange: (v: string) => void
  enPlaceholder: string; arPlaceholder: string
}> = ({ enValue, arValue, onEnChange, onArChange, enPlaceholder, arPlaceholder }) => (
  <div className="space-y-3">
    <div className="flex items-center gap-2">
      <span className="w-6 h-5 flex items-center justify-center rounded bg-blue-100 text-blue-700 text-[10px] font-bold">EN</span>
      <textarea
        value={enValue}
        onChange={(e) => onEnChange(e.target.value)}
        rows={2}
        className="flex-1 px-3 py-2 rounded-lg border border-slate-200 bg-white text-sm font-body-md text-on-surface focus:outline-none focus:ring-2 focus:ring-primary/20 resize-vertical"
        placeholder={enPlaceholder}
        dir="ltr"
      />
    </div>
    <div className="flex items-start gap-2">
      <span className="w-6 h-5 flex items-center justify-center rounded bg-green-100 text-green-700 text-[10px] font-bold mt-2">AR</span>
      <textarea
        value={arValue}
        onChange={(e) => onArChange(e.target.value)}
        rows={2}
        className="flex-1 px-3 py-2 rounded-lg border border-slate-200 bg-white text-sm font-body-md text-on-surface focus:outline-none focus:ring-2 focus:ring-primary/20 resize-vertical"
        placeholder={arPlaceholder}
        dir="rtl"
        style={{ fontFamily: "'Noto Kufi Arabic', sans-serif" }}
      />
    </div>
  </div>
)

const NumberItem: React.FC<{ icon: string; title: string; description: string; value: number; onChange: (val: number) => void; suffix: string }> = ({ icon, title, description, value, onChange, suffix }) => (
  <div className="flex items-center justify-between p-6">
    <div className="flex items-center gap-4">
      <div className="w-10 h-10 rounded-lg bg-slate-50 flex items-center justify-center text-slate-500">
        <span className="material-symbols-outlined">{icon}</span>
      </div>
      <div>
        <p className="font-headline-md text-on-surface">{title}</p>
        <p className="font-body-md text-on-surface-variant">{description}</p>
      </div>
    </div>
    <div className="flex items-center gap-2">
      <input type="number" min="1" max="1000" value={value} onChange={(e) => onChange(parseInt(e.target.value) || 1)} className="w-20 px-3 py-1.5 rounded-lg border border-slate-200 bg-white text-sm text-center font-medium text-on-surface focus:outline-none focus:ring-2 focus:ring-primary/20" />
      <span className="text-label-sm text-on-surface-variant">{suffix}</span>
    </div>
  </div>
)
