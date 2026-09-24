import { describe, expect, it } from "vitest"
import type { Listing } from "@/lib/api"
import { buildItems } from "./items"

const listing: Listing = {
  path: "",
  dirs: [
    { name: "Music", mtime: 0 },
    { name: "Podcasts", mtime: 0 },
  ],
  files: [{ name: "Intro.flac", size: 10, mtime: 0 }],
}

describe("buildItems", () => {
  it("hides top-level folders already listed as volumes", () => {
    const items = buildItems({
      dir: "",
      listing,
      roots: [{ name: "Music", total: null, free: null }],
      hits: null,
      filter: "",
    })
    expect(items.map(i => i.key)).toEqual(["d:Podcasts", "f:Intro.flac"])
  })

  it("adds an up row and joins paths inside a folder", () => {
    const items = buildItems({ dir: "Music", listing, roots: [], hits: null, filter: "" })
    expect(items[0]).toEqual({ kind: "up", key: ".." })
    expect(items[1]).toMatchObject({ kind: "dir", path: "Music/Music" })
    expect(items[3]).toMatchObject({ kind: "file", path: "Music/Intro.flac", size: 10 })
  })

  it("filters the folder by name, including volumes at the root", () => {
    const roots = [{ name: "Music", total: null, free: null }]
    const items = buildItems({ dir: "", listing, roots, hits: null, filter: "mus" })
    expect(items.map(i => i.key)).toEqual(["d:Music"])
  })

  it("shows search hits instead of the folder", () => {
    const hits = [
      { path: "A/b.flac", name: "b.flac", dir: "A", isDir: false },
      { path: "C", name: "C", dir: "", isDir: true },
    ]
    const items = buildItems({ dir: "X", listing, roots: [], hits, filter: "b" })
    expect(items).toEqual([
      { kind: "file", key: "s:A/b.flac", path: "A/b.flac", name: "b.flac", sub: "A" },
      { kind: "dir", key: "s:C", path: "C", name: "C", sub: "" },
    ])
  })
})
