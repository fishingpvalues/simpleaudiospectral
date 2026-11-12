import { AudioWaveform, Loader2 } from "lucide-react"
import type { Progress } from "@/lib/api"
import { clock } from "@/lib/clock"

interface EmptyStateProps {
  analysing: boolean
  error: string | null
  name?: string
  progress: Progress | null
}

/** The main area before a file is shown: prompt, analysis progress or error. */
export function EmptyState({ analysing, error, name, progress }: EmptyStateProps) {
  const pct = Math.floor((progress?.done ?? 0) * 100)
  const side = progress?.stages?.filter(s => ["loudness", "bits", "soxbits"].includes(s.key) && s.done < 1) ?? []
  return (
    <div className="flex h-full flex-col items-center justify-center gap-3 text-center text-muted-foreground">
      {analysing ? (
        <>
          <Loader2 className="size-6 animate-spin" aria-hidden="true" />
          <p className="max-w-md truncate text-sm text-foreground" title={name}>
            {name}
          </p>
          <div className="flex w-72 max-w-[calc(100vw-2rem)] flex-col gap-1.5">
            <div className="flex items-baseline justify-between gap-3 text-xs">
              <span role="status" className="truncate">
                {progress ? progress.stage : "Starting"}
              </span>
              <span className="text-foreground tabular-nums">{pct}%</span>
            </div>
            <div
              className="h-1.5 overflow-hidden rounded-full bg-muted"
              role="progressbar"
              aria-label={`Analysing ${name ?? "file"}`}
              aria-valuemin={0}
              aria-valuemax={100}
              aria-valuenow={pct}
              aria-valuetext={`${pct}%, ${progress?.stage ?? "starting"}`}
            >
              <div
                className="h-full rounded-full bg-foreground/70 transition-[width] duration-300 ease-out"
                style={{ width: `${(progress?.done ?? 0) * 100}%` }}
              />
            </div>
            <div className="flex justify-between gap-3 text-xs tabular-nums">
              <span>{progress?.elapsed != null ? `${clock(progress.elapsed)} elapsed` : " "}</span>
              <span>{progress?.eta != null && progress.eta > 0 ? `about ${clock(progress.eta)} left` : ""}</span>
            </div>
            {side.length > 0 && (
              <p className="text-left text-xs">
                Alongside:{" "}
                {side.map((s, i) => (
                  <span key={s.key}>
                    {i > 0 && ", "}
                    {s.label} {Math.floor(s.done * 100)}%
                  </span>
                ))}
              </p>
            )}
          </div>
          <p className="max-w-sm text-xs">
            Every frame of the file is analysed. The first analysis of a long file takes a while; the result is kept, so
            opening it again is instant.
          </p>
        </>
      ) : error ? (
        <p className="text-sm text-destructive">{error}</p>
      ) : (
        <>
          <AudioWaveform className="size-10" />
          <p className="max-w-md text-sm">
            Open a FLAC, MP3, WAV, ALAC, Opus, Ogg, AIFF, WavPack or APE file to see its spectral, waveform and lowpass
            analysis.
          </p>
        </>
      )}
    </div>
  )
}
