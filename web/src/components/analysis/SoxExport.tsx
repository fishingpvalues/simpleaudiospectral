import { Download } from "lucide-react"
import { Button } from "@/components/ui/button"
import { Term } from "@/components/ui/tooltip"
import { PanelHeading } from "./PanelHeading"

/** Links to the server-rendered SoX-style spectrogram PNGs. */
export function SoxExport({ fullUrl, viewUrl }: { fullUrl: string; viewUrl: string }) {
  return (
    <div className="space-y-2">
      <PanelHeading className="">
        <Term term="sox">Export SoX spectral</Term>
      </PanelHeading>
      <div className="flex gap-2">
        <Button variant="outline" size="sm" asChild>
          <a href={fullUrl} target="_blank" rel="noreferrer">
            <Download />
            Full track
          </a>
        </Button>
        <Button variant="outline" size="sm" asChild>
          <a href={viewUrl} target="_blank" rel="noreferrer">
            <Download />
            Current view
          </a>
        </Button>
      </div>
      <p className="text-xs text-muted-foreground">
        1800x1025, Kaiser window, 120 dB range: the widely used SoX spectrogram format.
      </p>
    </div>
  )
}
