import { fmtHz, fmtTime, freqTicks, timeTicks } from "@/lib/scale"
import { MONO_FONT } from "../constants"
import { crisp, type Geometry } from "../geometry"

type Ctx = CanvasRenderingContext2D

/** Time ruler above the waveform: labelled ticks with four minor ticks between. */
export function drawRuler(g: Ctx, geo: Pick<Geometry, "view" | "plotW" | "xOf">, h: number) {
  const { view, plotW, xOf } = geo
  g.fillStyle = "#0a0a0a"
  g.fillRect(0, 0, plotW, h)
  const { step, ticks } = timeTicks(view.t0, view.t1, plotW)
  g.font = MONO_FONT
  g.textBaseline = "top"
  for (const t of ticks) {
    const x = crisp(xOf(t))
    g.strokeStyle = "rgba(255,255,255,0.35)"
    g.beginPath()
    g.moveTo(x, h - 7)
    g.lineTo(x, h)
    g.stroke()
    g.fillStyle = "#a3a3a3"
    g.fillText(fmtTime(t, step), x + 3, 5)
    for (let k = 1; k < 5; k++) {
      const xm = crisp(xOf(t + (k * step) / 5))
      g.strokeStyle = "rgba(255,255,255,0.15)"
      g.beginPath()
      g.moveTo(xm, h - 3)
      g.lineTo(xm, h)
      g.stroke()
    }
  }
}

/** Frequency axis right of the plot, like Audition. Labels closer than 13 px
 * are dropped, and so is one under the "Hz" caption. */
export function drawFreqAxis(g: Ctx, geo: Pick<Geometry, "view" | "scale" | "specH" | "yOf">, w: number) {
  const { view, scale, specH, yOf } = geo
  g.fillStyle = "#0a0a0a"
  g.fillRect(0, 0, w, specH)
  g.font = MONO_FONT
  g.textBaseline = "middle"
  let lastY = -100
  for (const f of freqTicks(view, scale, specH).reverse()) {
    const y = crisp(yOf(f))
    if (y - lastY < 13 || y < 16) continue
    lastY = y
    g.strokeStyle = "rgba(255,255,255,0.35)"
    g.beginPath()
    g.moveTo(0, y)
    g.lineTo(5, y)
    g.stroke()
    g.fillStyle = f % 1000 === 0 && f >= 10000 ? "#fafafa" : "#a3a3a3"
    g.fillText(fmtHz(f), 9, y)
  }
  g.fillStyle = "#737373"
  g.fillText("Hz", 9, 8)
}
