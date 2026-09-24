import type { Stft } from "@/lib/api"
import type { Geometry } from "../geometry"

/** Reference band for hole detection, and the band searched for holes. */
const REF_BAND: [number, number] = [12000, 15500]
const HOLE_BAND_LO = 15800
/** A cell this many dB below its row's typical offset is a hole. */
const HOLE_GAP_DB = 24
/** Frames whose reference level is below this byte value are too quiet to judge. */
const QUIET = 60
/** Bytes per dB: the server maps -160..0 dBFS onto 0..255. */
const BYTES_PER_DB = 255 / 160

export interface HoleOptions {
  /** Centre frequency of each matrix row, top row first. */
  rowHz: Float32Array
  /** Highest frequency to search: just under the detected cut-off. */
  top: number
  /** ABGR pixel value to paint holes with. */
  color: number
}

/** Colours the byte matrix through a 256-entry ABGR lookup table. */
export function paintCells(data: Uint8Array, table: Uint32Array, px: Uint32Array) {
  for (let i = 0; i < data.length; i++) px[i] = table[data[i]]
}

/** Spectral holes. A lossy encoder drops whole bands in single frames, so
 * a hole is a cell far below what THAT frequency row usually carries
 * relative to the same frame's 12-15.5 kHz level. Measuring against the
 * row's own typical offset means a master that simply rolls off at the
 * top is not flagged; only frame-to-frame dropouts are. */
export function markHoles(px: Uint32Array, d: Uint8Array, cols: number, rows: number, o: HoleOptions) {
  const { rowHz: hz, top, color } = o
  const refRows: number[] = [],
    bandRows: number[] = []
  for (let r = 0; r < rows; r++) {
    if (hz[r] >= REF_BAND[0] && hz[r] <= REF_BAND[1]) refRows.push(r)
    else if (hz[r] >= HOLE_BAND_LO && hz[r] <= top) bandRows.push(r)
  }
  const gap = Math.round(HOLE_GAP_DB * BYTES_PER_DB)
  if (!refRows.length || !bandRows.length) return
  const ref = new Int16Array(cols)
  const tmp: number[] = []
  for (let c = 0; c < cols; c++) {
    tmp.length = 0
    for (const r of refRows) tmp.push(d[r * cols + c])
    tmp.sort((x, y) => x - y)
    ref[c] = tmp[tmp.length >> 1]
  }
  const diffs: number[] = []
  for (const r of bandRows) {
    diffs.length = 0
    for (let c = 0; c < cols; c += 3) if (ref[c] >= QUIET) diffs.push(d[r * cols + c] - ref[c])
    if (diffs.length < 8) continue
    diffs.sort((x, y) => x - y)
    const typical = diffs[diffs.length >> 1]
    for (let c = 0; c < cols; c++) {
      if (ref[c] < QUIET) continue // quiet frame: nothing to compare against
      if (d[r * cols + c] - ref[c] < typical - gap) px[r * cols + c] = color
    }
  }
}

/** Renders the matrix to an offscreen canvas at its native resolution. */
export function colorizeStft(s: Stft, table: Uint32Array, holes: HoleOptions | null): HTMLCanvasElement {
  const { cols, rows } = s.meta
  const c = document.createElement("canvas")
  c.width = cols
  c.height = rows
  const g = c.getContext("2d")!
  const img = g.createImageData(cols, rows)
  const px = new Uint32Array(img.data.buffer)
  paintCells(s.data, table, px)
  if (holes) markHoles(px, s.data, cols, rows, holes)
  g.putImageData(img, 0, 0)
  return c
}

/** Base spectrogram. The last matrix is drawn transformed into the current
 * view, so pan and zoom feel instant while the exact one is being fetched. */
export function drawSpectrogram(
  g: CanvasRenderingContext2D,
  geo: Pick<Geometry, "scale" | "plotW" | "specH" | "xOf" | "yOf">,
  s: Stft | null,
  img: CanvasImageSource | null,
) {
  const { plotW, specH, xOf, yOf } = geo
  g.fillStyle = "#000"
  g.fillRect(0, 0, plotW, specH)
  if (!s || !img) return
  const m = s.meta
  // A matrix on the other frequency scale cannot be stretched into place.
  if (m.scale !== geo.scale) return
  const dx = xOf(m.t0),
    dw = xOf(m.t1) - dx
  const dy = yOf(m.f1),
    dh = yOf(m.f0) - dy
  g.imageSmoothingEnabled = dw < m.cols || dh < m.rows
  g.drawImage(img, dx, dy, dw, dh)
}
