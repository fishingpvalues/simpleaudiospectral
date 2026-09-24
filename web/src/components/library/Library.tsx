import { useEffect, useMemo, useRef, type KeyboardEvent } from "react"
import { Clock, FileAudio, Folder, ListChecks } from "lucide-react"
import { baseName, extOf, parentDir } from "@/lib/path"
import { loadRecent } from "@/lib/recent"
import { fmtBytes } from "@/lib/scale"
import { Button } from "@/components/ui/button"
import { Kbd } from "@/components/ui/kbd"
import { ScrollArea } from "@/components/ui/scroll-area"
import { Tip } from "@/components/ui/tooltip"
import { Breadcrumbs } from "./Breadcrumbs"
import { buildItems, type Item } from "./items"
import { LibraryRow, Section, SectionLabel } from "./LibraryRow"
import { SearchBox } from "./SearchBox"
import { useLibrary } from "./useLibrary"
import { Volumes } from "./Volumes"

/** Recent files shown at the library root. */
const RECENT_SHOWN = 6

interface LibraryProps {
  dir: string
  setDir: (d: string) => void
  current: string | null
  onOpen: (path: string) => void
  onScan: (dir: string) => void
}

export function Library({ dir, setDir, current, onOpen, onScan }: LibraryProps) {
  const { listing, roots, indexed, query, setQuery, hits, searching, error, sel, setSel } = useLibrary(dir)
  const listRef = useRef<HTMLDivElement>(null)
  const inputRef = useRef<HTMLInputElement>(null)

  const f = query.toLowerCase()
  const items = useMemo(() => buildItems({ dir, listing, roots, hits, filter: f }), [hits, listing, f, dir, roots])

  useEffect(() => {
    setSel(i => Math.min(i, Math.max(0, items.length - 1)))
  }, [items.length, setSel])
  useEffect(() => {
    listRef.current?.querySelector<HTMLElement>(`[data-idx="${sel}"]`)?.scrollIntoView({ block: "nearest" })
  }, [sel])

  const activate = (it: Item) => {
    if (it.kind === "up") setDir(parentDir(dir))
    else if (it.kind === "dir") setDir(it.path)
    else onOpen(it.path)
  }

  const onKey = (e: KeyboardEvent) => {
    if (e.key === "ArrowDown") {
      e.preventDefault()
      setSel(i => Math.min(items.length - 1, i + 1))
    } else if (e.key === "ArrowUp") {
      e.preventDefault()
      setSel(i => Math.max(0, i - 1))
    } else if (e.key === "Enter" && items[sel]) {
      e.preventDefault()
      activate(items[sel])
    } else if (e.key === "Escape") {
      setQuery("")
      ;(e.target as HTMLElement).blur()
    } else if (e.key === "Backspace" && !query && dir && e.target === inputRef.current) {
      e.preventDefault()
      setDir(parentDir(dir))
    }
  }

  // "/" focuses the search from anywhere, like most file browsers.
  useEffect(() => {
    const h = (e: globalThis.KeyboardEvent) => {
      if (e.key === "/" && !(e.target as HTMLElement).closest("input,textarea")) {
        e.preventDefault()
        inputRef.current?.focus()
      }
    }
    window.addEventListener("keydown", h)
    return () => window.removeEventListener("keydown", h)
  }, [])

  const atRoot = !dir && !hits
  const audioHere = (listing?.files.length ?? 0) > 0
  const rec = atRoot ? loadRecent().slice(0, RECENT_SHOWN) : []

  return (
    <div className="flex h-full min-h-0 flex-col">
      <div className="flex items-center gap-1 px-3 pt-3 pb-2">
        <Breadcrumbs dir={dir} setDir={setDir} />
        {audioHere && (
          <Tip label="Scan every track in this folder">
            <Button variant="outline" size="sm" onClick={() => onScan(dir)}>
              <ListChecks />
              Scan
            </Button>
          </Tip>
        )}
      </div>
      <SearchBox
        inputRef={inputRef}
        query={query}
        onChange={q => {
          setQuery(q)
          setSel(0)
        }}
        onClear={() => setQuery("")}
        onKeyDown={onKey}
        searching={searching}
      />
      {hits && (
        <div className="px-4 pb-1 text-[11px] text-muted-foreground">
          {hits.length} {hits.length === 1 ? "result" : "results"} across the library
          {indexed && !indexed.ready ? " (index still building)" : ""}
        </div>
      )}
      <ScrollArea className="min-h-0 flex-1">
        <div ref={listRef} className="px-1.5 pb-3" role="listbox" aria-label="Library" tabIndex={-1} onKeyDown={onKey}>
          {atRoot && roots.length > 0 && <Volumes roots={roots} onOpen={setDir} />}
          {rec.length > 0 && (
            <Section label="Recent">
              {rec.map(p => (
                <LibraryRow
                  key={"r:" + p}
                  icon={<Clock />}
                  label={baseName(p) ?? p}
                  sub={parentDir(p)}
                  active={current === p}
                  onClick={() => onOpen(p)}
                />
              ))}
            </Section>
          )}
          {atRoot && roots.length > 0 && items.length > 0 && <SectionLabel>Folders</SectionLabel>}
          {items.map((it, i) => (
            <LibraryRow
              key={it.key}
              idx={i}
              focused={i === sel}
              icon={it.kind === "file" ? <FileAudio /> : <Folder />}
              label={it.kind === "up" ? ".." : it.name}
              sub={it.kind !== "up" ? it.sub : undefined}
              meta={it.kind === "file" ? `${extOf(it.name)}${it.size ? " " + fmtBytes(it.size) : ""}` : undefined}
              active={it.kind === "file" && current === it.path}
              onClick={() => {
                setSel(i)
                activate(it)
              }}
            />
          ))}
          {error && <p className="px-2 py-4 text-sm text-destructive">{error}</p>}
          {listing && !items.length && (
            <p className="px-2 py-4 text-sm text-muted-foreground">{hits ? "No matches." : "Nothing here."}</p>
          )}
        </div>
      </ScrollArea>
      <div className="border-t px-3 py-1.5 text-[11px] text-muted-foreground">
        <Kbd>Up</Kbd> <Kbd>Down</Kbd> move, <Kbd>Enter</Kbd> open, <Kbd>Bksp</Kbd> up a level
        {indexed?.ready && <span className="float-right">{indexed.entries.toLocaleString()} indexed</span>}
      </div>
    </div>
  )
}
