import { describe, expect, it } from "vitest"
import { clock } from "./clock"

describe("clock", () => {
  it("formats seconds as m:ss or h:mm:ss", () => {
    expect(clock(0)).toBe("0:00")
    expect(clock(75)).toBe("1:15")
    expect(clock(3725)).toBe("1:02:05")
    expect(clock(-3)).toBe("0:00")
  })
})
