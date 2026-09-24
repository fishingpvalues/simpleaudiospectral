import type { Info } from "@/lib/api"
import { fmtBytes, fmtTime } from "@/lib/scale"
import { Stat } from "./Stat"

/** Format facts and the headline lowpass numbers. */
export function FileStats({ info }: { info: Info }) {
  const a = info.analysis
  const khz = a?.cutoffHz ? a.cutoffHz / 1000 : null
  return (
    <dl className="grid grid-cols-2 gap-x-3 gap-y-2 text-sm">
      <Stat t="codec" k="Codec" v={info.codecName?.toUpperCase() ?? "-"} />
      <Stat t="sampleRate" k="Sample rate" v={`${(info.sampleRate / 1000).toFixed(1)} kHz`} />
      <Stat
        t="bitDepth"
        k="Bit depth"
        v={info.bits ? `${info.bits} bit${info.bitDepthUsed ? ` (${info.bitDepthUsed})` : ""}` : "-"}
      />
      <Stat t="channels" k="Channels" v={String(info.channels)} />
      <Stat t="duration" k="Duration" v={fmtTime(info.duration, 0.01)} />
      <Stat t="bitrate" k="Bitrate" v={info.bitrate ? `${Math.round(info.bitrate / 1000)} kbps` : "-"} />
      <Stat t="size" k="Size" v={info.size ? fmtBytes(info.size) : "-"} />
      <Stat t="sideLevel" k="Side level" v={a ? `${a.sideDb.toFixed(1)} dB` : "-"} />
      <Stat t="cutoff" k="Cut-off" v={khz ? `${khz.toFixed(2)} kHz` : "none"} mono />
      <Stat t="drop" k="Drop" v={a ? `${a.dropDb} dB` : "-"} mono />
      <Stat t="extent" k="Content up to" v={a ? `${(a.extentHz / 1000).toFixed(1)} kHz` : "-"} mono />
      <Stat t="encoder" k="Encoder" v={info.encoder ?? "-"} />
      {a?.hiresDb != null && <Stat t="hires" k="Above 22 kHz" v={`${a.hiresDb} dB`} mono />}
    </dl>
  )
}
