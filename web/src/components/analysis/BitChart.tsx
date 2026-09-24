import type { Stats } from "@/lib/api"
import { cn } from "@/lib/utils"
import { Term } from "@/components/ui/tooltip"

/** Share of ones per bit position; a bit that is never set shows as dead. */
export function BitChart({ u }: { u: NonNullable<Stats["bitUsage"]> }) {
  // MSB on the left, like reading a sample word.
  const bars = [...u.ones].reverse()
  return (
    <div className="mt-3">
      <div className="mb-1 flex justify-between text-[11px] text-muted-foreground">
        <Term term="bitUsage">Bit usage (MSB .. LSB)</Term>
        <span>{u.unusedLowBits ? `${u.unusedLowBits} low bits always 0` : "all bits used"}</span>
      </div>
      <div
        className="flex h-12 items-end gap-px rounded-md border bg-black p-1"
        role="img"
        aria-label={`Bit usage: ${u.unusedLowBits ? `${u.unusedLowBits} lowest bits never set` : `all ${u.bits} bits carry data`}`}
      >
        {bars.map((v, i) => {
          const bit = u.bits - 1 - i
          const dead = bit < u.unusedLowBits
          return (
            <div
              key={i}
              className="flex h-full flex-1 flex-col justify-end"
              title={`bit ${bit}: ${(v * 100).toFixed(1)}% ones`}
            >
              <div
                className={cn("w-full rounded-[1px]", dead ? "bg-destructive" : "bg-neutral-300")}
                style={{ height: `${Math.max(2, v * 200)}%`, maxHeight: "100%" }}
              />
            </div>
          )
        })}
      </div>
      {u.unusedLowBits >= 8 && u.bits >= 24 && (
        <p className="mt-1 text-xs text-warning">
          Padded: a {u.bits - u.unusedLowBits}-bit master in a {u.bits}-bit file.
        </p>
      )}
    </div>
  )
}
