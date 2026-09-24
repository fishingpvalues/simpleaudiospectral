import { useEffect, useRef } from "react"
import { api, type Stft } from "@/lib/api"
import type { View } from "@/lib/scale"
import type { Settings } from "@/lib/settings"
import { useLatest } from "@/hooks/useLatest"
import { deriveSeries, meanSpectrum, type Derived } from "./derive"
import type { Spectrum } from "./types"

/** Debounce before fetching a new matrix, so a wheel burst fetches once. */
const DEBOUNCE_MS = 90
const MAX_COLS = 4096
const MAX_ROWS = 2048

interface UseStftArgs {
  path: string
  settings: Pick<Settings, "ch" | "fft" | "win" | "scale">
  view: View
  plotW: number
  specH: number
  onLoading: (b: boolean) => void
  onViewSpectrum?: (s: Spectrum | null) => void
  /** Called after a new matrix and its derived series are in the refs. */
  onLand: () => void
}

/** The spectrogram matrix of the current view at device resolution. The
 * previous matrix stays in the ref until the next one lands. */
export function useStft({ path, settings, view, plotW, specH, onLoading, onViewSpectrum, onLand }: UseStftArgs) {
  const stftRef = useRef<Stft | null>(null)
  const derivedRef = useRef<Derived | null>(null)
  const onViewSpectrumRef = useLatest(onViewSpectrum)
  const { ch, fft, win, scale } = settings

  useEffect(() => {
    if (plotW < 16 || specH < 16) return
    const dpr = window.devicePixelRatio || 1
    const ctl = new AbortController()
    const timer = setTimeout(async () => {
      onLoading(true)
      try {
        const s = await api.stft(
          {
            path,
            ch,
            fft,
            win,
            scale,
            t0: view.t0.toFixed(4),
            t1: view.t1.toFixed(4),
            f0: Math.round(view.f0),
            f1: Math.round(view.f1),
            cols: Math.min(MAX_COLS, Math.round(plotW * dpr)),
            rows: Math.min(MAX_ROWS, Math.round(specH * dpr)),
          },
          ctl.signal,
        )
        stftRef.current = s
        derivedRef.current = deriveSeries(s)
        onViewSpectrumRef.current?.(meanSpectrum(derivedRef.current, s.meta.cols))
        onLand()
      } catch (e) {
        if ((e as Error).name !== "AbortError") console.error(e)
      } finally {
        if (!ctl.signal.aborted) onLoading(false)
      }
    }, DEBOUNCE_MS)
    return () => {
      clearTimeout(timer)
      ctl.abort()
    }
  }, [path, ch, fft, win, scale, view, plotW, specH, onLoading, onLand, onViewSpectrumRef])

  useEffect(() => {
    stftRef.current = null
  }, [path])

  return { stftRef, derivedRef }
}
