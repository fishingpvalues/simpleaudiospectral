import { describe, expect, it } from "vitest"
import { crisp, makeGeometry } from "./geometry"

describe("makeGeometry", () => {
  const geo = makeGeometry({ t0: 10, t1: 20, f0: 0, f1: 20000 }, "linear", 1000, 400)

  it("maps time to x and back", () => {
    expect(geo.xOf(10)).toBe(0)
    expect(geo.xOf(15)).toBe(500)
    expect(geo.tOf(250)).toBe(12.5)
  })

  it("maps frequency to y from the top", () => {
    expect(geo.yOf(20000)).toBe(0)
    expect(geo.yOf(0)).toBe(400)
    expect(geo.fOf(100)).toBe(15000)
  })

  it("round-trips on a log scale", () => {
    const g = makeGeometry({ t0: 0, t1: 1, f0: 20, f1: 20000 }, "log", 100, 300)
    expect(g.fOf(g.yOf(1000))).toBeCloseTo(1000, 6)
  })
})

describe("crisp", () => {
  it("snaps to the pixel centre", () => {
    expect(crisp(10.2)).toBe(10.5)
    expect(crisp(10.7)).toBe(11.5)
  })
})
