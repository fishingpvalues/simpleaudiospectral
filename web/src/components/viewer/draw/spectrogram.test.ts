import { describe, expect, it } from "vitest"
import type { Stft } from "@/lib/api"
import { recordingContext } from "@/test/canvasStub"
import { makeGeometry } from "../geometry"
import { drawSpectrogram, markHoles, paintCells } from "./spectrogram"

describe("paintCells", () => {
  it("looks every byte up in the table", () => {
    const table = Uint32Array.from({ length: 256 }, (_, i) => i * 2)
    const px = new Uint32Array(3)
    paintCells(Uint8Array.from([0, 1, 255]), table, px)
    expect(Array.from(px)).toEqual([0, 2, 510])
  })
})

describe("markHoles", () => {
  const HOLE = 7
  // Row 0: 16 kHz (band), row 1: 13 kHz (reference). 30 frames.
  const rowHz = Float32Array.from([16000, 13000])
  const cols = 30

  function matrix(band: (c: number) => number, ref = 200) {
    const d = new Uint8Array(2 * cols)
    for (let c = 0; c < cols; c++) {
      d[c] = band(c)
      d[cols + c] = ref
    }
    return d
  }

  it("marks a single-frame dropout far below the row's usual offset", () => {
    const d = matrix(c => (c === 12 ? 100 : 190))
    const px = new Uint32Array(d.length)
    markHoles(px, d, cols, 2, { rowHz, top: 20000, color: HOLE })
    expect([...px.keys()].filter(i => px[i] === HOLE)).toEqual([12])
  })

  it("does not flag a master that simply rolls off", () => {
    const d = matrix(() => 100)
    const px = new Uint32Array(d.length)
    markHoles(px, d, cols, 2, { rowHz, top: 20000, color: HOLE })
    expect(px.includes(HOLE)).toBe(false)
  })

  it("skips quiet frames and rows above the cut-off", () => {
    const quiet = matrix(c => (c === 12 ? 0 : 190), 40)
    const px = new Uint32Array(quiet.length)
    markHoles(px, quiet, cols, 2, { rowHz, top: 20000, color: HOLE })
    expect(px.includes(HOLE)).toBe(false)
    const d = matrix(c => (c === 12 ? 100 : 190))
    markHoles(px, d, cols, 2, { rowHz, top: 15900, color: HOLE })
    expect(px.includes(HOLE)).toBe(false)
  })
})

describe("drawSpectrogram", () => {
  const s = {
    meta: { t0: 0, t1: 10, f0: 0, f1: 1000, cols: 100, rows: 50, scale: "linear" },
    data: new Uint8Array(0),
  } as unknown as Stft
  const img = {} as CanvasImageSource

  it("stretches the last matrix into the current view", () => {
    const { ctx, calls } = recordingContext()
    drawSpectrogram(ctx, makeGeometry({ t0: 5, t1: 10, f0: 0, f1: 500 }, "linear", 200, 100), s, img)
    expect(calls("drawImage")).toEqual([[img, -200, -100, 400, 200]])
  })

  it("only clears when the matrix is on the other scale", () => {
    const { ctx, calls } = recordingContext()
    drawSpectrogram(ctx, makeGeometry({ t0: 0, t1: 10, f0: 20, f1: 1000 }, "log", 200, 100), s, img)
    expect(calls("fillRect")).toEqual([[0, 0, 200, 100]])
    expect(calls("drawImage")).toEqual([])
  })
})
