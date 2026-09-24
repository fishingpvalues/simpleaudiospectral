import { useEffect, useRef } from "react"
import type { Info } from "@/lib/api"
import type { RefLine } from "@/lib/references"
import type { Cursor, Spectrum } from "@/components/viewer/types"
import { drawSpectrumChart, fitCanvas } from "./charts"

interface SpectrumChartProps {
  info: Info
  cursor: Cursor | null
  viewSpec: Spectrum | null
  refs: RefLine[]
}

export function SpectrumChart({ info, cursor, viewSpec, refs }: SpectrumChartProps) {
  const ref = useRef<HTMLCanvasElement>(null)
  useEffect(() => {
    const c = ref.current
    if (!c) return
    const { g, w, h } = fitCanvas(c)
    drawSpectrumChart(g, w, h, {
      nyquist: info.sampleRate / 2,
      refs,
      analysis: info.analysis,
      viewSpec,
      cursorSlice: cursor?.slice ?? null,
      cursorHz: cursor ? cursor.f : null,
    })
  }, [info, cursor, viewSpec, refs])
  const a = info.analysis
  return (
    <canvas
      ref={ref}
      className="h-44 w-full rounded-md border"
      role="img"
      aria-label={`Average spectrum. ${a?.cutoffHz ? `Level falls by ${a.dropDb} dB at ${(a.cutoffHz / 1000).toFixed(1)} kilohertz.` : `Content reaches ${((a?.extentHz ?? 0) / 1000).toFixed(1)} kilohertz without a brick wall.`}`}
    />
  )
}
