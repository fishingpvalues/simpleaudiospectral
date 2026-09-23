import type { Scale } from "./api"

export interface View {
  t0: number
  t1: number
  f0: number
  f1: number
}

/** Frequency -> 0..1 from the TOP of the plot (1 = f0 at the bottom). */
export function fToY(f: number, v: View, scale: Scale): number {
  if (scale === "log") {
    const lo = Math.log(Math.max(v.f0, 10)),
      hi = Math.log(v.f1)
    return (hi - Math.log(Math.max(f, 10))) / (hi - lo)
  }
  return (v.f1 - f) / (v.f1 - v.f0)
}

export function yToF(y: number, v: View, scale: Scale): number {
  if (scale === "log") {
    const lo = Math.log(Math.max(v.f0, 10)),
      hi = Math.log(v.f1)
    return Math.exp(hi - y * (hi - lo))
  }
  return v.f1 - y * (v.f1 - v.f0)
}

const NICE = [1, 2, 5]

/** Round step giving about `target` ticks across `span`. */
export function niceStep(span: number, target: number): number {
  const raw = span / Math.max(1, target)
  const p = Math.pow(10, Math.floor(Math.log10(raw)))
  for (const n of NICE) if (n * p >= raw) return n * p
  return 10 * p
}

export function timeTicks(t0: number, t1: number, px: number): { step: number; ticks: number[] } {
  const step = niceStep(t1 - t0, px / 90)
  const ticks: number[] = []
  for (let t = Math.ceil(t0 / step) * step; t <= t1 + 1e-9; t += step) ticks.push(t)
  return { step, ticks }
}

export function freqTicks(v: View, scale: Scale, px: number): number[] {
  if (scale === "log") {
    const out: number[] = []
    for (const d of [10, 100, 1000, 10000, 100000])
      for (const m of [1, 2, 5]) {
        const f = d * m
        if (f >= v.f0 && f <= v.f1) out.push(f)
      }
    return out
  }
  const step = niceStep(v.f1 - v.f0, px / 26)
  const out: number[] = []
  for (let f = Math.ceil(v.f0 / step) * step; f <= v.f1 + 1e-6; f += step) out.push(f)
  return out
}

export function fmtTime(t: number, step = 1): string {
  const dec = step >= 1 ? 0 : step >= 0.1 ? 1 : step >= 0.01 ? 2 : 3
  // Round once, up front: 59.6 s at 0 decimals must become 1:00, not 0:60.
  const f = Math.pow(10, dec)
  const s = Math.round(Math.max(0, t) * f) / f
  const m = Math.floor(s / 60)
  const sec = s - m * 60
  return `${m}:${sec.toFixed(dec).padStart(dec ? 3 + dec : 2, "0")}`
}

export function fmtHz(f: number, precise = false): string {
  if (f >= 1000) {
    const k = f / 1000
    return `${precise ? k.toFixed(2) : Number.isInteger(k) ? k.toFixed(0) : k.toFixed(1)}k`
  }
  return `${Math.round(f)}`
}

export function fmtBytes(n: number): string {
  if (n > 2 ** 40) return `${(n / 2 ** 40).toFixed(2)} TiB`
  if (n > 1 << 30) return `${(n / (1 << 30)).toFixed(2)} GiB`
  if (n > 1 << 20) return `${(n / (1 << 20)).toFixed(1)} MiB`
  return `${(n / 1024).toFixed(0)} KiB`
}

/** Lowpass references from RED's spectral guide. */
export const RED_REFS: { khz: number; label: string }[] = [
  { khz: 16, label: "128" },
  { khz: 18.5, label: "V2" },
  { khz: 19, label: "192" },
  { khz: 19.5, label: "V0" },
  { khz: 20, label: "256" },
  { khz: 20.5, label: "320" },
]
