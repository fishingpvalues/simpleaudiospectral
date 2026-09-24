import type { Channel, Scale } from "./api"
import { DEFAULT_REF_SETS, type RefSetId } from "./references"

export interface Settings {
  ch: Channel
  scale: Scale
  fft: number
  win: string
  cmap: string
  floor: number
  ceil: number
  refs: boolean
  refSets: RefSetId[]
  cutoff: boolean
  grid: boolean
  follow: boolean
  holes: boolean
  rolloff: boolean
}

/** Setter for one settings key, as handed to the toolbar and popovers. */
export type SetSetting = <K extends keyof Settings>(k: K, v: Settings[K]) => void

/** The settings that are plain on/off switches. */
export type BooleanSetting = "refs" | "cutoff" | "grid" | "follow" | "holes" | "rolloff"

export const DEFAULTS: Settings = {
  ch: "mix",
  scale: "linear",
  fft: 4096,
  win: "blackman-harris",
  cmap: "audition",
  floor: -120,
  ceil: 0,
  refs: true,
  refSets: DEFAULT_REF_SETS,
  cutoff: true,
  grid: true,
  follow: true,
  holes: false,
  rolloff: false,
}

export const FFTS = [512, 1024, 2048, 4096, 8192, 16384, 32768]
export const WINDOWS = ["blackman-harris", "kaiser", "hann", "hamming", "blackman"]
export const STORE = "spectrals.settings.v1"

type Store = Pick<Storage, "getItem" | "setItem">

/** Stored settings over the defaults, so keys added later get their default.
 * Falls back to the defaults on bad JSON or when storage is unavailable. */
export function loadSettings(storage?: Store): Settings {
  try {
    const s = storage ?? localStorage
    return { ...DEFAULTS, ...JSON.parse(s.getItem(STORE) ?? "{}") }
  } catch {
    return DEFAULTS
  }
}

export function saveSettings(settings: Settings, storage?: Store): void {
  try {
    ;(storage ?? localStorage).setItem(STORE, JSON.stringify(settings))
  } catch {
    /* private mode */
  }
}
