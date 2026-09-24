import { describe, expect, it } from "vitest"
import { activeRefs, DEFAULT_REF_SETS, LOSSLESS_ROW, lowpassTable, REF_SETS } from "./references"

describe("activeRefs", () => {
  it("returns only lines of the chosen sets", () => {
    const lines = activeRefs(["opus"])
    expect(lines).toEqual(REF_SETS.find(s => s.id === "opus")!.lines)
  })

  it("sorts across sets, lowest first", () => {
    const khz = activeRefs(DEFAULT_REF_SETS).map(r => r.khz)
    expect(khz).toEqual([...khz].sort((a, b) => a - b))
    expect(khz.length).toBe(6 + 4 + 1)
  })

  it("is empty without sets", () => {
    expect(activeRefs([])).toEqual([])
  })

  it("does not depend on the order of ids", () => {
    expect(activeRefs(["aac", "lame"])).toEqual(activeRefs(["lame", "aac"]))
  })
})

describe("lowpassTable", () => {
  const refs = activeRefs(["lame"])

  it("lists highest first and ends with the lossless row", () => {
    const { rows } = lowpassTable(refs, null)
    expect(rows.at(-1)).toBe(LOSSLESS_ROW)
    expect(rows[0].label).toBe("LAME 320k")
  })

  it("matches lossless when no cut-off was found", () => {
    expect(lowpassTable(refs, null).match).toBe(LOSSLESS_ROW)
  })

  it("matches by the measured cut-off, not the drawn line", () => {
    // 16.8 kHz is the measured edge of LAME 128k; its line is at 17.1.
    expect(lowpassTable(refs, 16.8).match.label).toBe("LAME 128k / V5")
    expect(lowpassTable(refs, 19.55).match.label).toBe("LAME 224-256k / V1")
  })
})
