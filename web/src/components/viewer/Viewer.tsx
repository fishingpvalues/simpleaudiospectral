import { useCallback, useEffect, useMemo, useRef, useState } from "react"
import type { Info } from "@/lib/api"
import { overlayColor } from "@/lib/colormaps"
import { activeRefs } from "@/lib/references"
import { fmtHz, fmtTime, type View } from "@/lib/scale"
import type { Settings } from "@/lib/settings"
import { clampView } from "@/lib/view"
import { useElementSize } from "@/hooks/useElementSize"
import { useLatest } from "@/hooks/useLatest"
import type { SetView } from "@/hooks/useViewHistory"
import type { PngRenderer } from "@/hooks/usePngExport"
import { AXIS_W, OVERVIEW_H, RULER_H, WAVE_H } from "./constants"
import { drawFreqAxis, drawRuler } from "./draw/axes"
import { drawSpecOverlay, drawWaveOverlay } from "./draw/overlays"
import { drawSpectrogram } from "./draw/spectrogram"
import { drawOverview, drawWaveform } from "./draw/waveform"
import { renderExportPng } from "./exportPng"
import { makeGeometry, setupCanvas } from "./geometry"
import type { Cursor, Drag, Mouse, Spectrum } from "./types"
import { useColorCache } from "./useColorCache"
import { useInteraction } from "./useInteraction"
import { usePlayheadLoop } from "./usePlayheadLoop"
import { useStft } from "./useStft"
import { useWaveData } from "./useWaveData"

interface ViewerProps {
  info: Info
  settings: Settings
  view: View
  setView: SetView
  audio: HTMLAudioElement | null
  playing: boolean
  onCursor: (c: Cursor | null) => void
  onLoading: (b: boolean) => void
  /** Mean spectrum of the visible view (Audition's "frequency analysis" of a range). */
  onViewSpectrum?: (s: Spectrum | null) => void
  /** Hands the parent a function that renders the current view to a PNG. */
  registerExport?: (fn: PngRenderer | null) => void
}

