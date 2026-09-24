import { useEffect, useState } from "react"
import type { Info } from "@/lib/api"
import { baseName } from "@/lib/path"
import { fmtHz, fmtTime, type View } from "@/lib/scale"

/** Delay before announcing a view, so zoom and pan settle first. */
const SETTLE_MS = 700

/** Screen readers: announce the verdict when a file is analysed and the view
 * after zoom/pan settles, instead of every intermediate frame. */
export function useAnnouncer(info: Info | null, view: View) {
  const [announce, setAnnounce] = useState("")
  useEffect(() => {
    if (!info) return
    const a = info.analysis
    setAnnounce(`${baseName(info.path)} loaded. ${a ? a.verdict : "No analysis."}`)
  }, [info])
  useEffect(() => {
    if (!info) return
    const t = setTimeout(
      () =>
        setAnnounce(
          `View ${fmtTime(view.t0, 0.1)} to ${fmtTime(view.t1, 0.1)}, ${fmtHz(view.f0)} to ${fmtHz(view.f1)} hertz.`,
        ),
      SETTLE_MS,
    )
    return () => clearTimeout(t)
  }, [view, info])
  return announce
}
