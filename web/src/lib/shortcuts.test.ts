import { describe, expect, it } from "vitest"
import { KEYMAP, SHORTCUT_HELP, shortcutFor } from "./shortcuts"

const key = (k: string, mods: Partial<{ metaKey: boolean; ctrlKey: boolean }> = {}) => ({
  key: k,
  metaKey: false,
  ctrlKey: false,
  ...mods,
})

describe("shortcutFor", () => {
  it("maps the documented keys", () => {
    expect(shortcutFor(key(" "))).toBe("togglePlay")
    expect(shortcutFor(key("+"))).toBe("zoomIn")
    expect(shortcutFor(key("="))).toBe("zoomIn")
    expect(shortcutFor(key("_"))).toBe("zoomOut")
    expect(shortcutFor(key("Backspace"))).toBe("back")
    expect(shortcutFor(key("4"))).toBe("chSide")
  })

  it("lets Cmd and Ctrl chords through", () => {
    expect(shortcutFor(key("r", { metaKey: true }))).toBeNull()
    expect(shortcutFor(key("0", { ctrlKey: true }))).toBeNull()
  })

  it("ignores unmapped keys, including object prototype names", () => {
    expect(shortcutFor(key("x"))).toBeNull()
    expect(shortcutFor(key("constructor"))).toBeNull()
  })

  it("is case sensitive like the original handler", () => {
    expect(shortcutFor(key("F"))).toBeNull()
  })
})

describe("SHORTCUT_HELP", () => {
  it("has unique keys (React list keys)", () => {
    const keys = SHORTCUT_HELP.map(([k]) => k)
    expect(new Set(keys).size).toBe(keys.length)
  })

  it("maps every action to at least one key", () => {
    expect(new Set(KEYMAP.values()).size).toBe(19)
  })
})
