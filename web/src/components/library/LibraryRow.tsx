import type { ReactNode } from "react"
import { cn } from "@/lib/utils"

/** Small upper-case group label ("Volumes", "Recent", "Folders"). */
export function SectionLabel({ children }: { children: ReactNode }) {
  return (
    <div className="px-2 pt-2 pb-1 text-[11px] font-medium tracking-wide text-muted-foreground uppercase">
      {children}
    </div>
  )
}

export function Section({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div className="mb-2">
      <SectionLabel>{label}</SectionLabel>
      {children}
    </div>
  )
}

interface LibraryRowProps {
  icon: ReactNode
  label: string
  sub?: string
  meta?: string
  onClick: () => void
  /** The open file. */
  active?: boolean
  /** The keyboard selection. */
  focused?: boolean
  /** Position in the navigable list, for scrolling the selection into view. */
  idx?: number
}

export function LibraryRow({ icon, label, sub, meta, onClick, active, focused, idx }: LibraryRowProps) {
  return (
    <button
      data-idx={idx}
      role="option"
      aria-selected={active}
      onClick={onClick}
      title={sub ? `${sub}/${label}` : label}
      className={cn(
        "flex w-full items-center gap-2 rounded-md px-2 py-1.5 text-left text-sm text-muted-foreground hover:bg-accent hover:text-foreground [&_svg]:size-4 [&_svg]:shrink-0",
        focused && "ring-1 ring-ring/60",
        active && "bg-secondary text-foreground",
      )}
    >
      {icon}
      <span className="min-w-0 flex-1">
        <span className="block truncate">{label}</span>
        {sub && <span className="block truncate text-[11px] text-muted-foreground/70">{sub}</span>}
      </span>
      {meta && <span className="shrink-0 font-mono text-[10px] text-muted-foreground/70">{meta}</span>}
    </button>
  )
}
