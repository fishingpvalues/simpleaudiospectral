import { useEffect, useRef } from "react"
import { palette } from "@/lib/colormaps"
import { Term } from "@/components/ui/tooltip"
import { PanelHeading } from "./PanelHeading"

/** The colour map as a bar, labelled with the display range. */
export function ColorScale({ cmap, floor, ceil }: { cmap: string; floor: number; ceil: number }) {
  return (
    <div>
      <PanelHeading>
        <Term term="range">Colour scale</Term>
      </PanelHeading>
      <ColorBar cmap={cmap} />
      <div className="mt-1 flex justify-between font-mono text-[11px] text-muted-foreground">
        <span>{floor} dB</span>
        <span>{ceil} dB</span>
      </div>
    </div>
  )
}

function ColorBar({ cmap }: { cmap: string }) {
  const ref = useRef<HTMLCanvasElement>(null)
  useEffect(() => {
    const c = ref.current
    if (!c) return
    c.width = 256
    c.height = 1
    const g = c.getContext("2d")!
    const img = g.createImageData(256, 1)
    img.data.set(palette(cmap))
    g.putImageData(img, 0, 0)
  }, [cmap])
  return <canvas ref={ref} className="h-3 w-full rounded-sm [image-rendering:pixelated]" aria-hidden="true" />
}
