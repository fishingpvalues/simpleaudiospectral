import { ChevronRight } from "lucide-react"

/** "library > a > b" with each segment clickable. */
export function Breadcrumbs({ dir, setDir }: { dir: string; setDir: (d: string) => void }) {
  const parts = dir ? dir.split("/") : []
  return (
    <nav className="flex min-w-0 flex-1 flex-wrap items-center gap-0.5 text-xs text-muted-foreground">
      <button className="hover:text-foreground" onClick={() => setDir("")}>
        library
      </button>
      {parts.map((p, i) => (
        <span key={i} className="flex min-w-0 items-center gap-0.5">
          <ChevronRight className="size-3 shrink-0" />
          <button
            className="max-w-36 truncate hover:text-foreground"
            title={p}
            onClick={() => setDir(parts.slice(0, i + 1).join("/"))}
          >
            {p}
          </button>
        </span>
      ))}
    </nav>
  )
}
