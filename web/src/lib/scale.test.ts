import { describe, expect, it } from "vitest"
import { fmtBytes, fmtHz, fmtTime, freqTicks, fToY, niceStep, timeTicks, yToF, type View } from "./scale"

const v: View = { t0: 0, t1: 10, f0: 0, f1: 22050 }

describe("fToY / yToF", () => {
  it("maps the band edges to the plot edges on a linear scale", () => {
    expect(fToY(v.f1, v, "linear")).toBe(0)
    expect(fToY(v.f0, v, "linear")).toBe(1)
    expect(fToY(11025, v, "linear")).toBeCloseTo(0.5)
  })

  it.each(["linear", "log"] as const)("round-trips on a %s scale", scale => {
    const view = { ...v, f0: 20 }
    for (const f of [20, 100, 1000, 8000, 16000, 22050])
      expect(yToF(fToY(f, view, scale), view, scale)).toBeCloseTo(f, 6)
  })

  it("clamps the log scale's floor at 10 Hz", () => {
    expect(fToY(0, v, "log")).toBe(1)
    expect(yToF(1, v, "log")).toBeCloseTo(10)
  })
})

describe("ticks", () => {
  it("picks 1-2-5 steps", () => {
    expect(niceStep(10, 10)).toBe(1)
    expect(niceStep(10, 4)).toBe(5)
    expect(niceStep(100, 3)).toBe(50)
    expect(niceStep(7, 1)).toBe(10)
  })

  it("time ticks cover the range at the chosen step", () => {
    const { step, ticks } = timeTicks(0.5, 10, 900)
    expect(step).toBe(1)
    expect(ticks[0]).toBe(1)
    expect(ticks.at(-1)).toBe(10)
  })

  it("log frequency ticks are 1-2-5 per decade inside the view", () => {
    expect(freqTicks({ ...v, f0: 50, f1: 1100 }, "log", 400)).toEqual([50, 100, 200, 500, 1000])
  })

  it("linear frequency ticks are evenly spaced", () => {
    const t = freqTicks(v, "linear", 520)
    expect(t[0]).toBe(0)
    expect(t[1] - t[0]).toBe(2000)
    expect(t.at(-1)).toBe(22000)
  })
})

describe("fmtTime", () => {
  it("formats minutes and seconds", () => {
    expect(fmtTime(0)).toBe("0:00")
    expect(fmtTime(75)).toBe("1:15")
    expect(fmtTime(3725)).toBe("1:02:05")
  })

  it("adds decimals for fine steps", () => {
    expect(fmtTime(1.234, 0.1)).toBe("0:01.2")
    expect(fmtTime(1.234, 0.01)).toBe("0:01.23")
    expect(fmtTime(1.2346, 0.001)).toBe("0:01.235")
  })

  it("rounds before splitting so 59.6 s is 1:00, not 0:60", () => {
    expect(fmtTime(59.6)).toBe("1:00")
  })

  it("never shows negative time", () => {
    expect(fmtTime(-3)).toBe("0:00")
  })
})

describe("fmtHz", () => {
  it("uses k above 1 kHz", () => {
    expect(fmtHz(500)).toBe("500")
    expect(fmtHz(16000)).toBe("16k")
    expect(fmtHz(16500)).toBe("16.5k")
    expect(fmtHz(16543, true)).toBe("16.54k")
  })
})

describe("fmtBytes", () => {
  it("picks a binary unit", () => {
    expect(fmtBytes(2048)).toBe("2 KiB")
    expect(fmtBytes(5 * 2 ** 20)).toBe("5.0 MiB")
    expect(fmtBytes(3 * 2 ** 30)).toBe("3.00 GiB")
  })
})
