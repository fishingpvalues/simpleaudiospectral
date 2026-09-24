export type ShortcutAction =
  | "togglePlay"
  | "zoomIn"
  | "zoomOut"
  | "fit"
  | "back"
  | "detailZoom"
  | "toggleHoles"
  | "toggleRolloff"
  | "exportPng"
  | "panLeft"
  | "panRight"
  | "toStart"
  | "toggleScale"
  | "toggleRefs"
  | "toggleGrid"
  | "chMix"
  | "chLeft"
  | "chRight"
  | "chSide"

/** Global single-key shortcuts, by KeyboardEvent.key. */
export const KEYMAP: ReadonlyMap<string, ShortcutAction> = new Map([
  [" ", "togglePlay"],
  ["+", "zoomIn"],
  ["=", "zoomIn"],
  ["-", "zoomOut"],
  ["_", "zoomOut"],
  ["0", "fit"],
  ["f", "fit"],
  ["Backspace", "back"],
  ["u", "back"],
  ["z", "detailZoom"],
  ["h", "toggleHoles"],
  ["o", "toggleRolloff"],
  ["e", "exportPng"],
  ["ArrowLeft", "panLeft"],
  ["ArrowRight", "panRight"],
  ["Home", "toStart"],
  ["l", "toggleScale"],
  ["r", "toggleRefs"],
  ["g", "toggleGrid"],
  ["1", "chMix"],
  ["2", "chLeft"],
  ["3", "chRight"],
  ["4", "chSide"],
])

/** Typing in these must not trigger shortcuts. */
export const SHORTCUT_IGNORE = "input,textarea,[role=combobox],[role=listbox]"

/** The action for a key press, or null. Browser and OS chords (Cmd/Ctrl) pass through. */
export function shortcutFor(e: { key: string; metaKey: boolean; ctrlKey: boolean }): ShortcutAction | null {
  if (e.metaKey || e.ctrlKey) return null
  return KEYMAP.get(e.key) ?? null
}

/** Rows of the "?" popover. Includes the pointer gestures of the viewer. */
export const SHORTCUT_HELP: [string, string][] = [
  ["Space", "play / pause"],
  ["drag", "box zoom (time + freq)"],
  ["shift+drag", "pan"],
  ["wheel", "zoom time"],
  ["alt+wheel", "zoom frequency"],
  ["wheel on Hz axis", "zoom frequency"],
  ["drag Hz axis", "pan frequency"],
  ["+ / -", "zoom in / out"],
  ["F / 0 / dbl-click", "fit"],
  ["< / >", "pan"],
  ["L", "lin / log"],
  ["R / G", "references / grid"],
  ["1 2 3 4", "mix / L / R / side"],
  ["click", "seek"],
  ["Z", "Detail zoom"],
  ["Backspace / U", "previous view"],
  ["H / O", "holes / rolloff overlay"],
  ["E", "export PNG"],
]
