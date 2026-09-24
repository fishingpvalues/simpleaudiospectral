import type { Analysis, StftMeta } from "@/lib/api"
import { freqTicks, timeTicks } from "@/lib/scale"
import type { RefLine } from "@/lib/references"
import { SANS_FONT } from "../constants"
import { crisp, type Geometry } from "../geometry"
import type { Drag, Mouse } from "../types"

type Ctx = CanvasRenderingContext2D
type Geo = Pick<Geometry, "view" | "scale" | "plotW" | "specH" | "xOf" | "yOf">

export function drawGrid(g: Ctx, geo: Geo) {
  const { view, scale, plotW, specH, xOf, yOf } = geo
  g.strokeStyle = "rgba(255,255,255,0.07)"
  g.lineWidth = 1
  g.beginPath()
  for (const f of freqTicks(view, scale, specH)) {
    const y = crisp(yOf(f))
    g.moveTo(0, y)
    g.lineTo(plotW, y)
  }
  for (const t of timeTicks(view.t0, view.t1, plotW).ticks) {
    const x = crisp(xOf(t))
    g.moveTo(x, 0)
    g.lineTo(x, specH)
  }
  g.stroke()
}

/** Dashed encoder lowpass lines, lowest first; crowded labels are dropped, the lines stay. */
export function drawRefLines(g: Ctx, geo: Geo, refs: RefLine[]) {
  const { view, plotW, yOf } = geo
  g.setLineDash([2, 4])
  g.lineWidth = 1
  let lastLabel = -100
  for (const r of refs) {
    const f = r.khz * 1000
    if (f < view.f0 || f > view.f1) continue
    const y = crisp(yOf(f))
    g.strokeStyle = "rgba(255,255,255,0.28)"
    g.beginPath()
    g.moveTo(0, y)
    g.lineTo(plotW, y)
    g.stroke()
    if (Math.abs(y - lastLabel) < 13) continue
    lastLabel = y
    g.fillStyle = "rgba(255,255,255,0.6)"
    g.textBaseline = "bottom"
    g.fillText(`${r.label}  ${r.khz}k`, 6, y - 2)
  }
  g.setLineDash([])
}

/** Boxed label right-aligned just above `y`. */
function tag(g: Ctx, plotW: number, y: number, label: string) {
  const tw = g.measureText(label).width
  g.fillStyle = "rgba(0,0,0,0.6)"
  g.fillRect(plotW - tw - 16, y - 20, tw + 10, 18)
  g.fillStyle = "#fff"
  g.fillText(label, plotW - tw - 11, y - 4)
}

/** The detected cut-off as a bold dashed line, plus the 16 kHz shelf when found. */
export function drawCutoff(g: Ctx, geo: Geo, a: Pick<Analysis, "cutoffHz" | "shelf16k">) {
  const { view, plotW, yOf } = geo
  if (!a.cutoffHz || a.cutoffHz < view.f0 || a.cutoffHz > view.f1) return
  const y = crisp(yOf(a.cutoffHz))
  g.strokeStyle = "rgba(255,255,255,0.95)"
  g.lineWidth = 1.5
  g.setLineDash([8, 5])
  g.beginPath()
  g.moveTo(0, y)
  g.lineTo(plotW, y)
  g.stroke()
  g.setLineDash([])
  g.font = "600 13px 'Geist Variable', sans-serif"
  g.textBaseline = "bottom"
  tag(g, plotW, y, `Frequency cut-off at ${(a.cutoffHz / 1000).toFixed(1)} kHz`)
  if (a.shelf16k && 16000 >= view.f0 && 16000 <= view.f1) tag(g, plotW, yOf(16000), "Shelf at 16 kHz")
}

/** 99% rolloff per matrix column; gaps where a column is silent. */
export function drawRolloff(g: Ctx, geo: Geo, m: StftMeta, rolloff: Float32Array, color: string) {
  const { xOf, yOf } = geo
  g.strokeStyle = color
  g.lineWidth = 1.25
  g.beginPath()
  let pen = false
  for (let c = 0; c < m.cols; c++) {
    const f = rolloff[c]
    if (!Number.isFinite(f)) {
      pen = false
      continue
    }
    const x = xOf(m.t0 + ((c + 0.5) / m.cols) * (m.t1 - m.t0)),
      y = yOf(f)
    if (pen) g.lineTo(x, y)
    else {
      g.moveTo(x, y)
      pen = true
    }
  }
  g.stroke()
}

