import { useEffect } from "react"
import type { View } from "@/lib/scale"

/** When following, the playhead re-enters the view this far from its left edge. */
const FOLLOW_LEAD = 0.05

interface UsePlayheadLoopArgs {
  playing: boolean
  audio: HTMLAudioElement | null
  follow: boolean
  view: View
  apply: (fn: (v: View) => View) => void
  paintOverlay: () => void
  paintWaveOverlay: () => void
}

/** Repaints the playhead every frame while playing, and pages the view along
 * when "follow playhead" is on. */
export function usePlayheadLoop({
  playing,
  audio,
  follow,
  view,
  apply,
  paintOverlay,
  paintWaveOverlay,
}: UsePlayheadLoopArgs) {
  useEffect(() => {
    if (!playing || !audio) return
    let raf = 0
    const loop = () => {
      const t = audio.currentTime
      if (follow && (t > view.t1 || t < view.t0)) {
        const span = view.t1 - view.t0
        apply(v => ({ ...v, t0: t - span * FOLLOW_LEAD, t1: t - span * FOLLOW_LEAD + span }))
      }
      paintOverlay()
      paintWaveOverlay()
      raf = requestAnimationFrame(loop)
    }
    raf = requestAnimationFrame(loop)
    return () => cancelAnimationFrame(raf)
    // paintWaveOverlay and apply change only together with paintOverlay or view.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [playing, audio, paintOverlay, view, follow])
}
