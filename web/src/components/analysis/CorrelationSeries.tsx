import { useEffect, useRef } from "react"
import { Term } from "@/components/ui/tooltip"
import { drawCorrelation, fitCanvas } from "./charts"

/** Stereo correlation per second of the whole track. */
export function CorrelationSeries({ series }: { series: number[] }) {
  const ref = useRef<HTMLCanvasElement>(null)
  useEffect(() => {
    const c = ref.current
    if (!c) return
    const { g, w, h } = fitCanvas(c)
    drawCorrelation(g, w, h, series)
  }, [series])
  return (
    <div className="mt-3">
      <div className="mb-1 text-[11px] text-muted-foreground">
        <Term term="corrSeries">Stereo correlation per second</Term> (red = out of phase)
      </div>
      <canvas
        ref={ref}
        className="h-14 w-full rounded-md border"
        role="img"
        aria-label={`Stereo correlation over time, ${series.filter(v => v < 0).length} of ${series.length} seconds out of phase`}
      />
    </div>
  )
}
