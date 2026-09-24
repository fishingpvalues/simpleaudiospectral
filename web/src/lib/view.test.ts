import { describe, expect, it } from "vitest"
import {
  clampView,
  detailView,
  fullView,
  jumpView,
  MIN_SPAN_F,
  MIN_SPAN_T,
  panBy,
  zoomCentered,
  zoomFreqAt,
  zoomTimeAt,
} from "./view"

const DUR = 100,
  NYQ = 22050
const v = { t0: 10, t1: 20, f0: 0, f1: NYQ }

describe("clampView", () => {
  it("keeps a view inside the track and the band", () => {
    expect(clampView({ t0: -5, t1: 5, f0: -100, f1: 1000 }, DUR, NYQ)).toEqual({ t0: 0, t1: 10, f0: 0, f1: 1100 })
    expect(clampView({ t0: 95, t1: 105, f0: 22000, f1: 23000 }, DUR, NYQ)).toEqual({
      t0: 90,
      t1: 100,
      f0: 21050,
      f1: NYQ,
    })
  })

  it("enforces the minimum spans", () => {
    const c = clampView({ t0: 5, t1: 5, f0: 1000, f1: 1000 }, DUR, NYQ)
    expect(c.t1 - c.t0).toBeCloseTo(MIN_SPAN_T)
    expect(c.f1 - c.f0).toBe(MIN_SPAN_F)
  })

  it("never exceeds the track", () => {
    expect(clampView({ t0: 0, t1: 500, f0: 0, f1: 1e6 }, DUR, NYQ)).toEqual(fullView(DUR, NYQ * 2))
  })
})

describe("toolbar zoom and pan", () => {
  it("zooms around the centre", () => {
    expect(zoomCentered(v, 0.5, DUR)).toMatchObject({ t0: 12.5, t1: 17.5 })
    expect(zoomCentered(v, 2, DUR)).toMatchObject({ t0: 5, t1: 25 })
  })

  it("stops at the track ends", () => {
    expect(zoomCentered({ ...v, t0: 0, t1: 10 }, 2, DUR)).toMatchObject({ t0: 0, t1: 20 })
    expect(zoomCentered(v, 100, DUR)).toMatchObject({ t0: 0, t1: DUR })
  })

  it("pans by a fraction of the span and stops at the ends", () => {
    expect(panBy(v, 0.25, DUR)).toMatchObject({ t0: 12.5, t1: 22.5 })
    expect(panBy(v, -5, DUR)).toMatchObject({ t0: 0, t1: 10 })
  })
})

describe("detailView", () => {
  it("covers 8 s from the loudest point, from 15 kHz up", () => {
    expect(detailView(30, DUR, 44100)).toEqual({ t0: 30, t1: 38, f0: 15000, f1: NYQ })
    expect(detailView(0, 5, 96000)).toEqual({ t0: 0, t1: 5, f0: 15000, f1: 48000 })
  })

  it("shows the top 7 kHz when Nyquist is low", () => {
    expect(detailView(0, DUR, 32000).f0).toBe(9000)
  })
})

describe("jumpView", () => {
  it("shows half a second around the time", () => {
    expect(jumpView(v, 50, DUR)).toMatchObject({ t0: 49.75, t1: 50.25 })
    expect(jumpView(v, 0.1, DUR).t0).toBe(0)
  })
})

describe("wheel zoom", () => {
  it("keeps the anchor time in place", () => {
    const z = zoomTimeAt(v, 0.5, 12, DUR)
    expect(z.t1 - z.t0).toBeCloseTo(5)
    expect((12 - z.t0) / (z.t1 - z.t0)).toBeCloseTo(0.2)
  })

  it("keeps the anchor frequency in place", () => {
    const z = zoomFreqAt(v, 0.5, 0.5, "linear", NYQ)
    expect(z.f1 - z.f0).toBeCloseTo(NYQ / 2)
    expect((z.f0 + z.f1) / 2).toBeCloseTo(NYQ / 2)
  })
})
