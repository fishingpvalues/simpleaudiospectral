import { useEffect, useRef, useState } from "react"
import { api } from "@/lib/api"
import type { View } from "@/lib/scale"
import { drawGoniometer } from "./charts"

/** Wait for the view to settle before asking the server. */
const DEBOUNCE_MS = 250
const SIZE = 160

/** Mid/side scatter of the visible time range, rendered by the server. */
export function Goniometer({ path, view }: { path: string; view: View }) {
  const ref = useRef<HTMLCanvasElement>(null)
  const [corr, setCorr] = useState<number | null>(null)
  useEffect(() => {
    const ctl = new AbortController()
    const t = setTimeout(() => {
      api
        .gonio({ path, t0: view.t0.toFixed(3), t1: view.t1.toFixed(3), size: SIZE }, ctl.signal)
        .then(r => {
          const c = ref.current
          if (!c) return
          c.width = r.size
          c.height = r.size
          drawGoniometer(c.getContext("2d")!, r.size, r.data)
          setCorr(r.correlation)
        })
        .catch(() => {})
    }, DEBOUNCE_MS)
    return () => {
      clearTimeout(t)
      ctl.abort()
    }
  }, [path, view.t0, view.t1])
  return (
    <div className="flex items-center gap-3">
      <canvas
        ref={ref}
        className="size-40 rounded-md border bg-black [image-rendering:pixelated]"
        role="img"
        aria-label={`Goniometer for the current view, correlation ${corr == null ? "unknown" : corr.toFixed(2)}`}
      />
      <div className="space-y-1 text-xs text-muted-foreground">
        <div>Vertical: mid (L+R)</div>
        <div>Horizontal: side (L-R)</div>
        <div className="pt-1 font-mono text-sm text-foreground">r = {corr == null ? "-" : corr.toFixed(3)}</div>
        <div>A vertical line = mono; a horizontal one = out of phase.</div>
      </div>
    </div>
  )
}
