import { useEffect, useState } from "react"

function readHash() {
  const p = new URLSearchParams(location.hash.slice(1))
  return { dir: p.get("dir") ?? "", file: p.get("file") }
}

/** The library folder and open file, mirrored in the URL hash (#dir=..&file=..). */
export function useHashRoute() {
  const [init] = useState(readHash)
  const [dir, setDir] = useState(init.dir)
  const [path, setPath] = useState<string | null>(init.file)

  useEffect(() => {
    const p = new URLSearchParams()
    if (dir) p.set("dir", dir)
    if (path) p.set("file", path)
    history.replaceState(null, "", `#${p}`)
  }, [dir, path])

  // A pasted deep link in an already open tab only changes the hash.
  useEffect(() => {
    const onHash = () => {
      const h = readHash()
      setDir(h.dir)
      if (h.file) setPath(h.file)
    }
    window.addEventListener("hashchange", onHash)
    return () => window.removeEventListener("hashchange", onHash)
  }, [])

  return { dir, setDir, path, setPath }
}
