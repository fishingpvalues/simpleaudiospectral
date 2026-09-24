import { useCallback, useRef } from "react"
import { exportFileName } from "@/lib/path"
import type { View } from "@/lib/scale"

/** Renders the current view to a PNG data URL, or null when there is nothing drawn. */
export type PngRenderer = () => string | null

/** The Viewer registers its renderer; the toolbar and the E key download it. */
export function usePngExport(path: string | null, view: View) {
  const renderer = useRef<PngRenderer | null>(null)
  const registerExport = useCallback((fn: PngRenderer | null) => {
    renderer.current = fn
  }, [])
  const exportPng = useCallback(() => {
    const url = renderer.current?.()
    if (!url || !path) return
    const a = document.createElement("a")
    a.href = url
    a.download = exportFileName(path, view)
    a.click()
  }, [path, view])
  return { exportPng, registerExport }
}
