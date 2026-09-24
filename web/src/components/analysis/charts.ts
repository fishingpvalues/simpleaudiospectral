import type { Analysis } from "@/lib/api"
import type { RefLine } from "@/lib/references"
import { fmtHz } from "@/lib/scale"
import type { Spectrum } from "@/components/viewer/types"

type Ctx = CanvasRenderingContext2D

const LABEL_FONT = "10px 'Geist Mono Variable', monospace"

/** Sizes a canvas to its CSS box at device resolution; draws in CSS pixels. */
export function fitCanvas(c: HTMLCanvasElement) {
  const dpr = window.devicePixelRatio || 1
  const w = c.clientWidth,
    h = c.clientHeight
  c.width = w * dpr
  c.height = h * dpr
  const g = c.getContext("2d")!
  g.setTransform(dpr, 0, 0, dpr, 0, 0)
  return { g, w, h }
}

function polyline(g: Ctx, n: number, x: (i: number) => number, y: (i: number) => number) {
  g.beginPath()
  for (let i = 0; i < n; i++) {
    if (i) g.lineTo(x(i), y(i))
    else g.moveTo(x(i), y(i))
  }
  g.stroke()
}

export interface SpectrumChartData {
  nyquist: number
  refs: RefLine[]
  analysis: Pick<Analysis, "curve" | "cutoffHz"> | null
  viewSpec: Spectrum | null
  cursorSlice: Spectrum | null
  /** Cursor frequency, NaN or null when the cursor is not over the spectrogram. */
  cursorHz: number | null
}

/** Level (dB) against linear frequency: the file's loudest-10% and median
 * curves, the view mean, and the column under the cursor. */
export function drawSpectrumChart(g: Ctx, w: number, h: number, d: SpectrumChartData) {
  g.fillStyle = "#000"
  g.fillRect(0, 0, w, h)
  const L = 34,
    B = 16,
    nyq = d.nyquist
  const lo = -140,
    hi = 0
  const X = (f: number) => L + ((w - L - 4) * f) / nyq
  const Y = (db: number) => ((h - B) * (hi - Math.max(lo, Math.min(hi, db)))) / (hi - lo)
  const vline = (x: number) => {
    g.beginPath()
    g.moveTo(x, 0)
    g.lineTo(x, h - B)
    g.stroke()
  }
  g.font = LABEL_FONT
  g.lineWidth = 1
  for (let db = hi; db >= lo; db -= 20) {
    g.strokeStyle = "rgba(255,255,255,0.08)"
    g.beginPath()
    g.moveTo(L, Y(db))
    g.lineTo(w, Y(db))
    g.stroke()
    g.fillStyle = "#737373"
    g.fillText(String(db), 2, Y(db) + 3)
  }
  const step = nyq > 30000 ? 10000 : 5000
  for (let f = 0; f <= nyq; f += step) {
    g.fillStyle = "#737373"
    g.fillText(fmtHz(f), X(f) - 6, h - 3)
  }
  g.setLineDash([2, 3])
  for (const r of d.refs) {
    if (r.khz * 1000 > nyq) continue
    g.strokeStyle = "rgba(255,255,255,0.18)"
    vline(X(r.khz * 1000))
  }
  g.setLineDash([])
  const a = d.analysis
  if (a) {
    const { hz, db, median } = a.curve
    g.strokeStyle = "#525252"
    g.lineWidth = 1
    polyline(
      g,
      hz.length,
      i => X(hz[i]),
      i => Y(median[i]),
    )
    g.strokeStyle = "#a3a3a3"
    g.lineWidth = 1.25
    polyline(
      g,
      hz.length,
      i => X(hz[i]),
      i => Y(db[i]),
    )
    if (a.cutoffHz) {
      g.strokeStyle = "#fff"
      g.setLineDash([5, 3])
      vline(X(a.cutoffHz))
      g.setLineDash([])
    }
  }
  const vs = d.viewSpec
  if (vs) {
    g.strokeStyle = "#22d3ee"
    g.lineWidth = 1
    polyline(
      g,
      vs.hz.length,
      i => X(vs.hz[i]),
      i => Y(vs.db[i]),
    )
  }
  const s = d.cursorSlice
  if (s) {
    g.strokeStyle = "#fff"
    g.lineWidth = 1
    polyline(
      g,
      s.hz.length,
      i => X(s.hz[i]),
      i => Y(s.db[i]),
    )
  }
  if (d.cursorHz != null && Number.isFinite(d.cursorHz)) {
    g.strokeStyle = "rgba(255,255,255,0.4)"
    vline(X(d.cursorHz))
  }
}

/** Correlation per second as bars around zero; out-of-phase seconds in red. */
export function drawCorrelation(g: Ctx, w: number, h: number, series: number[]) {
  g.fillStyle = "#000"
  g.fillRect(0, 0, w, h)
  const Y = (v: number) => (h / 2) * (1 - v)
  g.strokeStyle = "rgba(255,255,255,0.12)"
  g.beginPath()
  g.moveTo(0, Y(0))
  g.lineTo(w, Y(0))
  g.stroke()
  series.forEach((v, i) => {
    const x = (i / series.length) * w
    g.fillStyle = v < 0 ? "#ef4444" : "#a3a3a3"
    g.fillRect(x, Math.min(Y(v), Y(0)), Math.max(1, w / series.length), Math.abs(Y(v) - Y(0)))
  })
  g.fillStyle = "#737373"
  g.font = LABEL_FONT
  g.fillText("+1", 2, 10)
  g.fillText("-1", 2, h - 3)
}

/** Greyscale density image of the goniometer with a centre cross. */
export function drawGoniometer(g: Ctx, size: number, data: Uint8Array) {
  const img = g.createImageData(size, size)
  for (let i = 0; i < data.length; i++) {
    const v = data[i]
    img.data[i * 4] = v
    img.data[i * 4 + 1] = v
    img.data[i * 4 + 2] = v
    img.data[i * 4 + 3] = 255
  }
  g.putImageData(img, 0, 0)
  g.strokeStyle = "rgba(255,255,255,0.15)"
  g.beginPath()
  g.moveTo(size / 2, 0)
  g.lineTo(size / 2, size)
  g.moveTo(0, size / 2)
  g.lineTo(size, size / 2)
  g.stroke()
}
