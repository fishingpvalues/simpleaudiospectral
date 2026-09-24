import type { Scale, Stft } from "@/lib/api"
import { fToY, yToF } from "@/lib/scale"
import type { Cursor, Spectrum } from "./types"

/** Fraction of a column's energy below the rolloff frequency. */
const ROLLOFF = 0.99

export interface Derived {
  /** Centre frequency of each matrix row, top row first. */
  rowHz: Float32Array
  /** 99% rolloff per column in Hz; NaN for a silent column. */
  rolloff: Float32Array
  /** Summed linear power per row, over all columns. */
  power: Float64Array
}

const metaView = (m: Stft["meta"]) => ({ t0: m.t0, t1: m.t1, f0: m.f0, f1: m.f1 })

/** Per-view series. The 99% spectral rolloff per column: a flat line is an
 * encoder lowpass, a line that moves with the music is a real top end. */
export function deriveSeries(s: Stft): Derived {
  const { cols, rows, dbFloor, dbCeil } = s.meta
  const mv = metaView(s.meta)
  const hz = new Float32Array(rows)
  for (let r = 0; r < rows; r++) hz[r] = yToF((r + 0.5) / rows, mv, s.meta.scale)
  const k = (dbCeil - dbFloor) / 255
  const pow = new Float32Array(256)
  for (let v = 0; v < 256; v++) pow[v] = Math.pow(10, (dbFloor + v * k) / 10)
  const ro = new Float32Array(cols)
  const power = new Float64Array(rows)
  const d = s.data
  for (let c = 0; c < cols; c++) {
    let tot = 0
    for (let r = 0; r < rows; r++) {
      const p = pow[d[r * cols + c]]
      tot += p
      power[r] += p
    }
    let acc = 0,
      f = hz[rows - 1]
    for (let r = rows - 1; r >= 0; r--) {
      acc += pow[d[r * cols + c]]
      if (acc >= ROLLOFF * tot) {
        f = hz[r]
        break
      }
    }
    ro[c] = tot > 1e-14 ? f : NaN
  }
  return { rowHz: hz, rolloff: ro, power }
}

/** Mean spectrum of the view, bottom to top (Audition's "frequency analysis" of a range). */
export function meanSpectrum({ rowHz, power }: Derived, cols: number): Spectrum {
  const rows = rowHz.length
  const hz = new Float32Array(rows),
    db = new Float32Array(rows)
  for (let r = 0; r < rows; r++) {
    hz[rows - 1 - r] = rowHz[r]
    db[rows - 1 - r] = 10 * Math.log10(power[r] / cols + 1e-30)
  }
  return { hz, db }
}

/** Level at (t, f) and the spectrum of that column, when the matrix covers `t`
 * on the displayed scale. */
export function readCursor(s: Stft | null, t: number, f: number, scale: Scale): Pick<Cursor, "db" | "slice"> {
  if (!s || s.meta.scale !== scale || t < s.meta.t0 || t > s.meta.t1) return { db: null, slice: null }
  const m = s.meta
  const col = Math.min(m.cols - 1, Math.max(0, Math.floor(((t - m.t0) / (m.t1 - m.t0)) * m.cols)))
  const mv = metaView(m)
  const row = Math.min(m.rows - 1, Math.max(0, Math.floor(fToY(f, mv, m.scale) * m.rows)))
  const k = (m.dbCeil - m.dbFloor) / 255
  const db = m.dbFloor + s.data[row * m.cols + col] * k
  const hz = new Float32Array(m.rows),
    dbs = new Float32Array(m.rows)
  for (let r = 0; r < m.rows; r++) {
    const rr = m.rows - 1 - r
    hz[r] = yToF((rr + 0.5) / m.rows, mv, m.scale)
    dbs[r] = m.dbFloor + s.data[rr * m.cols + col] * k
  }
  return { db, slice: { hz, db: dbs } }
}
