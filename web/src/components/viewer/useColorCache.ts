import { useCallback, useEffect, useMemo, useRef } from "react"
import type { Stft } from "@/lib/api"
import { lut, overlayColor } from "@/lib/colormaps"
import type { Settings } from "@/lib/settings"
import { colorizeStft } from "./draw/spectrogram"

/** Byte range the server quantises levels into, in dBFS. */
const Q_FLOOR = -160,
  Q_CEIL = 0
/** Holes are searched up to this far below the detected cut-off (Hz). */
const HOLE_MARGIN_HZ = 150

interface UseColorCacheArgs {
  path: string
  settings: Pick<Settings, "cmap" | "floor" | "ceil" | "holes">
  /** Top of the hole search: the detected cut-off, else Nyquist. */
  holeTopHz: number
  redraw: () => void
}

/** The coloured spectrogram image, cached until the matrix, the colour table
 * or the holes setting changes. */
export function useColorCache({ path, settings, holeTopHz, redraw }: UseColorCacheArgs) {
  const colored = useRef<HTMLCanvasElement | null>(null)
  const { cmap, floor, ceil, holes } = settings

  /** A new matrix landed. */
  const invalidate = useCallback(() => {
    colored.current = null
  }, [])

  useEffect(() => {
    colored.current = null
  }, [path])

  const table = useMemo(() => lut(cmap, floor, ceil, Q_FLOOR, Q_CEIL), [cmap, floor, ceil])
  useEffect(() => {
    colored.current = null
    redraw()
  }, [table, redraw, holes])

  const colorize = (s: Stft | null, rowHz: Float32Array | undefined): HTMLCanvasElement | null => {
    if (!s) return null
    if (colored.current) return colored.current
    const opts =
      holes && rowHz
        ? { rowHz, top: Math.min(s.meta.f1, holeTopHz - HOLE_MARGIN_HZ), color: overlayColor(cmap).abgr }
        : null
    colored.current = colorizeStft(s, table, opts)
    return colored.current
  }

  return { table, invalidate, colorize }
}
