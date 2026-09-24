export type Channel = "mix" | "left" | "right" | "side"
export type Scale = "linear" | "log"

export interface Listing {
  path: string
  dirs: { name: string; mtime: number }[]
  files: { name: string; size: number; mtime: number }[]
}
export interface Root {
  name: string
  total: number | null
  free: number | null
}
export interface SearchHit {
  path: string
  name: string
  dir: string
  isDir: boolean
}

export interface Analysis {
  cutoffHz: number | null
  dropDb: number
  extentHz: number
  nyquistHz: number
  shelf16k: boolean
  sideDb: number
  verdict: string
  level: "ok" | "warn" | "bad"
  refDb: number
  curve: { hz: number[]; db: number[]; median: number[] }
  shelfDropDb: number
  hiresDb: number | null
  hfSd: number | null
  family: string | null
  resampledFrom: number | null
  crtTone: number | null
  loudestAt: number
}

export interface Info {
  path: string
  codec: string | null
  codecName: string | null
  sampleRate: number
  channels: number
  bits: number | null
  bitDepthUsed: string | null
  duration: number
  bitrate: number
  size: number
  encoder: string | null
  artist: string | null
  title: string | null
  album: string | null
  date: string | null
  analysis: Analysis | null
}

export interface Stats {
  loudness: {
    lufs: number | null
    lra: number | null
    truePeakDb: number | null
    samplePeakDb: number | null
    rmsDb: number | null
    dcOffset: number | null
    flatFactor: number | null
    noiseFloorDb: number | null
    effectiveBits: string | null
  }
  dynamics: {
    dr: number
    drPerChannel: number[]
    clipEvents: number
    flatTopEvents: number
    clipTimes: number[]
    correlation: number | null
    correlationSeries?: number[]
    identicalChannels: boolean
    rumbleDb: number | null
    clicksPerMin: number
  } | null
  quietFloorDb: number | null
  channelCutoffs: { left: number | null; right: number | null; side: number | null }
  bitUsage: { bits: number; ones: number[]; unusedLowBits: number } | null
}

export interface ScanRow {
  name: string
  codec?: string
  sampleRate?: number
  bits?: number | null
  duration?: number
  bitrate?: number
  cutoffHz?: number | null
  level?: "ok" | "warn" | "bad"
  family?: string | null
  shelf16k?: boolean
  hfSd?: number | null
  verdict?: string
  dr?: number
  clipEvents?: number
  lufs?: number | null
  truePeakDb?: number | null
  error?: string
}

export interface StftMeta {
  cols: number
  rows: number
  t0: number
  t1: number
  f0: number
  f1: number
  scale: Scale
  fft: number
  sr: number
  dbFloor: number
  dbCeil: number
  binHz: number
  framesPerCol: number
  duration: number
}

export interface Stft {
  meta: StftMeta
  data: Uint8Array
}

const q = (o: Record<string, string | number>) =>
  Object.entries(o)
    .map(([k, v]) => `${k}=${encodeURIComponent(v)}`)
    .join("&")

/** Fired when the server wants the API key (401); the AuthGate shows the login. */
export const UNAUTHORIZED = "sas:unauthorized"

async function get(url: string, signal?: AbortSignal): Promise<Response> {
  const r = await fetch(url, { signal })
  if (r.status === 401) {
    window.dispatchEvent(new Event(UNAUTHORIZED))
    throw new Error("API key required")
  }
  return r
}

export interface Health {
  status: string
  version: string
  indexed: boolean
  auth: boolean
  authenticated: boolean
}

async function json<T>(url: string, signal?: AbortSignal): Promise<T> {
  const r = await get(url, signal)
  const body = await r.json()
  if (!r.ok) throw new Error(body.error ?? r.statusText)
  return body as T
}

export interface Progress {
  stage: string
  done: number
}

/** The analysis of a long file runs in the background; the server answers 202
 * with its stage until the result is ready. */
