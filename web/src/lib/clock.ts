/** 75 -> "1:15", 3725 -> "1:02:05". */
export function clock(seconds: number): string {
  const s = Math.max(0, Math.round(seconds))
  const h = Math.floor(s / 3600),
    m = Math.floor((s % 3600) / 60),
    r = s % 60
  const mm = h ? String(m).padStart(2, "0") : String(m)
  return `${h ? `${h}:` : ""}${mm}:${String(r).padStart(2, "0")}`
}
