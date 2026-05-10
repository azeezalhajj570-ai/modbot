import React from 'react'
import type { ManagedGroup } from '@miniapp/shared'

interface GroupSelectorProps {
  groups: ManagedGroup[]
  selectedGroup: ManagedGroup | null
  onSelect: (group: ManagedGroup) => void
}

export const GroupSelector: React.FC<GroupSelectorProps> = ({ groups, selectedGroup, onSelect }) => {
  return (
    <div className="bg-white rounded-xl p-4 shadow-[0_4px_20px_rgba(15,23,42,0.05)] flex items-center justify-between">
      <div className="flex items-center gap-4">
        <div className="w-12 h-12 rounded-xl bg-primary-fixed flex items-center justify-center text-primary">
          <span className="material-symbols-outlined text-3xl">group</span>
        </div>
        <div>
          <h2 className="font-headline-md text-on-surface line-clamp-1 max-w-[200px]">{selectedGroup?.title || 'Select Group'}</h2>
          <p className="font-label-sm text-on-surface-variant">Admin access verified</p>
        </div>
      </div>
      
      <div className="relative group">
        <button className="flex items-center gap-1 text-primary font-label-md px-3 py-1.5 rounded-lg bg-primary/5 hover:bg-primary/10 transition-colors">
          Switch
          <span className="material-symbols-outlined">expand_more</span>
        </button>
        
        <div className="absolute left-0 top-full mt-2 w-64 bg-white rounded-xl shadow-xl border border-slate-100 hidden group-hover:block z-[60] overflow-hidden">
          {groups.map(g => (
            <button 
              key={g.id}
              onClick={() => onSelect(g)}
              className={`w-full text-right px-4 py-3 hover:bg-slate-50 transition-colors flex items-center gap-3 ${selectedGroup?.id === g.id ? 'bg-primary/5 text-primary' : 'text-on-surface'}`}
            >
              <span className="material-symbols-outlined text-xl opacity-40">chat_bubble</span>
              <span className="flex-1 truncate">{g.title}</span>
              {selectedGroup?.id === g.id && <span className="material-symbols-outlined text-primary">check</span>}
            </button>
          ))}
        </div>
      </div>
    </div>
  )
}
