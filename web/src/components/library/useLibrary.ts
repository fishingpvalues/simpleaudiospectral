import { useEffect, useState } from "react"
import { api, type Listing, type Root, type SearchHit } from "@/lib/api"

/** Queries shorter than this only filter the current folder. */
const MIN_QUERY = 2
const DEBOUNCE_MS = 150

/** Folder listing, volumes, and library-wide search. The current folder is
 * filtered instantly as well; search runs once the query is 2+ characters. */
export function useLibrary(dir: string) {
  const [listing, setListing] = useState<Listing | null>(null)
  const [roots, setRoots] = useState<Root[]>([])
  const [indexed, setIndexed] = useState<{ ready: boolean; entries: number } | null>(null)
  const [query, setQuery] = useState("")
  const [hits, setHits] = useState<SearchHit[] | null>(null)
  const [searching, setSearching] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [sel, setSel] = useState(0)

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

  useEffect(() => {
    if (query.trim().length < MIN_QUERY) {
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
    }, DEBOUNCE_MS)
    return () => {
      clearTimeout(t)
      ctl.abort()
    }
  }, [query])

  return { listing, roots, indexed, query, setQuery, hits, searching, error, sel, setSel }
}
