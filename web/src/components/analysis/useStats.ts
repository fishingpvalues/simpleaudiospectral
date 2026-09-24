import { useEffect, useState } from "react"
import { api, type Stats } from "@/lib/api"

/** Loudness and dynamics of the whole file; measured on first request. */
export function useStats(path: string) {
  const [stats, setStats] = useState<Stats | null>(null)
  const [error, setError] = useState<string | null>(null)
  useEffect(() => {
    const ctl = new AbortController()
    setStats(null)
    setError(null)
    api
      .stats(path, ctl.signal)
      .then(setStats)
      .catch(e => {
        if (e.name !== "AbortError") setError(String(e.message ?? e))
      })
    return () => ctl.abort()
  }, [path])
  return { stats, error }
}
