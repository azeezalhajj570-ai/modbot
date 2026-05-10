import React, { useState, useRef, useEffect } from 'react'
import type { ManagedGroup } from '@miniapp/shared'
import { useLang } from './LanguageContext'

interface GroupSelectorProps {
  groups: ManagedGroup[]
  selectedGroup: ManagedGroup | null
  onSelect: (group: ManagedGroup) => void
}

export const GroupSelector: React.FC<GroupSelectorProps> = ({ groups, selectedGroup, onSelect }) => {
  const { t, lang } = useLang()
  const [open, setOpen] = useState(false)
  const containerRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    const handleClickOutside = (e: MouseEvent) => {
      if (containerRef.current && !containerRef.current.contains(e.target as Node)) {
        setOpen(false)
      }
    }
    document.addEventListener('mousedown', handleClickOutside)
    return () => document.removeEventListener('mousedown', handleClickOutside)
  }, [])

  return (
    <div className="bg-white rounded-xl p-4 shadow-[0_4px_20px_rgba(15,23,42,0.05)] flex items-center justify-between" style={{ fontFamily: lang === 'ar' ? "'Noto Kufi Arabic', sans-serif" : 'inherit' }}>
      <div className="flex items-center gap-4">
        <div className="w-12 h-12 rounded-xl bg-primary-fixed flex items-center justify-center text-primary">
          <span className="material-symbols-outlined text-3xl">forum</span>
        </div>
        <div>
          <h2 className="font-headline-md text-on-surface line-clamp-1 max-w-[200px]">{selectedGroup?.title || t('group.select')}</h2>
          <p className="font-label-sm text-on-surface-variant font-mono">ID: {selectedGroup?.tg_group_id}</p>
        </div>
      </div>

      <div className="relative" ref={containerRef}>
        <button
          onClick={() => setOpen(prev => !prev)}
          className="flex items-center gap-1 text-primary font-label-md px-3 py-1.5 rounded-lg bg-primary/5 hover:bg-primary/10 transition-colors"
        >
          {t('group.switch')}
          <span className="material-symbols-outlined">expand_more</span>
        </button>

        <div className={`absolute ${lang === 'ar' ? 'left-0' : 'right-0'} md:left-0 top-full mt-2 w-64 bg-white rounded-xl shadow-xl border border-slate-100 z-[60] overflow-hidden ${open ? 'block' : 'hidden'}`}>
          {groups.map(g => (
            <button
              key={g.id}
              onClick={() => { onSelect(g); setOpen(false) }}
              className={`w-full text-right px-4 py-3 hover:bg-slate-50 transition-colors flex items-center gap-3 ${selectedGroup?.id === g.id ? 'bg-primary/5 text-primary' : 'text-on-surface'}`}
            >
              <span className="material-symbols-outlined text-xl opacity-40">chat_bubble</span>
              <div className="flex-1 min-w-0">
                <span className="block truncate">{g.title}</span>
                <span className="block text-xs text-on-surface-variant/60 truncate font-mono">ID: {g.tg_group_id}</span>
              </div>
              {selectedGroup?.id === g.id && <span className="material-symbols-outlined text-primary">check</span>}
            </button>
          ))}
        </div>
      </div>
    </div>
  )
}