export function Viewer({
  info,
  settings,
  view,
  setView,
  audio,
  playing,
  onCursor,
  onLoading,
  onViewSpectrum,
  registerExport,
}: ViewerProps) {
  const specWrap = useRef<HTMLDivElement>(null)
  const { w: plotW0, h: specH } = useElementSize(specWrap)
  const plotW = Math.max(0, plotW0)
  const nyq = info.sampleRate / 2
  const dur = info.duration

  const cRuler = useRef<HTMLCanvasElement>(null)
  const cWave = useRef<HTMLCanvasElement>(null)
  const cWaveOver = useRef<HTMLCanvasElement>(null)
  const cSpec = useRef<HTMLCanvasElement>(null)
  const cOver = useRef<HTMLCanvasElement>(null)
  const cAxis = useRef<HTMLCanvasElement>(null)
  const cOverview = useRef<HTMLCanvasElement>(null)

  const dragRef = useRef<Drag | null>(null)
  const mouseRef = useRef<Mouse | null>(null)
  const [tick, setTick] = useState(0) // bumps when fetched data lands
  const redraw = useCallback(() => setTick(t => t + 1), [])
  const { table, invalidate, colorize } = useColorCache({
    path: info.path,
    settings,
    holeTopHz: info.analysis?.cutoffHz ?? info.sampleRate / 2,
    redraw,
  })
  const onStftLand = useCallback(() => {
    invalidate()
    redraw()
  }, [invalidate, redraw])

  const clamp = useCallback((v: View) => clampView(v, dur, nyq), [dur, nyq])
  const apply = useCallback((fn: (v: View) => View) => setView(v => clamp(fn(v))), [setView, clamp])

  // ------------------------------------------------------------- fetching
  const { stftRef, derivedRef } = useStft({
    path: info.path,
    settings,
    view,
    plotW,
    specH,
    onLoading,
    onViewSpectrum,
    onLand: onStftLand,
  })
  const { waveRef, overviewRef } = useWaveData({
    path: info.path,
    ch: settings.ch,
    view,
    duration: dur,
    plotW,
    onLand: redraw,
  })

  // ------------------------------------------------------------- drawing
  const geo = useMemo(() => makeGeometry(view, settings.scale, plotW, specH), [view, settings.scale, plotW, specH])

  useEffect(() => {
    const g = setupCanvas(cSpec.current, plotW, specH)
    if (g) drawSpectrogram(g, geo, stftRef.current, colorize(stftRef.current, derivedRef.current?.rowHz))
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [tick, geo, table])

  useEffect(() => {
    const g = setupCanvas(cWave.current, plotW, WAVE_H)
    if (g) drawWaveform(g, view, plotW, WAVE_H, waveRef.current)
  }, [tick, view, plotW, waveRef])

  useEffect(() => {
    const g = setupCanvas(cRuler.current, plotW, RULER_H)
    if (g) drawRuler(g, geo, RULER_H)
  }, [geo, plotW])

  useEffect(() => {
    const g = setupCanvas(cAxis.current, AXIS_W, specH)
    if (g) drawFreqAxis(g, geo, AXIS_W)
  }, [geo, specH])

  useEffect(() => {
    const g = setupCanvas(cOverview.current, plotW, OVERVIEW_H)
    if (g) drawOverview(g, view, dur, plotW, OVERVIEW_H, overviewRef.current)
  }, [tick, view, plotW, dur, overviewRef])

  // Overlay: grid, reference lines, cutoff, cursor, selection, playhead.
  const paintOverlay = useCallback(() => {
    const g = setupCanvas(cOver.current, plotW, specH)
    if (!g) return
    const sm = stftRef.current,
      ro = derivedRef.current?.rolloff
    drawSpecOverlay(g, geo, {
      grid: settings.grid,
      refs: settings.refs ? activeRefs(settings.refSets) : null,
      analysis: settings.cutoff ? info.analysis : null,
      rolloff:
        settings.rolloff && ro && sm && sm.meta.scale === settings.scale
          ? { meta: sm.meta, values: ro, color: overlayColor(settings.cmap).css }
          : null,
      drag: dragRef.current,
      mouse: mouseRef.current,
      playhead: audio ? audio.currentTime : null,
    })
  }, [plotW, specH, geo, settings, info.analysis, audio, stftRef, derivedRef])

  useEffect(() => {
    paintOverlay()
  }, [paintOverlay, tick])

  const paintWaveOverlay = useCallback(() => {
    const g = setupCanvas(cWaveOver.current, plotW, WAVE_H)
    if (g) drawWaveOverlay(g, geo, WAVE_H, dragRef.current, mouseRef.current, audio ? audio.currentTime : null)
  }, [plotW, geo, audio])

  usePlayheadLoop({
    playing,
    audio,
    follow: settings.follow,
    view,
    apply,
    paintOverlay,
    paintWaveOverlay,
  })

  useEffect(() => {
    paintWaveOverlay()
  })

  // ------------------------------------------------------------- interaction
  // Through a ref: the compiler forbids writing to a prop from a hook callback.
  const audioRef = useLatest(audio)
  const seek = useCallback(
    (t: number) => {
      if (audioRef.current) audioRef.current.currentTime = t
    },
    [audioRef],
  )
  const on = useInteraction({
    geo,
    duration: dur,
    nyquist: nyq,
    setView,
    apply,
    clamp,
    seek,
    stftRef,
    dragRef,
    mouseRef,
    onCursor,
    drawOverlay: paintOverlay,
    drawWaveOverlay: paintWaveOverlay,
    specCanvasRef: cOver,
    axisCanvasRef: cAxis,
    waveCanvasRef: cWaveOver,
  })

  useEffect(() => {
    if (!registerExport) return
    registerExport(() =>
      renderExportPng({
        canvases: {
          ruler: cRuler.current,
          wave: cWave.current,
          spec: cSpec.current,
          overlay: cOver.current,
          axis: cAxis.current,
        },
        info,
        view,
        settings,
        plotW,
        specH,
      }),
    )
    return () => registerExport(null)
  }, [registerExport, plotW, specH, info, view, settings])

  const a = info.analysis
  return (
    <div
      className="grid h-full min-h-0 select-none"
      style={{
        gridTemplateColumns: `1fr ${AXIS_W}px`,
        gridTemplateRows: `${RULER_H}px ${WAVE_H}px 1fr ${OVERVIEW_H}px`,
      }}
    >
      <canvas
        ref={cRuler}
        className="block cursor-pointer"
        style={{ width: plotW, height: RULER_H }}
        aria-hidden="true"
        {...on.ruler}
      />
      <div className="flex items-center justify-center border-l bg-neutral-950 font-mono text-[10px] text-muted-foreground">
        {fmtTime(view.t1 - view.t0, 0.001)}
      </div>

      <div className="relative border-b border-white/10">
        <canvas ref={cWave} className="absolute inset-0" style={{ width: plotW, height: WAVE_H }} aria-hidden="true" />
        <canvas
          ref={cWaveOver}
          className="absolute inset-0 cursor-crosshair"
          style={{ width: plotW, height: WAVE_H }}
          role="img"
          aria-label="Waveform. Click to seek, drag to zoom time."
          {...on.wave}
        />
      </div>
      <div className="flex flex-col justify-between border-b border-l border-white/10 bg-neutral-950 py-1 pl-2 font-mono text-[10px] text-muted-foreground">
        <span>0 dB</span>
        <span>-inf</span>
        <span>0 dB</span>
      </div>

      <div ref={specWrap} className="relative min-h-0 overflow-hidden">
        <canvas ref={cSpec} className="absolute inset-0" style={{ width: plotW, height: specH }} aria-hidden="true" />
        <canvas
          ref={cOver}
          className="absolute inset-0 cursor-crosshair outline-none focus-visible:ring-2 focus-visible:ring-ring"
          style={{ width: plotW, height: specH }}
          tabIndex={0}
          role="img"
          aria-roledescription="spectrogram"
          aria-label={`Spectrogram, ${settings.ch} channel, ${fmtTime(view.t0, 0.1)} to ${fmtTime(view.t1, 0.1)}, ${fmtHz(view.f0)} to ${fmtHz(view.f1)} hertz. ${a?.cutoffHz ? `Detected cut-off ${(a.cutoffHz / 1000).toFixed(1)} kilohertz.` : "No brick-wall cut-off detected."} Plus and minus zoom, arrow keys pan, F fits the track.`}
          {...on.spec}
          onContextMenu={e => e.preventDefault()}
        />
      </div>
      <canvas
        ref={cAxis}
        className="block cursor-ns-resize border-l"
        style={{ width: AXIS_W, height: specH }}
        aria-hidden="true"
        {...on.axis}
      />

      <canvas
        ref={cOverview}
        className="block cursor-grab border-t"
        style={{ width: plotW, height: OVERVIEW_H }}
        role="img"
        aria-label={`Track overview, viewing ${fmtTime(view.t0, 1)} to ${fmtTime(view.t1, 1)} of ${fmtTime(dur, 1)}`}
        {...on.overview}
      />
      <div className="border-t border-l bg-neutral-950" />
    </div>
  )
}
