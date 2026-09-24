import { useLayoutEffect, useRef } from "react"

/** A ref that always holds the latest value, for callbacks read from inside
 * effects that should not re-run when the callback identity changes. */
export function useLatest<T>(value: T) {
  const ref = useRef(value)
  useLayoutEffect(() => {
    ref.current = value
  }, [value])
  return ref
}
