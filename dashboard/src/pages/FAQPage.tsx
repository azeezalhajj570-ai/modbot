import { useEffect, useState } from 'react'

import { Badge, Button, Card, EmptyState, Field, InlineMessage, Input, ListItem, Select, Textarea, ToggleRow, ContentGrid } from '../components/ui/primitives'
import { PageShell } from '../lib/page-shell'
import {
  aiAnalyzeGroupMessages,
  convertUnansweredToFAQ,
  createFAQEntry,
  deleteFAQEntry,
  fetchFAQEntries,
  fetchFAQSettings,
  fetchUnansweredQuestions,
  testFAQMatch,
  updateFAQSettings,
} from '../lib/api'
import { useDashboardGroups } from '../lib/use-dashboard-groups'
import { useI18n } from '../lib/i18n'

export default function FAQPage() {
  const { t } = useI18n()
  const { groups, currentGroup, currentGroupId, setCurrentGroupId, loading: groupsLoading, error: groupsError } = useDashboardGroups()
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [feedback, setFeedback] = useState('')
  const [settings, setSettings] = useState<any>(null)
  const [entries, setEntries] = useState<any[]>([])
  const [unanswered, setUnanswered] = useState<any[]>([])
  const [savingSettings, setSavingSettings] = useState(false)
  const [suggestionThreshold, setSuggestionThreshold] = useState('3')
  const [autoReplyThreshold, setAutoReplyThreshold] = useState('5')

  const [newQuestion, setNewQuestion] = useState('')
  const [newAnswer, setNewAnswer] = useState('')
  const [newKeywords, setNewKeywords] = useState('')
  const [creatingEntry, setCreatingEntry] = useState(false)

  const [testQuery, setTestQuery] = useState('')
  const [testResult, setTestResult] = useState<any>(null)
  const [testing, setTesting] = useState(false)

  const [convertAnswers, setConvertAnswers] = useState<Record<number, string>>({})
  const [aiAnalyzing, setAiAnalyzing] = useState(false)
  const [aiResult, setAiResult] = useState<any>(null)

  useEffect(() => {
    if (currentGroupId == null) {
      setLoading(groupsLoading)
      return
    }

    let cancelled = false
    ;(async () => {
      setLoading(true)
      setError('')
      setFeedback('')
      try {
        const [faqSettings, faqEntries, faqUnanswered] = await Promise.all([
          fetchFAQSettings(currentGroupId),
          fetchFAQEntries(currentGroupId),
          fetchUnansweredQuestions(currentGroupId),
        ])
        if (cancelled) return

        setSettings(faqSettings)
        setEntries(faqEntries)
        setUnanswered(faqUnanswered)
        setSuggestionThreshold(String(faqSettings.suggestion_threshold ?? 3))
        setAutoReplyThreshold(String(faqSettings.auto_reply_threshold ?? 5))
      } catch {
        if (!cancelled) setError(t('faq.loadError'))
      } finally {
        if (!cancelled) setLoading(false)
      }
    })()

    return () => { cancelled = true }
  }, [currentGroupId, groupsLoading])

  async function handleSaveSettings() {
    if (currentGroupId == null || settings == null) return

    const threshold = Number(suggestionThreshold)
    const autoThreshold = Number(autoReplyThreshold)
    if (!Number.isFinite(threshold) || threshold < 1) {
      setError(t('faq.invalidThreshold'))
      return
    }
    if (!Number.isFinite(autoThreshold) || autoThreshold < 1) {
      setError(t('faq.invalidThreshold'))
      return
    }

    setSavingSettings(true)
    setError('')
    setFeedback('')
    try {
      const updated = await updateFAQSettings(currentGroupId, {
        enabled_safe_mode: settings.enabled_safe_mode,
        suggestion_threshold: threshold,
        auto_reply_threshold: autoThreshold,
      })
      setSettings(updated)
      setSuggestionThreshold(String(updated.suggestion_threshold ?? threshold))
      setAutoReplyThreshold(String(updated.auto_reply_threshold ?? autoThreshold))
      setFeedback(t('faq.settingsSaved'))
    } catch {
      setError(t('faq.settingsError'))
    } finally {
      setSavingSettings(false)
    }
  }

  async function handleCreateEntry() {
    if (currentGroupId == null) return
    if (!newQuestion.trim() || !newAnswer.trim()) {
      setError(t('faq.entryRequired'))
      return
    }

    setCreatingEntry(true)
    setError('')
    setFeedback('')
    try {
      const keywords = newKeywords.split(',').map((k) => k.trim()).filter(Boolean)
      const entry = await createFAQEntry(currentGroupId, { question: newQuestion, answer: newAnswer, keywords })
      setEntries((current) => [...current, entry])
      setNewQuestion('')
      setNewAnswer('')
      setNewKeywords('')
      setFeedback(t('faq.entryCreated'))
    } catch {
      setError(t('faq.entryError'))
    } finally {
      setCreatingEntry(false)
    }
  }

  async function handleTestMatch() {
    if (currentGroupId == null || !testQuery.trim()) return

    setTesting(true)
    setError('')
    setTestResult(null)
    try {
      const result = await testFAQMatch(currentGroupId, testQuery)
      setTestResult(result)
    } catch {
      setError(t('faq.testError'))
    } finally {
      setTesting(false)
    }
  }

  async function handleDeleteEntry(entryId: number) {
    if (currentGroupId == null) return
    setError('')
    setFeedback('')
    try {
      await deleteFAQEntry(currentGroupId, entryId)
      setEntries((current) => current.filter((entry) => entry.id !== entryId))
      setFeedback(t('faq.entryDeleted'))
    } catch {
      setError(t('faq.entryError'))
    }
  }

  async function handleConvertToFAQ(questionId: number) {
    if (currentGroupId == null) return
    const answer = convertAnswers[questionId]?.trim()
    if (!answer) {
      setError(t('faq.convertRequired'))
      return
    }

    setError('')
    setFeedback('')
    try {
      await convertUnansweredToFAQ(currentGroupId, questionId, answer)
      setUnanswered((current) => current.filter((q) => q.id !== questionId))
      setConvertAnswers((current) => { const next = { ...current }; delete next[questionId]; return next })
      setFeedback(t('faq.converted'))
    } catch {
      setError(t('faq.convertError'))
    }
  }

  function handleConvertAnswerChange(questionId: number, value: string) {
    setConvertAnswers((current) => ({ ...current, [questionId]: value }))
  }

  async function handleAIAnalyze() {
    if (currentGroupId == null) return
    setAiAnalyzing(true)
    setError('')
    setFeedback('')
    setAiResult(null)
    try {
      const result = await aiAnalyzeGroupMessages(currentGroupId, 1000)
      setAiResult(result)
      setFeedback(`${t('faq.aiResult')} ${result.entries_saved} ${t('faq.aiFrom')} ${result.messages_analyzed} ${t('faq.aiMessages')}.`)
      const faqEntries = await fetchFAQEntries(currentGroupId)
      setEntries(faqEntries)
    } catch (e: any) {
      setError(e?.response?.data?.detail || t('faq.aiError'))
    }
    setAiAnalyzing(false)
  }

  return (
    <PageShell
      titleKey="page.faq"
      descriptionKey="page.faq.desc"
      loading={loading}
      actions={(
        <div style={{ minWidth: 200 }}>
          <Select value={currentGroupId ?? ''} onChange={(event) => setCurrentGroupId(Number(event.target.value) || null)} disabled={groupsLoading || groups.length === 0}>
            {groups.length === 0 ? <option value="">{t('faq.noGroups')}</option> : null}
            {groups.map((group) => (
              <option key={group.id} value={group.id}>{group.title}</option>
            ))}
          </Select>
        </div>
      )}
    >
      {groupsError ? <InlineMessage tone="danger">{groupsError}</InlineMessage> : null}
      {currentGroup ? <InlineMessage tone="neutral">{t('faq.managing')} {currentGroup.title}.</InlineMessage> : null}
      {error ? <InlineMessage tone="danger">{error}</InlineMessage> : null}
      {feedback ? <InlineMessage tone="success">{feedback}</InlineMessage> : null}

      {settings ? (
        <Card title={t('faq.settingsTitle')} subtitle={t('faq.settingsDesc')}>
          <ToggleRow
            title={t('faq.safeMode')}
            subtitle={t('faq.safeModeDesc')}
            checked={settings.enabled_safe_mode}
            disabled={currentGroupId == null}
            onCheckedChange={(checked) => setSettings((current) => current ? { ...current, enabled_safe_mode: checked } : null)}
          />
          <ContentGrid columns="repeat(auto-fit, minmax(240px, 1fr))">
            <Field label={t('faq.suggestionThreshold')} hint={t('faq.suggestionThresholdHint')}>
              <Input
                type="range"
                min={1}
                max={10}
                value={suggestionThreshold}
                onChange={(event) => setSuggestionThreshold(event.target.value)}
              />
              <div style={{ fontSize: 13, color: 'var(--ui-text-muted)', marginTop: 4 }}>{t('faq.threshold')}: {suggestionThreshold}</div>
            </Field>
            <Field label={t('faq.autoReplyThreshold')} hint={t('faq.autoReplyThresholdHint')}>
              <Input
                type="range"
                min={1}
                max={20}
                value={autoReplyThreshold}
                onChange={(event) => setAutoReplyThreshold(event.target.value)}
              />
              <div style={{ fontSize: 13, color: 'var(--ui-text-muted)', marginTop: 4 }}>{t('faq.threshold')}: {autoReplyThreshold}</div>
            </Field>
          </ContentGrid>
          <div style={{ marginTop: 16 }}>
            <Button onClick={() => void handleSaveSettings()} disabled={savingSettings || currentGroupId == null}>
              {savingSettings ? `${t('faq.saving')}...` : t('faq.saveSettings')}
            </Button>
          </div>
        </Card>
      ) : null}

      <Card title={t('faq.aiTitle')} subtitle={t('faq.aiDesc')}>
        <p style={{ color: 'var(--ui-text-muted)', fontSize: 13, marginBottom: 12 }}>
          {t('faq.aiBody')}
        </p>
        <div style={{ display: 'flex', gap: 8, alignItems: 'center', flexWrap: 'wrap' }}>
          <Button onClick={() => void handleAIAnalyze()} disabled={aiAnalyzing || currentGroupId == null}>
            {aiAnalyzing ? t('faq.aiAnalyzing') : t('faq.aiRun')}
          </Button>
        </div>
        {aiResult && (
          <div style={{ marginTop: 12, padding: 12, borderRadius: 8, background: 'var(--ui-primary-soft)', fontSize: 13 }}>
            {t('faq.aiMessages')}: {aiResult.messages_analyzed} | {t('faq.aiChunks')}: {aiResult.chunks_processed} |
            {t('faq.aiExtracted')}: {aiResult.entries_extracted} | {t('faq.aiSaved')}: {aiResult.entries_saved}
          </div>
        )}
      </Card>

      <Card title={t('faq.testTitle')} subtitle={t('faq.testDesc')}>
        <div style={{ display: 'flex', gap: 8, alignItems: 'flex-end', flexWrap: 'wrap' }}>
          <div style={{ flex: 1, minWidth: 200 }}>
            <Field label={t('faq.question')}>
              <Input
                placeholder={t('faq.testPlaceholder')}
                value={testQuery}
                onChange={(event) => setTestQuery(event.target.value)}
                onKeyDown={(event) => { if (event.key === 'Enter') void handleTestMatch() }}
              />
            </Field>
          </div>
          <Button onClick={() => void handleTestMatch()} disabled={testing || !testQuery.trim()}>
            {testing ? `${t('faq.testing')}...` : t('faq.test')}
          </Button>
        </div>
        {testResult ? (
          <div style={{ marginTop: 12, padding: 12, borderRadius: 8, background: 'var(--ui-surface-2)' }}>
            {testResult.matched ? (
              <>
                <div style={{ fontWeight: 600, marginBottom: 4 }}>{t('faq.matched')} ({t('faq.confidence')}: {testResult.confidence.toFixed(2)})</div>
                <div style={{ fontSize: 13, color: 'var(--ui-text-muted)', marginBottom: 4 }}>{t('faq.entryId')}: {testResult.entry_id}</div>
                <div style={{ fontSize: 13 }}>{t('faq.answer')}: {testResult.answer}</div>
              </>
            ) : (
              <div style={{ color: 'var(--ui-text-muted)' }}>{t('faq.noMatch')} ({t('faq.confidence')}: {testResult.confidence.toFixed(2)}).</div>
            )}
          </div>
        ) : null}
      </Card>

      <Card title={t('faq.entriesTitle')} subtitle={t('faq.entriesDesc')}>
        <div style={{ marginBottom: 16, display: 'grid', gap: 12 }}>
          <Field label={t('faq.question')}>
            <Input
              placeholder={t('faq.entryQuestionPlaceholder')}
              value={newQuestion}
              onChange={(event) => setNewQuestion(event.target.value)}
            />
          </Field>
          <Field label={t('faq.answer')}>
            <Textarea
              placeholder={t('faq.entryAnswerPlaceholder')}
              value={newAnswer}
              onChange={(event) => setNewAnswer(event.target.value)}
            />
          </Field>
          <Field label={t('faq.keywords')} hint={t('faq.keywordsHint')}>
            <Input
              placeholder={t('faq.keywordsPlaceholder')}
              value={newKeywords}
              onChange={(event) => setNewKeywords(event.target.value)}
            />
          </Field>
          <div>
            <Button onClick={() => void handleCreateEntry()} disabled={creatingEntry || currentGroupId == null}>
              {creatingEntry ? `${t('faq.creating')}...` : t('faq.addEntry')}
            </Button>
          </div>
        </div>
        {entries.length > 0 ? (
          <div style={{ display: 'grid' }}>
            {entries.map((entry) => (
              <ListItem
                key={entry.id}
                title={entry.question}
                subtitle={entry.answer}
                meta={<Badge tone={entry.enabled ? 'success' : 'neutral'}>{entry.enabled ? t('faq.enabled') : t('faq.disabled')}</Badge>}
                actions={(
                  <Button variant="destructive" onClick={() => void handleDeleteEntry(entry.id)}>{t('faq.delete')}</Button>
                )}
              />
            ))}
          </div>
        ) : (
          <EmptyState title={t('faq.noEntries')} subtitle={t('faq.noEntriesDesc')} />
        )}
      </Card>

      <Card title={t('faq.unansweredTitle')} subtitle={t('faq.unansweredDesc')}>
        {unanswered.length > 0 ? (
          <div style={{ display: 'grid' }}>
            {unanswered.map((question) => (
              <ListItem
                key={question.id}
                title={question.question_preview ?? question.question}
                subtitle={`${t('faq.askedBy')} ${question.user_id ?? t('faq.unknown')} \u00b7 ${question.frequency_count ?? 0} ${t('faq.times')}`}
                meta={<Badge tone="warning">{question.last_seen_at ? new Date(question.last_seen_at).toLocaleDateString() : ''}</Badge>}
                actions={(
                  <div style={{ display: 'flex', gap: 8, alignItems: 'center', flexWrap: 'wrap' }}>
                    <Input
                      placeholder={t('faq.convertPlaceholder')}
                      value={convertAnswers[question.id] ?? ''}
                      onChange={(event) => handleConvertAnswerChange(question.id, event.target.value)}
                      style={{ minWidth: 160 }}
                    />
                    <Button onClick={() => void handleConvertToFAQ(question.id)} disabled={!convertAnswers[question.id]?.trim()}>
                      {t('faq.convert')}
                    </Button>
                  </div>
                )}
              />
            ))}
          </div>
        ) : (
          <EmptyState title={t('faq.noUnanswered')} subtitle={t('faq.noUnansweredDesc')} />
        )}
      </Card>
    </PageShell>
  )
}
