import { useEffect, useMemo, useState } from "react"
import { Loader2, X } from "lucide-react"
import { api, type ScanRow } from "@/lib/api"
import type { Term as TermKey } from "@/lib/glossary"
import { summarizeScan } from "@/lib/scan"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { ScrollArea } from "@/components/ui/scroll-area"
import { Term } from "@/components/ui/tooltip"
import { ScanTableRow } from "./ScanTableRow"

const COLUMNS: [string, TermKey | null][] = [
  ["", null],
  ["Track", null],
  ["Format", "codec"],
  ["Cut-off", "cutoff"],
  ["Likely source", "scanLikely"],
  ["HF var", "hfVar"],
  ["DR", "dr"],
  ["LUFS", "lufs"],
  ["True peak", "truePeak"],
  ["Clips", "clipping"],
  ["Length", "duration"],
]

interface AlbumScanProps {
  dir: string
  onOpen: (path: string) => void
  onClose: () => void
}

/** Analyses every track of a folder and flags the odd one out. Rows stream in
 * as the server finishes them. */
export function AlbumScan({ dir, onOpen, onClose }: AlbumScanProps) {
  const [rows, setRows] = useState<ScanRow[]>([])
  const [total, setTotal] = useState<number | null>(null)
  const [done, setDone] = useState(false)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    const ctl = new AbortController()
    setRows([])
    setTotal(null)
    setDone(false)
    setError(null)
    api
      .scan(dir, setTotal, r => setRows(rs => [...rs, r]), ctl.signal)
      .then(() => setDone(true))
      .catch(e => {
        if (e.name !== "AbortError") setError(String(e.message ?? e))
      })
    return () => ctl.abort()
  }, [dir])

  const summary = useMemo(() => summarizeScan(rows), [rows])

  const base = dir ? `${dir}/` : ""
  return (
    <div className="flex h-full min-h-0 flex-col">
      <div className="flex items-center gap-3 border-b px-4 py-3">
        <div className="min-w-0 flex-1">
          <h2 className="truncate text-sm font-semibold">Album scan - {dir || "library"}</h2>
          <p className="text-xs text-muted-foreground">
            {total == null ? "starting..." : `${rows.length} / ${total} tracks`}
            {summary.dr != null && ` - album DR${summary.dr}`}
          </p>
        </div>
        <div className="flex items-center gap-1.5">
          <Badge variant="success">{summary.counts.ok} lossless</Badge>
          <Badge variant="warning">{summary.counts.warn} check</Badge>
          <Badge variant="destructive">{summary.counts.bad} suspect</Badge>
          {!done && !error && <Loader2 className="size-4 animate-spin text-muted-foreground" />}
        </div>
        <Button variant="ghost" size="icon-sm" onClick={onClose} aria-label="Close scan">
          <X />
        </Button>
      </div>
      {error && <p className="px-4 py-3 text-sm text-destructive">{error}</p>}
      <ScrollArea className="min-h-0 flex-1">
        <table className="w-full text-sm">
          <caption className="sr-only">
            Per-track analysis of {dir || "library"}; select a row to open the track
          </caption>
          <thead className="sticky top-0 bg-background text-left text-xs text-muted-foreground">
            <tr className="border-b">
              {COLUMNS.map(([h, t]) => (
                <th key={h} scope="col" className="px-3 py-2 font-medium whitespace-nowrap">
                  {t ? <Term term={t}>{h}</Term> : h}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {rows.map(r => (
              <ScanTableRow key={r.name} r={r} odd={summary.outlier(r)} onOpen={() => onOpen(base + r.name)} />
            ))}
          </tbody>
        </table>
        {done && rows.length === 0 && (
          <p className="px-4 py-6 text-sm text-muted-foreground">No audio files directly in this folder.</p>
        )}
      </ScrollArea>
      <p className="border-t px-4 py-2 text-xs text-muted-foreground">
        HF var = frame-to-frame spread of 16-19 kHz energy in dB. MP3 codes that band only when bits are left over
        (13-23 dB); AAC, Opus, Vorbis and lossless keep it steady (under 8).
      </p>
    </div>
  )
}
