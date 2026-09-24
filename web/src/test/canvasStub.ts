/** One recorded canvas operation: a method call or a property assignment. */
export type Op = { call: string; args: unknown[] } | { set: string; value: unknown }

/** A CanvasRenderingContext2D stand-in that records what is drawn. Text is
 * measured as 6 px per character so label layout is deterministic. */
export function recordingContext() {
  const ops: Op[] = []
  const state: Record<string, unknown> = {}
  const ctx = new Proxy(state, {
    get(target, key: string) {
      if (key in target) return target[key]
      if (key === "measureText") return (s: string) => ({ width: s.length * 6 })
      return (...args: unknown[]) => {
        ops.push({ call: key, args })
      }
    },
    set(target, key: string, value) {
      target[key] = value
      ops.push({ set: key, value })
      return true
    },
  }) as unknown as CanvasRenderingContext2D
  const calls = (name: string) => ops.flatMap(o => ("call" in o && o.call === name ? [o.args] : []))
  const texts = () => calls("fillText").map(a => a[0] as string)
  return { ctx, ops, calls, texts }
}
