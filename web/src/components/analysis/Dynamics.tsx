import type { Stats } from "@/lib/api"
import { fmtTime } from "@/lib/scale"
import { Badge } from "@/components/ui/badge"
import { Term } from "@/components/ui/tooltip"
import { BitChart } from "./BitChart"
import { ChannelCutoffs } from "./ChannelCutoffs"
import { CorrelationSeries } from "./CorrelationSeries"
import { PanelHeading } from "./PanelHeading"
import { Stat, StatTile } from "./Stat"
import { useStats } from "./useStats"

/** At most this many clip buttons; a badly clipped master has thousands. */
const MAX_CLIP_BUTTONS = 120

const f1 = (v: number | null | undefined, unit = "") => (v == null ? "-" : `${v.toFixed(1)}${unit}`)

/** A hi-res file whose quiet passages stay above -100 dBFS is likely a 16-bit source. */
const shallowFloor = (bits: number | null, st: Stats) => bits != null && bits > 16 && (st.quietFloorDb ?? -200) > -100

interface DynamicsProps {
  path: string
  channels: number
  bits: number | null
  onJump: (t: number) => void
}

export function Dynamics({ path, channels, bits, onJump }: DynamicsProps) {
  const { stats: st, error: err } = useStats(path)
  const L = st?.loudness,
    D = st?.dynamics
  const drTone = D ? (D.dr >= 14 ? "text-success" : D.dr <= 7 ? "text-destructive" : "text-warning") : ""
  return (
    <div>
      <PanelHeading>Loudness and dynamics</PanelHeading>
      {err && <p className="text-sm text-destructive">{err}</p>}
      {!st && !err && <p className="text-sm text-muted-foreground">Measuring (EBU R128, DR, true peak)...</p>}
      {st && (
        <>
          <div className="mb-3 grid grid-cols-3 gap-2">
            <StatTile label="DR" value={D ? `DR${D.dr}` : "-"} className={drTone} t="dr" />
            <StatTile label="Integrated" value={L?.lufs == null ? "-" : `${L.lufs.toFixed(1)}`} unit="LUFS" t="lufs" />
            <StatTile label="Range" value={L?.lra == null ? "-" : L.lra.toFixed(1)} unit="LU" t="lra" />
          </div>
          <dl className="grid grid-cols-2 gap-x-3 gap-y-2 text-sm">
            <Stat t="truePeak" k="True peak" v={f1(L?.truePeakDb, " dBTP")} mono warn={(L?.truePeakDb ?? -99) > 0} />
            <Stat t="samplePeak" k="Sample peak" v={f1(L?.samplePeakDb, " dBFS")} mono />
            <Stat t="rms" k="RMS" v={f1(L?.rmsDb, " dBFS")} mono />
            <Stat t="noiseFloor" k="Noise floor" v={f1(L?.noiseFloorDb, " dB")} mono />
            <Stat t="clipping" k="Clipping" v={D ? `${D.clipEvents} runs` : "-"} mono warn={(D?.clipEvents ?? 0) > 0} />
            <Stat
              t="dcOffset"
              k="DC offset"
              v={L?.dcOffset == null ? "-" : L.dcOffset.toExponential(1)}
              mono
              warn={Math.abs(L?.dcOffset ?? 0) > 0.001}
            />
            {channels > 1 && (
              <Stat
                t="correlation"
                k="L/R correlation"
                v={D?.correlation == null ? "-" : D.correlation.toFixed(3)}
                mono
                warn={(D?.correlation ?? 1) < 0}
              />
            )}
            <Stat t="effectiveBits" k="Effective bits" v={L?.effectiveBits ?? "-"} mono />
            {D && D.drPerChannel.length > 1 && (
              <Stat t="drPerChannel" k="DR L / R" v={D.drPerChannel.join(" / ")} mono />
            )}
            <Stat t="quietFloor" k="Quiet floor" v={f1(st.quietFloorDb, " dBFS")} mono warn={shallowFloor(bits, st)} />
            {D && D.flatTopEvents > 0 && <Stat t="flatTop" k="Flat tops" v={`${D.flatTopEvents} runs`} mono warn />}
            <Stat t="rumble" k="Rumble 5-20 Hz" v={f1(D?.rumbleDb, " dB")} mono />
            <Stat t="clicks" k="Isolated clicks" v={D ? `${D.clicksPerMin}/min` : "-"} mono />
          </dl>
          {D && (D.rumbleDb ?? -99) > -20 && D.clicksPerMin >= 10 && (
            <Badge variant="outline" className="mt-2">
              rumble + clicks: vinyl or other analogue source
            </Badge>
          )}
          {shallowFloor(bits, st) && (
            <p className="mt-2 text-xs text-warning">
              Quiet passages bottom out above -100 dBFS: a real {bits}-bit master usually goes lower. Could be a 16-bit
              source in a {bits}-bit file.
            </p>
          )}
          <ChannelCutoffs c={st.channelCutoffs} />
          {st.bitUsage && <BitChart u={st.bitUsage} />}
          {D && D.clipTimes.length > 0 && <ClipTimes times={D.clipTimes} onJump={onJump} />}
          {D?.identicalChannels && channels > 1 && (
            <Badge variant="warning" className="mt-2">
              L and R are bit-identical (mono)
            </Badge>
          )}
          {D?.correlationSeries && D.correlationSeries.length > 1 && <CorrelationSeries series={D.correlationSeries} />}
        </>
      )}
    </div>
  )
}

function ClipTimes({ times, onJump }: { times: number[]; onJump: (t: number) => void }) {
  return (
    <div className="mt-3">
      <div className="mb-1 text-[11px] text-muted-foreground">
        <Term term="clipping">Clipped and flat-top runs</Term>, select one to jump there
      </div>
      <div className="flex max-h-24 flex-wrap gap-1 overflow-auto">
        {times.slice(0, MAX_CLIP_BUTTONS).map(t => (
          <button
            key={t}
            onClick={() => onJump(t)}
            className="rounded border px-1.5 py-0.5 font-mono text-[11px] hover:bg-accent"
          >
            {fmtTime(t, 0.01)}
          </button>
        ))}
      </div>
    </div>
  )
}
