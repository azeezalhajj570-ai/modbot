import React from 'react'
import type { DashboardModerationEvent } from '@miniapp/shared'

interface DashboardPageProps {
  safetyScore: number
  stats: {
    scanned: number
    spam: number
    activeMembers: number
    deleted: number
  }
  recentEvents: DashboardModerationEvent[]
  loading?: boolean
}

const CATEGORY_LABELS: Record<string, string> = {
  arabic_ad: 'Arabic Ad',
  investment_scam: 'Investment Scam',
  crypto_scam: 'Crypto Scam',
  phishing_link: 'Phishing',
  link_spam: 'Link Spam',
  repeated_promo: 'Repeated Promo',
  safe: 'Safe',
}

const CATEGORY_COLORS: Record<string, string> = {
  arabic_ad: 'bg-blue-100 text-blue-700',
  investment_scam: 'bg-amber-100 text-amber-700',
  crypto_scam: 'bg-purple-100 text-purple-700',
  phishing_link: 'bg-red-100 text-red-700',
  link_spam: 'bg-orange-100 text-orange-700',
  repeated_promo: 'bg-rose-100 text-rose-700',
  safe: 'bg-green-100 text-green-700',
}

const ACTION_ICONS: Record<string, string> = {
  delete: 'delete',
  warn: 'warning',
  ban: 'block',
  mute: 'volume_off',
  review: 'visibility',
  none: 'check_circle',
}

function formatTime(iso: string): string {
  try {
    const d = new Date(iso)
    return d.toLocaleString(undefined, { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' })
  } catch { return iso }
}

export const DashboardPage: React.FC<DashboardPageProps> = ({ safetyScore, stats, recentEvents, loading }) => {
  return (
    <div className="space-y-stack-lg">
      <div className="flex flex-col gap-2">
        <h2 className="text-headline-xl font-headline-xl text-primary">Security Analytics</h2>
        <p className="text-body-md font-body-md text-on-secondary-container">Community health and safety overview.</p>
      </div>

      <div className="grid grid-cols-1 md:grid-cols-12 gap-gutter">
        {/* Safety Score Card */}
        <div className="md:col-span-5 bg-white rounded-xl shadow-[0_4px_20px_rgba(15,23,42,0.05)] p-stack-md flex flex-col items-center justify-center text-center space-y-stack-md">
          <div className="relative w-48 h-48 flex items-center justify-center">
            <div 
              className="absolute inset-0 rounded-full safety-gauge rotate-[-45deg]" 
              style={{ 
                background: `conic-gradient(from 180deg, #006193 0%, #006193 ${safetyScore}%, #e2e7ff ${safetyScore}%, #e2e7ff 100%)` 
              }}
            ></div>
            <div className="flex flex-col items-center">
              <span className="text-headline-xl font-headline-xl text-primary">{safetyScore}</span>
              <span className="text-label-md font-label-md text-on-secondary-container">Safety Score</span>
            </div>
          </div>
          <div className="space-y-base">
            <h3 className="text-headline-md font-headline-md">Excellent Standing</h3>
            <p className="text-body-md font-body-md text-on-secondary-container px-4">
              {stats.spam} threats detected and {stats.deleted} messages removed.
            </p>
          </div>
        </div>

        {/* Mini Stats Cards */}
        <div className="md:col-span-7 grid grid-cols-1 gap-4">
          <div className="bg-white rounded-xl p-6 shadow-[0_4px_20px_rgba(15,23,42,0.05)] flex justify-between items-center">
            <div>
              <p className="text-label-md text-on-secondary-container mb-1">Messages Tracked</p>
              <p className="text-headline-lg font-bold">
                {loading ? '...' : stats.scanned.toLocaleString()}
              </p>
            </div>
            <span className="material-symbols-outlined text-primary p-3 bg-primary-fixed rounded-xl">qr_code_scanner</span>
          </div>
          
          <div className="bg-white rounded-xl p-6 shadow-[0_4px_20px_rgba(15,23,42,0.05)] flex justify-between items-center">
            <div>
              <p className="text-label-md text-on-secondary-container mb-1">Spam Detected</p>
              <p className="text-headline-lg font-bold text-error">
                {loading ? '...' : stats.spam.toLocaleString()}
              </p>
            </div>
            <span className="material-symbols-outlined text-error p-3 bg-error-container rounded-xl">gpp_maybe</span>
          </div>

          <div className="bg-white rounded-xl p-6 shadow-[0_4px_20px_rgba(15,23,42,0.05)] flex justify-between items-center">
            <div>
              <p className="text-label-md text-on-secondary-container mb-1">Messages Deleted</p>
              <p className="text-headline-lg font-bold text-secondary">
                {loading ? '...' : stats.deleted.toLocaleString()}
              </p>
            </div>
            <span className="material-symbols-outlined text-secondary p-3 bg-secondary-fixed-dim rounded-xl">delete_sweep</span>
          </div>

          <div className="bg-white rounded-xl p-6 shadow-[0_4px_20px_rgba(15,23,42,0.05)] flex justify-between items-center">
            <div>
              <p className="text-label-md text-on-secondary-container mb-1">Active Members</p>
              <p className="text-headline-lg font-bold">
                {loading ? '...' : stats.activeMembers.toLocaleString()}
              </p>
            </div>
            <span className="material-symbols-outlined text-secondary p-3 bg-secondary-fixed rounded-xl">group</span>
          </div>
        </div>
      </div>

      {/* Recent Moderation Events */}
      <div className="bg-white rounded-xl shadow-[0_4px_20px_rgba(15,23,42,0.05)] p-stack-md">
        <div className="flex items-center justify-between mb-stack-md">
          <h3 className="text-headline-md font-headline-md">Recent Moderation Activity</h3>
          {loading && <span className="material-symbols-outlined animate-spin text-primary">progress_activity</span>}
        </div>
        {recentEvents.length === 0 ? (
          <p className="text-body-md text-on-secondary-container text-center py-8">
            {loading ? 'Loading moderation events...' : 'No moderation events recorded yet.'}
          </p>
        ) : (
          <div className="space-y-stack-sm">
            {recentEvents.map((event) => (
              <div
                key={event.id}
                className="flex items-start gap-stack-md p-stack-md rounded-lg border border-outline-variant bg-surface-container-low"
              >
                <div className="flex-shrink-0 w-10 h-10 rounded-full bg-error-container flex items-center justify-center">
                  <span className="material-symbols-outlined text-error text-lg">
                    {ACTION_ICONS[event.action_taken] || 'report'}
                  </span>
                </div>
                <div className="flex-1 min-w-0">
                  <div className="flex items-center gap-2 flex-wrap">
                    <span className="text-label-md font-label-md">
                      {event.username || 'Anonymous'}
                    </span>
                    <span className={`text-label-sm px-2 py-0.5 rounded-full ${CATEGORY_COLORS[event.category] || 'bg-gray-100 text-gray-600'}`}>
                      {CATEGORY_LABELS[event.category] || event.category}
                    </span>
                    <span className="text-label-sm text-on-secondary-container">
                      {Math.round(event.confidence * 100)}% confidence
                    </span>
                  </div>
                  {event.text_preview && (
                    <p className="text-body-md font-body-md text-on-secondary-container mt-1 truncate max-w-md">
                      {event.text_preview}
                    </p>
                  )}
                  <p className="text-label-sm text-on-secondary-container mt-1 opacity-60">
                    {formatTime(event.created_at)}
                  </p>
                </div>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  )
}
