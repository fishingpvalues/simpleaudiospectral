import { useCallback, useEffect, type PointerEvent, type RefObject } from "react"
import type { Stft } from "@/lib/api"
import type { View } from "@/lib/scale"
import { zoomFreqAt, zoomTimeAt } from "@/lib/view"
import type { SetView } from "@/hooks/useViewHistory"
import { CLICK_SLOP } from "./constants"
import { readCursor } from "./derive"
import { overviewSpan } from "./draw/waveform"
import { localPoint, type Geometry } from "./geometry"
import type { Cursor, Drag, Mouse } from "./types"

type CanvasPointer = PointerEvent<HTMLCanvasElement>

interface UseInteractionArgs {
  geo: Geometry
  duration: number
  nyquist: number
  setView: SetView
  /** setView through clampView. */
  apply: (fn: (v: View) => View) => void
  clamp: (v: View) => View
  /** Moves the playhead; a no-op without an audio element. */
  seek: (t: number) => void
  stftRef: RefObject<Stft | null>
  dragRef: RefObject<Drag | null>
  mouseRef: RefObject<Mouse | null>
  onCursor: (c: Cursor | null) => void
  drawOverlay: () => void
  drawWaveOverlay: () => void
  /** Canvases that take wheel events. */
  specCanvasRef: RefObject<HTMLCanvasElement | null>
  axisCanvasRef: RefObject<HTMLCanvasElement | null>
  waveCanvasRef: RefObject<HTMLCanvasElement | null>
}

/** Pointer and wheel handling for the viewer: box zoom, pan, seek, axis drag,
 * overview drag, and the cursor readout. */
