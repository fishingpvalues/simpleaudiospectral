import { AlertTriangle, CheckCircle2, XCircle } from "lucide-react"
import type { Info } from "@/lib/api"
import { Badge } from "@/components/ui/badge"
import { Term } from "@/components/ui/tooltip"

const LEVEL = {
  ok: { label: "Looks lossless", icon: CheckCircle2, variant: "success" as const },
  warn: { label: "Check manually", icon: AlertTriangle, variant: "warning" as const },
  bad: { label: "Suspect transcode", icon: XCircle, variant: "destructive" as const },
}

/** Side channel quieter than this means the stereo file carries mono. */
const MONO_SIDE_DB = -60

/** The verdict with its evidence badges, at the top of the panel. */
export function VerdictCard({ info }: { info: Info }) {
  const a = info.analysis
  const lv = a ? LEVEL[a.level] : LEVEL.warn
  const padded = info.bitDepthUsed && /^16\/(24|32)/.test(info.bitDepthUsed)
  const mono = a && a.sideDb < MONO_SIDE_DB
  return (
    <div className="rounded-lg border bg-card p-3">
      <Badge variant={lv.variant} className="mb-2">
        <lv.icon />
        {lv.label}
      </Badge>
      <p className="text-sm leading-relaxed text-card-foreground/90">
        {a?.verdict ?? "No analysis (file too short?)."}
      </p>
      <div className="mt-2 flex flex-wrap gap-1.5">
        {a?.family && <Badge variant="outline">likely {a.family}</Badge>}
        {a?.resampledFrom && (
          <Badge variant="destructive">resampled from {(a.resampledFrom / 1000).toFixed(1)} kHz</Badge>
        )}
        {a?.hfSd != null && (
          <Badge variant={a.hfSd >= 10 ? "warning" : "outline"}>
            <Term term="hfVar">HF var {a.hfSd} dB</Term>
          </Badge>
        )}
        {a?.crtTone && (
          <Badge variant="outline">
            <Term term="crt">{(a.crtTone / 1000).toFixed(3)} kHz CRT tone</Term>
          </Badge>
        )}
        {a?.shelf16k && (
          <Badge variant="warning">
            <Term term="shelf">16 kHz shelf</Term>
          </Badge>
        )}
        {padded && <Badge variant="warning">padded {info.bitDepthUsed} bit</Badge>}
        {mono && (
          <Badge variant="warning">
            <Term term="sideLevel">mono in stereo</Term>
          </Badge>
        )}
      </div>
    </div>
  )
}
