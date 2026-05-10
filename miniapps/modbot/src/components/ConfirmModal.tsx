import React from 'react'
import { useLang } from './LanguageContext'

interface ConfirmModalProps {
  open: boolean
  title: string
  message: string
  confirmLabel?: string
  cancelLabel?: string
  danger?: boolean
  onConfirm: () => void
  onCancel: () => void
}

export const ConfirmModal: React.FC<ConfirmModalProps> = ({
  open, title, message, confirmLabel = 'Confirm', cancelLabel = 'Cancel',
  danger, onConfirm, onCancel,
}) => {
  const { dir, lang } = useLang()
  if (!open) return null

  return (
    <div dir={dir} className="fixed inset-0 z-[250] flex items-center justify-center p-4" style={{ fontFamily: lang === 'ar' ? "'Noto Kufi Arabic', sans-serif" : 'inherit' }}>
      <div className="absolute inset-0 bg-black/30 backdrop-blur-sm" onClick={onCancel} />
      <div className="relative bg-white rounded-2xl w-full max-w-sm shadow-2xl p-6">
        <div className="flex flex-col items-center text-center gap-3 mb-6">
          <div className={`w-12 h-12 rounded-full flex items-center justify-center ${danger ? 'bg-red-50' : 'bg-slate-50'}`}>
            <span className={`material-symbols-outlined text-2xl ${danger ? 'text-red-500' : 'text-slate-500'}`}>
              {danger ? 'delete' : 'help'}
            </span>
          </div>
          <h3 className="font-headline-md text-on-surface">{title}</h3>
          <p className="font-body-md text-on-surface-variant">{message}</p>
        </div>
        <div className="flex gap-3">
          <button onClick={onCancel} className="flex-1 bg-slate-100 text-on-surface py-2.5 rounded-lg font-label-md transition-all active:scale-95">
            {cancelLabel}
          </button>
          <button
            onClick={onConfirm}
            className={`flex-1 py-2.5 rounded-lg font-label-md transition-all active:scale-95 ${
              danger ? 'bg-red-600 text-white hover:bg-red-700' : 'bg-primary text-white'
            }`}
          >
            {confirmLabel}
          </button>
        </div>
      </div>
    </div>
  )
}