export function useInteraction({
  geo,
  duration,
  nyquist,
  setView,
  apply,
  clamp,
  seek,
  stftRef,
  dragRef,
  mouseRef,
  onCursor,
  drawOverlay,
  drawWaveOverlay,
  specCanvasRef,
  axisCanvasRef,
  waveCanvasRef,
}: UseInteractionArgs) {
  const { view, scale, plotW, specH, tOf, fOf } = geo

  const report = useCallback(
    (x: number, y: number | null) => {
      const t = tOf(x)
      if (y === null) {
        onCursor({ t, f: NaN, db: null, slice: null })
        return
      }
      const f = fOf(y)
      onCursor({ t, f, ...readCursor(stftRef.current, t, f, scale) })
    },
    [tOf, fOf, onCursor, scale, stftRef],
  )

  const zoomTime = useCallback(
    (factor: number, anchorT: number) => apply(v => zoomTimeAt(v, factor, anchorT, duration)),
    [apply, duration],
  )
  const zoomFreq = useCallback(
    (factor: number, anchorY: number) => apply(v => zoomFreqAt(v, factor, anchorY / specH, scale, nyquist)),
    [apply, nyquist, specH, scale],
  )

  // Wheel needs passive:false to preventDefault, so attach natively.
  useEffect(() => {
    const el = specCanvasRef.current,
      ax = axisCanvasRef.current,
      wv = waveCanvasRef.current
    if (!el || !ax || !wv) return
    const onWheel = (e: WheelEvent) => {
      e.preventDefault()
      const { x, y } = localPoint(e, e.currentTarget as HTMLElement)
      if (Math.abs(e.deltaX) > Math.abs(e.deltaY) && !e.ctrlKey) {
        const dt = (e.deltaX / plotW) * (view.t1 - view.t0)
        apply(v => ({ ...v, t0: v.t0 + dt, t1: v.t1 + dt }))
      } else if (e.shiftKey) {
        const dt = (e.deltaY / plotW) * (view.t1 - view.t0)
        apply(v => ({ ...v, t0: v.t0 + dt, t1: v.t1 + dt }))
      } else if (e.altKey && e.currentTarget === el) {
        zoomFreq(Math.exp(e.deltaY * 0.002), y)
      } else {
        // Ctrl+wheel is the trackpad pinch: zoom faster.
        zoomTime(Math.exp(e.deltaY * (e.ctrlKey ? 0.01 : 0.002)), tOf(x))
      }
    }
    const onAxisWheel = (e: WheelEvent) => {
      e.preventDefault()
      zoomFreq(Math.exp(e.deltaY * 0.002), localPoint(e, ax).y)
    }
    el.addEventListener("wheel", onWheel, { passive: false })
    wv.addEventListener("wheel", onWheel, { passive: false })
    ax.addEventListener("wheel", onAxisWheel, { passive: false })
    return () => {
      el.removeEventListener("wheel", onWheel)
      wv.removeEventListener("wheel", onWheel)
      ax.removeEventListener("wheel", onAxisWheel)
    }
  }, [apply, zoomTime, zoomFreq, tOf, plotW, view, specCanvasRef, axisCanvasRef, waveCanvasRef])

  const seekTo = (e: CanvasPointer) => {
    seek(tOf(localPoint(e, e.currentTarget).x))
  }
  const fitAll = () => setView({ t0: 0, t1: duration, f0: 0, f1: nyquist })
  const endDrag = () => {
    dragRef.current = null
  }

  const spec = {
    onPointerDown: (e: CanvasPointer) => {
      const { x, y } = localPoint(e, e.currentTarget)
      e.currentTarget.setPointerCapture(e.pointerId)
      dragRef.current =
        e.shiftKey || e.button === 1 || e.button === 2
          ? { kind: "pan", x0: x, y0: y, v0: view }
          : { kind: "box", x0: x, y0: y, x1: x, y1: y }
    },
    onPointerMove: (e: CanvasPointer) => {
      const { x, y } = localPoint(e, e.currentTarget)
      mouseRef.current = { x, y, area: "spec" }
      const d = dragRef.current
      if (d?.kind === "box") {
        d.x1 = Math.max(0, Math.min(plotW, x))
        d.y1 = Math.max(0, Math.min(specH, y))
      }
      if (d?.kind === "pan") {
        const dt = ((d.x0 - x) / plotW) * (d.v0.t1 - d.v0.t0)
        // On a log axis a vertical drag has no constant Hz offset: time only.
        const df = scale === "linear" ? ((y - d.y0) / specH) * (d.v0.f1 - d.v0.f0) : 0
        setView(clamp({ t0: d.v0.t0 + dt, t1: d.v0.t1 + dt, f0: d.v0.f0 + df, f1: d.v0.f1 + df }))
      }
      report(x, y)
      drawOverlay()
      drawWaveOverlay()
    },
    onPointerUp: (e: CanvasPointer) => {
      const d = dragRef.current
      dragRef.current = null
      if (d?.kind === "box") {
        const w = Math.abs(d.x1 - d.x0),
          h = Math.abs(d.y1 - d.y0)
        if (w > CLICK_SLOP) {
          const ta = tOf(Math.min(d.x0, d.x1)),
            tb = tOf(Math.max(d.x0, d.x1))
          if (h > CLICK_SLOP) {
            const fa = fOf(Math.max(d.y0, d.y1)),
              fb = fOf(Math.min(d.y0, d.y1))
            apply(() => ({ t0: ta, t1: tb, f0: fa, f1: fb }))
          } else apply(v => ({ ...v, t0: ta, t1: tb }))
        } else seekTo(e)
      }
      drawOverlay()
    },
    onPointerLeave: () => {
      mouseRef.current = null
      onCursor(null)
      drawOverlay()
      drawWaveOverlay()
    },
    onDoubleClick: fitAll,
  }

  const wave = {
    onPointerDown: (e: CanvasPointer) => {
      const { x } = localPoint(e, e.currentTarget)
      e.currentTarget.setPointerCapture(e.pointerId)
      dragRef.current = { kind: "wave", x0: x, x1: x }
    },
    onPointerMove: (e: CanvasPointer) => {
      const { x } = localPoint(e, e.currentTarget)
      mouseRef.current = { x, y: 0, area: "wave" }
      const d = dragRef.current
      if (d?.kind === "wave") d.x1 = Math.max(0, Math.min(plotW, x))
      report(x, null)
      drawOverlay()
      drawWaveOverlay()
    },
    onPointerUp: (e: CanvasPointer) => {
      const d = dragRef.current
      dragRef.current = null
      if (d?.kind === "wave") {
        if (Math.abs(d.x1 - d.x0) > CLICK_SLOP) {
          const ta = tOf(Math.min(d.x0, d.x1)),
            tb = tOf(Math.max(d.x0, d.x1))
          apply(v => ({ ...v, t0: ta, t1: tb }))
        } else seekTo(e)
      }
      drawWaveOverlay()
    },
    onPointerLeave: spec.onPointerLeave,
    onDoubleClick: fitAll,
  }

  const axis = {
    onPointerDown: (e: CanvasPointer) => {
      e.currentTarget.setPointerCapture(e.pointerId)
      dragRef.current = { kind: "axis", y0: localPoint(e, e.currentTarget).y, v0: view }
    },
    onPointerMove: (e: CanvasPointer) => {
      const d = dragRef.current
      if (d?.kind !== "axis") return
      const y = localPoint(e, e.currentTarget).y
      const df = ((y - d.y0) / specH) * (d.v0.f1 - d.v0.f0)
      setView(clamp({ ...d.v0, f0: d.v0.f0 + df, f1: d.v0.f1 + df }))
    },
    onPointerUp: endDrag,
    onDoubleClick: () => apply(v => ({ ...v, f0: 0, f1: nyquist })),
  }

  const overview = {
    onPointerDown: (e: CanvasPointer) => {
      e.currentTarget.setPointerCapture(e.pointerId)
      const x = localPoint(e, e.currentTarget).x
      const { x0, x1 } = overviewSpan(view, duration, plotW)
      if (x >= x0 && x <= x1) dragRef.current = { kind: "overview", dx: x - x0 }
      else {
        // Outside the viewport: centre it on the click, then drag from its middle.
        const span = view.t1 - view.t0,
          t = (x / plotW) * duration
        apply(v => ({ ...v, t0: t - span / 2, t1: t + span / 2 }))
        dragRef.current = { kind: "overview", dx: (span / 2 / duration) * plotW }
      }
    },
    onPointerMove: (e: CanvasPointer) => {
      const d = dragRef.current
      if (d?.kind !== "overview") return
      const x = localPoint(e, e.currentTarget).x
      const t0 = ((x - d.dx) / plotW) * duration
      apply(v => ({ ...v, t0, t1: t0 + (v.t1 - v.t0) }))
    },
    onPointerUp: endDrag,
  }

  return { spec, wave, axis, overview, ruler: { onPointerDown: seekTo } }
}
