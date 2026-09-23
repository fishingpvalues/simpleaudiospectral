// 256-entry RGBA lookup tables. "audition" follows Adobe Audition's spectral
// display (black - violet - red - orange - yellow - white), which is what the
// RED guide's screenshots use; "spek" follows Spek.
type Stop = [number, string]

const MAPS: Record<string, Stop[]> = {
  // Adobe Audition's spectral frequency display, matched against the RED
  // guide's Audition CS6 screenshots: black floor, indigo/violet low energy,
  // magenta-red mids, orange-yellow peaks, white only at the very top.
  audition: [[0, "#000000"], [0.14, "#0b0726"], [0.28, "#2c0a5a"], [0.42, "#620f78"], [0.55, "#a3147a"],
    [0.66, "#d61f3f"], [0.76, "#f0501a"], [0.86, "#fa9a17"], [0.94, "#fde25a"], [1, "#ffffff"]],
  spek: [[0, "#000000"], [0.2, "#00004a"], [0.4, "#6a0080"], [0.6, "#e0002a"], [0.78, "#ff8000"], [0.9, "#ffe000"], [1, "#ffffff"]],
  // Colour-vision-deficiency safe (perceptually uniform, monotonic lightness).
  cividis: [[0, "#00224e"], [0.125, "#123570"], [0.25, "#3b496c"], [0.375, "#575d6d"], [0.5, "#707173"],
    [0.625, "#8a8779"], [0.75, "#a69d75"], [0.875, "#c4b56c"], [1, "#fee838"]],
  viridis: [[0, "#440154"], [0.125, "#482878"], [0.25, "#3e4989"], [0.375, "#31688e"], [0.5, "#26828e"],
    [0.625, "#1f9e89"], [0.75, "#35b779"], [0.875, "#6ece58"], [1, "#fde725"]],
  magma: [[0, "#000004"], [0.125, "#1c1044"], [0.25, "#4f127b"], [0.375, "#812581"], [0.5, "#b5367a"],
    [0.625, "#e55064"], [0.75, "#fb8761"], [0.875, "#fec287"], [1, "#fcfdbf"]],
  inferno: [[0, "#000004"], [0.14, "#1b0c41"], [0.29, "#4a0c6b"], [0.43, "#781c6d"], [0.57, "#a52c60"], [0.71, "#cf4446"], [0.86, "#ed6925"], [0.93, "#fb9b06"], [1, "#fcffa4"]],
  gray: [[0, "#000000"], [1, "#ffffff"]],
}

export const COLORMAP_GROUPS: { label: string; maps: string[] }[] = [
  { label: "Classic", maps: ["audition", "spek"] },
  { label: "Colour-blind safe", maps: ["cividis", "viridis", "magma", "inferno", "gray"] },
]

/** Accent for analysis overlays (holes, rolloff) that stays visible on the map. */
export function overlayColor(name: string): { css: string; abgr: number } {
  return ["viridis", "cividis", "gray"].includes(name)
    ? { css: "#ff2d95", abgr: (255 << 24) | (0x95 << 16) | (0x2d << 8) | 0xff }
    : { css: "#22d3ee", abgr: (255 << 24) | (0xee << 16) | (0xd3 << 8) | 0x22 }
}

export const COLORMAPS = Object.keys(MAPS)

function hex(h: string): [number, number, number] {
  return [parseInt(h.slice(1, 3), 16), parseInt(h.slice(3, 5), 16), parseInt(h.slice(5, 7), 16)]
}

const cache = new Map<string, Uint8ClampedArray>()

/** 256 x RGBA for the palette itself. */
export function palette(name: string): Uint8ClampedArray {
  const hit = cache.get(name)
  if (hit) return hit
  const stops = MAPS[name] ?? MAPS.audition
  const out = new Uint8ClampedArray(256 * 4)
  for (let i = 0; i < 256; i++) {
    const t = i / 255
    let j = 0
    while (j < stops.length - 2 && t > stops[j + 1][0]) j++
    const [t0, c0] = stops[j], [t1, c1] = stops[j + 1]
    const u = Math.min(1, Math.max(0, (t - t0) / (t1 - t0 || 1)))
    const a = hex(c0), b = hex(c1)
    out[i * 4] = a[0] + (b[0] - a[0]) * u
    out[i * 4 + 1] = a[1] + (b[1] - a[1]) * u
    out[i * 4 + 2] = a[2] + (b[2] - a[2]) * u
    out[i * 4 + 3] = 255
  }
  cache.set(name, out)
  return out
}

/**
 * Quantised-dB -> packed ABGR lookup, folding in the display range: the server
 * sends dB on a fixed -160..0 scale, so floor/ceiling changes are instant and
 * never refetch.
 */
export function lut(name: string, dbFloor: number, dbCeil: number, qFloor: number, qCeil: number): Uint32Array {
  const pal = palette(name)
  const out = new Uint32Array(256)
  for (let v = 0; v < 256; v++) {
    const db = qFloor + (v / 255) * (qCeil - qFloor)
    const t = Math.min(1, Math.max(0, (db - dbFloor) / (dbCeil - dbFloor)))
    const i = Math.round(t * 255) * 4
    out[v] = (255 << 24) | (pal[i + 2] << 16) | (pal[i + 1] << 8) | pal[i]
  }
  return out
}
