import { expect, test, type Page } from "@playwright/test"

// Every test fails on a console error or an uncaught exception, which also
// catches Content-Security-Policy violations.
const consoleErrors = new WeakMap<Page, string[]>()

test.beforeEach(async ({ page }) => {
  const errors: string[] = []
  consoleErrors.set(page, errors)
  page.on("console", m => m.type() === "error" && errors.push(m.text()))
  page.on("pageerror", e => errors.push(String(e)))
})

test.afterEach(async ({ page }) => {
  expect(consoleErrors.get(page)).toEqual([])
})

// View changes closer together than this are one step of the zoom history.
const HISTORY_BURST_MS = 450

const spectrogram = (page: Page) => page.getByRole("img", { name: /^Spectrogram,/ })

async function open(page: Page, file: string) {
  await page.goto(`/#dir=Artist%2FAlbum&file=Artist%2FAlbum%2F${encodeURIComponent(file)}`)
  await expect(page.getByRole("complementary", { name: "Analysis" })).toContainText(/Lowpass at|No lowpass/)
}

async function viewLabel(page: Page) {
  return (await spectrogram(page).getAttribute("aria-label")) ?? ""
}

test("a transcode names its lowpass and likely codec", async ({ page }) => {
  await open(page, "02 transcode.flac")
  const panel = page.getByRole("complementary", { name: "Analysis" })
  await expect(panel).toContainText(/Lowpass at 1[5-7]\.\d kHz, \d+ dB drop: MP3 128k\./)
  await expect(panel).toContainText("Suspect transcode")
  await expect(page.getByRole("banner")).toContainText(/cut-off 1[5-7]\.\d kHz/)
})

test("a lossless file reports no lowpass", async ({ page }) => {
  await open(page, "01 real.flac")
  await expect(page.getByRole("complementary", { name: "Analysis" })).toContainText("No lowpass.")
  await expect(page.getByRole("banner")).toContainText("no lowpass")
})

test("keyboard: detail zoom, fit and back", async ({ page }) => {
  await open(page, "01 real.flac")
  const full = await viewLabel(page)
  expect(full).toContain("0:00.0 to 0:12.0")
  await page.keyboard.press("z")
  await expect.poll(() => viewLabel(page)).not.toBe(full)
  const zoomed = await viewLabel(page)
  expect(zoomed).toMatch(/to 22\.1k hertz/)
  await page.waitForTimeout(HISTORY_BURST_MS)
  await page.keyboard.press("f")
  await expect.poll(() => viewLabel(page)).toBe(full)
  await page.keyboard.press("Backspace")
  await expect.poll(() => viewLabel(page)).toBe(zoomed)
})

test("wheel and box zoom change the view", async ({ page }) => {
  await open(page, "01 real.flac")
  const full = await viewLabel(page)
  const box = (await spectrogram(page).boundingBox())!
  await page.mouse.move(box.x + box.width / 2, box.y + box.height / 2)
  await page.mouse.wheel(0, -400)
  await expect.poll(() => viewLabel(page)).not.toBe(full)
  await page.keyboard.press("f")
  await expect.poll(() => viewLabel(page)).toBe(full)
  await page.mouse.move(box.x + box.width * 0.2, box.y + box.height * 0.2)
  await page.mouse.down()
  await page.mouse.move(box.x + box.width * 0.5, box.y + box.height * 0.6, { steps: 8 })
  await page.mouse.up()
  await expect.poll(() => viewLabel(page)).not.toBe(full)
})

test("display settings persist and drive the reference table", async ({ page }) => {
  await open(page, "02 transcode.flac")
  const settings = () => page.evaluate(() => JSON.parse(localStorage.getItem("spectrals.settings.v1") ?? "{}"))
  await page.keyboard.press("g")
  await expect.poll(async () => (await settings()).grid).toBe(false)
  await page.getByRole("button", { name: "Display", exact: true }).click()
  await page.getByRole("switch", { name: "Vorbis (libvorbis) lowpass lines" }).click()
  await expect.poll(async () => (await settings()).refSets).toContain("vorbis")
  await page.keyboard.press("Escape")
  await expect(page.getByRole("complementary", { name: "Analysis" })).toContainText("Vorbis q3")
  await page.reload()
  await expect(page.getByRole("complementary", { name: "Analysis" })).toContainText("Vorbis q3")
})

