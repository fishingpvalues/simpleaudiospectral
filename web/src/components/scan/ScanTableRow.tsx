import { AlertTriangle, CheckCircle2, XCircle } from "lucide-react"
import type { ScanRow } from "@/lib/api"
import { fmtTime } from "@/lib/scale"
import { cn } from "@/lib/utils"

const ICON = { ok: CheckCircle2, warn: AlertTriangle, bad: XCircle }
const TONE = { ok: "text-success", warn: "text-warning", bad: "text-destructive" }

const levelText = (l: ScanRow["level"]) =>
  l === "ok" ? "looks lossless" : l === "bad" ? "suspect transcode" : "check manually"

interface ScanTableRowProps {
  r: ScanRow
  /** Stands out from the rest of the album. */
  odd: boolean
  onOpen: () => void
}

export function ScanTableRow({ r, odd, onOpen }: ScanTableRowProps) {
  const Icon = r.level ? ICON[r.level] : AlertTriangle
  return (
    <tr
      onClick={() => !r.error && onOpen()}
      tabIndex={0}
      onKeyDown={e => {
        if (e.key === "Enter" && !r.error) onOpen()
      }}
      aria-label={`${r.name}: ${levelText(r.level)}${r.cutoffHz ? `, cut-off ${(r.cutoffHz / 1000).toFixed(1)} kilohertz` : ""}`}
      className={cn("cursor-pointer border-b border-border/60 hover:bg-accent", odd && "bg-warning/5")}
    >
      <td className="px-3 py-2">
        <Icon aria-hidden="true" className={cn("size-4", r.level ? TONE[r.level] : "text-muted-foreground")} />
      </td>
      <td className="max-w-[26rem] px-3 py-2">
        <div className="truncate" title={r.name}>
          {r.name}
        </div>
        {r.error && <div className="text-xs text-destructive">{r.error}</div>}
        {odd && !r.error && <div className="text-xs text-warning">differs from the rest of the album</div>}
      </td>
      <td className="px-3 py-2 font-mono text-xs whitespace-nowrap">
        {r.codec?.toUpperCase()} {r.sampleRate ? `${(r.sampleRate / 1000).toFixed(1)}k` : ""}{" "}
        {r.bits ? `${r.bits}b` : ""}
      </td>
      <td className="px-3 py-2 font-mono whitespace-nowrap">
        {r.cutoffHz ? `${(r.cutoffHz / 1000).toFixed(2)} kHz` : "none"}
      </td>
      <td className="px-3 py-2 whitespace-nowrap">
        {r.family ?? (r.level === "ok" ? "lossless" : "-")}
        {r.shelf16k ? " + 16k shelf" : ""}
      </td>
      <td className="px-3 py-2 font-mono">{r.hfSd ?? "-"}</td>
      <td className="px-3 py-2 font-mono">{r.dr != null ? `DR${r.dr}` : "-"}</td>
      <td className="px-3 py-2 font-mono">{r.lufs != null ? r.lufs.toFixed(1) : "-"}</td>
      <td className={cn("px-3 py-2 font-mono", (r.truePeakDb ?? -99) > 0 && "text-warning")}>
        {r.truePeakDb != null ? r.truePeakDb.toFixed(1) : "-"}
      </td>
      <td className={cn("px-3 py-2 font-mono", (r.clipEvents ?? 0) > 0 && "text-warning")}>{r.clipEvents ?? "-"}</td>
      <td className="px-3 py-2 font-mono">{r.duration ? fmtTime(r.duration) : "-"}</td>
    </tr>
  )
}
