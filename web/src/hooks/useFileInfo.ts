import { useEffect, useState } from "react"
import { api, type Info, type Progress } from "@/lib/api"
import { useLatest } from "./useLatest"

/** Fetches the analysis of `path`, polling while the server is still working
 * on a long file. `onLoaded` runs once per file, when its info lands. */
export function useFileInfo(path: string | null, onLoaded: (info: Info) => void) {
  const [info, setInfo] = useState<Info | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [analysing, setAnalysing] = useState(false)
  const [progress, setProgress] = useState<Progress | null>(null)
  const onLoadedRef = useLatest(onLoaded)

  useEffect(() => {
    if (!path) return
    const ctl = new AbortController()
    setAnalysing(true)
    setError(null)
    setInfo(null)
    setProgress(null)
    api
      .info(path, ctl.signal, setProgress)
      .then(i => {
        setInfo(i)
        onLoadedRef.current(i)
      })
      .catch(e => {
        if (e.name !== "AbortError") setError(String(e.message ?? e))
      })
      .finally(() => setAnalysing(false))
    return () => ctl.abort()
  }, [path, onLoadedRef])

  return { info, error, analysing, progress }
}
