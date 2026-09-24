/**
 * Encoder lowpass references: where each encoder setting stops coding, taken
 * from the encoder's own source code and checked by encoding white noise at
 * 44.1 kHz and measuring the edge with this tool. A lowpass is a fixed
 * property of an encoder setting, so these are facts about the encoders, not
 * judgements about quality. See the README ("Reference lines") for sources.
 */
export type RefSetId = "lame" | "aac" | "vorbis" | "opus" | "guide"

export interface RefLine {
  /** Drawn line: the top of the encoder's transition band, where content ends. */
  khz: number
  /** This tool's measured cut-off for that setting (white noise, 44.1 kHz).
   * It sits in the middle of the drop, which for LAME is below the line, so a
   * detected cut-off is matched against this rather than the line. */
  at?: number
  label: string
}

export interface RefSet {
  id: RefSetId
  name: string
  source: string
  lines: RefLine[]
}

export const REF_SETS: RefSet[] = [
  {
    id: "lame",
    name: "MP3 (LAME)",
    // lame.c optimum_bandwidth() and the VBR table, identical from 3.99.5 to 4.0.
    // Values are the top of the polyphase transition band that `lame --verbose`
    // reports at 44.1 kHz. -V 0 has no lowpass since 3.99.
    source: "LAME 3.99.5-4.0 lame.c; transition band from lame --verbose",
    lines: [
      { khz: 17.1, at: 16.78, label: "LAME 128k / V5" },
      { khz: 17.8, at: 17.47, label: "LAME 160k / V4" },
      { khz: 18.5, at: 18.16, label: "LAME V3" },
      { khz: 19.2, at: 18.85, label: "LAME 192k / V2" },
      { khz: 19.9, at: 19.53, label: "LAME 224-256k / V1" },
      { khz: 20.6, at: 20.26, label: "LAME 320k" },
    ],
  },
  {
    id: "aac",
    name: "AAC",
    // FFmpeg: AAC_CUTOFF_FROM_BITRATE in libavcodec/psymodel.h (bandwidth from
    // bitrate per channel). Apple's encoder is closed; its values are measured.
    // From 256k both code up to ~21.6 kHz, which is no visible lowpass.
    source: "FFmpeg psymodel.h and aacenc.c; Apple AudioToolbox measured",
    lines: [
      { khz: 17.3, at: 17.3, label: "FFmpeg AAC 128k" },
      { khz: 19.4, at: 19.36, label: "FFmpeg AAC 192k" },
      { khz: 18.6, at: 18.6, label: "Apple AAC 128k" },
      { khz: 19.7, at: 19.74, label: "Apple AAC 192k" },
    ],
  },
  {
    id: "vorbis",
    name: "Vorbis (libvorbis)",
    // lib/modes/psych_44.h, _psy_lowpass_44[] by quality; q6 and up has none.
    source: "libvorbis psych_44.h _psy_lowpass_44",
    lines: [
      { khz: 15.1, at: 15.23, label: "Vorbis q0" },
      { khz: 16.5, at: 16.61, label: "Vorbis q2" },
      { khz: 17.2, at: 17.3, label: "Vorbis q3" },
      { khz: 18.9, at: 19.02, label: "Vorbis q4" },
      { khz: 20.1, at: 20.4, label: "Vorbis q5" },
    ],
  },
  {
    id: "opus",
    name: "Opus",
    // RFC 6716 section 2: fullband = 20 kHz audio bandwidth; libopus uses
    // fullband for music from about 12 kb/s up, so every music bitrate ends here.
    source: "RFC 6716 section 2; libopus bandwidth thresholds",
    lines: [{ khz: 20, at: 20.28, label: "Opus (fullband)" }],
  },
  {
    id: "guide",
    name: "Rule-of-thumb values",
    // Round figures often quoted in spectral-check guides. They are not from
    // encoder sources and differ from them by up to 1 kHz; off by default.
    source: "Commonly quoted round figures, not encoder data",
    lines: [
      { khz: 16, label: "rule of thumb 128k" },
      { khz: 18.5, label: "rule of thumb V2" },
      { khz: 19, label: "rule of thumb 192k" },
      { khz: 19.5, label: "rule of thumb V0" },
      { khz: 20, label: "rule of thumb 256k" },
      { khz: 20.5, label: "rule of thumb 320k" },
    ],
  },
]

export const DEFAULT_REF_SETS: RefSetId[] = ["lame", "aac", "opus"]

/** The lines of the chosen sets, lowest first. */
export function activeRefs(ids: RefSetId[]): RefLine[] {
  return REF_SETS.filter(s => ids.includes(s.id))
    .flatMap(s => s.lines)
    .sort((a, b) => a.khz - b.khz)
}

/** Row the analysis panel adds under the encoder lines. */
export const LOSSLESS_ROW: RefLine = { khz: 22, label: "No lowpass (lossless)" }

/** The analysis panel's reference table, highest first, and the row that
 * matches the detected cut-off (in kHz; null = no lowpass found). */
export function lowpassTable(refs: RefLine[], cutoffKhz: number | null): { rows: RefLine[]; match: RefLine } {
  const rows = [...refs].reverse().concat(LOSSLESS_ROW)
  // Nearest by the measured cut-off of each setting, which is what the analyser reports.
  const near = (r: RefLine) => Math.abs((r.at ?? r.khz) - (cutoffKhz ?? 22))
  const match = cutoffKhz === null ? rows[rows.length - 1] : rows.reduce((b, r) => (near(r) < near(b) ? r : b))
  return { rows, match }
}
