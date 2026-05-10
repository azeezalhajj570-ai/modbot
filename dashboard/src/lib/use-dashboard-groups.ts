import { useEffect, useMemo, useState } from 'react'

import { fetchCurrentUser } from './api'

export interface ManagedGroup {
  id: number
  title: string
  tg_group_id: number
  role: string
}

const ACTIVE_GROUP_KEY = 'dashboard_active_group_id'

export function useDashboardGroups() {
  const [groups, setGroups] = useState<ManagedGroup[]>([])
  const [currentGroupId, setCurrentGroupId] = useState<number | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')

  useEffect(() => {
    let cancelled = false

    ;(async () => {
      setLoading(true)
      setError('')
      try {
        const response = await fetchCurrentUser()
        if (cancelled) return

        const nextGroups = Array.isArray(response.groups) ? response.groups as ManagedGroup[] : []
        setGroups(nextGroups)

        const storedId = Number(window.localStorage.getItem(ACTIVE_GROUP_KEY) || '')
        const preferredId = Number.isFinite(storedId) ? storedId : NaN
        const nextCurrentGroup =
          nextGroups.find((group) => group.id === preferredId)
          ?? nextGroups[0]
          ?? null

        setCurrentGroupId(nextCurrentGroup?.id ?? null)
      } catch {
        if (!cancelled) {
          setError('Unable to load your managed groups.')
          setGroups([])
          setCurrentGroupId(null)
        }
      } finally {
        if (!cancelled) setLoading(false)
      }
    })()

    return () => { cancelled = true }
  }, [])

  useEffect(() => {
    if (currentGroupId == null) return
    window.localStorage.setItem(ACTIVE_GROUP_KEY, String(currentGroupId))
  }, [currentGroupId])

  const currentGroup = useMemo(
    () => groups.find((group) => group.id === currentGroupId) ?? null,
    [currentGroupId, groups],
  )

  return {
    groups,
    currentGroup,
    currentGroupId,
    setCurrentGroupId,
    loading,
    error,
  }
}
