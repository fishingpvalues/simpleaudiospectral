import type { ScanRow } from "./api"

type Level = NonNullable<ScanRow["level"]>

export interface ScanSummary {
  counts: Record<Level, number>
  /** True for a track that stands out from the rest of the album. */
  outlier: (r: ScanRow) => boolean
  /** Mean DR over the tracks that have one, rounded. */
  dr: number | null
}

/** A track without a detected cut-off counts as reaching 22.05 kHz. */
const NO_CUTOFF = 22050

export function median(xs: number[]): number {
  const s = [...xs].sort((a, b) => a - b)
  return s.length ? s[Math.floor(s.length / 2)] : NaN
}

/** One odd track in an album is the classic mixed-source upload: flag rows
 * whose cut-off sits well away from the album median, or whose verdict
 * differs from the majority. */
export function summarizeScan(rows: ScanRow[]): ScanSummary {
  const cuts = rows.map(r => r.cutoffHz ?? NO_CUTOFF)
  const med = median(cuts)
  const counts = { ok: 0, warn: 0, bad: 0 }
  rows.forEach(r => {
    if (r.level) counts[r.level]++
  })
  const major = (Object.entries(counts).sort((a, b) => b[1] - a[1])[0]?.[0] ?? "ok") as Level
  const outlier = (r: ScanRow) =>
    rows.length > 2 && (Math.abs((r.cutoffHz ?? NO_CUTOFF) - med) > 700 || (!!r.level && r.level !== major))
  const drs = rows.map(r => r.dr).filter((v): v is number => v != null)
  return { counts, outlier, dr: drs.length ? Math.round(drs.reduce((a, b) => a + b, 0) / drs.length) : null }
}
