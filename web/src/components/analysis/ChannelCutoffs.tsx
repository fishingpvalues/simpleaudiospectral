import type { Stats } from "@/lib/api"
import { cn } from "@/lib/utils"
import { Term } from "@/components/ui/tooltip"

/** Cut-offs further apart than this (Hz) are worth a warning. */
const MISMATCH_HZ = 700

const khz = (v: number | null) => (v ? `${(v / 1000).toFixed(2)} kHz` : "none")

export function ChannelCutoffs({ c }: { c: Stats["channelCutoffs"] }) {
  const lr = c.left && c.right ? Math.abs(c.left - c.right) : 0
  const sideLow = c.side && (!c.left || c.side < c.left - MISMATCH_HZ)
  return (
    <div className="mt-3">
      <div className="mb-1 text-[11px] text-muted-foreground">
        <Term term="channelCutoffs">Cut-off per channel</Term>
      </div>
      <div className="grid grid-cols-3 gap-2 font-mono text-xs">
        <div className="rounded border px-2 py-1">L {khz(c.left)}</div>
        <div className="rounded border px-2 py-1">R {khz(c.right)}</div>
        <div className={cn("rounded border px-2 py-1", sideLow && "border-warning text-warning")}>S {khz(c.side)}</div>
      </div>
      {sideLow && (
        <p className="mt-1 text-xs text-warning">
          Side channel is cut lower than L/R: typical of joint-stereo lossy coding.
        </p>
      )}
      {lr > MISMATCH_HZ && (
        <p className="mt-1 text-xs text-warning">
          L and R cut-offs differ by {(lr / 1000).toFixed(1)} kHz: channels from different sources?
        </p>
      )}
    </div>
  )
}
