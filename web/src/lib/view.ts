import type { Scale } from "./api"
import { yToF, type View } from "./scale"

/** Smallest time span (s) and frequency span (Hz) a view can zoom to. */
export const MIN_SPAN_T = 0.02
export const MIN_SPAN_F = 100

/** The whole track, 0 Hz to Nyquist. */
export function fullView(duration: number, sampleRate: number): View {
  return { t0: 0, t1: duration, f0: 0, f1: sampleRate / 2 }
}

/** Keeps a view inside the track and the band, preserving its span where it fits. */
export function clampView(v: View, duration: number, nyquist: number): View {
  let { t0, t1, f0, f1 } = v
  const span = Math.min(duration, Math.max(MIN_SPAN_T, t1 - t0))
  if (t0 < 0) t0 = 0
  if (t0 + span > duration) t0 = Math.max(0, duration - span)
  t1 = t0 + span
  const fs = Math.min(nyquist, Math.max(MIN_SPAN_F, f1 - f0))
  if (f0 < 0) f0 = 0
  if (f0 + fs > nyquist) f0 = Math.max(0, nyquist - fs)
  f1 = f0 + fs
  return { t0, t1, f0, f1 }
}

/** Toolbar zoom: scales the time span around the view's centre. */
export function zoomCentered(v: View, factor: number, duration: number): View {
  const c = (v.t0 + v.t1) / 2,
    span = Math.min(duration, Math.max(MIN_SPAN_T, (v.t1 - v.t0) * factor))
  const t0 = Math.max(0, Math.min(duration - span, c - span / 2))
  return { ...v, t0, t1: t0 + span }
}

/** Shifts the view by a fraction of its own span. */
export function panBy(v: View, frac: number, duration: number): View {
  const span = v.t1 - v.t0,
    t0 = Math.max(0, Math.min(duration - span, v.t0 + span * frac))
  return { ...v, t0, t1: t0 + span }
}

/** Detail zoom: the loudest 8 s, top of the band. */
export function detailView(loudestAt: number, duration: number, sampleRate: number): View {
  const nyq = sampleRate / 2
  return {
    t0: loudestAt,
    t1: Math.min(duration, loudestAt + 8),
    f0: Math.max(0, Math.min(15000, nyq - 7000)),
    f1: nyq,
  }
}

/** Half a second around `t`, for jumping to a clip. */
export function jumpView(v: View, t: number, duration: number): View {
  return { ...v, t0: Math.max(0, t - 0.25), t1: Math.min(duration, t + 0.25) }
}

/** Wheel zoom in time, keeping `anchorT` under the pointer. */
export function zoomTimeAt(v: View, factor: number, anchorT: number, duration: number): View {
  const span = Math.max(MIN_SPAN_T, Math.min(duration, (v.t1 - v.t0) * factor))
  const u = (anchorT - v.t0) / (v.t1 - v.t0)
  return { ...v, t0: anchorT - u * span, t1: anchorT - u * span + span }
}

/** Wheel zoom in frequency, keeping the frequency at `anchorY` (0..1 from the top) in place. */
export function zoomFreqAt(v: View, factor: number, anchorY: number, scale: Scale, nyquist: number): View {
  const f = yToF(anchorY, v, scale)
  const span = Math.max(MIN_SPAN_F, Math.min(nyquist, (v.f1 - v.f0) * factor))
  const u = (v.f1 - f) / (v.f1 - v.f0)
  const f1 = f + u * span
  return { ...v, f1, f0: f1 - span }
}
