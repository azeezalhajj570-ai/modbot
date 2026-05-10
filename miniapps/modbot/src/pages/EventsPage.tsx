import React from 'react'
import type { AIModerationEvent } from '@miniapp/shared'
import { useLang } from '../components/LanguageContext'

interface EventsPageProps {
  events: AIModerationEvent[]
  onAction: (eventId: number, action: string) => void
  actionLoading?: number | null
  loading?: boolean
}

const CATEGORY_STYLES: Record<string, string> = {
  arabic_ad: 'bg-blue-50 text-blue-600',
  investment_scam: 'bg-amber-50 text-amber-600',
  crypto_scam: 'bg-purple-50 text-purple-600',
  phishing_link: 'bg-error-container text-error',
  link_spam: 'bg-orange-50 text-orange-600',
  repeated_promo: 'bg-rose-50 text-rose-600',
}

const STATUS_STYLES: Record<string, string> = {
  pending: 'bg-amber-50 text-amber-600',
  reviewed: 'bg-green-50 text-green-600',
  dismissed: 'bg-slate-50 text-slate-500',
}

function getCategoryStyle(category: string): string {
  return CATEGORY_STYLES[category] || 'bg-slate-50 text-slate-600'
}

function formatTime(iso: string): string {
  try {
    const d = new Date(iso)
    return d.toLocaleString(undefined, { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' })
  } catch { return iso }
}

export const EventsPage: React.FC<EventsPageProps> = ({ events, onAction, actionLoading, loading }) => {
  const { t, lang } = useLang()
  const pendingEvents = events.filter(e => e.status === 'pending' || e.status === 'new')
  const resolvedEvents = events.filter(e => e.status !== 'pending' && e.status !== 'new')

  return (
    <div className="space-y-stack-lg pb-10" style={{ fontFamily: lang === 'ar' ? "'Noto Kufi Arabic', sans-serif" : 'inherit' }}>
      <div className="space-y-stack-sm">
        <h2 className="font-headline-lg text-on-surface">{t('events.title')}</h2>
        <p className="font-body-md text-on-surface-variant">
          {t('events.subtitle')}
          {pendingEvents.length > 0 && (
            <span className="text-error font-medium"> {t('events.pending_count', { count: pendingEvents.length })}</span>
          )}
        </p>
      </div>

      {/* Pending Actions */}
      {pendingEvents.length > 0 && (
        <section className="space-y-stack-md">
          <h3 className="font-label-md text-amber-600 tracking-widest px-1 uppercase">{t('events.requires_action')}</h3>
          {pendingEvents.map(event => (
            <EventCard
              key={event.id}
              event={event}
              onAction={onAction}
              actionLoading={actionLoading}
            />
          ))}
        </section>
      )}

      {/* All Events */}
      <section className="space-y-stack-md">
        <h3 className="font-label-md text-primary tracking-widest px-1 uppercase">
          {pendingEvents.length > 0 ? t('events.all_events') : t('events.title')}
        </h3>
        {loading && events.length === 0 ? (
          <div className="bg-white rounded-xl p-10 text-center space-y-4 shadow-[0_4px_20px_rgba(15,23,42,0.05)]">
            <span className="material-symbols-outlined text-6xl text-slate-200 animate-pulse">notification_important</span>
            <p className="text-on-secondary-container font-medium">{t('events.loading')}</p>
          </div>
        ) : events.length === 0 ? (
          <div className="bg-white rounded-xl p-10 text-center space-y-4 shadow-[0_4px_20px_rgba(15,23,42,0.05)]">
            <span className="material-symbols-outlined text-6xl text-slate-200">check_circle</span>
            <p className="text-on-secondary-container font-medium">{t('events.no_events')}</p>
            <p className="text-body-md text-on-surface-variant">{t('events.no_events_desc')}</p>
          </div>
        ) : (
          <div className="space-y-stack-md">
            {events.map(event => (
              <EventCard
                key={event.id}
                event={event}
                onAction={onAction}
                actionLoading={actionLoading}
              />
            ))}
          </div>
        )}
      </section>

      {/* Resolved Events */}
      {resolvedEvents.length > 0 && pendingEvents.length > 0 && (
        <details className="bg-white rounded-xl shadow-[0_4px_20px_rgba(15,23,42,0.05)]">
          <summary className="p-5 font-headline-md text-on-surface cursor-pointer hover:bg-slate-50 rounded-xl transition-colors">
            {t('events.resolved', { count: resolvedEvents.length })}
          </summary>
          <div className="px-5 pb-5 space-y-3">
            {resolvedEvents.map(event => (
              <div key={event.id} className="flex items-start gap-3 p-3 rounded-lg bg-slate-50 border border-slate-100">
                <div className="w-8 h-8 rounded-full bg-green-50 flex items-center justify-center flex-shrink-0 mt-0.5">
                  <span className="material-symbols-outlined text-green-600 text-sm">check</span>
                </div>
                <div className="flex-1 min-w-0">
                  <div className="flex items-center gap-2 flex-wrap">
                    <span className="font-label-md text-on-surface">{event.username || t('events.anonymous')}</span>
                    <span className={`px-2 py-0.5 rounded-full text-label-sm ${getCategoryStyle(event.category)}`}>
                      {event.category.replace('_', ' ')}
                    </span>
                    <span className="text-label-sm text-on-surface-variant">
                      {formatTime(event.created_at)}
                    </span>
                  </div>
                  <p className="text-label-sm text-on-surface-variant mt-1">
                    {t('events.action', { action: event.action_taken })}
                    {event.dry_run && ` (${t('events.dry_run')})`}
                  </p>
                </div>
              </div>
            ))}
          </div>
        </details>
      )}
    </div>
  )
}

const EventCard: React.FC<{
  event: AIModerationEvent
  onAction: (eventId: number, action: string) => void
  actionLoading?: number | null
}> = ({ event, onAction, actionLoading }) => {
  const { t } = useLang()
  const isPending = event.status === 'pending' || event.status === 'new'

  return (
    <div className="bg-white rounded-xl shadow-[0_4px_20px_rgba(15,23,42,0.05)] p-5 flex flex-col gap-4 border border-slate-50">
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-3">
          <div className="w-10 h-10 rounded-full bg-slate-100 flex items-center justify-center text-slate-400">
            <span className="material-symbols-outlined">person</span>
          </div>
          <div>
            <p className="font-label-md text-on-surface">{event.username || t('events.anonymous')}</p>
            <p className="font-label-sm text-on-surface-variant">{formatTime(event.created_at)}</p>
          </div>
        </div>
        <div className="flex items-center gap-2">
          <span className={`px-3 py-1 rounded-full font-label-sm ${getCategoryStyle(event.category)}`}>
            {event.category.replace('_', ' ')}
          </span>
          {event.dry_run && (
            <span className="px-2 py-1 rounded-full font-label-sm bg-amber-50 text-amber-600">
              {t('events.dry_run')}
            </span>
          )}
        </div>
      </div>

      {event.text_preview && (
        <div className="px-1">
          <p className="font-body-md text-on-surface leading-relaxed italic border-r-4 border-slate-100 pr-3 py-1">
            "{event.text_preview}"
          </p>
          {event.matched_signals && event.matched_signals.length > 0 && (
            <div className="mt-2 flex gap-2 overflow-x-auto pb-1">
              {event.matched_signals.map((signal, idx) => (
                <span key={idx} className="bg-slate-50 text-slate-500 text-[10px] px-2 py-0.5 rounded border border-slate-100 whitespace-nowrap">
                  {signal}
                </span>
              ))}
              <span className="bg-primary-fixed text-primary text-[10px] px-2 py-0.5 rounded border border-primary/10 whitespace-nowrap">
                {t('events.confidence', { pct: Math.round(event.confidence * 100) })}
              </span>
            </div>
          )}
        </div>
      )}

      <div className="flex items-center justify-between pt-2">
        <div className="flex items-center gap-2">
          <span className={`px-2 py-1 rounded-full font-label-sm ${STATUS_STYLES[event.status] || 'bg-slate-50 text-slate-500'}`}>
            {event.status}
          </span>
          {event.action_taken && event.action_taken !== 'none' && (
            <span className="text-label-sm text-on-surface-variant">
              {t('events.action', { action: event.action_taken })}
            </span>
          )}
        </div>

        {isPending && (
          <div className="flex items-center gap-2 flex-wrap justify-end">
            <button
              onClick={() => onAction(event.id, 'approve')}
              disabled={actionLoading === event.id}
              className="bg-primary text-white px-4 py-2 rounded-lg font-label-md transition-all active:scale-95 disabled:opacity-50 text-sm"
            >
              {actionLoading === event.id ? '...' : t('events.approve')}
            </button>
            {event.recommended_action === 'warn' && (
              <ActionButton onClick={() => onAction(event.id, 'warn')} loading={actionLoading === event.id} label={t('events.warn')} />
            )}
            {event.recommended_action === 'mute' && (
              <ActionButton onClick={() => onAction(event.id, 'mute')} loading={actionLoading === event.id} label={t('events.mute')} />
            )}
            {event.recommended_action === 'ban' && (
              <ActionButton onClick={() => onAction(event.id, 'ban')} loading={actionLoading === event.id} label={t('events.ban')} danger />
            )}
            <button
              onClick={() => onAction(event.id, 'delete')}
              disabled={actionLoading === event.id}
              className="bg-surface-container-low text-error px-4 py-2 rounded-lg font-label-md transition-all active:scale-95 hover:bg-error-container/20 disabled:opacity-50 text-sm"
            >
              {t('events.dismiss')}
            </button>
          </div>
        )}
      </div>
    </div>
  )
}

const ActionButton: React.FC<{
  onClick: () => void
  loading: boolean
  label: string
  danger?: boolean
}> = ({ onClick, loading, label, danger }) => (
  <button
    onClick={onClick}
    disabled={loading}
    className={`px-4 py-2 rounded-lg font-label-md transition-all active:scale-95 disabled:opacity-50 text-sm ${
      danger
        ? 'bg-error-container text-error hover:bg-red-200'
        : 'bg-amber-50 text-amber-600 hover:bg-amber-100'
    }`}
  >
    {loading ? '...' : label}
  </button>
)
