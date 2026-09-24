import type { Info } from "@/lib/api"
import { baseName } from "@/lib/path"
import { fmtHz, fmtTime, type View } from "@/lib/scale"
import type { Settings } from "@/lib/settings"
import { AXIS_W, RULER_H, WAVE_H } from "./constants"

const TITLE_H = 44

/** The second title line: format, view bounds, display settings, cut-off. */
export function exportCaption(info: Info, view: View, settings: Pick<Settings, "ch" | "scale" | "fft" | "win">) {
  const a = info.analysis
  return `${info.codecName?.toUpperCase()} ${(info.sampleRate / 1000).toFixed(1)} kHz ${info.bits ?? "?"} bit  |  ${fmtTime(view.t0, 0.01)}-${fmtTime(view.t1, 0.01)}  ${fmtHz(view.f0)}-${fmtHz(view.f1)} Hz  |  ${settings.ch} ${settings.scale} FFT ${settings.fft} ${settings.win}  |  cut-off ${a?.cutoffHz ? (a.cutoffHz / 1000).toFixed(2) + " kHz" : "none"}`
}

export interface ExportCanvases {
  ruler: HTMLCanvasElement | null
  wave: HTMLCanvasElement | null
  spec: HTMLCanvasElement | null
  overlay: HTMLCanvasElement | null
  axis: HTMLCanvasElement | null
}

interface ExportArgs {
  canvases: ExportCanvases
  info: Info
  view: View
  settings: Settings
  plotW: number
  specH: number
}

/** PNG of exactly what is on screen: title, ruler, waveform, spectrogram with
 * overlays, Hz axis: a zoomed spectrogram with its context. */
export function renderExportPng({ canvases, info, view, settings, plotW, specH }: ExportArgs): string | null {
  const dpr = window.devicePixelRatio || 1
  const W = plotW + AXIS_W,
    H = TITLE_H + RULER_H + WAVE_H + specH
  const c = document.createElement("canvas")
  c.width = W * dpr
  c.height = H * dpr
  const g = c.getContext("2d")
  if (!g) return null
  g.scale(dpr, dpr)
  g.fillStyle = "#0a0a0a"
  g.fillRect(0, 0, W, H)
  g.fillStyle = "#fafafa"
  g.font = "600 14px 'Geist Variable', sans-serif"
  g.textBaseline = "top"
  g.fillText(baseName(info.path) ?? "", 10, 7)
  g.fillStyle = "#a3a3a3"
  g.font = "12px 'Geist Mono Variable', monospace"
  g.fillText(exportCaption(info, view, settings), 10, 26)
  const put = (el: HTMLCanvasElement | null, x: number, y: number, w: number, h: number) => {
    if (el) g.drawImage(el, x, y, w, h)
  }
  const specY = TITLE_H + RULER_H + WAVE_H
  put(canvases.ruler, 0, TITLE_H, plotW, RULER_H)
  put(canvases.wave, 0, TITLE_H + RULER_H, plotW, WAVE_H)
  put(canvases.spec, 0, specY, plotW, specH)
  put(canvases.overlay, 0, specY, plotW, specH)
  put(canvases.axis, plotW, specY, AXIS_W, specH)
  return c.toDataURL("image/png")
}
