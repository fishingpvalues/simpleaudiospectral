import type { Scale } from "@/lib/api"
import { fToY, yToF, type View } from "@/lib/scale"

/** Maps between the current view and plot pixels. */
export interface Geometry {
  view: View
  scale: Scale
  plotW: number
  specH: number
  xOf: (t: number) => number
  tOf: (x: number) => number
  yOf: (f: number) => number
  fOf: (y: number) => number
}

export function makeGeometry(view: View, scale: Scale, plotW: number, specH: number): Geometry {
  return {
    view,
    scale,
    plotW,
    specH,
    xOf: t => ((t - view.t0) / (view.t1 - view.t0)) * plotW,
    tOf: x => view.t0 + (x / plotW) * (view.t1 - view.t0),
    yOf: f => fToY(f, view, scale) * specH,
    fOf: y => yToF(y / specH, view, scale),
  }
}

/** Pixel-snapped coordinate for crisp 1 px lines. */
export const crisp = (v: number) => Math.round(v) + 0.5

/** Pointer position relative to an element. */
export function localPoint(e: { clientX: number; clientY: number }, el: HTMLElement) {
  const r = el.getBoundingClientRect()
  return { x: e.clientX - r.left, y: e.clientY - r.top }
}

/** Sizes a canvas's backing store for the device pixel ratio and returns a
 * context that draws in CSS pixels, or null while it has no size. */
export function setupCanvas(c: HTMLCanvasElement | null, w: number, h: number) {
  if (!c || w <= 0 || h <= 0) return null
  const dpr = window.devicePixelRatio || 1
  const W = Math.round(w * dpr),
    H = Math.round(h * dpr)
  if (c.width !== W || c.height !== H) {
    c.width = W
    c.height = H
  }
  const g = c.getContext("2d")!
  g.setTransform(dpr, 0, 0, dpr, 0, 0)
  return g
}
