import { useLayoutEffect, useState, type RefObject } from "react"

/** Content-box size of an element in whole CSS pixels, kept current by a ResizeObserver. */
export function useElementSize(ref: RefObject<HTMLElement | null>) {
  const [size, setSize] = useState({ w: 0, h: 0 })
  useLayoutEffect(() => {
    const el = ref.current
    if (!el) return
    const ro = new ResizeObserver(([e]) =>
      setSize({ w: Math.floor(e.contentRect.width), h: Math.floor(e.contentRect.height) }),
    )
    ro.observe(el)
    return () => ro.disconnect()
  }, [ref])
  return size
}
