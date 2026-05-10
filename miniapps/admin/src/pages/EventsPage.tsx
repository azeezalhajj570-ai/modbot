import React from 'react'
import type { AIModerationEvent } from '@miniapp/shared'

interface EventsPageProps {
  events: AIModerationEvent[]
  onAction: (eventId: number, action: 'approve' | 'delete' | 'warn' | 'mute' | 'ban') => void
  actionLoading?: number | null
}

export const EventsPage: React.FC<EventsPageProps> = ({ events, onAction, actionLoading }) => {
  return (
    <div className="space-y-stack-lg pb-10">
      <div className="space-y-stack-sm">
        <h2 className="font-headline-lg text-on-surface">Moderation Alerts</h2>
        <p className="font-body-md text-on-surface-variant">Review flagged messages and improve community safety.</p>
      </div>

      <div className="space-y-stack-md">
        {events.length === 0 ? (
          <div className="bg-white rounded-xl p-10 text-center space-y-4 shadow-[0_4px_20px_rgba(15,23,42,0.05)]">
            <span className="material-symbols-outlined text-6xl text-slate-200">check_circle</span>
            <p className="text-on-secondary-container font-medium">All clear! No flagged messages to review.</p>
          </div>
        ) : (
          events.map((event) => (
            <div key={event.id} className="bg-white rounded-xl shadow-[0_4px_20px_rgba(15,23,42,0.05)] p-5 flex flex-col gap-4 border border-slate-50">
              <div className="flex items-center justify-between">
                <div className="flex items-center gap-3">
                  <div className="w-10 h-10 rounded-full bg-slate-100 flex items-center justify-center text-slate-400">
                    <span className="material-symbols-outlined">person</span>
                  </div>
                  <div>
                    <p className="font-label-md text-on-surface">{event.username || 'Anonymous'}</p>
                    <p className="font-label-sm text-on-surface-variant">{new Date(event.created_at).toLocaleTimeString()}</p>
                  </div>
                </div>
                <span className={`px-3 py-1 rounded-full font-label-sm ${getCategoryStyle(event.category)}`}>
                  {event.category.replace('_', ' ')}
                </span>
              </div>
              
              <div className="px-1">
                <p className="font-body-md text-on-surface leading-relaxed italic border-r-4 border-slate-100 pr-3 py-1">
                  "{event.text_preview}"
                </p>
                <div className="mt-2 flex gap-2 overflow-x-auto pb-1">
                  {event.matched_signals.map((signal, idx) => (
                    <span key={idx} className="bg-slate-50 text-slate-500 text-[10px] px-2 py-0.5 rounded border border-slate-100 whitespace-nowrap">
                      {signal}
                    </span>
                  ))}
                  <span className="bg-primary-fixed text-primary text-[10px] px-2 py-0.5 rounded border border-primary/10 whitespace-nowrap">
                    Confidence: {Math.round(event.confidence * 100)}%
                  </span>
                </div>
              </div>

              <div className="flex items-center gap-3 pt-2">
                <button 
                  onClick={() => onAction(event.id, 'approve')}
                  disabled={actionLoading === event.id}
                  className="flex-1 bg-primary text-white py-2.5 rounded-lg font-label-md transition-all active:scale-95 disabled:opacity-50"
                >
                  {actionLoading === event.id ? '...' : 'Approve'}
                </button>
                <button 
                  onClick={() => onAction(event.id, 'delete')}
                  disabled={actionLoading === event.id}
                  className="flex-1 bg-surface-container-low text-error py-2.5 rounded-lg font-label-md transition-all active:scale-95 hover:bg-error-container/20 disabled:opacity-50"
                >
                  {actionLoading === event.id ? '...' : 'Delete'}
                </button>
              </div>
            </div>
          ))
        )}
      </div>
    </div>
  )
}

function getCategoryStyle(category: string): string {
  switch (category) {
    case 'arabic_ad': return 'bg-blue-50 text-blue-600'
    case 'investment_scam': return 'bg-amber-50 text-amber-600'
    case 'crypto_scam': return 'bg-purple-50 text-purple-600'
    case 'phishing_link': return 'bg-error-container text-error'
    default: return 'bg-slate-50 text-slate-600'
  }
}
