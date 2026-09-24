import { describe, expect, it } from "vitest"
import { activeRefs } from "@/lib/references"
import { recordingContext } from "@/test/canvasStub"
import { makeGeometry } from "../geometry"
import { drawCutoff, drawRefLines, drawSpecOverlay, drawWaveOverlay, type SpecOverlay } from "./overlays"

const geo = makeGeometry({ t0: 0, t1: 10, f0: 0, f1: 22050 }, "linear", 1000, 441)
const none: SpecOverlay = {
  grid: false,
  refs: null,
  analysis: null,
  rolloff: null,
  drag: null,
  mouse: null,
  playhead: null,
}

describe("drawRefLines", () => {
  it("draws every line in view but drops crowded labels", () => {
    const { ctx, calls, texts } = recordingContext()
    drawRefLines(ctx, geo, activeRefs(["lame", "aac"]))
    expect(calls("stroke").length).toBe(10)
    // 17.1/17.3 and 19.2/19.4 are 4 px apart at this height.
    expect(texts().length).toBeLessThan(10)
    expect(texts()[0]).toBe("LAME 128k / V5  17.1k")
  })

  it("skips lines outside the view", () => {
    const { ctx, calls } = recordingContext()
    drawRefLines(ctx, makeGeometry({ t0: 0, t1: 1, f0: 0, f1: 17200 }, "linear", 100, 100), activeRefs(["lame"]))
    expect(calls("stroke").length).toBe(1)
  })
})

describe("drawCutoff", () => {
  it("labels the cut-off and the 16 kHz shelf", () => {
    const { ctx, texts } = recordingContext()
    drawCutoff(ctx, geo, { cutoffHz: 16000, shelf16k: true })
    expect(texts()).toEqual(["Frequency cut-off at 16.0 kHz", "Shelf at 16 kHz"])
  })

  it("draws nothing without a cut-off in view", () => {
    const { ctx, ops } = recordingContext()
    drawCutoff(ctx, geo, { cutoffHz: null, shelf16k: false })
    drawCutoff(ctx, makeGeometry({ t0: 0, t1: 1, f0: 0, f1: 8000 }, "linear", 100, 100), {
      cutoffHz: 16000,
      shelf16k: false,
    })
    expect(ops).toEqual([])
  })
})

describe("drawSpecOverlay", () => {
  it("clears and draws nothing else when every layer is off", () => {
    const { ctx, calls } = recordingContext()
    drawSpecOverlay(ctx, geo, none)
    expect(calls("clearRect")).toEqual([[0, 0, 1000, 441]])
    expect(calls("stroke")).toEqual([])
  })

  it("draws the playhead only inside the view", () => {
    const inView = recordingContext()
    drawSpecOverlay(inView.ctx, geo, { ...none, playhead: 5 })
    expect(inView.calls("moveTo")).toEqual([[500, 0]])
    const outside = recordingContext()
    drawSpecOverlay(outside.ctx, geo, { ...none, playhead: 12 })
    expect(outside.calls("stroke")).toEqual([])
  })

  it("hides the crosshair while dragging", () => {
    const { ctx, calls } = recordingContext()
    drawSpecOverlay(ctx, geo, {
      ...none,
      mouse: { x: 10, y: 20, area: "spec" },
      drag: { kind: "box", x0: 0, y0: 0, x1: 50, y1: 40 },
    })
    expect(calls("strokeRect")).toEqual([[0.5, 0.5, 50, 40]])
    expect(calls("moveTo")).toEqual([])
  })
})

describe("drawWaveOverlay", () => {
  it("keeps the previous lineWidth for the cursor line", () => {
    const { ctx, ops } = recordingContext()
    drawWaveOverlay(ctx, geo, 96, null, { x: 10, y: 0, area: "wave" }, null)
    expect(ops.some(o => "set" in o && o.set === "lineWidth")).toBe(false)
  })

  it("shades a wave selection", () => {
    const { ctx, calls } = recordingContext()
    drawWaveOverlay(ctx, geo, 96, { kind: "wave", x0: 80, x1: 20 }, null, null)
    expect(calls("fillRect")).toEqual([[20, 0, 60, 96]])
  })
})
