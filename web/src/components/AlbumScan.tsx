import { useEffect, useMemo, useState } from "react"
import { AlertTriangle, CheckCircle2, Loader2, X, XCircle } from "lucide-react"
import { api, type ScanRow } from "@/lib/api"
import { fmtTime } from "@/lib/scale"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { ScrollArea } from "@/components/ui/scroll-area"
import { cn } from "@/lib/utils"

interface Props { dir: string; onOpen: (path: string) => void; onClose: () => void }

const ICON = { ok: CheckCircle2, warn: AlertTriangle, bad: XCircle }
const TONE = { ok: "text-success", warn: "text-warning", bad: "text-destructive" }

function median(xs: number[]) {
  const s = [...xs].sort((a, b) => a - b)
  return s.length ? s[Math.floor(s.length / 2)] : NaN
}

export function AlbumScan({ dir, onOpen, onClose }: Props) {
  const [rows, setRows] = useState<ScanRow[]>([])
  const [total, setTotal] = useState<number | null>(null)
  const [done, setDone] = useState(false)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    const ctl = new AbortController()
    setRows([]); setTotal(null); setDone(false); setError(null)
    api.scan(dir, setTotal, r => setRows(rs => [...rs, r]), ctl.signal)
      .then(() => setDone(true))
      .catch(e => { if (e.name !== "AbortError") setError(String(e.message ?? e)) })
    return () => ctl.abort()
  }, [dir])

  // One odd track in an album is the classic mixed-source upload: flag rows
  // whose cut-off sits well away from the album median, or whose verdict
  // differs from the majority.
  const summary = useMemo(() => {
    const cuts = rows.map(r => r.cutoffHz ?? 22050)
    const med = median(cuts)
    const counts = { ok: 0, warn: 0, bad: 0 }
    rows.forEach(r => { if (r.level) counts[r.level]++ })
    const major = (Object.entries(counts).sort((a, b) => b[1] - a[1])[0]?.[0] ?? "ok") as keyof typeof counts
    const outlier = (r: ScanRow) => rows.length > 2 && (Math.abs((r.cutoffHz ?? 22050) - med) > 700 || (r.level && r.level !== major))
    const drs = rows.map(r => r.dr).filter((v): v is number => v != null)
    return { counts, outlier, dr: drs.length ? Math.round(drs.reduce((a, b) => a + b, 0) / drs.length) : null }
  }, [rows])

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
        <Button variant="ghost" size="icon-sm" onClick={onClose} aria-label="Close scan"><X /></Button>
      </div>
      {error && <p className="px-4 py-3 text-sm text-destructive">{error}</p>}
      <ScrollArea className="min-h-0 flex-1">
        <table className="w-full text-sm">
          <caption className="sr-only">Per-track analysis of {dir || "library"}; select a row to open the track</caption>
          <thead className="sticky top-0 bg-background text-left text-xs text-muted-foreground">
            <tr className="border-b">
              {["", "Track", "Format", "Cut-off", "Likely source", "HF var", "DR", "LUFS", "True peak", "Clips", "Length"].map(h => (
                <th key={h} className="px-3 py-2 font-medium whitespace-nowrap">{h}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {rows.map(r => {
              const Icon = r.level ? ICON[r.level] : AlertTriangle
              const odd = summary.outlier(r)
              return (
                <tr key={r.name} onClick={() => !r.error && onOpen(base + r.name)} tabIndex={0}
                  onKeyDown={e => { if (e.key === "Enter" && !r.error) onOpen(base + r.name) }}
                  aria-label={`${r.name}: ${r.level === "ok" ? "looks lossless" : r.level === "bad" ? "suspect transcode" : "check manually"}${r.cutoffHz ? `, cut-off ${(r.cutoffHz / 1000).toFixed(1)} kilohertz` : ""}`}
                  className={cn("cursor-pointer border-b border-border/60 hover:bg-accent", odd && "bg-warning/5")}>
                  <td className="px-3 py-2"><Icon aria-hidden="true" className={cn("size-4", r.level ? TONE[r.level] : "text-muted-foreground")} /></td>
                  <td className="max-w-[26rem] px-3 py-2">
                    <div className="truncate" title={r.name}>{r.name}</div>
                    {r.error && <div className="text-xs text-destructive">{r.error}</div>}
                    {odd && !r.error && <div className="text-xs text-warning">differs from the rest of the album</div>}
                  </td>
                  <td className="px-3 py-2 font-mono text-xs whitespace-nowrap">
                    {r.codec?.toUpperCase()} {r.sampleRate ? `${(r.sampleRate / 1000).toFixed(1)}k` : ""} {r.bits ? `${r.bits}b` : ""}
                  </td>
                  <td className="px-3 py-2 font-mono whitespace-nowrap">{r.cutoffHz ? `${(r.cutoffHz / 1000).toFixed(2)} kHz` : "none"}</td>
                  <td className="px-3 py-2 whitespace-nowrap">{r.family ?? (r.level === "ok" ? "lossless" : "-")}{r.shelf16k ? " + 16k shelf" : ""}</td>
                  <td className="px-3 py-2 font-mono">{r.hfSd ?? "-"}</td>
                  <td className="px-3 py-2 font-mono">{r.dr != null ? `DR${r.dr}` : "-"}</td>
                  <td className="px-3 py-2 font-mono">{r.lufs != null ? r.lufs.toFixed(1) : "-"}</td>
                  <td className={cn("px-3 py-2 font-mono", (r.truePeakDb ?? -99) > 0 && "text-warning")}>{r.truePeakDb != null ? r.truePeakDb.toFixed(1) : "-"}</td>
                  <td className={cn("px-3 py-2 font-mono", (r.clipEvents ?? 0) > 0 && "text-warning")}>{r.clipEvents ?? "-"}</td>
                  <td className="px-3 py-2 font-mono">{r.duration ? fmtTime(r.duration) : "-"}</td>
                </tr>
              )
            })}
          </tbody>
        </table>
        {done && rows.length === 0 && <p className="px-4 py-6 text-sm text-muted-foreground">No audio files directly in this folder.</p>}
      </ScrollArea>
      <p className="border-t px-4 py-2 text-xs text-muted-foreground">
        HF var = frame-to-frame spread of 16-19 kHz energy in dB. MP3 codes that band only when bits are left over (13-23 dB);
        AAC, Opus, Vorbis and lossless keep it steady (under 8).
      </p>
    </div>
  )
}
