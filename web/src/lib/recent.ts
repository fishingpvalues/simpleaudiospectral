const KEY = "spectrals.recent"
const MAX = 20

/** Recently opened files, newest first. */
export function loadRecent(): string[] {
  try {
    return JSON.parse(localStorage.getItem(KEY) ?? "[]")
  } catch {
    return []
  }
}

/** Moves `path` to the front of the recent list. */
export function pushRecent(path: string): void {
  try {
    const rec = JSON.parse(localStorage.getItem(KEY) ?? "[]") as string[]
    localStorage.setItem(KEY, JSON.stringify([path, ...rec.filter(x => x !== path)].slice(0, MAX)))
  } catch {
    /* storage unavailable */
  }
}
