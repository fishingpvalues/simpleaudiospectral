import type { Info } from "@/lib/api"
import { fmtHz, fmtTime, type View } from "@/lib/scale"
import type { Settings } from "@/lib/settings"
import { Term } from "@/components/ui/tooltip"
import type { Cursor } from "@/components/viewer/types"

interface StatusBarProps {
  info: Info | null
  view: View
  cursor: Cursor | null
  settings: Settings
}

/** Footer: the view bounds, the cursor readout and the FFT resolution. */
export function StatusBar({ info, view, cursor, settings }: StatusBarProps) {
  return (
    <footer
      aria-label="Cursor readout"
      className="col-span-3 flex items-center gap-5 border-t px-3 font-mono text-xs text-muted-foreground"
    >
      {info ? (
        <>
          <span>
            view {fmtTime(view.t0, 0.01)} - {fmtTime(view.t1, 0.01)}
          </span>
          <span>
            {fmtHz(view.f0)} - {fmtHz(view.f1)} Hz
          </span>
          {cursor && <span className="text-foreground">t {fmtTime(cursor.t, 0.001)}</span>}
          {cursor && Number.isFinite(cursor.f) && <span className="text-foreground">f {fmtHz(cursor.f, true)}Hz</span>}
          {cursor?.db != null && <span className="text-foreground">{cursor.db.toFixed(1)} dBFS</span>}
          <span className="ml-auto">
            <Term term="hzPerBin">
              FFT {settings.fft} = {(info.sampleRate / settings.fft).toFixed(1)} Hz/bin,{" "}
              {((settings.fft / info.sampleRate) * 1000).toFixed(1)} ms
            </Term>
          </span>
        </>
      ) : (
        <span>drag = box zoom - shift+drag = pan - wheel = zoom - alt+wheel = frequency zoom</span>
      )}
    </footer>
  )
}
