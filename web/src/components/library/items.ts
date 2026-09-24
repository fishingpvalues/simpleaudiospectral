import type { Listing, Root, SearchHit } from "@/lib/api"

/** One row of the keyboard-navigable library list. */
export type Item =
  | { kind: "up"; key: string }
  | { kind: "dir"; key: string; path: string; name: string; sub?: string }
  | { kind: "file"; key: string; path: string; name: string; sub?: string; size?: number }

interface BuildArgs {
  dir: string
  listing: Listing | null
  roots: Root[]
  hits: SearchHit[] | null
  /** Lower-cased filter for the current folder. */
  filter: string
}

/** Search hits when there are any, else the current folder filtered by name. */
export function buildItems({ dir, listing, roots, hits, filter: f }: BuildArgs): Item[] {
  if (hits) {
    return hits.map(h =>
      h.isDir
        ? { kind: "dir" as const, key: "s:" + h.path, path: h.path, name: h.name, sub: h.dir }
        : { kind: "file" as const, key: "s:" + h.path, path: h.path, name: h.name, sub: h.dir },
    )
  }
  const join = (n: string) => (dir ? `${dir}/${n}` : n)
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
}
