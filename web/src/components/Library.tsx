import { useCallback, useEffect, useMemo, useRef, useState } from "react"
import { ChevronRight, Clock, FileAudio, Folder, HardDrive, ListChecks, Loader2, Search, X } from "lucide-react"
import { api, type Listing, type Root, type SearchHit } from "@/lib/api"
import { fmtBytes } from "@/lib/scale"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Kbd } from "@/components/ui/kbd"
import { ScrollArea } from "@/components/ui/scroll-area"
import { Tip } from "@/components/ui/tooltip"
import { cn } from "@/lib/utils"

interface Props {
  dir: string
  setDir: (d: string) => void
  current: string | null
  onOpen: (path: string) => void
  onScan: (dir: string) => void
}

type Item =
  | { kind: "up"; key: string }
  | { kind: "dir"; key: string; path: string; name: string; sub?: string }
  | { kind: "file"; key: string; path: string; name: string; sub?: string; size?: number }

const ext = (n: string) => n.slice(n.lastIndexOf(".") + 1).toUpperCase()

function recent(): string[] {
  try {
    return JSON.parse(localStorage.getItem("spectrals.recent") ?? "[]")
  } catch {
    return []
  }
}

export function Library({ dir, setDir, current, onOpen, onScan }: Props) {
  const [listing, setListing] = useState<Listing | null>(null)
  const [roots, setRoots] = useState<Root[]>([])
  const [indexed, setIndexed] = useState<{ ready: boolean; entries: number } | null>(null)
  const [query, setQuery] = useState("")
  const [hits, setHits] = useState<SearchHit[] | null>(null)
  const [searching, setSearching] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [sel, setSel] = useState(0)
  const listRef = useRef<HTMLDivElement>(null)
  const inputRef = useRef<HTMLInputElement>(null)

  useEffect(() => {
    let live = true
    setQuery("")
    setHits(null)
    setSel(0)
    api
      .ls(dir)
      .then(l => {
        if (live) {
          setListing(l)
          setError(null)
        }
      })
      .catch(e => live && setError(String(e.message ?? e)))
    return () => {
      live = false
    }
  }, [dir])

  useEffect(() => {
    api
      .roots()
      .then(r => {
        setRoots(r.roots)
        setIndexed({ ready: r.indexed, entries: r.entries })
      })
      .catch(() => {})
  }, [])

  // Library-wide search once the query is 2+ characters; the current folder
  // is filtered instantly as well.
  useEffect(() => {
    if (query.trim().length < 2) {
      setHits(null)
      return
    }
    const ctl = new AbortController()
    setSearching(true)
    const t = setTimeout(() => {
      api
        .search(query, ctl.signal)
        .then(r => {
          setHits(r.results)
          setIndexed(i => ({ entries: i?.entries ?? 0, ready: r.ready }))
        })
        .catch(() => {})
        .finally(() => setSearching(false))
    }, 150)
    return () => {
      clearTimeout(t)
      ctl.abort()
    }
  }, [query])

  const join = useCallback((n: string) => (dir ? `${dir}/${n}` : n), [dir])
  const f = query.toLowerCase()

  const items: Item[] = useMemo(() => {
    if (hits) {
      return hits.map(h =>
        h.isDir
          ? { kind: "dir" as const, key: "s:" + h.path, path: h.path, name: h.name, sub: h.dir }
          : { kind: "file" as const, key: "s:" + h.path, path: h.path, name: h.name, sub: h.dir },
      )
    }
    const out: Item[] = []
    if (dir) out.push({ kind: "up", key: ".." })
    // At the root the volumes list already shows every top-level folder.
    const shown = !dir && !f ? new Set(roots.map(r => r.name)) : new Set<string>()
    for (const d of listing?.dirs ?? [])
      if (!shown.has(d.name) && (!f || d.name.toLowerCase().includes(f)))
        out.push({ kind: "dir", key: "d:" + d.name, path: join(d.name), name: d.name })
    for (const x of listing?.files ?? [])
      if (!f || x.name.toLowerCase().includes(f))
        out.push({ kind: "file", key: "f:" + x.name, path: join(x.name), name: x.name, size: x.size })
    return out
  }, [hits, listing, f, dir, join, roots])

  useEffect(() => {
    setSel(i => Math.min(i, Math.max(0, items.length - 1)))
  }, [items.length])
  useEffect(() => {
    listRef.current?.querySelector<HTMLElement>(`[data-idx="${sel}"]`)?.scrollIntoView({ block: "nearest" })
  }, [sel])

  const activate = (it: Item) => {
    if (it.kind === "up") setDir(dir.split("/").slice(0, -1).join("/"))
    else if (it.kind === "dir") setDir(it.path)
    else onOpen(it.path)
  }

  const onKey = (e: React.KeyboardEvent) => {
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
      setDir(dir.split("/").slice(0, -1).join("/"))
    }
  }

  // "/" focuses the search from anywhere, like most file browsers.
  useEffect(() => {
    const h = (e: KeyboardEvent) => {
      if (e.key === "/" && !(e.target as HTMLElement).closest("input,textarea")) {
        e.preventDefault()
        inputRef.current?.focus()
      }
    }
    window.addEventListener("keydown", h)
    return () => window.removeEventListener("keydown", h)
  }, [])

  const parts = dir ? dir.split("/") : []
  const audioHere = (listing?.files.length ?? 0) > 0
  const rec = !dir && !hits ? recent().slice(0, 6) : []

  return (
    <div className="flex h-full min-h-0 flex-col">
      <div className="flex items-center gap-1 px-3 pt-3 pb-2">
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
        {audioHere && (
          <Tip label="Scan every track in this folder">
            <Button variant="outline" size="sm" onClick={() => onScan(dir)}>
              <ListChecks />
              Scan
            </Button>
          </Tip>
        )}
      </div>
      <div className="relative px-3 pb-2">
        <Search className="pointer-events-none absolute top-2 left-5.5 size-4 text-muted-foreground" />
        <Input
          ref={inputRef}
          onKeyDown={onKey}
          value={query}
          onChange={e => {
            setQuery(e.target.value)
            setSel(0)
          }}
          placeholder="Search library"
          className="pr-14 pl-8"
          aria-label="Search library"
        />
        <div className="absolute top-1.5 right-5 flex items-center gap-1">
          {searching && <Loader2 className="size-3.5 animate-spin text-muted-foreground" />}
          {query ? (
            <button
              onClick={() => setQuery("")}
              aria-label="Clear search"
              className="text-muted-foreground hover:text-foreground"
            >
              <X className="size-4" />
            </button>
          ) : (
            <Kbd>/</Kbd>
          )}
        </div>
      </div>
      {hits && (
        <div className="px-4 pb-1 text-[11px] text-muted-foreground">
          {hits.length} {hits.length === 1 ? "result" : "results"} across the library
          {indexed && !indexed.ready ? " (index still building)" : ""}
        </div>
      )}
      <ScrollArea className="min-h-0 flex-1">
        <div ref={listRef} className="px-1.5 pb-3" role="listbox" aria-label="Library" tabIndex={-1} onKeyDown={onKey}>
          {!dir && !hits && roots.length > 0 && (
            <Section label="Volumes">
              {roots.map(r => {
                const used = r.total && r.free != null ? 1 - r.free / r.total : null
                return (
                  <button
                    key={r.name}
                    onClick={() => setDir(r.name)}
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
          )}
          {rec.length > 0 && (
            <Section label="Recent">
              {rec.map(p => (
                <Row
                  key={"r:" + p}
                  icon={<Clock />}
                  label={p.split("/").pop() ?? p}
                  sub={p.split("/").slice(0, -1).join("/")}
                  active={current === p}
                  onClick={() => onOpen(p)}
                />
              ))}
            </Section>
          )}
          {!dir && !hits && roots.length > 0 && items.length > 0 && (
            <div className="px-2 pt-2 pb-1 text-[11px] font-medium tracking-wide text-muted-foreground uppercase">
              Folders
            </div>
          )}
          {items.map((it, i) => (
            <Row
              key={it.key}
              idx={i}
              focused={i === sel}
              icon={it.kind === "file" ? <FileAudio /> : <Folder />}
              label={it.kind === "up" ? ".." : it.name}
              sub={it.kind !== "up" ? it.sub : undefined}
              meta={it.kind === "file" ? `${ext(it.name)}${it.size ? " " + fmtBytes(it.size) : ""}` : undefined}
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

function Section({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="mb-2">
      <div className="px-2 pt-2 pb-1 text-[11px] font-medium tracking-wide text-muted-foreground uppercase">
        {label}
      </div>
      {children}
    </div>
  )
}

function Row({
  icon,
  label,
  sub,
  meta,
  onClick,
  active,
  focused,
  idx,
}: {
  icon: React.ReactNode
  label: string
  sub?: string
  meta?: string
  onClick: () => void
  active?: boolean
  focused?: boolean
  idx?: number
}) {
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
