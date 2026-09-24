import type { View } from "@/lib/scale"
import type { WaveTile } from "../types"

type Ctx = CanvasRenderingContext2D

/** A sample at or beyond this magnitude counts as clipped. */
const CLIP = 0.999

/** Waveform of the view with -6 and -12 dB guides; clipped columns get a red mark on top. */
export function drawWaveform(g: Ctx, view: View, plotW: number, h: number, wv: WaveTile | null) {
  g.fillStyle = "#000"
  g.fillRect(0, 0, plotW, h)
  const mid = h / 2,
    amp = h / 2 - 4
  g.strokeStyle = "rgba(255,255,255,0.08)"
  g.lineWidth = 1
  for (const lv of [-6, -12]) {
    const a = Math.pow(10, lv / 20) * amp
    g.beginPath()
    g.moveTo(0, mid - a)
    g.lineTo(plotW, mid - a)
    g.moveTo(0, mid + a)
    g.lineTo(plotW, mid + a)
    g.stroke()
  }
  g.strokeStyle = "rgba(255,255,255,0.18)"
  g.beginPath()
  g.moveTo(0, mid)
  g.lineTo(plotW, mid)
  g.stroke()
  if (!wv) return
  // The tile may be for an older view: place it by its own time range.
  const n = wv.data.length / 2
  const x0 = ((wv.t0 - view.t0) / (view.t1 - view.t0)) * plotW
  const xs = (((wv.t1 - wv.t0) / (view.t1 - view.t0)) * plotW) / n
  g.fillStyle = "#e5e5e5"
  for (let i = 0; i < n; i++) {
    const lo = wv.data[2 * i],
      hi = wv.data[2 * i + 1]
    const x = x0 + i * xs
    if (x < -2 || x > plotW + 2) continue
    const y1 = mid - Math.min(1, hi) * amp,
      y2 = mid - Math.max(-1, lo) * amp
    g.fillRect(x, y1, Math.max(1, xs), Math.max(1, y2 - y1))
  }
  g.fillStyle = "#ef4444"
  for (let i = 0; i < n; i++) {
    if (wv.data[2 * i + 1] >= CLIP || wv.data[2 * i] <= -CLIP) g.fillRect(x0 + i * xs, 0, Math.max(1, xs), 3)
  }
}

/** Whole-track strip under the plot with the viewport as a rectangle. */
export function drawOverview(
  g: Ctx,
  view: View,
  duration: number,
  plotW: number,
  h: number,
  data: Float32Array | null,
) {
  g.fillStyle = "#050505"
  g.fillRect(0, 0, plotW, h)
  if (data) {
    const n = data.length / 2,
      mid = h / 2,
      amp = h / 2 - 3
    g.fillStyle = "#525252"
    for (let i = 0; i < n; i++) {
      const y1 = mid - data[2 * i + 1] * amp,
        y2 = mid - data[2 * i] * amp
      g.fillRect((i / n) * plotW, y1, Math.max(1, plotW / n), Math.max(1, y2 - y1))
    }
  }
  const { x0, x1 } = overviewSpan(view, duration, plotW)
  g.fillStyle = "rgba(255,255,255,0.08)"
  g.fillRect(x0, 0, Math.max(2, x1 - x0), h)
  g.strokeStyle = "rgba(255,255,255,0.7)"
  g.lineWidth = 1
  g.strokeRect(Math.round(x0) + 0.5, 0.5, Math.max(2, Math.round(x1 - x0) - 1), h - 1)
}

/** Overview x of the viewport edges, shared by drawing and dragging. */
export function overviewSpan(view: View, duration: number, plotW: number) {
  return { x0: (view.t0 / duration) * plotW, x1: (view.t1 / duration) * plotW }
}
