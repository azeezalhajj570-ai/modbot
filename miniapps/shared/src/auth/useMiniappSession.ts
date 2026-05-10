import { useEffect, useState } from 'react'

import { fetchMe } from '../api'
import type { ManagedGroup, MiniappIdentity } from '../types'

export function useMiniappSession() {
  const [identity, setIdentity] = useState<MiniappIdentity | null>(null)
  const [groups, setGroups] = useState<ManagedGroup[]>([])
  const [selectedGroupId, setSelectedGroupId] = useState<number | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  const refreshSession = async () => {
    setLoading(true)
    try {
      const nextIdentity = await fetchMe()
      setIdentity(nextIdentity)
      setGroups(nextIdentity.groups)
      setSelectedGroupId((current: number | null) => current ?? nextIdentity.groups[0]?.id ?? null)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to load miniapp session')
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    let cancelled = false
    ;(async () => {
      try {
        const nextIdentity = await fetchMe()
        if (cancelled) {
          return
        }
        setIdentity(nextIdentity)
        setGroups(nextIdentity.groups)
        setSelectedGroupId((current: number | null) => current ?? nextIdentity.groups[0]?.id ?? null)
      } catch (err) {
        if (!cancelled) {
          setError(err instanceof Error ? err.message : 'Failed to load miniapp session')
        }
      } finally {
        if (!cancelled) {
          setLoading(false)
        }
      }
    })()
    return () => {
      cancelled = true
    }
  }, [])

  return {
    identity,
    groups,
    selectedGroupId,
    setSelectedGroupId,
    loading,
    error,
    refreshSession,
  }
}
