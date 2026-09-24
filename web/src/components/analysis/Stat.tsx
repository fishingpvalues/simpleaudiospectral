import type { Term as TermKey } from "@/lib/glossary"
import { cn } from "@/lib/utils"
import { Term } from "@/components/ui/tooltip"

interface StatProps {
  k: string
  v: string
  mono?: boolean
  warn?: boolean
  t?: TermKey
}

/** One term/value pair of a <dl> grid. */
export function Stat({ k, v, mono, warn, t }: StatProps) {
  return (
    <div className="min-w-0">
      <dt className="text-[11px] text-muted-foreground">{t ? <Term term={t}>{k}</Term> : k}</dt>
      <dd className={cn("truncate", mono && "font-mono", warn && "text-warning")} title={v}>
        {v}
      </dd>
    </div>
  )
}

interface StatTileProps {
  label: string
  value: string
  unit?: string
  className?: string
  t: TermKey
}

/** A headline number (DR, LUFS, LRA) in its own box. */
export function StatTile({ label, value, unit, className, t }: StatTileProps) {
  return (
    <div className="rounded-md border bg-card px-2.5 py-2">
      <div className="text-[11px] text-muted-foreground">
        <Term term={t}>{label}</Term>
      </div>
      <div className={cn("font-mono text-lg leading-tight font-semibold", className)}>
        {value}
        {unit && <span className="ml-1 text-xs font-normal text-muted-foreground">{unit}</span>}
      </div>
    </div>
  )
}
