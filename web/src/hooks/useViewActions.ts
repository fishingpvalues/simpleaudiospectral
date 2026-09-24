import { useCallback } from "react"
import type { Info } from "@/lib/api"
import { detailView, fullView, jumpView, panBy, zoomCentered } from "@/lib/view"
import type { SetView } from "./useViewHistory"

/** Toolbar and keyboard view changes; each is a no-op until a file is loaded. */
export function useViewActions(info: Info | null, setView: SetView, seek: (t: number) => boolean) {
  const zoom = useCallback(
    (factor: number) => setView(v => (info ? zoomCentered(v, factor, info.duration) : v)),
    [info, setView],
  )
  const fit = useCallback(() => info && setView(fullView(info.duration, info.sampleRate)), [info, setView])
  const pan = useCallback((frac: number) => setView(v => (info ? panBy(v, frac, info.duration) : v)), [info, setView])
  const detailZoom = useCallback(() => {
    if (!info) return
    setView(detailView(info.analysis?.loudestAt ?? 0, info.duration, info.sampleRate))
  }, [info, setView])
  const jump = useCallback(
    (t: number) => {
      if (!info) return
      setView(v => jumpView(v, t, info.duration))
      seek(t)
    },
    [info, setView, seek],
  )
  return { zoom, fit, pan, detailZoom, jump }
}
