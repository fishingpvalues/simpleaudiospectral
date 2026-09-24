import { useEffect } from "react"
import { SHORTCUT_IGNORE, shortcutFor, type ShortcutAction } from "@/lib/shortcuts"
import { useLatest } from "./useLatest"

/** A handler returns false when it did nothing, so the key keeps its default. */
export type ShortcutHandlers = Record<ShortcutAction, () => unknown>

export function useKeyboardShortcuts(handlers: ShortcutHandlers) {
  const latest = useLatest(handlers)
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if ((e.target as HTMLElement).closest(SHORTCUT_IGNORE)) return
      const action = shortcutFor(e)
      if (!action) return
      if (latest.current[action]() === false) return
      e.preventDefault()
    }
    window.addEventListener("keydown", onKey)
    return () => window.removeEventListener("keydown", onKey)
  }, [latest])
}
