import { useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState } from "react"
import { api, type Info, type Stft } from "@/lib/api"
import { lut, overlayColor } from "@/lib/colormaps"
import { fmtHz, fmtTime, freqTicks, fToY, RED_REFS, timeTicks, yToF, type View } from "@/lib/scale"
import type { Settings } from "@/App"

export const AXIS_W = 56
const RULER_H = 24
const WAVE_H = 96
const OVERVIEW_H = 36
const MIN_SPAN_T = 0.02
const MIN_SPAN_F = 100

export interface Cursor {
  t: number
  f: number
  db: number | null
  /** Spectrum slice at the cursor: freqs (Hz) and dBFS, bottom to top. */
  slice: { hz: Float32Array; db: Float32Array } | null
}

interface Props {
  info: Info
  settings: Settings
  view: View
  setView: (v: View | ((v: View) => View)) => void
  audio: HTMLAudioElement | null
  playing: boolean
  onCursor: (c: Cursor | null) => void
  onLoading: (b: boolean) => void
  /** Mean spectrum of the visible view (Audition's "frequency analysis" of a range). */
  onViewSpectrum?: (s: { hz: Float32Array; db: Float32Array } | null) => void
  /** Hands the parent a function that renders the current view to a PNG. */
  registerExport?: (fn: (() => string | null) | null) => void
}

type Drag =
  | { kind: "box"; x0: number; y0: number; x1: number; y1: number }
  | { kind: "pan"; x0: number; y0: number; v0: View }
  | { kind: "axis"; y0: number; v0: View }
  | { kind: "overview"; dx: number }
  | { kind: "wave"; x0: number; x1: number }

function useSize(ref: React.RefObject<HTMLElement | null>) {
  const [size, setSize] = useState({ w: 0, h: 0 })
  useLayoutEffect(() => {
    const el = ref.current
    if (!el) return
    const ro = new ResizeObserver(([e]) => setSize({ w: Math.floor(e.contentRect.width), h: Math.floor(e.contentRect.height) }))
    ro.observe(el)
    return () => ro.disconnect()
  }, [ref])
  return size
}

function setupCanvas(c: HTMLCanvasElement | null, w: number, h: number) {
  if (!c || w <= 0 || h <= 0) return null
  const dpr = window.devicePixelRatio || 1
  const W = Math.round(w * dpr), H = Math.round(h * dpr)
  if (c.width !== W || c.height !== H) { c.width = W; c.height = H }
  const g = c.getContext("2d")!
  g.setTransform(dpr, 0, 0, dpr, 0, 0)
  return g
}

