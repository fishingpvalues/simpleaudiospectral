/** Last path segment: the file or folder name. */
export const baseName = (p: string): string | undefined => p.split("/").pop()

/** Everything before the last segment ("" at the top level). */
export const parentDir = (p: string): string => p.split("/").slice(0, -1).join("/")

/** Upper-case file extension, for the library's format column. */
export const extOf = (n: string): string => n.slice(n.lastIndexOf(".") + 1).toUpperCase()

/** "Track.flac" viewed from 12.3 s to 20.3 s -> "Track.12.3-20.3s.png". */
export function exportFileName(path: string, view: { t0: number; t1: number }): string {
  return `${baseName(path)?.replace(/\.[^.]+$/, "")}.${view.t0.toFixed(1)}-${view.t1.toFixed(1)}s.png`
}
