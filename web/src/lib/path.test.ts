import { describe, expect, it } from "vitest"
import { baseName, exportFileName, extOf, parentDir } from "./path"

describe("path helpers", () => {
  it("splits paths", () => {
    expect(baseName("a/b/c.flac")).toBe("c.flac")
    expect(parentDir("a/b/c.flac")).toBe("a/b")
    expect(parentDir("c.flac")).toBe("")
  })

  it("upper-cases the extension", () => {
    expect(extOf("x.flac")).toBe("FLAC")
    expect(extOf("x.tar.gz")).toBe("GZ")
  })

  it("names the PNG after the file and the view", () => {
    expect(exportFileName("Music/01 Song.flac", { t0: 12.34, t1: 20.25 })).toBe("01 Song.12.3-20.3s.png")
  })
})
