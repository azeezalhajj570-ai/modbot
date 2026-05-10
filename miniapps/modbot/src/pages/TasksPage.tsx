import React, { useState } from 'react'
import type { AutomationTask, ScheduledMessage } from '@miniapp/shared'
import { ConfirmModal } from '../components/ConfirmModal'
import { useLang } from '../components/LanguageContext'

interface InlineButtonDraft {
  text: string
  url: string
}

interface TasksPageProps {
  tasks: AutomationTask[]
  scheduledMessages: ScheduledMessage[]
  onCreateTask: (payload: {
    task_key: string
    enabled?: boolean
    conditions?: Record<string, unknown>
    config?: Record<string, unknown>
  }) => void
  onUpdateTask: (assignmentId: string, payload: Record<string, unknown>) => void
  onDeleteTask: (assignmentId: string) => void
  onCreateScheduledMessage: (payload: {
    text: string
    schedule: string
    delete_after_seconds?: number
  }) => void
  onUpdateScheduledMessage: (entryId: string, payload: Record<string, unknown>) => void
  onDeleteScheduledMessage: (entryId: string) => void
  onSendNowScheduledMessage?: (entryId: string) => void
  loading?: boolean
}

function formatDate(iso: string): string {
  try {
    const d = new Date(iso + 'Z')
    if (isNaN(d.getTime())) return iso
    return d.toLocaleString(undefined, { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' })
  } catch { return iso }
}

export const TasksPage: React.FC<TasksPageProps> = ({
  tasks, scheduledMessages,
  onCreateTask, onUpdateTask, onDeleteTask,
  onCreateScheduledMessage, onUpdateScheduledMessage, onDeleteScheduledMessage,
  onSendNowScheduledMessage,
  loading,
}) => {
  const { t, lang } = useLang()
  const [expandedTask, setExpandedTask] = useState<string | null>(null)
  const [expandedScheduled, setExpandedScheduled] = useState<string | null>(null)

  const [showSchedForm, setShowSchedForm] = useState(false)
  const [editingSched, setEditingSched] = useState<ScheduledMessage | null>(null)
  const [schedText, setSchedText] = useState('')
  const [schedType, setSchedType] = useState<'onetime' | 'recurring'>('onetime')
  const [schedDatetime, setSchedDatetime] = useState('')
  const [schedCronPreset, setSchedCronPreset] = useState('0 9 * * *')
  const [schedCronCustom, setSchedCronCustom] = useState('')
  const [schedDeleteAfter, setSchedDeleteAfter] = useState('')

  const [showTaskForm, setShowTaskForm] = useState(false)
  const [editingTask, setEditingTask] = useState<AutomationTask | null>(null)
  const [taskKey, setTaskKey] = useState('reply_message')
  const [taskEnabled, setTaskEnabled] = useState(true)
  const [taskKeyword, setTaskKeyword] = useState('')
  const [taskTemplate, setTaskTemplate] = useState('')
  const [taskDestination, setTaskDestination] = useState('')
  const [taskDeliveryMode, setTaskDeliveryMode] = useState('text')
  const [taskDeleteAfter, setTaskDeleteAfter] = useState('')
  const [taskInlineButtons, setTaskInlineButtons] = useState<InlineButtonDraft[]>([])
  const [confirmDelete, setConfirmDelete] = useState<{
    type: 'scheduled' | 'task'
    id: string
  } | null>(null)

  const openNewSchedForm = () => {
    setEditingSched(null)
    setSchedText('')
    setSchedType('onetime')
    setSchedDatetime('')
    setSchedCronPreset('0 9 * * *')
    setSchedCronCustom('')
    setSchedDeleteAfter('')
    setShowSchedForm(true)
  }

  const openEditSchedForm = (msg: ScheduledMessage) => {
    setEditingSched(msg)
    setSchedText(msg.text)
    if (msg.cron) {
      setSchedType('recurring')
      setSchedCronPreset(msg.cron)
      setSchedCronCustom('')
      setSchedDatetime('')
    } else {
      setSchedType('onetime')
      const d = new Date(msg.send_at + 'Z')
      const localStr = `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}T${String(d.getHours()).padStart(2, '0')}:${String(d.getMinutes()).padStart(2, '0')}`
      setSchedDatetime(localStr)
      setSchedCronPreset('0 9 * * *')
      setSchedCronCustom('')
    }
    setSchedDeleteAfter(msg.delete_after_seconds ? String(msg.delete_after_seconds) : '')
    setShowSchedForm(true)
  }

  const submitSchedForm = () => {
    if (!schedText.trim()) return
    let schedule: string
    if (schedType === 'recurring') {
      schedule = schedCronCustom.trim() || schedCronPreset
    } else {
      const raw = schedDatetime.trim()
      if (raw) {
        const d = new Date(raw)
        schedule = `${d.getUTCFullYear()}-${String(d.getUTCMonth() + 1).padStart(2, '0')}-${String(d.getUTCDate()).padStart(2, '0')} ${String(d.getUTCHours()).padStart(2, '0')}:${String(d.getUTCMinutes()).padStart(2, '0')}`
      } else {
        schedule = new Date().toISOString().replace('T', ' ').slice(0, 16)
      }
    }
    const payload = {
      text: schedText.trim(),
      schedule,
      ...(schedDeleteAfter ? { delete_after_seconds: parseInt(schedDeleteAfter) || 0 } : {}),
    }
    if (editingSched) {
      onUpdateScheduledMessage(editingSched.id, payload)
    } else {
      onCreateScheduledMessage(payload)
    }
    setShowSchedForm(false)
    setEditingSched(null)
  }

  const openNewTaskForm = () => {
    setEditingTask(null)
    setTaskKey('reply_message')
    setTaskEnabled(true)
    setTaskKeyword('')
    setTaskTemplate('')
    setTaskDestination('')
    setTaskDeliveryMode('text')
    setTaskDeleteAfter('')
    setTaskInlineButtons([])
    setShowTaskForm(true)
  }

  const openEditTaskForm = (task: AutomationTask) => {
    setEditingTask(task)
    setTaskKey(task.task_key)
    setTaskEnabled(task.enabled)
    setTaskKeyword((task.conditions?.text_contains as string) || '')
    setTaskDestination((task.config?.destination as string) || '')
    setTaskDeliveryMode((task.config?.delivery_mode as string) || 'text')
    setTaskTemplate((task.config?.message_template as string) || '')
    setTaskDeleteAfter(task.config?.delete_after_seconds ? String(task.config.delete_after_seconds) : '')
    setTaskInlineButtons(Array.isArray(task.config?.inline_buttons) ? task.config.inline_buttons as InlineButtonDraft[] : [])
    setShowTaskForm(true)
  }

  const submitTaskForm = () => {
    if (!taskKey.trim()) return
    const conditions: Record<string, unknown> = {}
    if (taskKeyword.trim()) conditions.text_contains = taskKeyword.trim()

    const config: Record<string, unknown> = {}
    if (taskTemplate.trim()) config.message_template = taskTemplate.trim()
    if (taskDeleteAfter) config.delete_after_seconds = parseInt(taskDeleteAfter) || 0
    if (taskKey === 'notify_destination') {
      if (taskDestination.trim()) config.destination = taskDestination.trim()
      config.delivery_mode = taskDeliveryMode
    }
    if (taskInlineButtons.length > 0) {
      config.inline_buttons = taskInlineButtons.filter(b => b.text.trim() && b.url.trim())
    }

    if (editingTask) {
      onUpdateTask(editingTask.assignment_id, {
        task_key: taskKey.trim(),
        executor_type: editingTask.executor_type,
        enabled: taskEnabled,
        conditions,
        config,
      })
    } else {
      onCreateTask({
        task_key: taskKey.trim(),
        enabled: taskEnabled,
        conditions,
        config,
      })
    }
    setShowTaskForm(false)
    setEditingTask(null)
  }

  return (
    <div className="space-y-stack-lg pb-10" style={{ fontFamily: lang === 'ar' ? "'Noto Kufi Arabic', sans-serif" : 'inherit' }}>
      <div className="space-y-stack-sm">
        <h2 className="font-headline-lg text-on-surface">{t('tasks.title')}</h2>
        <p className="font-body-md text-on-surface-variant">{t('tasks.subtitle')}</p>
      </div>

      {/* Scheduled Messages */}
      <section className="space-y-stack-md">
        <div className="flex items-center justify-between">
          <h3 className="font-label-md text-primary tracking-widest px-1 uppercase">{t('tasks.scheduled')}</h3>
          <button
            onClick={openNewSchedForm}
            className="flex items-center gap-1 text-primary font-label-md px-3 py-1.5 rounded-lg bg-primary/5 hover:bg-primary/10 transition-colors"
          >
            <span className="material-symbols-outlined text-lg">add</span>
            {t('tasks.new_msg')}
          </button>
        </div>

        {loading && scheduledMessages.length === 0 ? (
          <div className="bg-white rounded-xl p-10 text-center space-y-4 shadow-[0_4px_20px_rgba(15,23,42,0.05)]">
            <span className="material-symbols-outlined text-6xl text-slate-200 animate-pulse">schedule</span>
            <p className="text-on-secondary-container font-medium">{t('tasks.loading_sched')}</p>
          </div>
        ) : scheduledMessages.length === 0 ? (
          <div className="bg-white rounded-xl p-10 text-center space-y-4 shadow-[0_4px_20px_rgba(15,23,42,0.05)]">
            <span className="material-symbols-outlined text-6xl text-slate-200">schedule</span>
            <p className="text-on-secondary-container font-medium">{t('tasks.no_sched')}</p>
            <p className="text-body-md text-on-surface-variant">{t('tasks.no_sched_desc')}</p>
          </div>
        ) : (
          <div className="space-y-stack-md">
            {scheduledMessages.map(msg => (
              <div key={msg.id} className="bg-white rounded-xl shadow-[0_4px_20px_rgba(15,23,42,0.05)] overflow-hidden">
                <button
                  onClick={() => setExpandedScheduled(expandedScheduled === msg.id ? null : msg.id)}
                  className="w-full p-5 flex items-center justify-between hover:bg-slate-50 transition-colors"
                >
                  <div className="flex items-center gap-4">
                    <div className="w-10 h-10 rounded-lg bg-amber-50 flex items-center justify-center text-amber-600">
                      <span className="material-symbols-outlined">schedule_send</span>
                    </div>
                    <div className="text-right">
                      <p className="font-headline-md text-on-surface line-clamp-1 max-w-[220px]">{msg.text}</p>
                      <p className="font-label-sm text-on-surface-variant">
                        {formatDate(msg.send_at)} {msg.delete_after_seconds ? `· Auto-delete ${msg.delete_after_seconds}s` : ''}
                      </p>
                    </div>
                  </div>
                  <span className="material-symbols-outlined text-slate-400">
                    {expandedScheduled === msg.id ? 'expand_less' : 'expand_more'}
                  </span>
                </button>

                {expandedScheduled === msg.id && (
                  <div className="px-5 pb-5 space-y-4 border-t border-slate-50 pt-4">
                    <div className="bg-slate-50 rounded-lg p-4">
                      <p className="font-label-sm text-on-surface-variant mb-2">Message Text</p>
                      <p className="font-body-md text-on-surface whitespace-pre-wrap">{msg.text}</p>
                    </div>
                      <div className="grid grid-cols-2 gap-4">
                        <div className="bg-slate-50 rounded-lg p-3">
                          <p className="font-label-sm text-on-surface-variant">Type</p>
                          <p className="font-body-md text-on-surface">{msg.cron ? `Recurring (${msg.cron})` : 'One-time'}</p>
                        </div>
                        <div className="bg-slate-50 rounded-lg p-3">
                          <p className="font-label-sm text-on-surface-variant">Send At</p>
                          <p className="font-body-md text-on-surface">{formatDate(msg.send_at)}</p>
                        </div>
                      </div>
                    <div className="flex gap-3 pt-2">
                      <button
                        onClick={() => openEditSchedForm(msg)}
                        className="flex-1 bg-primary-fixed text-primary py-2.5 rounded-lg font-label-md transition-all active:scale-95 hover:bg-primary/10"
                      >
                        <span className="material-symbols-outlined text-sm align-middle ml-1">edit</span>
                        {t('tasks.edit')}
                      </button>
                      {onSendNowScheduledMessage && (
                        <button
                          onClick={() => onSendNowScheduledMessage(msg.id)}
                          className="flex-1 bg-green-50 text-green-600 py-2.5 rounded-lg font-label-md transition-all active:scale-95 hover:bg-green-100"
                        >
                          <span className="material-symbols-outlined text-sm align-middle ml-1">send</span>
                          Send Now
                        </button>
                      )}
                      <button
                        onClick={() => setConfirmDelete({ type: 'scheduled', id: msg.id })}
                        className="flex-1 bg-red-50 text-error py-2.5 rounded-lg font-label-md transition-all active:scale-95 hover:bg-red-100"
                      >
                        <span className="material-symbols-outlined text-sm align-middle ml-1">delete</span>
                        {t('tasks.cancel')}
                      </button>
                    </div>
                  </div>
                )}
              </div>
            ))}
          </div>
        )}
      </section>

      {/* Automation Tasks */}
      <section className="space-y-stack-md">
        <div className="flex items-center justify-between">
          <h3 className="font-label-md text-primary tracking-widest px-1 uppercase">{t('tasks.automation')}</h3>
          <button
            onClick={openNewTaskForm}
            className="flex items-center gap-1 text-primary font-label-md px-3 py-1.5 rounded-lg bg-primary/5 hover:bg-primary/10 transition-colors"
          >
            <span className="material-symbols-outlined text-lg">add</span>
            {t('tasks.new_task')}
          </button>
        </div>

        {loading && tasks.length === 0 ? (
          <div className="bg-white rounded-xl p-10 text-center space-y-4 shadow-[0_4px_20px_rgba(15,23,42,0.05)]">
            <span className="material-symbols-outlined text-6xl text-slate-200 animate-pulse">assignment</span>
            <p className="text-on-secondary-container font-medium">{t('tasks.loading_tasks')}</p>
          </div>
        ) : tasks.length === 0 ? (
          <div className="bg-white rounded-xl p-10 text-center space-y-4 shadow-[0_4px_20px_rgba(15,23,42,0.05)]">
            <span className="material-symbols-outlined text-6xl text-slate-200">assignment</span>
            <p className="text-on-secondary-container font-medium">{t('tasks.no_tasks')}</p>
            <p className="text-body-md text-on-surface-variant">{t('tasks.no_tasks_desc')}</p>
          </div>
        ) : (
          <div className="space-y-stack-md">
            {tasks.map(task => (
              <div key={task.assignment_id} className="bg-white rounded-xl shadow-[0_4px_20px_rgba(15,23,42,0.05)] overflow-hidden">
                <button
                  onClick={() => setExpandedTask(expandedTask === task.assignment_id ? null : task.assignment_id)}
                  className="w-full p-5 flex items-center justify-between hover:bg-slate-50 transition-colors"
                >
                  <div className="flex items-center gap-4">
                    <div className={`w-10 h-10 rounded-lg flex items-center justify-center ${
                      task.enabled ? 'bg-green-50 text-green-600' : 'bg-slate-50 text-slate-400'
                    }`}>
                      <span className="material-symbols-outlined">
                        {task.enabled ? 'play_circle' : 'pause_circle'}
                      </span>
                    </div>
                    <div className="text-right">
                      <p className="font-headline-md text-on-surface">{task.task_key}</p>
                      <p className="font-label-sm text-on-surface-variant">
                        {task.executor_type} ·                         {task.enabled ? t('tasks.active') : t('tasks.paused')}
                        {task.group_titles?.length ? ` · ${task.group_titles.join(', ')}` : ''}
                      </p>
                    </div>
                  </div>
                  <div className="flex items-center gap-2">
                    <span className={`w-2 h-2 rounded-full ${task.enabled ? 'bg-green-500' : 'bg-slate-300'}`} />
                    <span className="material-symbols-outlined text-slate-400">
                      {expandedTask === task.assignment_id ? 'expand_less' : 'expand_more'}
                    </span>
                  </div>
                </button>

                {expandedTask === task.assignment_id && (
                  <div className="px-5 pb-5 space-y-4 border-t border-slate-50 pt-4">
                    {Object.keys(task.conditions).length > 0 && (
                      <div>
                        <p className="font-label-sm text-on-surface-variant mb-2">{t('tasks.conditions')}</p>
                        <pre className="bg-slate-50 rounded-lg p-3 text-xs font-mono text-on-surface overflow-x-auto">
                          {JSON.stringify(task.conditions, null, 2)}
                        </pre>
                      </div>
                    )}
                    {Object.keys(task.config).length > 0 && (
                      <div>
                        <p className="font-label-sm text-on-surface-variant mb-2">{t('tasks.config')}</p>
                        <pre className="bg-slate-50 rounded-lg p-3 text-xs font-mono text-on-surface overflow-x-auto">
                          {JSON.stringify(task.config, null, 2)}
                        </pre>
                      </div>
                    )}
                    <div className="flex gap-3 pt-2">
                      <button
                        onClick={() => {
                          onUpdateTask(task.assignment_id, {
                            task_key: task.task_key,
                            executor_type: task.executor_type,
                            enabled: !task.enabled,
                          })
                        }}
                        className={`flex-1 py-2.5 rounded-lg font-label-md transition-all active:scale-95 ${
                          task.enabled
                            ? 'bg-amber-50 text-amber-600 hover:bg-amber-100'
                            : 'bg-green-50 text-green-600 hover:bg-green-100'
                        }`}
                      >
                        <span className="material-symbols-outlined text-sm align-middle ml-1">
                          {task.enabled ? 'pause' : 'play_arrow'}
                        </span>
                        {task.enabled ? t('tasks.pause') : t('tasks.resume')}
                      </button>
                      <button
                        onClick={() => openEditTaskForm(task)}
                        className="flex-1 bg-primary-fixed text-primary py-2.5 rounded-lg font-label-md transition-all active:scale-95 hover:bg-primary/10"
                      >
                        <span className="material-symbols-outlined text-sm align-middle ml-1">edit</span>
                        {t('tasks.edit')}
                      </button>
                      <button
                        onClick={() => setConfirmDelete({ type: 'task', id: task.assignment_id })}
                        className="flex-1 bg-red-50 text-error py-2.5 rounded-lg font-label-md transition-all active:scale-95 hover:bg-red-100"
                      >
                        <span className="material-symbols-outlined text-sm align-middle ml-1">delete</span>
                        {t('tasks.delete')}
                      </button>
                    </div>
                  </div>
                )}
              </div>
            ))}
          </div>
        )}
      </section>

      {/* Scheduled Message Form Modal */}
      {showSchedForm && (
        <Modal onClose={() => setShowSchedForm(false)} title={editingSched ? t('sched_form.title_edit') : t('sched_form.title_new')}>
          <div className="space-y-4">
            <div>
              <label className="font-label-sm text-on-surface-variant block mb-1">{t('sched_form.msg_text')}</label>
              <textarea
                value={schedText}
                onChange={e => setSchedText(e.target.value)}
                rows={4}
                className="w-full px-3 py-2 rounded-lg border border-slate-200 bg-white text-sm font-body-md text-on-surface focus:outline-none focus:ring-2 focus:ring-primary/20 resize-vertical"
                placeholder="Enter the message text to send..."
              />
            </div>

            <div>
              <label className="font-label-sm text-on-surface-variant block mb-2">{t('sched_form.sched_type')}</label>
              <div className="flex gap-2">
                <button
                  type="button"
                  onClick={() => setSchedType('onetime')}
                  className={`flex-1 py-2 rounded-lg font-label-md transition-all ${
                    schedType === 'onetime'
                      ? 'bg-primary text-white'
                      : 'bg-slate-100 text-on-surface-variant hover:bg-slate-200'
                  }`}
                >
                  {lang === 'ar' ? 'مرة واحدة' : 'One-time'}
                </button>
                <button
                  type="button"
                  onClick={() => setSchedType('recurring')}
                  className={`flex-1 py-2 rounded-lg font-label-md transition-all ${
                    schedType === 'recurring'
                      ? 'bg-primary text-white'
                      : 'bg-slate-100 text-on-surface-variant hover:bg-slate-200'
                  }`}
                >
                  {lang === 'ar' ? 'متكرر' : 'Recurring'}
                </button>
              </div>
            </div>

            {schedType === 'onetime' ? (
              <div>
                <label className="font-label-sm text-on-surface-variant block mb-1">{t('sched_form.send_dt')}</label>
                <input
                  type="datetime-local"
                  value={schedDatetime}
                  onChange={e => setSchedDatetime(e.target.value)}
                  className="w-full px-3 py-2 rounded-lg border border-slate-200 bg-white text-sm font-body-md text-on-surface focus:outline-none focus:ring-2 focus:ring-primary/20"
                />
                <p className="text-label-sm text-on-surface-variant mt-1">{t('sched_form.send_dt_desc')}</p>
              </div>
            ) : (
              <div>
                <label className="font-label-sm text-on-surface-variant block mb-2">{t('sched_form.recurring_sched')}</label>
                <div className="grid grid-cols-2 gap-2 mb-3">
                  {[
                    { label: t('sched_form.daily_9'), value: '0 9 * * *' },
                    { label: t('sched_form.daily_12'), value: '0 12 * * *' },
                    { label: t('sched_form.daily_18'), value: '0 18 * * *' },
                    { label: t('sched_form.weekdays'), value: '0 9 * * 1-5' },
                    { label: t('sched_form.weekly'), value: '0 9 * * 1' },
                    { label: t('sched_form.monthly'), value: '0 9 1 * *' },
                  ].map(preset => (
                    <button
                      key={preset.value}
                      type="button"
                      onClick={() => { setSchedCronPreset(preset.value); setSchedCronCustom('') }}
                      className={`py-2 px-3 rounded-lg text-xs font-label-md transition-all text-left ${
                        schedCronPreset === preset.value && !schedCronCustom
                          ? 'bg-primary/10 text-primary border border-primary/30'
                          : 'bg-slate-50 text-on-surface-variant border border-slate-100 hover:bg-slate-100'
                      }`}
                    >
                      {preset.label}
                    </button>
                  ))}
                </div>
                <div>
                  <label className="font-label-sm text-on-surface-variant block mb-1">{t('sched_form.custom_cron')}</label>
                  <input
                    value={schedCronCustom}
                    onChange={e => { setSchedCronCustom(e.target.value); setSchedCronPreset('') }}
                    className="w-full px-3 py-2 rounded-lg border border-slate-200 bg-white text-sm font-mono text-on-surface focus:outline-none focus:ring-2 focus:ring-primary/20"
                    placeholder="*/5 9-17 * * 1-5"
                  />
                  <p className="text-label-sm text-on-surface-variant mt-1">{t('sched_form.cron_hint')}</p>
                </div>
              </div>
            )}

            <div>
              <label className="font-label-sm text-on-surface-variant block mb-1">{t('sched_form.auto_delete')}</label>
              <input
                type="number"
                value={schedDeleteAfter}
                onChange={e => setSchedDeleteAfter(e.target.value)}
                className="w-full px-3 py-2 rounded-lg border border-slate-200 bg-white text-sm font-body-md text-on-surface focus:outline-none focus:ring-2 focus:ring-primary/20"
                placeholder="e.g. 3600"
                min="0"
              />
            </div>

            <div className="flex gap-3 pt-2">
              <button onClick={() => setShowSchedForm(false)} className="flex-1 bg-slate-100 text-on-surface py-2.5 rounded-lg font-label-md transition-all active:scale-95">
                {t('sched_form.cancel')}
              </button>
              <button
                onClick={submitSchedForm}
                disabled={!schedText.trim()}
                className="flex-1 bg-primary text-white py-2.5 rounded-lg font-label-md transition-all active:scale-95 disabled:opacity-50"
              >
                {editingSched ? t('sched_form.save') : t('sched_form.create')}
              </button>
            </div>
          </div>
        </Modal>
      )}

      {/* Task Form Modal */}
      {showTaskForm && (
        <Modal onClose={() => setShowTaskForm(false)} title={editingTask ? t('task_form.title_edit') : t('task_form.title_new')}>
          <div className="space-y-4">
            <div>
              <label className="font-label-sm text-on-surface-variant block mb-1">{t('task_form.task_type')}</label>
              <select
                value={taskKey}
                onChange={e => setTaskKey(e.target.value)}
                className="w-full px-3 py-2 rounded-lg border border-slate-200 bg-white text-sm font-body-md text-on-surface focus:outline-none focus:ring-2 focus:ring-primary/20"
              >
                <option value="reply_message">{t('task_form.reply_msg')}</option>
                <option value="notify_destination">{t('task_form.notify_dest')}</option>
                <option value="welcome_flow">{t('task_form.welcome')}</option>
                <option value="lead_capture">{t('task_form.lead')}</option>
                <option value="escalation_alert">{t('task_form.escalation')}</option>
              </select>
            </div>

            <div className="flex items-center gap-3">
              <label className="relative inline-flex items-center cursor-pointer">
                <input type="checkbox" className="sr-only peer" checked={taskEnabled} onChange={e => setTaskEnabled(e.target.checked)} />
                <div className="w-11 h-6 bg-slate-200 peer-focus:outline-none rounded-full peer peer-checked:after:-translate-x-full rtl:peer-checked:after:-translate-x-full peer-checked:after:border-white after:content-[''] after:absolute after:top-[2px] after:right-[2px] after:bg-white after:border-gray-300 after:border after:rounded-full after:h-5 after:w-5 after:transition-all peer-checked:bg-primary" />
              </label>
              <span className="font-body-md text-on-surface">{t('task_form.enabled')}</span>
            </div>

            <div>
              <label className="font-label-sm text-on-surface-variant block mb-1">{t('task_form.keyword')}</label>
              <input
                value={taskKeyword}
                onChange={e => setTaskKeyword(e.target.value)}
                className="w-full px-3 py-2 rounded-lg border border-slate-200 bg-white text-sm font-body-md text-on-surface focus:outline-none focus:ring-2 focus:ring-primary/20"
                placeholder={t('task_form.keyword_placeholder')}
              />
              <p className="text-label-sm text-on-surface-variant mt-1">{t('task_form.keyword_desc')}</p>
            </div>

            <div>
              <label className="font-label-sm text-on-surface-variant block mb-1">{t('task_form.template')}</label>
              <textarea
                value={taskTemplate}
                onChange={e => setTaskTemplate(e.target.value)}
                rows={3}
                className="w-full px-3 py-2 rounded-lg border border-slate-200 bg-white text-sm font-body-md text-on-surface focus:outline-none focus:ring-2 focus:ring-primary/20 resize-vertical"
                placeholder={taskKey === 'notify_destination' ? 'Notify: {text}' : 'We will reply shortly.'}
              />
              <p className="text-label-sm text-on-surface-variant mt-1">{t('task_form.template_hint')}</p>
            </div>

            {/* Inline buttons (reply_message only) */}
            {taskKey === 'reply_message' && (
              <div>
                <div className="flex items-center justify-between mb-2">
                  <label className="font-label-sm text-on-surface-variant">{t('task_form.inline_buttons')}</label>
                  <button
                    type="button"
                    onClick={() => setTaskInlineButtons(prev => [...prev, { text: '', url: '' }])}
                    className="text-primary font-label-md hover:underline"
                  >
                    {t('task_form.add_button')}
                  </button>
                </div>
                <p className="text-label-sm text-on-surface-variant mb-3">{t('task_form.inline_desc')}</p>
                {taskInlineButtons.length === 0 ? (
                  <div className="bg-slate-50 rounded-lg p-4 text-center text-label-sm text-on-surface-variant">
                    {t('task_form.no_buttons')}
                  </div>
                ) : (
                  <div className="space-y-3 max-h-[40vh] overflow-y-auto">
                    {taskInlineButtons.map((btn, idx) => (
                      <div key={idx} className="bg-slate-50 rounded-lg p-3 space-y-2">
                        <input
                          value={btn.text}
                          onChange={e => {
                            const next = [...taskInlineButtons]
                            next[idx] = { ...next[idx], text: e.target.value }
                            setTaskInlineButtons(next)
                          }}
                          className="w-full px-3 py-2 rounded-lg border border-slate-200 bg-white text-sm font-body-md text-on-surface focus:outline-none focus:ring-2 focus:ring-primary/20"
                          placeholder={`${lang === 'ar' ? 'الزر' : 'Button'} ${idx + 1}`}
                        />
                        <div className="flex gap-2">
                          <input
                            value={btn.url}
                            onChange={e => {
                              const next = [...taskInlineButtons]
                              next[idx] = { ...next[idx], url: e.target.value }
                              setTaskInlineButtons(next)
                            }}
                            className="flex-1 min-w-0 px-3 py-2 rounded-lg border border-slate-200 bg-white text-sm font-body-md text-on-surface focus:outline-none focus:ring-2 focus:ring-primary/20 truncate"
                            placeholder="https://example.com"
                          />
                          <button
                            type="button"
                            onClick={() => setTaskInlineButtons(prev => prev.filter((_, i) => i !== idx))}
                            className="flex items-center gap-1 px-3 py-2 text-sm font-medium text-red-600 bg-red-50 hover:bg-red-100 rounded-lg transition-colors flex-shrink-0"
                          >
                            <span className="material-symbols-outlined text-base">delete</span>
                            <span>{t('tasks.remove')}</span>
                          </button>
                        </div>
                      </div>
                    ))}
                  </div>
                )}
              </div>
            )}

            {/* Destination + delivery mode (notify_destination only) */}
            {taskKey === 'notify_destination' && (
              <>
                <div>
                  <label className="font-label-sm text-on-surface-variant block mb-1">{t('task_form.destination')}</label>
                  <input
                    value={taskDestination}
                    onChange={e => setTaskDestination(e.target.value)}
                    className="w-full px-3 py-2 rounded-lg border border-slate-200 bg-white text-sm font-body-md text-on-surface focus:outline-none focus:ring-2 focus:ring-primary/20"
                    placeholder="-1001234567890"
                  />
                </div>
                <div>
                  <label className="font-label-sm text-on-surface-variant block mb-1">{t('task_form.delivery_mode')}</label>
                  <select
                    value={taskDeliveryMode}
                    onChange={e => setTaskDeliveryMode(e.target.value)}
                    className="w-full px-3 py-2 rounded-lg border border-slate-200 bg-white text-sm font-body-md text-on-surface focus:outline-none focus:ring-2 focus:ring-primary/20"
                  >
                    <option value="text">{t('task_form.text')}</option>
                    <option value="forward">{t('task_form.forward')}</option>
                    <option value="copy">{t('task_form.copy')}</option>
                    <option value="text_and_forward">{t('task_form.text_forward')}</option>
                    <option value="text_and_copy">{t('task_form.text_copy')}</option>
                  </select>
                </div>
              </>
            )}

            <div>
              <label className="font-label-sm text-on-surface-variant block mb-1">{t('task_form.delete_after')}</label>
              <input
                type="number"
                min="0"
                value={taskDeleteAfter}
                onChange={e => setTaskDeleteAfter(e.target.value)}
                className="w-full px-3 py-2 rounded-lg border border-slate-200 bg-white text-sm font-body-md text-on-surface focus:outline-none focus:ring-2 focus:ring-primary/20"
                placeholder="e.g. 3600"
              />
            </div>

            <div className="flex gap-3 pt-2">
              <button onClick={() => setShowTaskForm(false)} className="flex-1 bg-slate-100 text-on-surface py-2.5 rounded-lg font-label-md transition-all active:scale-95">
                {t('task_form.cancel')}
              </button>
              <button
                onClick={submitTaskForm}
                disabled={!taskKey.trim()}
                className="flex-1 bg-primary text-white py-2.5 rounded-lg font-label-md transition-all active:scale-95 disabled:opacity-50"
              >
                {editingTask ? t('task_form.save') : t('task_form.create')}
              </button>
            </div>
          </div>
        </Modal>
      )}

      <ConfirmModal
        open={confirmDelete?.type === 'scheduled'}
        title={t('confirm.title_cancel')}
        message={t('confirm.msg_cancel')}
        confirmLabel={t('confirm.cancel_msg')}
        danger
        onConfirm={() => {
          if (confirmDelete) onDeleteScheduledMessage(confirmDelete.id)
          setConfirmDelete(null)
        }}
        onCancel={() => setConfirmDelete(null)}
      />

      <ConfirmModal
        open={confirmDelete?.type === 'task'}
        title={t('confirm.title_delete')}
        message={t('confirm.msg_delete')}
        confirmLabel={t('confirm.delete_task')}
        danger
        onConfirm={() => {
          if (confirmDelete) onDeleteTask(confirmDelete.id)
          setConfirmDelete(null)
        }}
        onCancel={() => setConfirmDelete(null)}
      />
    </div>
  )
}

const Modal: React.FC<{ onClose: () => void; title: string; children: React.ReactNode }> = ({ onClose, title, children }) => (
  <div className="fixed inset-0 z-[200] flex items-end sm:items-center justify-center">
    <div className="absolute inset-0 bg-black/30 backdrop-blur-sm" onClick={onClose} />
    <div className="relative bg-white rounded-t-2xl sm:rounded-2xl w-full max-w-lg max-h-[85vh] overflow-y-auto shadow-2xl p-6 pb-8">
      <div className="flex items-center justify-between mb-5">
        <h3 className="font-headline-md text-on-surface">{title}</h3>
        <button onClick={onClose} className="p-1 rounded-full hover:bg-slate-100 transition-colors">
          <span className="material-symbols-outlined text-slate-400">close</span>
        </button>
      </div>
      {children}
    </div>
  </div>
)