export function drawBox(g: Ctx, d: Extract<Drag, { kind: "box" }>) {
  const x = Math.min(d.x0, d.x1),
    y = Math.min(d.y0, d.y1)
  g.fillStyle = "rgba(255,255,255,0.08)"
  g.fillRect(x, y, Math.abs(d.x1 - d.x0), Math.abs(d.y1 - d.y0))
  g.strokeStyle = "rgba(255,255,255,0.85)"
  g.lineWidth = 1
  g.strokeRect(x + 0.5, y + 0.5, Math.abs(d.x1 - d.x0), Math.abs(d.y1 - d.y0))
}

/** Crosshair on the spectrogram; only the vertical line over the waveform. */
export function drawCrosshair(g: Ctx, m: Mouse, plotW: number, h: number) {
  g.strokeStyle = "rgba(255,255,255,0.45)"
  g.lineWidth = 1
  g.beginPath()
  g.moveTo(crisp(m.x), 0)
  g.lineTo(crisp(m.x), h)
  if (m.area === "spec") {
    g.moveTo(0, crisp(m.y))
    g.lineTo(plotW, crisp(m.y))
  }
  g.stroke()
}

export function drawPlayhead(g: Ctx, x: number, h: number) {
  g.strokeStyle = "#fff"
  g.lineWidth = 1.5
  g.beginPath()
  g.moveTo(x, 0)
  g.lineTo(x, h)
  g.stroke()
}

export interface SpecOverlay {
  grid: boolean
  refs: RefLine[] | null
  analysis: Pick<Analysis, "cutoffHz" | "shelf16k"> | null
  rolloff: { meta: StftMeta; values: Float32Array; color: string } | null
  drag: Drag | null
  mouse: Mouse | null
  /** Playhead time, or null without an audio element. */
  playhead: number | null
}

/** Everything drawn over the spectrogram, in paint order. */
export function drawSpecOverlay(g: Ctx, geo: Geo, o: SpecOverlay) {
  const { plotW, specH, xOf } = geo
  g.clearRect(0, 0, plotW, specH)
  if (o.grid) drawGrid(g, geo)
  g.font = SANS_FONT
  if (o.refs) drawRefLines(g, geo, o.refs)
  if (o.analysis) drawCutoff(g, geo, o.analysis)
  if (o.rolloff) drawRolloff(g, geo, o.rolloff.meta, o.rolloff.values, o.rolloff.color)
  if (o.drag?.kind === "box") drawBox(g, o.drag)
  if (o.mouse && !o.drag) drawCrosshair(g, o.mouse, plotW, specH)
  if (o.playhead != null) {
    const x = xOf(o.playhead)
    if (x >= 0 && x <= plotW) drawPlayhead(g, x, specH)
  }
}

/** Selection, cursor line and playhead over the waveform. */
export function drawWaveOverlay(
  g: Ctx,
  geo: Pick<Geometry, "plotW" | "xOf">,
  h: number,
  drag: Drag | null,
  mouse: Mouse | null,
  playhead: number | null,
) {
  const { plotW, xOf } = geo
  g.clearRect(0, 0, plotW, h)
  if (drag?.kind === "wave") {
    const x = Math.min(drag.x0, drag.x1)
    g.fillStyle = "rgba(255,255,255,0.12)"
    g.fillRect(x, 0, Math.abs(drag.x1 - drag.x0), h)
  }
  if (mouse && !drag) {
    // No lineWidth here: it keeps the playhead's from the previous frame.
    g.strokeStyle = "rgba(255,255,255,0.45)"
    g.beginPath()
    g.moveTo(crisp(mouse.x), 0)
    g.lineTo(crisp(mouse.x), h)
    g.stroke()
  }
  if (playhead != null) drawPlayhead(g, xOf(playhead), h)
}