async function poll<T>(url: string, signal?: AbortSignal, onProgress?: (p: Progress) => void): Promise<T> {
  for (;;) {
    const r = await get(url, signal)
    const body = await r.json()
    if (r.status === 202) {
      onProgress?.(body as Progress)
      await new Promise<void>((res, rej) => {
        const t = setTimeout(res, 1000)
        signal?.addEventListener("abort", () => {
          clearTimeout(t)
          rej(new DOMException("aborted", "AbortError"))
        })
      })
      continue
    }
    if (!r.ok) throw new Error(body.error ?? r.statusText)
    return body as T
  }
}

export const api = {
  health: () => fetch("/api/health").then(r => r.json() as Promise<Health>),
  /** Exchanges the key for an HttpOnly session cookie; false when the key is wrong. */
  async login(key: string): Promise<boolean> {
    const r = await fetch("/api/login", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ key }),
    })
    if (r.status === 401) return false
    if (!r.ok) throw new Error(((await r.json()) as { error?: string }).error ?? r.statusText)
    return true
  },
  async logout() {
    await fetch("/api/logout", { method: "POST" })
    window.dispatchEvent(new Event(UNAUTHORIZED))
  },
  ls: (path: string) => json<Listing>(`/api/ls?${q({ path })}`),
  roots: () => json<{ roots: Root[]; indexed: boolean; entries: number }>("/api/roots"),
  search: (query: string, signal?: AbortSignal) =>
    json<{ ready: boolean; results: SearchHit[] }>(`/api/search?${q({ q: query, limit: 150 })}`, signal),
  info: (path: string, signal?: AbortSignal, onProgress?: (p: Progress) => void) =>
    poll<Info>(`/api/info?${q({ path })}`, signal, onProgress),
  stats: (path: string, signal?: AbortSignal, onProgress?: (p: Progress) => void) =>
    poll<Stats>(`/api/stats?${q({ path })}`, signal, onProgress),
  async stft(p: Record<string, string | number>, signal?: AbortSignal): Promise<Stft> {
    const r = await get(`/api/stft?${q(p)}`, signal)
    if (!r.ok) throw new Error((await r.json()).error ?? r.statusText)
    const meta = JSON.parse(r.headers.get("X-Meta") ?? "{}") as StftMeta
    return { meta, data: new Uint8Array(await r.arrayBuffer()) }
  },
  async wave(p: Record<string, string | number>, signal?: AbortSignal): Promise<Float32Array> {
    const r = await get(`/api/wave?${q(p)}`, signal)
    if (!r.ok) throw new Error(r.statusText)
    return new Float32Array(await r.arrayBuffer())
  },
  audioUrl: (path: string, transcode = false) => `/api/audio?${q(transcode ? { path, format: "flac" } : { path })}`,
  async gonio(
    p: Record<string, string | number>,
    signal?: AbortSignal,
  ): Promise<{ size: number; correlation: number; data: Uint8Array }> {
    const r = await get(`/api/gonio?${q(p)}`, signal)
    if (!r.ok) throw new Error(r.statusText)
    const meta = JSON.parse(r.headers.get("X-Meta") ?? "{}")
    return { ...meta, data: new Uint8Array(await r.arrayBuffer()) }
  },
  /** Streams one row per track as the server finishes it. */
  async scan(path: string, onTotal: (n: number) => void, onRow: (r: ScanRow) => void, signal?: AbortSignal) {
    const r = await get(`/api/scan?${q({ path })}`, signal)
    if (!r.ok || !r.body) throw new Error(r.statusText)
    const reader = r.body.getReader(),
      dec = new TextDecoder()
    let buf = ""
    for (;;) {
      const { value, done } = await reader.read()
      if (done) break
      buf += dec.decode(value, { stream: true })
      let i
      while ((i = buf.indexOf("\n")) >= 0) {
        const line = buf.slice(0, i).trim()
        buf = buf.slice(i + 1)
        if (!line) continue
        const o = JSON.parse(line)
        if ("total" in o) onTotal(o.total)
        else onRow(o as ScanRow)
      }
    }
  },
  soxUrl: (p: Record<string, string | number>) => `/api/spectrogram?${q(p)}`,
}