export function Viewer({ info, settings, view, setView, audio, playing, onCursor, onLoading, onViewSpectrum, registerExport }: Props) {
  const specWrap = useRef<HTMLDivElement>(null)
  const { w: plotW0, h: specH } = useSize(specWrap)
  const plotW = Math.max(0, plotW0)
  const nyq = info.sampleRate / 2
  const dur = info.duration

  const cRuler = useRef<HTMLCanvasElement>(null)
  const cWave = useRef<HTMLCanvasElement>(null)
  const cSpec = useRef<HTMLCanvasElement>(null)
  const cOver = useRef<HTMLCanvasElement>(null)
  const cAxis = useRef<HTMLCanvasElement>(null)
  const cOverview = useRef<HTMLCanvasElement>(null)

  const stft = useRef<Stft | null>(null)
  const colored = useRef<HTMLCanvasElement | null>(null)
  const wave = useRef<{ t0: number; t1: number; data: Float32Array } | null>(null)
  const overview = useRef<Float32Array | null>(null)
  const drag = useRef<Drag | null>(null)
  const mouse = useRef<{ x: number; y: number; area: "spec" | "wave" } | null>(null)
  const [tick, setTick] = useState(0) // bumps when fetched data lands
  const redraw = useCallback(() => setTick(t => t + 1), [])

  const clampView = useCallback((v: View): View => {
    let { t0, t1, f0, f1 } = v
    let span = Math.min(dur, Math.max(MIN_SPAN_T, t1 - t0))
    if (t0 < 0) t0 = 0
    if (t0 + span > dur) t0 = Math.max(0, dur - span)
    t1 = t0 + span
    let fs = Math.min(nyq, Math.max(MIN_SPAN_F, f1 - f0))
    if (f0 < 0) f0 = 0
    if (f0 + fs > nyq) f0 = Math.max(0, nyq - fs)
    f1 = f0 + fs
    return { t0, t1, f0, f1 }
  }, [dur, nyq])
  const apply = useCallback((fn: (v: View) => View) => setView(v => clampView(fn(v))), [setView, clampView])

  // ------------------------------------------------------------- fetching
  useEffect(() => {
    if (plotW < 16 || specH < 16) return
    const dpr = window.devicePixelRatio || 1
    const ctl = new AbortController()
    const timer = setTimeout(async () => {
      onLoading(true)
      try {
        const s = await api.stft({
          path: info.path, ch: settings.ch, fft: settings.fft, win: settings.win, scale: settings.scale,
          t0: view.t0.toFixed(4), t1: view.t1.toFixed(4), f0: Math.round(view.f0), f1: Math.round(view.f1),
          cols: Math.min(4096, Math.round(plotW * dpr)), rows: Math.min(2048, Math.round(specH * dpr)),
        }, ctl.signal)
        stft.current = s
        colored.current = null
        derive(s)
        redraw()
      } catch (e) {
        if ((e as Error).name !== "AbortError") console.error(e)
      } finally {
        if (!ctl.signal.aborted) onLoading(false)
      }
    }, 90)
    return () => { clearTimeout(timer); ctl.abort() }
  }, [info.path, settings.ch, settings.fft, settings.win, settings.scale, view, plotW, specH, redraw, onLoading])

  useEffect(() => {
    if (plotW < 16) return
    const dpr = window.devicePixelRatio || 1
    const ctl = new AbortController()
    const timer = setTimeout(async () => {
      try {
        const data = await api.wave({ path: info.path, ch: settings.ch, t0: view.t0.toFixed(4), t1: view.t1.toFixed(4),
          cols: Math.min(8192, Math.round(plotW * dpr)) }, ctl.signal)
        wave.current = { t0: view.t0, t1: view.t1, data }
        redraw()
      } catch (e) {
        if ((e as Error).name !== "AbortError") console.error(e)
      }
    }, 60)
    return () => { clearTimeout(timer); ctl.abort() }
  }, [info.path, settings.ch, view.t0, view.t1, plotW, redraw])

  useEffect(() => {
    if (plotW < 16) return
    const ctl = new AbortController()
    api.wave({ path: info.path, ch: "mix", t0: 0, t1: dur, cols: Math.min(4096, plotW) }, ctl.signal)
      .then(d => { overview.current = d; redraw() }).catch(() => {})
    return () => ctl.abort()
  }, [info.path, dur, plotW, redraw])

  useEffect(() => { stft.current = null; wave.current = null; overview.current = null; colored.current = null }, [info.path])

  // Per-view derived series: 99% spectral rolloff per column (a flat line =
  // an encoder lowpass, a line that moves with the music = a real top end),
  // and the mean spectrum of the view for the analysis panel.
  const rolloff = useRef<Float32Array | null>(null)
  const rowHz = useRef<Float32Array | null>(null)
  function derive(s: Stft) {
    const { cols, rows, dbFloor, dbCeil } = s.meta
    const mv = { t0: s.meta.t0, t1: s.meta.t1, f0: s.meta.f0, f1: s.meta.f1 }
    const hz = new Float32Array(rows)
    for (let r = 0; r < rows; r++) hz[r] = yToF((r + 0.5) / rows, mv, s.meta.scale)
    rowHz.current = hz
    const k = (dbCeil - dbFloor) / 255
    const pow = new Float32Array(256)
    for (let v = 0; v < 256; v++) pow[v] = Math.pow(10, (dbFloor + v * k) / 10)
    const ro = new Float32Array(cols)
    const mean = new Float64Array(rows)
    const d = s.data
    for (let c = 0; c < cols; c++) {
      let tot = 0
      for (let r = 0; r < rows; r++) { const p = pow[d[r * cols + c]]; tot += p; mean[r] += p }
      let acc = 0, f = hz[rows - 1]
      for (let r = rows - 1; r >= 0; r--) { acc += pow[d[r * cols + c]]; if (acc >= 0.99 * tot) { f = hz[r]; break } }
      ro[c] = tot > 1e-14 ? f : NaN
    }
    rolloff.current = ro
    if (onViewSpectrum) {
      const outHz = new Float32Array(rows), outDb = new Float32Array(rows)
      for (let r = 0; r < rows; r++) { outHz[rows - 1 - r] = hz[r]; outDb[rows - 1 - r] = 10 * Math.log10(mean[r] / cols + 1e-30) }
      onViewSpectrum({ hz: outHz, db: outDb })
    }
  }

  // ------------------------------------------------------------- colouring
  const table = useMemo(() => lut(settings.cmap, settings.floor, settings.ceil, -160, 0), [settings.cmap, settings.floor, settings.ceil])
  useEffect(() => { colored.current = null; redraw() }, [table, redraw, settings.holes])

  function colorize(): HTMLCanvasElement | null {
    const s = stft.current
    if (!s) return null
    if (colored.current) return colored.current
    const { cols, rows } = s.meta
    const c = document.createElement("canvas")
    c.width = cols; c.height = rows
    const g = c.getContext("2d")!
    const img = g.createImageData(cols, rows)
    const px = new Uint32Array(img.data.buffer)
    const d = s.data
    for (let i = 0; i < d.length; i++) px[i] = table[d[i]]
    // Spectral holes. A lossy encoder drops whole bands in single frames, so
    // a hole is a cell far below what THAT frequency row usually carries
    // relative to the same frame's 12-15.5 kHz level. Measuring against the
    // row's own typical offset means a master that simply rolls off at the
    // top is not flagged; only frame-to-frame dropouts are.
    const hz = rowHz.current
    if (settings.holes && hz) {
      const top = Math.min(s.meta.f1, (info.analysis?.cutoffHz ?? info.sampleRate / 2) - 150)
      const refRows: number[] = [], bandRows: number[] = []
      for (let r = 0; r < rows; r++) {
        if (hz[r] >= 12000 && hz[r] <= 15500) refRows.push(r)
        else if (hz[r] >= 15800 && hz[r] <= top) bandRows.push(r)
      }
      const q = 255 / 160
      const gap = Math.round(24 * q)
      const HOLE = overlayColor(settings.cmap).abgr
      if (refRows.length && bandRows.length) {
        const ref = new Int16Array(cols)
        const tmp: number[] = []
        for (let c = 0; c < cols; c++) {
          tmp.length = 0
          for (const r of refRows) tmp.push(d[r * cols + c])
          tmp.sort((x, y) => x - y)
          ref[c] = tmp[tmp.length >> 1]
        }
        const diffs: number[] = []
        for (const r of bandRows) {
          diffs.length = 0
          for (let c = 0; c < cols; c += 3) if (ref[c] >= 60) diffs.push(d[r * cols + c] - ref[c])
          if (diffs.length < 8) continue
          diffs.sort((x, y) => x - y)
          const typical = diffs[diffs.length >> 1]
          for (let c = 0; c < cols; c++) {
            if (ref[c] < 60) continue // quiet frame: nothing to compare against
            if (d[r * cols + c] - ref[c] < typical - gap) px[r * cols + c] = HOLE
          }
        }
      }
    }
    g.putImageData(img, 0, 0)
    colored.current = c
    return c
  }

  // ------------------------------------------------------------- drawing
  const xOf = useCallback((t: number) => ((t - view.t0) / (view.t1 - view.t0)) * plotW, [view, plotW])
  const tOf = useCallback((x: number) => view.t0 + (x / plotW) * (view.t1 - view.t0), [view, plotW])
  const yOf = useCallback((f: number) => fToY(f, view, settings.scale) * specH, [view, settings.scale, specH])
  const fOf = useCallback((y: number) => yToF(y / specH, view, settings.scale), [view, settings.scale, specH])

  // Base spectrogram. The last matrix is drawn transformed into the current
  // view, so pan and zoom feel instant while the exact one is being fetched.
  useEffect(() => {
    const g = setupCanvas(cSpec.current, plotW, specH)
    if (!g) return
    g.fillStyle = "#000"
    g.fillRect(0, 0, plotW, specH)
    const s = stft.current
    const img = colorize()
    if (!s || !img) return
    const m = s.meta
    if (m.scale !== settings.scale) return
    const dx = xOf(m.t0), dw = xOf(m.t1) - dx
    const dy = yOf(m.f1), dh = yOf(m.f0) - dy
    g.imageSmoothingEnabled = dw < m.cols || dh < m.rows
    g.drawImage(img, dx, dy, dw, dh)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [tick, view, plotW, specH, settings.scale, table])

  // Waveform
  useEffect(() => {
    const g = setupCanvas(cWave.current, plotW, WAVE_H)
    if (!g) return
    g.fillStyle = "#000"; g.fillRect(0, 0, plotW, WAVE_H)
    const mid = WAVE_H / 2, amp = WAVE_H / 2 - 4
    g.strokeStyle = "rgba(255,255,255,0.08)"; g.lineWidth = 1
    for (const lv of [-6, -12]) {
      const a = Math.pow(10, lv / 20) * amp
      g.beginPath(); g.moveTo(0, mid - a); g.lineTo(plotW, mid - a); g.moveTo(0, mid + a); g.lineTo(plotW, mid + a); g.stroke()
    }
    g.strokeStyle = "rgba(255,255,255,0.18)"
    g.beginPath(); g.moveTo(0, mid); g.lineTo(plotW, mid); g.stroke()
    const wv = wave.current
    if (wv) {
      const n = wv.data.length / 2
      const x0 = ((wv.t0 - view.t0) / (view.t1 - view.t0)) * plotW
      const xs = ((wv.t1 - wv.t0) / (view.t1 - view.t0)) * plotW / n
      g.fillStyle = "#e5e5e5"
      for (let i = 0; i < n; i++) {
        const lo = wv.data[2 * i], hi = wv.data[2 * i + 1]
        const x = x0 + i * xs
        if (x < -2 || x > plotW + 2) continue
        const y1 = mid - Math.min(1, hi) * amp, y2 = mid - Math.max(-1, lo) * amp
        g.fillRect(x, y1, Math.max(1, xs), Math.max(1, y2 - y1))
      }
      // clipped samples in red
      g.fillStyle = "#ef4444"
      for (let i = 0; i < n; i++) {
        if (wv.data[2 * i + 1] >= 0.999 || wv.data[2 * i] <= -0.999) g.fillRect(x0 + i * xs, 0, Math.max(1, xs), 3)
      }
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [tick, view, plotW])

  // Ruler
  useEffect(() => {
    const g = setupCanvas(cRuler.current, plotW, RULER_H)
    if (!g) return
    g.fillStyle = "#0a0a0a"; g.fillRect(0, 0, plotW, RULER_H)
    const { step, ticks } = timeTicks(view.t0, view.t1, plotW)
    g.font = "11px 'Geist Mono Variable', monospace"; g.textBaseline = "top"
    for (const t of ticks) {
      const x = Math.round(xOf(t)) + 0.5
      g.strokeStyle = "rgba(255,255,255,0.35)"
      g.beginPath(); g.moveTo(x, RULER_H - 7); g.lineTo(x, RULER_H); g.stroke()
      g.fillStyle = "#a3a3a3"; g.fillText(fmtTime(t, step), x + 3, 5)
      for (let k = 1; k < 5; k++) {
        const xm = Math.round(xOf(t + (k * step) / 5)) + 0.5
        g.strokeStyle = "rgba(255,255,255,0.15)"
        g.beginPath(); g.moveTo(xm, RULER_H - 3); g.lineTo(xm, RULER_H); g.stroke()
      }
    }
  }, [view, plotW, xOf])

  // Frequency axis (right, like Audition)
  useEffect(() => {
    const g = setupCanvas(cAxis.current, AXIS_W, specH)
    if (!g) return
    g.fillStyle = "#0a0a0a"; g.fillRect(0, 0, AXIS_W, specH)
    g.font = "11px 'Geist Mono Variable', monospace"; g.textBaseline = "middle"
    let lastY = -100
    for (const f of freqTicks(view, settings.scale, specH).reverse()) {
      const y = Math.round(yOf(f)) + 0.5
      if (y - lastY < 13 || y < 16) continue
      lastY = y
      g.strokeStyle = "rgba(255,255,255,0.35)"
      g.beginPath(); g.moveTo(0, y); g.lineTo(5, y); g.stroke()
      g.fillStyle = f % 1000 === 0 && f >= 10000 ? "#fafafa" : "#a3a3a3"
      g.fillText(fmtHz(f), 9, y)
    }
    g.fillStyle = "#737373"; g.fillText("Hz", 9, 8)
  }, [view, settings.scale, specH, yOf])

  // Overview: whole track, viewport rectangle
  useEffect(() => {
    const g = setupCanvas(cOverview.current, plotW, OVERVIEW_H)
    if (!g) return
    g.fillStyle = "#050505"; g.fillRect(0, 0, plotW, OVERVIEW_H)
    const d = overview.current
    if (d) {
      const n = d.length / 2, mid = OVERVIEW_H / 2, amp = OVERVIEW_H / 2 - 3
      g.fillStyle = "#525252"
      for (let i = 0; i < n; i++) {
        const y1 = mid - d[2 * i + 1] * amp, y2 = mid - d[2 * i] * amp
        g.fillRect((i / n) * plotW, y1, Math.max(1, plotW / n), Math.max(1, y2 - y1))
      }
    }
    const x0 = (view.t0 / dur) * plotW, x1 = (view.t1 / dur) * plotW
    g.fillStyle = "rgba(255,255,255,0.08)"; g.fillRect(x0, 0, Math.max(2, x1 - x0), OVERVIEW_H)
    g.strokeStyle = "rgba(255,255,255,0.7)"; g.lineWidth = 1
    g.strokeRect(Math.round(x0) + 0.5, 0.5, Math.max(2, Math.round(x1 - x0) - 1), OVERVIEW_H - 1)
  }, [tick, view, plotW, dur])

  // Overlay: grid, reference lines, cutoff, cursor, selection, playhead.
  const drawOverlay = useCallback(() => {
    const g = setupCanvas(cOver.current, plotW, specH)
    if (!g) return
    g.clearRect(0, 0, plotW, specH)
    const a = info.analysis
    if (settings.grid) {
      g.strokeStyle = "rgba(255,255,255,0.07)"; g.lineWidth = 1
      g.beginPath()
      for (const f of freqTicks(view, settings.scale, specH)) { const y = Math.round(yOf(f)) + 0.5; g.moveTo(0, y); g.lineTo(plotW, y) }
      for (const t of timeTicks(view.t0, view.t1, plotW).ticks) { const x = Math.round(xOf(t)) + 0.5; g.moveTo(x, 0); g.lineTo(x, specH) }
      g.stroke()
    }
    g.font = "11px 'Geist Variable', sans-serif"
    if (settings.refs) {
      g.setLineDash([2, 4]); g.lineWidth = 1
      let lastLabel = -100
      for (const r of RED_REFS) {
        const f = r.khz * 1000
        if (f < view.f0 || f > view.f1) continue
        const y = Math.round(yOf(f)) + 0.5
        g.strokeStyle = "rgba(255,255,255,0.28)"
        g.beginPath(); g.moveTo(0, y); g.lineTo(plotW, y); g.stroke()
        if (Math.abs(y - lastLabel) < 13) continue // lines stay, crowded labels go
        lastLabel = y
        g.fillStyle = "rgba(255,255,255,0.6)"; g.textBaseline = "bottom"
        g.fillText(`${r.label}  ${r.khz}k`, 6, y - 2)
      }
      g.setLineDash([])
    }
    if (settings.cutoff && a?.cutoffHz && a.cutoffHz >= view.f0 && a.cutoffHz <= view.f1) {
      const y = Math.round(yOf(a.cutoffHz)) + 0.5
      g.strokeStyle = "rgba(255,255,255,0.95)"; g.lineWidth = 1.5; g.setLineDash([8, 5])
      g.beginPath(); g.moveTo(0, y); g.lineTo(plotW, y); g.stroke(); g.setLineDash([])
      const label = `Frequency cut-off at ${(a.cutoffHz / 1000).toFixed(1)} kHz`
      g.font = "600 13px 'Geist Variable', sans-serif"; g.textBaseline = "bottom"
      const tw = g.measureText(label).width
      g.fillStyle = "rgba(0,0,0,0.6)"; g.fillRect(plotW - tw - 16, y - 20, tw + 10, 18)
      g.fillStyle = "#fff"; g.fillText(label, plotW - tw - 11, y - 4)
      if (a.shelf16k && 16000 >= view.f0 && 16000 <= view.f1) {
        const ys = yOf(16000), l2 = "Shelf at 16 kHz"
        const w2 = g.measureText(l2).width
        g.fillStyle = "rgba(0,0,0,0.6)"; g.fillRect(plotW - w2 - 16, ys - 20, w2 + 10, 18)
        g.fillStyle = "#fff"; g.fillText(l2, plotW - w2 - 11, ys - 4)
      }
    }
    const ro = rolloff.current, sm = stft.current
    if (settings.rolloff && ro && sm && sm.meta.scale === settings.scale) {
      const m = sm.meta
      g.strokeStyle = overlayColor(settings.cmap).css; g.lineWidth = 1.25; g.beginPath()
      let pen = false
      for (let c = 0; c < m.cols; c++) {
        const f = ro[c]
        if (!Number.isFinite(f)) { pen = false; continue }
        const x = xOf(m.t0 + ((c + 0.5) / m.cols) * (m.t1 - m.t0)), y = yOf(f)
        if (pen) g.lineTo(x, y); else { g.moveTo(x, y); pen = true }
      }
      g.stroke()
    }
    const d = drag.current
    if (d?.kind === "box") {
      const x = Math.min(d.x0, d.x1), y = Math.min(d.y0, d.y1)
      g.fillStyle = "rgba(255,255,255,0.08)"; g.fillRect(x, y, Math.abs(d.x1 - d.x0), Math.abs(d.y1 - d.y0))
      g.strokeStyle = "rgba(255,255,255,0.85)"; g.lineWidth = 1
      g.strokeRect(x + 0.5, y + 0.5, Math.abs(d.x1 - d.x0), Math.abs(d.y1 - d.y0))
    }
    const m = mouse.current
    if (m && !d) {
      g.strokeStyle = "rgba(255,255,255,0.45)"; g.lineWidth = 1
      g.beginPath()
      g.moveTo(Math.round(m.x) + 0.5, 0); g.lineTo(Math.round(m.x) + 0.5, specH)
      if (m.area === "spec") { g.moveTo(0, Math.round(m.y) + 0.5); g.lineTo(plotW, Math.round(m.y) + 0.5) }
      g.stroke()
    }
    if (audio) {
      const x = xOf(audio.currentTime)
      if (x >= 0 && x <= plotW) {
        g.strokeStyle = "#fff"; g.lineWidth = 1.5
        g.beginPath(); g.moveTo(x, 0); g.lineTo(x, specH); g.stroke()
      }
    }
  }, [plotW, specH, view, settings, info.analysis, xOf, yOf, audio])

  useEffect(() => { drawOverlay() }, [drawOverlay, tick])

  // Playhead animation + follow.
  useEffect(() => {
    if (!playing || !audio) return
    let raf = 0
    const loop = () => {
      const t = audio.currentTime
      if (settings.follow && (t > view.t1 || t < view.t0)) {
        const span = view.t1 - view.t0
        apply(v => ({ ...v, t0: t - span * 0.05, t1: t - span * 0.05 + span }))
      }
      drawOverlay()
      drawWavePlayhead()
      raf = requestAnimationFrame(loop)
    }
    raf = requestAnimationFrame(loop)
    return () => cancelAnimationFrame(raf)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [playing, audio, drawOverlay, view, settings.follow])

  const wavePlayhead = useRef<HTMLCanvasElement>(null)
  function drawWavePlayhead() {
    const g = setupCanvas(wavePlayhead.current, plotW, WAVE_H)
    if (!g) return
    g.clearRect(0, 0, plotW, WAVE_H)
    const d = drag.current
    if (d?.kind === "wave") {
      const x = Math.min(d.x0, d.x1)
      g.fillStyle = "rgba(255,255,255,0.12)"; g.fillRect(x, 0, Math.abs(d.x1 - d.x0), WAVE_H)
    }
    const m = mouse.current
    if (m && !d) {
      g.strokeStyle = "rgba(255,255,255,0.45)"
      g.beginPath(); g.moveTo(Math.round(m.x) + 0.5, 0); g.lineTo(Math.round(m.x) + 0.5, WAVE_H); g.stroke()
    }
    if (audio) {
      const x = xOf(audio.currentTime)
      g.strokeStyle = "#fff"; g.lineWidth = 1.5
      g.beginPath(); g.moveTo(x, 0); g.lineTo(x, WAVE_H); g.stroke()
    }
  }
  useEffect(() => { drawWavePlayhead() })

  // ------------------------------------------------------------- cursor
  const report = useCallback((x: number, y: number | null) => {
    const t = tOf(x)
    if (y === null) { onCursor({ t, f: NaN, db: null, slice: null }); return }
    const f = fOf(y)
    const s = stft.current
    let db: number | null = null, slice: Cursor["slice"] = null
    if (s && s.meta.scale === settings.scale && t >= s.meta.t0 && t <= s.meta.t1) {
      const m = s.meta
      const col = Math.min(m.cols - 1, Math.max(0, Math.floor(((t - m.t0) / (m.t1 - m.t0)) * m.cols)))
      const mv = { t0: m.t0, t1: m.t1, f0: m.f0, f1: m.f1 }
      const row = Math.min(m.rows - 1, Math.max(0, Math.floor(fToY(f, mv, m.scale) * m.rows)))
      const k = (m.dbCeil - m.dbFloor) / 255
      db = m.dbFloor + s.data[row * m.cols + col] * k
      const hz = new Float32Array(m.rows), dbs = new Float32Array(m.rows)
      for (let r = 0; r < m.rows; r++) {
        const rr = m.rows - 1 - r
        hz[r] = yToF((rr + 0.5) / m.rows, mv, m.scale)
        dbs[r] = m.dbFloor + s.data[rr * m.cols + col] * k
      }
      slice = { hz, db: dbs }
    }
    onCursor({ t, f, db, slice })
  }, [tOf, fOf, onCursor, settings.scale])

  // ------------------------------------------------------------- interaction
  const local = (e: { clientX: number; clientY: number }, el: HTMLElement) => {
    const r = el.getBoundingClientRect()
    return { x: e.clientX - r.left, y: e.clientY - r.top }
  }

  const zoomTime = useCallback((factor: number, anchorT: number) => apply(v => {
    const span = Math.max(MIN_SPAN_T, Math.min(dur, (v.t1 - v.t0) * factor))
    const u = (anchorT - v.t0) / (v.t1 - v.t0)
    return { ...v, t0: anchorT - u * span, t1: anchorT - u * span + span }
  }), [apply, dur])

  const zoomFreq = useCallback((factor: number, anchorY: number) => apply(v => {
    const f = yToF(anchorY / specH, v, settings.scale)
    const span = Math.max(MIN_SPAN_F, Math.min(nyq, (v.f1 - v.f0) * factor))
    const u = (v.f1 - f) / (v.f1 - v.f0)
    const f1 = f + u * span
    return { ...v, f1, f0: f1 - span }
  }), [apply, nyq, specH, settings.scale])

  // Wheel needs passive:false to preventDefault, so attach natively.
  useEffect(() => {
    const el = cOver.current, ax = cAxis.current, wv = wavePlayhead.current
    if (!el || !ax || !wv) return
    const onWheel = (e: WheelEvent) => {
      e.preventDefault()
      const { x, y } = local(e, e.currentTarget as HTMLElement)
      if (Math.abs(e.deltaX) > Math.abs(e.deltaY) && !e.ctrlKey) {
        const dt = (e.deltaX / plotW) * (view.t1 - view.t0)
        apply(v => ({ ...v, t0: v.t0 + dt, t1: v.t1 + dt }))
      } else if (e.shiftKey) {
        const dt = (e.deltaY / plotW) * (view.t1 - view.t0)
        apply(v => ({ ...v, t0: v.t0 + dt, t1: v.t1 + dt }))
      } else if (e.altKey && e.currentTarget === el) {
        zoomFreq(Math.exp(e.deltaY * 0.002), y)
      } else {
        zoomTime(Math.exp(e.deltaY * (e.ctrlKey ? 0.01 : 0.002)), tOf(x))
      }
    }
    const onAxisWheel = (e: WheelEvent) => {
      e.preventDefault()
      zoomFreq(Math.exp(e.deltaY * 0.002), local(e, ax).y)
    }
    el.addEventListener("wheel", onWheel, { passive: false })
    wv.addEventListener("wheel", onWheel, { passive: false })
    ax.addEventListener("wheel", onAxisWheel, { passive: false })
    return () => {
      el.removeEventListener("wheel", onWheel)
      wv.removeEventListener("wheel", onWheel)
      ax.removeEventListener("wheel", onAxisWheel)
    }
  }, [apply, zoomTime, zoomFreq, tOf, plotW, view])

  const onSpecDown = (e: React.PointerEvent<HTMLCanvasElement>) => {
    const { x, y } = local(e, e.currentTarget)
    e.currentTarget.setPointerCapture(e.pointerId)
    drag.current = e.shiftKey || e.button === 1 || e.button === 2
      ? { kind: "pan", x0: x, y0: y, v0: view }
      : { kind: "box", x0: x, y0: y, x1: x, y1: y }
  }
  const onSpecMove = (e: React.PointerEvent<HTMLCanvasElement>) => {
    const { x, y } = local(e, e.currentTarget)
    mouse.current = { x, y, area: "spec" }
    const d = drag.current
    if (d?.kind === "box") { d.x1 = Math.max(0, Math.min(plotW, x)); d.y1 = Math.max(0, Math.min(specH, y)) }
    if (d?.kind === "pan") {
      const dt = ((d.x0 - x) / plotW) * (d.v0.t1 - d.v0.t0)
      const lin = settings.scale === "linear"
      const df = lin ? ((y - d.y0) / specH) * (d.v0.f1 - d.v0.f0) : 0
      setView(clampView({ t0: d.v0.t0 + dt, t1: d.v0.t1 + dt, f0: d.v0.f0 + df, f1: d.v0.f1 + df }))
    }
    report(x, y)
    drawOverlay(); drawWavePlayhead()
  }
  const onSpecUp = (e: React.PointerEvent<HTMLCanvasElement>) => {
    const d = drag.current
    drag.current = null
    if (d?.kind === "box") {
      const w = Math.abs(d.x1 - d.x0), h = Math.abs(d.y1 - d.y0)
      if (w > 6) {
        const ta = tOf(Math.min(d.x0, d.x1)), tb = tOf(Math.max(d.x0, d.x1))
        if (h > 6) {
          const fa = fOf(Math.max(d.y0, d.y1)), fb = fOf(Math.min(d.y0, d.y1))
          apply(() => ({ t0: ta, t1: tb, f0: fa, f1: fb }))
        } else apply(v => ({ ...v, t0: ta, t1: tb }))
      } else if (audio) {
        audio.currentTime = tOf(local(e, e.currentTarget).x)
      }
    }
    drawOverlay()
  }
  const onLeave = () => { mouse.current = null; onCursor(null); drawOverlay(); drawWavePlayhead() }

  const onWaveDown = (e: React.PointerEvent<HTMLCanvasElement>) => {
    const { x } = local(e, e.currentTarget)
    e.currentTarget.setPointerCapture(e.pointerId)
    drag.current = { kind: "wave", x0: x, x1: x }
  }
  const onWaveMove = (e: React.PointerEvent<HTMLCanvasElement>) => {
    const { x } = local(e, e.currentTarget)
    mouse.current = { x, y: 0, area: "wave" }
    const d = drag.current
    if (d?.kind === "wave") d.x1 = Math.max(0, Math.min(plotW, x))
    report(x, null)
    drawOverlay(); drawWavePlayhead()
  }
  const onWaveUp = (e: React.PointerEvent<HTMLCanvasElement>) => {
    const d = drag.current
    drag.current = null
    if (d?.kind === "wave") {
      if (Math.abs(d.x1 - d.x0) > 6) {
        const ta = tOf(Math.min(d.x0, d.x1)), tb = tOf(Math.max(d.x0, d.x1))
        apply(v => ({ ...v, t0: ta, t1: tb }))
      } else if (audio) audio.currentTime = tOf(local(e, e.currentTarget).x)
    }
    drawWavePlayhead()
  }

  const onAxisDown = (e: React.PointerEvent<HTMLCanvasElement>) => {
    e.currentTarget.setPointerCapture(e.pointerId)
    drag.current = { kind: "axis", y0: local(e, e.currentTarget).y, v0: view }
  }
  const onAxisMove = (e: React.PointerEvent<HTMLCanvasElement>) => {
    const d = drag.current
    if (d?.kind !== "axis") return
    const y = local(e, e.currentTarget).y
    const df = ((y - d.y0) / specH) * (d.v0.f1 - d.v0.f0)
    setView(clampView({ ...d.v0, f0: d.v0.f0 + df, f1: d.v0.f1 + df }))
  }

  const onOverviewDown = (e: React.PointerEvent<HTMLCanvasElement>) => {
    e.currentTarget.setPointerCapture(e.pointerId)
    const x = local(e, e.currentTarget).x
    const x0 = (view.t0 / dur) * plotW, x1 = (view.t1 / dur) * plotW
    if (x >= x0 && x <= x1) drag.current = { kind: "overview", dx: x - x0 }
    else {
      const span = view.t1 - view.t0, t = (x / plotW) * dur
      apply(v => ({ ...v, t0: t - span / 2, t1: t + span / 2 }))
      drag.current = { kind: "overview", dx: (span / 2 / dur) * plotW }
    }
  }
  const onOverviewMove = (e: React.PointerEvent<HTMLCanvasElement>) => {
    const d = drag.current
    if (d?.kind !== "overview") return
    const x = local(e, e.currentTarget).x
    const t0 = ((x - d.dx) / plotW) * dur
    apply(v => ({ ...v, t0, t1: t0 + (v.t1 - v.t0) }))
  }
  const endDrag = () => { drag.current = null }

  const fitAll = () => setView({ t0: 0, t1: dur, f0: 0, f1: nyq })

  // PNG of exactly what is on screen: title, ruler, waveform, spectrogram with
  // overlays, Hz axis. This is the "zoomed spectral" a reviewer asks for.
  useEffect(() => {
    if (!registerExport) return
    registerExport(() => {
      const dpr = window.devicePixelRatio || 1
      const TITLE = 44, W = plotW + AXIS_W, H = TITLE + RULER_H + WAVE_H + specH
      const c = document.createElement("canvas")
      c.width = W * dpr; c.height = H * dpr
      const g = c.getContext("2d")
      if (!g) return null
      g.scale(dpr, dpr)
      g.fillStyle = "#0a0a0a"; g.fillRect(0, 0, W, H)
      g.fillStyle = "#fafafa"; g.font = "600 14px 'Geist Variable', sans-serif"; g.textBaseline = "top"
      g.fillText(info.path.split("/").pop() ?? "", 10, 7)
      g.fillStyle = "#a3a3a3"; g.font = "12px 'Geist Mono Variable', monospace"
      const a = info.analysis
      g.fillText(`${info.codecName?.toUpperCase()} ${(info.sampleRate / 1000).toFixed(1)} kHz ${info.bits ?? "?"} bit  |  ${fmtTime(view.t0, 0.01)}-${fmtTime(view.t1, 0.01)}  ${fmtHz(view.f0)}-${fmtHz(view.f1)} Hz  |  ${settings.ch} ${settings.scale} FFT ${settings.fft} ${settings.win}  |  cut-off ${a?.cutoffHz ? (a.cutoffHz / 1000).toFixed(2) + " kHz" : "none"}`, 10, 26)
      const put = (el: HTMLCanvasElement | null, x: number, y: number, w: number, h: number) => { if (el) g.drawImage(el, x, y, w, h) }
      put(cRuler.current, 0, TITLE, plotW, RULER_H)
      put(cWave.current, 0, TITLE + RULER_H, plotW, WAVE_H)
      put(cSpec.current, 0, TITLE + RULER_H + WAVE_H, plotW, specH)
      put(cOver.current, 0, TITLE + RULER_H + WAVE_H, plotW, specH)
      put(cAxis.current, plotW, TITLE + RULER_H + WAVE_H, AXIS_W, specH)
      return c.toDataURL("image/png")
    })
    return () => registerExport(null)
  }, [registerExport, plotW, specH, info, view, settings])

  return (
    <div className="grid h-full min-h-0 select-none" style={{ gridTemplateColumns: `1fr ${AXIS_W}px`, gridTemplateRows: `${RULER_H}px ${WAVE_H}px 1fr ${OVERVIEW_H}px` }}>
      <canvas ref={cRuler} className="block cursor-pointer" style={{ width: plotW, height: RULER_H }} aria-hidden="true"
        onPointerDown={e => { if (audio) audio.currentTime = tOf(local(e, e.currentTarget).x) }} />
      <div className="flex items-center justify-center border-l bg-neutral-950 font-mono text-[10px] text-muted-foreground">
        {fmtTime(view.t1 - view.t0, 0.001)}
      </div>

      <div className="relative border-b border-white/10">
        <canvas ref={cWave} className="absolute inset-0" style={{ width: plotW, height: WAVE_H }} aria-hidden="true" />
        <canvas ref={wavePlayhead} className="absolute inset-0 cursor-crosshair" style={{ width: plotW, height: WAVE_H }}
          role="img" aria-label="Waveform. Click to seek, drag to zoom time."
          onPointerDown={onWaveDown} onPointerMove={onWaveMove} onPointerUp={onWaveUp} onPointerLeave={onLeave} onDoubleClick={fitAll} />
      </div>
      <div className="flex flex-col justify-between border-b border-l border-white/10 bg-neutral-950 py-1 pl-2 font-mono text-[10px] text-muted-foreground">
        <span>0 dB</span><span>-inf</span><span>0 dB</span>
      </div>

      <div ref={specWrap} className="relative min-h-0 overflow-hidden">
        <canvas ref={cSpec} className="absolute inset-0" style={{ width: plotW, height: specH }} aria-hidden="true" />
        <canvas ref={cOver} className="absolute inset-0 cursor-crosshair outline-none focus-visible:ring-2 focus-visible:ring-ring" style={{ width: plotW, height: specH }}
          tabIndex={0} role="img" aria-roledescription="spectrogram"
          aria-label={`Spectrogram, ${settings.ch} channel, ${fmtTime(view.t0, 0.1)} to ${fmtTime(view.t1, 0.1)}, ${fmtHz(view.f0)} to ${fmtHz(view.f1)} hertz. ${info.analysis?.cutoffHz ? `Detected cut-off ${(info.analysis.cutoffHz / 1000).toFixed(1)} kilohertz.` : "No brick-wall cut-off detected."} Plus and minus zoom, arrow keys pan, F fits the track.`}
          onPointerDown={onSpecDown} onPointerMove={onSpecMove} onPointerUp={onSpecUp} onPointerLeave={onLeave}
          onDoubleClick={fitAll} onContextMenu={e => e.preventDefault()} />
      </div>
      <canvas ref={cAxis} className="block cursor-ns-resize border-l" style={{ width: AXIS_W, height: specH }} aria-hidden="true"
        onPointerDown={onAxisDown} onPointerMove={onAxisMove} onPointerUp={endDrag}
        onDoubleClick={() => apply(v => ({ ...v, f0: 0, f1: nyq }))} />

      <canvas ref={cOverview} className="block cursor-grab border-t" style={{ width: plotW, height: OVERVIEW_H }}
        role="img" aria-label={`Track overview, viewing ${fmtTime(view.t0, 1)} to ${fmtTime(view.t1, 1)} of ${fmtTime(dur, 1)}`}
        onPointerDown={onOverviewDown} onPointerMove={onOverviewMove} onPointerUp={endDrag} />
      <div className="border-t border-l bg-neutral-950" />
    </div>
  )
}
