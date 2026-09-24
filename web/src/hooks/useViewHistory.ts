import { useCallback, useLayoutEffect, useRef, useState } from "react"
import type { View } from "@/lib/scale"

/** Changes closer together than this are one history step. */
const BURST_MS = 400
const MAX_HISTORY = 100

export type SetView = (v: View | ((v: View) => View)) => void

/** The visible view plus an undo stack. A burst of wheel events is one step,
 * so only push when the previous change is more than 400 ms old. */
export function useViewHistory(initial: View) {
  const [view, setViewRaw] = useState<View>(initial)
  const history = useRef<View[]>([])
  const lastPush = useRef(0)
  const viewRef = useRef(view)
  useLayoutEffect(() => {
    viewRef.current = view
  }, [view])

  const setView: SetView = useCallback(v => {
    const now = performance.now()
    if (now - lastPush.current > BURST_MS) {
      history.current.push(viewRef.current)
      if (history.current.length > MAX_HISTORY) history.current.shift()
    }
    lastPush.current = now
    setViewRaw(v)
  }, [])

  const back = useCallback(() => {
    const v = history.current.pop()
    if (v) {
      lastPush.current = 0
      setViewRaw(v)
    }
  }, [])

  /** A new file: forget the old file's history. */
  const reset = useCallback((v: View) => {
    history.current = []
    setViewRaw(v)
  }, [])

  return { view, setView, back, reset }
}
