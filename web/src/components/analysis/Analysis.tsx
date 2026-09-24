import type { Info } from "@/lib/api"
import { activeRefs } from "@/lib/references"
import type { View } from "@/lib/scale"
import type { Settings } from "@/lib/settings"
import { ScrollArea } from "@/components/ui/scroll-area"
import { Separator } from "@/components/ui/separator"
import { Term } from "@/components/ui/tooltip"
import type { Cursor, Spectrum } from "@/components/viewer/types"
import { ColorScale } from "./ColorScale"
import { Dynamics } from "./Dynamics"
import { FileStats } from "./FileStats"
import { Goniometer } from "./Goniometer"
import { LowpassTable } from "./LowpassTable"
import { PanelHeading } from "./PanelHeading"
import { SoxExport } from "./SoxExport"
import { SpectrumChart } from "./SpectrumChart"
import { VerdictCard } from "./VerdictCard"

interface AnalysisProps {
  info: Info
  cursor: Cursor | null
  settings: Settings
  soxFull: string
  soxZoom: string
  view: View
  viewSpec: Spectrum | null
  onJump: (t: number) => void
}

/** Right-hand panel: verdict, file facts, dynamics and the reference charts. */
export function Analysis({ info, cursor, settings, soxFull, soxZoom, view, viewSpec, onJump }: AnalysisProps) {
  const a = info.analysis
  const refs = activeRefs(settings.refSets)
  return (
    <ScrollArea className="h-full">
      <div className="space-y-4 p-4">
        <VerdictCard info={info} />
        <FileStats info={info} />

        <Separator />

        <Dynamics path={info.path} channels={info.channels} bits={info.bits} onJump={onJump} />

        {info.channels > 1 && (
          <div>
            <PanelHeading>
              <Term term="goniometer">Goniometer (current view)</Term>
            </PanelHeading>
            <Goniometer path={info.path} view={view} />
          </div>
        )}

        <Separator />

        <LowpassTable refs={refs} cutoffKhz={a?.cutoffHz ? a.cutoffHz / 1000 : null} />

        <div>
          <PanelHeading>Frequency analysis</PanelHeading>
          <SpectrumChart info={info} cursor={cursor} viewSpec={viewSpec} refs={refs} />
          <p className="mt-1.5 text-xs text-muted-foreground">
            Light grey: loudest 10% of frames (shows the lowpass). Dark grey: median frame (shows a 16 kHz shelf). Cyan:
            mean of the visible view. White: the column under the cursor.
          </p>
        </div>

        <ColorScale cmap={settings.cmap} floor={settings.floor} ceil={settings.ceil} />

        <Separator />

        <SoxExport fullUrl={soxFull} viewUrl={soxZoom} />
      </div>
    </ScrollArea>
  )
}
