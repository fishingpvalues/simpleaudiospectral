import { describe, expect, it } from "vitest"
import type { Stft, StftMeta } from "@/lib/api"
import { deriveSeries, meanSpectrum, readCursor } from "./derive"

/** A linear 0..1000 Hz matrix, dB = floor + byte * (ceil - floor) / 255. */
function stft(rows: number, cols: number, data: number[]): Stft {
  const meta: StftMeta = {
    cols,
    rows,
    t0: 0,
    t1: cols,
    f0: 0,
    f1: 1000,
    scale: "linear",
    fft: 4096,
    sr: 2000,
    dbFloor: -255,
    dbCeil: 0,
    binHz: 1,
    framesPerCol: 1,
    duration: cols,
  }
  return { meta, data: Uint8Array.from(data) }
}

describe("deriveSeries", () => {
  it("gives row centre frequencies, top row first", () => {
    const { rowHz } = deriveSeries(stft(4, 1, [0, 0, 0, 0]))
    expect(Array.from(rowHz)).toEqual([875, 625, 375, 125])
  })

  it("puts the rolloff at the highest row holding the top 1% of energy", () => {
    // Column 0: all energy in row 2 (375 Hz). Column 1: energy in row 0 (875 Hz).
    const s = stft(4, 2, [0, 255, 0, 0, 255, 0, 0, 0])
    const { rolloff } = deriveSeries(s)
    expect(rolloff[0]).toBe(375)
    expect(rolloff[1]).toBe(875)
  })

  it("marks a silent column NaN", () => {
    expect(deriveSeries(stft(2, 1, [0, 0])).rolloff[0]).toBeNaN()
  })
})

describe("meanSpectrum", () => {
  it("returns bottom-to-top mean levels", () => {
    const s = stft(2, 2, [255, 255, 0, 0])
    const spec = meanSpectrum(deriveSeries(s), 2)
    expect(Array.from(spec.hz)).toEqual([250, 750])
    expect(spec.db[1]).toBeCloseTo(0)
    expect(spec.db[0]).toBeLessThan(-200)
  })
})

describe("readCursor", () => {
  const s = stft(2, 2, [255, 0, 51, 102])

  it("reads the level of the cell under the cursor", () => {
    expect(readCursor(s, 0.5, 900, "linear").db).toBe(0)
    expect(readCursor(s, 1.5, 100, "linear").db).toBe(-153)
  })

  it("returns the column as a bottom-to-top slice", () => {
    const { slice } = readCursor(s, 1.5, 100, "linear")
    expect(Array.from(slice!.hz)).toEqual([250, 750])
    expect(Array.from(slice!.db)).toEqual([-153, -255])
  })

  it("reads nothing outside the matrix or on the other scale", () => {
    expect(readCursor(s, 5, 100, "linear")).toEqual({ db: null, slice: null })
    expect(readCursor(s, 0.5, 100, "log")).toEqual({ db: null, slice: null })
    expect(readCursor(null, 0.5, 100, "linear")).toEqual({ db: null, slice: null })
  })
})
