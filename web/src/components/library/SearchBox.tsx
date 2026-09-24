import type { KeyboardEvent, RefObject } from "react"
import { Loader2, Search, X } from "lucide-react"
import { Input } from "@/components/ui/input"
import { Kbd } from "@/components/ui/kbd"

interface SearchBoxProps {
  inputRef: RefObject<HTMLInputElement | null>
  query: string
  /** Called with the new text on every edit. */
  onChange: (q: string) => void
  onClear: () => void
  onKeyDown: (e: KeyboardEvent) => void
  searching: boolean
}

export function SearchBox({ inputRef, query, onChange, onClear, onKeyDown, searching }: SearchBoxProps) {
  return (
    <div className="relative px-3 pb-2">
      <Search className="pointer-events-none absolute top-2 left-5.5 size-4 text-muted-foreground" />
      <Input
        ref={inputRef}
        onKeyDown={onKeyDown}
        value={query}
        onChange={e => onChange(e.target.value)}
        placeholder="Search library"
        className="pr-14 pl-8"
        aria-label="Search library"
      />
      <div className="absolute top-1.5 right-5 flex items-center gap-1">
        {searching && <Loader2 className="size-3.5 animate-spin text-muted-foreground" />}
        {query ? (
          <button onClick={onClear} aria-label="Clear search" className="text-muted-foreground hover:text-foreground">
            <X className="size-4" />
          </button>
        ) : (
          <Kbd>/</Kbd>
        )}
      </div>
    </div>
  )
}
