import type { View } from "@/lib/scale"

/** A spectrum as frequencies (Hz) and levels (dBFS), bottom to top. */
export interface Spectrum {
  hz: Float32Array
  db: Float32Array
}

export interface Cursor {
  t: number
  f: number
  db: number | null
  /** Spectrum slice at the cursor. */
  slice: Spectrum | null
}

/** What the pointer is doing between pointerdown and pointerup. */
export type Drag =
  | { kind: "box"; x0: number; y0: number; x1: number; y1: number }
  | { kind: "pan"; x0: number; y0: number; v0: View }
  | { kind: "axis"; y0: number; v0: View }
  | { kind: "overview"; dx: number }
  | { kind: "wave"; x0: number; x1: number }

/** Pointer position over the plot, in CSS pixels; `wave` has no frequency. */
export interface Mouse {
  x: number
  y: number
  area: "spec" | "wave"
}

/** Min/max pairs of a time range, as served by /api/wave. */
export interface WaveTile {
  t0: number
  t1: number
  data: Float32Array
}
