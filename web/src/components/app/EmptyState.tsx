import { AudioWaveform, Loader2 } from "lucide-react"
import type { Progress } from "@/lib/api"

interface EmptyStateProps {
  analysing: boolean
  error: string | null
  name?: string
  progress: Progress | null
}

/** The main area before a file is shown: prompt, analysis progress or error. */
export function EmptyState({ analysing, error, name, progress }: EmptyStateProps) {
  return (
    <div className="flex h-full flex-col items-center justify-center gap-3 text-center text-muted-foreground">
      {analysing ? (
        <>
          <Loader2 className="size-6 animate-spin" aria-hidden="true" />
          <p className="text-sm" role="status">
            {progress ? `${progress.stage}` : "Decoding"} - {name}
          </p>
          {progress && progress.done > 0 && (
            <div
              className="h-1 w-64 overflow-hidden rounded-full bg-muted"
              role="progressbar"
              aria-valuemin={0}
              aria-valuemax={100}
              aria-valuenow={Math.round(progress.done * 100)}
            >
              <div className="h-full bg-foreground/70" style={{ width: `${progress.done * 100}%` }} />
            </div>
          )}
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