test("search finds a track and opens it", async ({ page }) => {
  await page.goto("/")
  await page.getByRole("textbox", { name: "Search library" }).fill("wavpack")
  await page.getByRole("option", { name: /03 wavpack\.wv/ }).click()
  await expect(page.getByRole("banner")).toContainText("03 wavpack.wv")
})

test("album scan lists every track with its verdict", async ({ page }) => {
  await open(page, "01 real.flac")
  await page.getByRole("button", { name: /Scan/ }).first().click()
  const main = page.getByRole("main")
  await expect(main).toContainText("3 / 3 tracks")
  await expect(main).toContainText("MP3 128k")
  await expect(main).toContainText("lossless")
})

test("playback plays FLAC directly and WavPack through the transcode", async ({ page }) => {
  const playedSeconds = () => page.evaluate(() => document.querySelector("audio")?.currentTime ?? 0)
  await open(page, "01 real.flac")
  await page.getByRole("button", { name: "Play / pause (Space)" }).click()
  await expect.poll(playedSeconds).toBeGreaterThan(0.3)
  await page.keyboard.press(" ")
  await open(page, "03 wavpack.wv")
  await page.getByRole("button", { name: "Play / pause (Space)" }).click()
  await expect.poll(playedSeconds).toBeGreaterThan(0.3)
  expect(await page.evaluate(() => document.querySelector("audio")?.currentSrc)).toContain("format=flac")
  await expect(page.getByRole("alert")).toHaveCount(0)
})

test("PNG export downloads the current view", async ({ page }) => {
  await open(page, "01 real.flac")
  const download = page.waitForEvent("download")
  await page.keyboard.press("e")
  expect((await download).suggestedFilename()).toMatch(/^01 real\.0\.0-12\.0s\.png$/)
})

test("the SoX spectrogram renders", async ({ page, request }) => {
  await open(page, "01 real.flac")
  const href = await page.getByRole("link", { name: /Full track/ }).getAttribute("href")
  const res = await request.get(href!)
  expect(res.status()).toBe(200)
  expect(res.headers()["content-type"]).toBe("image/png")
})

test("library keyboard: arrows and Enter open a file", async ({ page }) => {
  await page.goto("/#dir=Artist%2FAlbum")
  const list = page.getByRole("listbox", { name: "Library" })
  await list.focus()
  await page.keyboard.press("ArrowDown")
  await page.keyboard.press("ArrowDown")
  await page.keyboard.press("Enter")
  await expect(page.getByRole("banner")).toContainText(/0[12] .*\.flac/)
})

test("a deep link pasted into an open tab opens that file", async ({ page }) => {
  await open(page, "01 real.flac")
  await page.evaluate(() => {
    location.hash = "#dir=Artist%2FAlbum&file=Artist%2FAlbum%2F02%20transcode.flac"
  })
  await expect(page.getByRole("banner")).toContainText("02 transcode.flac")
  await expect(page.getByRole("complementary", { name: "Analysis" })).toContainText("MP3 128k")
})

test("arrow keys pan a zoomed view; overlays draw without errors", async ({ page }) => {
  await open(page, "02 transcode.flac")
  // Zoom in around the centre, so there is room to pan either way.
  await page.keyboard.press("+")
  await expect.poll(() => viewLabel(page)).not.toContain("0:00.0 to 0:12.0")
  const zoomed = await viewLabel(page)
  await page.keyboard.press("ArrowLeft")
  await expect.poll(() => viewLabel(page)).not.toBe(zoomed)
  for (const key of ["h", "o", "r", "g"]) await page.keyboard.press(key)
  const settings = await page.evaluate(() => JSON.parse(localStorage.getItem("spectrals.settings.v1") ?? "{}"))
  expect(settings).toMatchObject({ holes: true, rolloff: true, refs: false, grid: false })
})
