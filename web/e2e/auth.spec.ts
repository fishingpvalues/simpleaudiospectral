import { expect, test } from "@playwright/test"
import { API_KEY } from "../playwright.config"

test("the API refuses requests without the key", async ({ request }) => {
  expect((await request.get("/api/ls?path=")).status()).toBe(401)
  expect((await request.get("/api/ls?path=", { headers: { "X-API-Key": API_KEY } })).status()).toBe(200)
  const health = await (await request.get("/api/health")).json()
  expect(health).toEqual({ status: "ok", auth: true, authenticated: false })
})

test("sign in, use the app, sign out", async ({ page }) => {
  const errors: string[] = []
  page.on("pageerror", e => errors.push(String(e)))
  await page.goto("/")
  const key = page.getByLabel("This server needs its API key.")
  await key.fill("wrong")
  await page.getByRole("button", { name: "Sign in" }).click()
  await expect(page.getByRole("alert")).toHaveText("Wrong API key.")

  await key.fill(API_KEY)
  await page.getByRole("button", { name: "Sign in" }).click()
  await expect(page.getByRole("listbox", { name: "Library" })).toBeVisible()
  await page.goto("/#dir=Artist%2FAlbum&file=Artist%2FAlbum%2F01%20real.flac")
  await expect(page.getByRole("complementary", { name: "Analysis" })).toContainText("No lowpass.")

  await page.getByRole("button", { name: "Sign out" }).click()
  await expect(page.getByRole("button", { name: "Sign in" })).toBeVisible()
  await page.reload()
  await expect(page.getByRole("button", { name: "Sign in" })).toBeVisible()
  expect(errors).toEqual([])
})
