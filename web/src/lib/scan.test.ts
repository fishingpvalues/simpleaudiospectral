import { describe, expect, it } from "vitest"
import type { ScanRow } from "./api"
import { median, summarizeScan } from "./scan"

const row = (name: string, o: Partial<ScanRow> = {}): ScanRow => ({ name, level: "ok", cutoffHz: null, ...o })

describe("median", () => {
  it("takes the upper middle", () => {
    expect(median([3, 1, 2])).toBe(2)
    expect(median([4, 1, 3, 2])).toBe(3)
    expect(median([])).toBeNaN()
  })
})

describe("summarizeScan", () => {
  it("counts levels and averages DR", () => {
    const s = summarizeScan([row("a", { dr: 10 }), row("b", { level: "bad", dr: 7 }), row("c", { level: "warn" })])
    expect(s.counts).toEqual({ ok: 1, warn: 1, bad: 1 })
    expect(s.dr).toBe(9)
  })

  it("has no DR without any", () => {
    expect(summarizeScan([row("a")]).dr).toBeNull()
  })

  it("flags a track whose cut-off is far from the album median", () => {
    const rows = [row("a"), row("b"), row("c", { cutoffHz: 16000 })]
    const s = summarizeScan(rows)
    expect(rows.map(s.outlier)).toEqual([false, false, true])
  })

  it("flags a verdict that differs from the majority", () => {
    const rows = [row("a"), row("b"), row("c", { level: "warn" })]
    expect(summarizeScan(rows).outlier(rows[2])).toBe(true)
  })

  it("flags nothing with two tracks or fewer", () => {
    const rows = [row("a"), row("b", { cutoffHz: 16000, level: "bad" })]
    expect(rows.map(summarizeScan(rows).outlier)).toEqual([false, false])
  })
})
