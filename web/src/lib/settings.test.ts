import { afterEach, describe, expect, it, vi } from "vitest"
import { DEFAULTS, loadSettings, saveSettings, STORE } from "./settings"

function memoryStore(init: Record<string, string> = {}) {
  const m = new Map(Object.entries(init))
  return { getItem: (k: string) => m.get(k) ?? null, setItem: (k: string, v: string) => void m.set(k, v), m }
}

afterEach(() => vi.unstubAllGlobals())

describe("loadSettings", () => {
  it("returns the defaults when nothing is stored", () => {
    expect(loadSettings(memoryStore())).toEqual(DEFAULTS)
  })

  it("merges stored keys over the defaults", () => {
    const s = loadSettings(memoryStore({ [STORE]: JSON.stringify({ fft: 8192, cmap: "spek" }) }))
    expect(s).toEqual({ ...DEFAULTS, fft: 8192, cmap: "spek" })
  })

  it("survives bad JSON", () => {
    expect(loadSettings(memoryStore({ [STORE]: "{not json" }))).toBe(DEFAULTS)
  })

  it("survives storage that throws", () => {
    const broken = {
      getItem: () => {
        throw new Error("SecurityError")
      },
      setItem: () => {},
    }
    expect(loadSettings(broken)).toBe(DEFAULTS)
  })

  it("survives a missing localStorage", () => {
    vi.stubGlobal("localStorage", undefined)
    expect(loadSettings()).toBe(DEFAULTS)
  })

  it("reads localStorage by default", () => {
    vi.stubGlobal("localStorage", memoryStore({ [STORE]: JSON.stringify({ grid: false }) }))
    expect(loadSettings().grid).toBe(false)
  })
})

describe("saveSettings", () => {
  it("writes under the versioned key", () => {
    const st = memoryStore()
    saveSettings({ ...DEFAULTS, holes: true }, st)
    expect(JSON.parse(st.m.get("spectrals.settings.v1")!).holes).toBe(true)
  })

  it("ignores storage errors", () => {
    const full = {
      getItem: () => null,
      setItem: () => {
        throw new Error("QuotaExceededError")
      },
    }
    expect(() => saveSettings(DEFAULTS, full)).not.toThrow()
  })
})
