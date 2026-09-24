import { useEffect, useRef } from "react"
import { api, type Channel } from "@/lib/api"
import type { View } from "@/lib/scale"
import type { WaveTile } from "./types"

const DEBOUNCE_MS = 60
const MAX_COLS = 8192
const MAX_OVERVIEW_COLS = 4096

interface UseWaveDataArgs {
  path: string
  ch: Channel
  view: View
  duration: number
  plotW: number
  /** Called whenever a tile lands. */
  onLand: () => void
}

/** Min/max waveform of the view (at device resolution) and of the whole track (mix). */
export function useWaveData({ path, ch, view, duration, plotW, onLand }: UseWaveDataArgs) {
  const waveRef = useRef<WaveTile | null>(null)
  const overviewRef = useRef<Float32Array | null>(null)
  const { t0, t1 } = view

  useEffect(() => {
    if (plotW < 16) return
    const dpr = window.devicePixelRatio || 1
    const ctl = new AbortController()
    const timer = setTimeout(async () => {
      try {
        const data = await api.wave(
          { path, ch, t0: t0.toFixed(4), t1: t1.toFixed(4), cols: Math.min(MAX_COLS, Math.round(plotW * dpr)) },
          ctl.signal,
        )
        waveRef.current = { t0, t1, data }
        onLand()
      } catch (e) {
        if ((e as Error).name !== "AbortError") console.error(e)
      }
    }, DEBOUNCE_MS)
    return () => {
      clearTimeout(timer)
      ctl.abort()
    }
  }, [path, ch, t0, t1, plotW, onLand])

  useEffect(() => {
    if (plotW < 16) return
    const ctl = new AbortController()
    api
      .wave({ path, ch: "mix", t0: 0, t1: duration, cols: Math.min(MAX_OVERVIEW_COLS, plotW) }, ctl.signal)
      .then(d => {
        overviewRef.current = d
        onLand()
      })
      .catch(() => {})
    return () => ctl.abort()
  }, [path, duration, plotW, onLand])

  useEffect(() => {
    waveRef.current = null
    overviewRef.current = null
  }, [path])

  return { waveRef, overviewRef }
}
