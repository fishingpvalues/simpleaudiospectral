import { HardDrive } from "lucide-react"
import type { Root } from "@/lib/api"
import { fmtBytes } from "@/lib/scale"
import { Section } from "./LibraryRow"

/** Library roots with a disk usage bar where the server knows it. */
export function Volumes({ roots, onOpen }: { roots: Root[]; onOpen: (name: string) => void }) {
  return (
    <Section label="Volumes">
      {roots.map(r => {
        const used = r.total && r.free != null ? 1 - r.free / r.total : null
        return (
          <button
            key={r.name}
            onClick={() => onOpen(r.name)}
            className="mb-1 w-full rounded-md border px-2.5 py-2 text-left hover:bg-accent"
          >
            <div className="flex items-center gap-2 text-sm">
              <HardDrive className="size-4 text-muted-foreground" />
              <span className="truncate">{r.name}</span>
            </div>
            {used != null && r.total && (
              <>
                <div className="mt-1.5 h-1 overflow-hidden rounded-full bg-muted">
                  <div className="h-full bg-foreground/70" style={{ width: `${used * 100}%` }} />
                </div>
                <div className="mt-1 text-[11px] text-muted-foreground">
                  {fmtBytes(r.free ?? 0)} free of {fmtBytes(r.total)}
                </div>
              </>
            )}
          </button>
        )
      })}
    </Section>
  )
}
