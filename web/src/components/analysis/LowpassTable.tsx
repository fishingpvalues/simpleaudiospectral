import { lowpassTable, type RefLine } from "@/lib/references"
import { cn } from "@/lib/utils"
import { Term } from "@/components/ui/tooltip"
import { PanelHeading } from "./PanelHeading"

/** Encoder settings by lowpass, with the one nearest the detected cut-off highlighted. */
export function LowpassTable({ refs, cutoffKhz }: { refs: RefLine[]; cutoffKhz: number | null }) {
  const { rows, match } = lowpassTable(refs, cutoffKhz)
  return (
    <div>
      <PanelHeading>
        <Term term="refs">Encoder lowpass reference</Term>
      </PanelHeading>
      <div className="overflow-hidden rounded-md border text-sm">
        {rows.map(r => (
          <div
            key={r.label}
            className={cn(
              "flex justify-between px-3 py-1.5 font-mono",
              r === match ? "bg-primary text-primary-foreground" : "odd:bg-card",
            )}
          >
            <span>{r.label}</span>
            <span>{r.khz} kHz</span>
          </div>
        ))}
      </div>
    </div>
  )
}
