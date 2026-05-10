import React from 'react'
import type { AIModerationSettings } from '@miniapp/shared'

interface ModerationPageProps {
  settings: AIModerationSettings
  onUpdate: (settings: Partial<AIModerationSettings>) => void
}

export const ModerationPage: React.FC<ModerationPageProps> = ({ settings, onUpdate }) => {
  return (
    <div className="space-y-stack-lg pb-10">
      <div className="space-y-stack-sm">
        <h2 className="font-headline-lg text-on-surface">Smart Protection Settings</h2>
        <p className="font-body-md text-on-surface-variant">Control how AI manages your community safety.</p>
      </div>

      <section className="space-y-stack-md">
        <h3 className="font-label-md text-primary tracking-widest px-1 uppercase">AI & Safety</h3>
        <div className="bg-white rounded-xl shadow-[0_4px_20px_rgba(15,23,42,0.05)] overflow-hidden">
          <ToggleItem
            icon="security"
            title="AI Spam Detection"
            description="Automatic detection of spam and phishing"
            checked={settings.enabled}
            onChange={(val) => onUpdate({ enabled: val })}
            iconColor="bg-blue-50 text-primary"
          />
          <div className="h-[1px] bg-slate-50 mx-container-padding"></div>
          <ToggleItem
            icon="shield_person"
            title="Safe Mode"
            description="Review suspicious content instead of auto-deleting"
            checked={settings.safe_mode}
            onChange={(val) => onUpdate({ safe_mode: val })}
            iconColor="bg-purple-50 text-purple-600"
          />
          <div className="h-[1px] bg-slate-50 mx-container-padding"></div>
          <ToggleItem
            icon="science"
            title="Dry Run"
            description="Log actions without executing side effects"
            checked={settings.dry_run}
            onChange={(val) => onUpdate({ dry_run: val })}
            iconColor="bg-amber-50 text-amber-600"
          />
        </div>
      </section>

      <section className="space-y-stack-md">
        <h3 className="font-label-md text-primary tracking-widest px-1 uppercase">Thresholds</h3>
        <div className="bg-white rounded-xl shadow-[0_4px_20px_rgba(15,23,42,0.05)] p-6 space-y-8">
          <SliderItem
            title="Review Threshold"
            description="Confidence score to trigger admin review"
            value={settings.review_threshold}
            onChange={(val) => onUpdate({ review_threshold: val })}
          />
          <SliderItem
            title="Auto-Delete Threshold"
            description="Confidence score for automated removal"
            value={settings.auto_delete_threshold}
            onChange={(val) => onUpdate({ auto_delete_threshold: val })}
          />
        </div>
      </section>
    </div>
  )
}

const ToggleItem: React.FC<{
  icon: string
  title: string
  description: string
  checked: boolean
  onChange: (val: boolean) => void
  iconColor: string
}> = ({ icon, title, description, checked, onChange, iconColor }) => (
  <div className="flex items-center justify-between p-6 hover:bg-slate-50 transition-colors">
    <div className="flex items-center gap-4">
      <div className={`w-10 h-10 rounded-lg flex items-center justify-center ${iconColor}`}>
        <span className="material-symbols-outlined">{icon}</span>
      </div>
      <div>
        <p className="font-headline-md text-on-surface">{title}</p>
        <p className="font-body-md text-on-surface-variant max-w-[200px] leading-tight">{description}</p>
      </div>
    </div>
    <label className="relative inline-flex items-center cursor-pointer">
      <input 
        type="checkbox" 
        className="sr-only peer" 
        checked={checked} 
        onChange={(e) => onChange(e.target.checked)} 
      />
      <div className="w-11 h-6 bg-slate-200 peer-focus:outline-none rounded-full peer peer-checked:after:-translate-x-full rtl:peer-checked:after:-translate-x-full peer-checked:after:border-white after:content-[''] after:absolute after:top-[2px] after:right-[2px] after:bg-white after:border-gray-300 after:border after:rounded-full after:h-5 after:w-5 after:transition-all peer-checked:bg-primary"></div>
    </label>
  </div>
)

const SliderItem: React.FC<{
  title: string
  description: string
  value: number
  onChange: (val: number) => void
}> = ({ title, description, value, onChange }) => (
  <div className="space-y-4">
    <div className="flex justify-between items-end">
      <div>
        <p className="font-headline-md text-on-surface">{title}</p>
        <p className="font-body-md text-on-surface-variant">{description}</p>
      </div>
      <span className="font-headline-lg text-primary">{Math.round(value * 100)}%</span>
    </div>
    <input
      type="range"
      min="0"
      max="1"
      step="0.01"
      value={value}
      onChange={(e) => onChange(parseFloat(e.target.value))}
      className="w-full h-1.5 bg-slate-100 rounded-lg appearance-none cursor-pointer accent-primary"
    />
  </div>
)
