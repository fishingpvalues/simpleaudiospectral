import { useEffect, useRef, useState } from "react"
import { AlertTriangle, CheckCircle2, Download, XCircle } from "lucide-react"
import { api, type Info, type Stats } from "@/lib/api"
import { palette } from "@/lib/colormaps"
import { fmtBytes, fmtHz, fmtTime, RED_REFS, type View } from "@/lib/scale"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Separator } from "@/components/ui/separator"
import { ScrollArea } from "@/components/ui/scroll-area"
import { cn } from "@/lib/utils"
import { Term } from "@/components/ui/tooltip"
import type { Term as TermKey } from "@/lib/glossary"
import type { Cursor } from "./Viewer"
import type { Settings } from "@/App"

const LEVEL = {
  ok: { label: "Looks lossless", icon: CheckCircle2, variant: "success" as const },
  warn: { label: "Check manually", icon: AlertTriangle, variant: "warning" as const },
  bad: { label: "Suspect transcode", icon: XCircle, variant: "destructive" as const },
}

const TABLE = [
  { khz: 22, label: "CD / lossless" },
  ...[...RED_REFS].reverse().map(r => ({ khz: r.khz, label: `MP3 ${r.label}` })),
]

type Spec = { hz: Float32Array; db: Float32Array } | null

interface Props {
  info: Info
  cursor: Cursor | null
  settings: Settings
  soxFull: string
  soxZoom: string
  view: View
  viewSpec: Spec
  onJump: (t: number) => void
}

export function Analysis({ info, cursor, settings, soxFull, soxZoom, view, viewSpec, onJump }: Props) {
  const a = info.analysis
  const lv = a ? LEVEL[a.level] : LEVEL.warn
  const khz = a?.cutoffHz ? a.cutoffHz / 1000 : null
  const match = khz === null ? 22 : TABLE.reduce((b, r) => (Math.abs(r.khz - khz) < Math.abs(b.khz - khz) ? r : b)).khz
  const padded = info.bitDepthUsed && /^16\/(24|32)/.test(info.bitDepthUsed)
  const mono = a && a.sideDb < -60

  return (
    <ScrollArea className="h-full">
      <div className="space-y-4 p-4">
        <div className="rounded-lg border bg-card p-3">
          <Badge variant={lv.variant} className="mb-2">
            <lv.icon />
            {lv.label}
          </Badge>
          <p className="text-sm leading-relaxed text-card-foreground/90">
            {a?.verdict ?? "No analysis (file too short?)."}
          </p>
          <div className="mt-2 flex flex-wrap gap-1.5">
            {a?.family && <Badge variant="outline">likely {a.family}</Badge>}
            {a?.resampledFrom && (
              <Badge variant="destructive">resampled from {(a.resampledFrom / 1000).toFixed(1)} kHz</Badge>
            )}
            {a?.hfSd != null && (
              <Badge variant={a.hfSd >= 10 ? "warning" : "outline"}>
                <Term term="hfVar">HF var {a.hfSd} dB</Term>
              </Badge>
            )}
            {a?.crtTone && (
              <Badge variant="outline">
                <Term term="crt">{(a.crtTone / 1000).toFixed(3)} kHz CRT tone</Term>
              </Badge>
            )}
            {a?.shelf16k && (
              <Badge variant="warning">
                <Term term="shelf">16 kHz shelf</Term>
              </Badge>
            )}
            {padded && <Badge variant="warning">padded {info.bitDepthUsed} bit</Badge>}
            {mono && (
              <Badge variant="warning">
                <Term term="sideLevel">mono in stereo</Term>
              </Badge>
            )}
          </div>
        </div>

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

        <Separator />

        <Dynamics path={info.path} channels={info.channels} bits={info.bits} onJump={onJump} />

        {info.channels > 1 && (
          <div>
            <h3 className="mb-2 text-xs font-medium tracking-wide text-muted-foreground uppercase">
              <Term term="goniometer">Goniometer (current view)</Term>
            </h3>
            <Goniometer path={info.path} view={view} />
          </div>
        )}

        <Separator />

        <div>
          <h3 className="mb-2 text-xs font-medium tracking-wide text-muted-foreground uppercase">
            <Term term="refs">Lowpass reference (RED guide)</Term>
          </h3>
          <div className="overflow-hidden rounded-md border text-sm">
            {TABLE.map(r => (
              <div
                key={r.khz}
                className={cn(
                  "flex justify-between px-3 py-1.5 font-mono",
                  r.khz === match ? "bg-primary text-primary-foreground" : "odd:bg-card",
                )}
              >
                <span>{r.label}</span>
                <span>{r.khz} kHz</span>
              </div>
            ))}
          </div>
        </div>

        <div>
          <h3 className="mb-2 text-xs font-medium tracking-wide text-muted-foreground uppercase">Frequency analysis</h3>
          <SpectrumChart info={info} cursor={cursor} viewSpec={viewSpec} />
          <p className="mt-1.5 text-xs text-muted-foreground">
            Light grey: loudest 10% of frames (shows the lowpass). Dark grey: median frame (shows a 16 kHz shelf). Cyan:
            mean of the visible view. White: the column under the cursor.
          </p>
        </div>

        <div>
          <h3 className="mb-2 text-xs font-medium tracking-wide text-muted-foreground uppercase">
            <Term term="range">Colour scale</Term>
          </h3>
          <ColorBar cmap={settings.cmap} />
          <div className="mt-1 flex justify-between font-mono text-[11px] text-muted-foreground">
            <span>{settings.floor} dB</span>
            <span>{settings.ceil} dB</span>
          </div>
        </div>

        <Separator />

        <div className="space-y-2">
          <h3 className="text-xs font-medium tracking-wide text-muted-foreground uppercase">
            <Term term="sox">Export SoX spectral</Term>
          </h3>
          <div className="flex gap-2">
            <Button variant="outline" size="sm" asChild>
              <a href={soxFull} target="_blank" rel="noreferrer">
                <Download />
                Full track
              </a>
            </Button>
            <Button variant="outline" size="sm" asChild>
              <a href={soxZoom} target="_blank" rel="noreferrer">
                <Download />
                Current view
              </a>
            </Button>
          </div>
          <p className="text-xs text-muted-foreground">
            1800x1025, Kaiser, 120 dB - the classic sox spectral uploaders post.
          </p>
        </div>
      </div>
    </ScrollArea>
  )
}

function Stat({ k, v, mono, warn, t }: { k: string; v: string; mono?: boolean; warn?: boolean; t?: TermKey }) {
  return (
    <div className="min-w-0">
      <dt className="text-[11px] text-muted-foreground">{t ? <Term term={t}>{k}</Term> : k}</dt>
      <dd className={cn("truncate", mono && "font-mono", warn && "text-warning")} title={v}>
        {v}
      </dd>
    </div>
  )
}

function ColorBar({ cmap }: { cmap: string }) {
  const ref = useRef<HTMLCanvasElement>(null)
  useEffect(() => {
    const c = ref.current
    if (!c) return
    c.width = 256
    c.height = 1
    const g = c.getContext("2d")!
    const img = g.createImageData(256, 1)
    img.data.set(palette(cmap))
    g.putImageData(img, 0, 0)
  }, [cmap])
  return <canvas ref={ref} className="h-3 w-full rounded-sm [image-rendering:pixelated]" aria-hidden="true" />
}

function SpectrumChart({ info, cursor, viewSpec }: { info: Info; cursor: Cursor | null; viewSpec: Spec }) {
  const ref = useRef<HTMLCanvasElement>(null)
  useEffect(() => {
    const c = ref.current
    if (!c) return
    const dpr = window.devicePixelRatio || 1
    const w = c.clientWidth,
      h = c.clientHeight
    c.width = w * dpr
    c.height = h * dpr
    const g = c.getContext("2d")!
    g.setTransform(dpr, 0, 0, dpr, 0, 0)
    g.fillStyle = "#000"
    g.fillRect(0, 0, w, h)
    const L = 34,
      B = 16,
      nyq = info.sampleRate / 2
    const lo = -140,
      hi = 0
    const X = (f: number) => L + ((w - L - 4) * f) / nyq
    const Y = (db: number) => ((h - B) * (hi - Math.max(lo, Math.min(hi, db)))) / (hi - lo)
    g.font = "10px 'Geist Mono Variable', monospace"
    g.lineWidth = 1
    for (let db = hi; db >= lo; db -= 20) {
      g.strokeStyle = "rgba(255,255,255,0.08)"
      g.beginPath()
      g.moveTo(L, Y(db))
      g.lineTo(w, Y(db))
      g.stroke()
      g.fillStyle = "#737373"
      g.fillText(String(db), 2, Y(db) + 3)
    }
    const step = nyq > 30000 ? 10000 : 5000
    for (let f = 0; f <= nyq; f += step) {
      g.fillStyle = "#737373"
      g.fillText(fmtHz(f), X(f) - 6, h - 3)
    }
    g.setLineDash([2, 3])
    for (const r of RED_REFS) {
      if (r.khz * 1000 > nyq) continue
      g.strokeStyle = "rgba(255,255,255,0.18)"
      g.beginPath()
      g.moveTo(X(r.khz * 1000), 0)
      g.lineTo(X(r.khz * 1000), h - B)
      g.stroke()
    }
    g.setLineDash([])
    const a = info.analysis
    if (a) {
      g.strokeStyle = "#525252"
      g.lineWidth = 1
      g.beginPath()
      a.curve.hz.forEach((f, i) => {
        const x = X(f),
          y = Y(a.curve.median[i])
        if (i) g.lineTo(x, y)
        else g.moveTo(x, y)
      })
      g.stroke()
      g.strokeStyle = "#a3a3a3"
      g.lineWidth = 1.25
      g.beginPath()
      a.curve.hz.forEach((f, i) => {
        const x = X(f),
          y = Y(a.curve.db[i])
        if (i) g.lineTo(x, y)
        else g.moveTo(x, y)
      })
      g.stroke()
      if (a.cutoffHz) {
        g.strokeStyle = "#fff"
        g.setLineDash([5, 3])
        g.beginPath()
        g.moveTo(X(a.cutoffHz), 0)
        g.lineTo(X(a.cutoffHz), h - B)
        g.stroke()
        g.setLineDash([])
      }
    }
    if (viewSpec) {
      g.strokeStyle = "#22d3ee"
      g.lineWidth = 1
      g.beginPath()
      for (let i = 0; i < viewSpec.hz.length; i++) {
        const x = X(viewSpec.hz[i]),
          y = Y(viewSpec.db[i])
        if (i) g.lineTo(x, y)
        else g.moveTo(x, y)
      }
      g.stroke()
    }
    const s = cursor?.slice
    if (s) {
      g.strokeStyle = "#fff"
      g.lineWidth = 1
      g.beginPath()
      for (let i = 0; i < s.hz.length; i++) {
        const x = X(s.hz[i]),
          y = Y(s.db[i])
        if (i) g.lineTo(x, y)
        else g.moveTo(x, y)
      }
      g.stroke()
    }
    if (cursor && Number.isFinite(cursor.f)) {
      g.strokeStyle = "rgba(255,255,255,0.4)"
      g.beginPath()
      g.moveTo(X(cursor.f), 0)
      g.lineTo(X(cursor.f), h - B)
      g.stroke()
    }
  }, [info, cursor, viewSpec])
  const a = info.analysis
  return (
    <canvas
      ref={ref}
      className="h-44 w-full rounded-md border"
      role="img"
      aria-label={`Average spectrum. ${a?.cutoffHz ? `Level falls by ${a.dropDb} dB at ${(a.cutoffHz / 1000).toFixed(1)} kilohertz.` : `Content reaches ${((a?.extentHz ?? 0) / 1000).toFixed(1)} kilohertz without a brick wall.`}`}
    />
  )
}

const f1 = (v: number | null | undefined, unit = "") => (v == null ? "-" : `${v.toFixed(1)}${unit}`)

function Dynamics({
  path,
  channels,
  bits,
  onJump,
}: {
  path: string
  channels: number
  bits: number | null
  onJump: (t: number) => void
}) {
  const [st, setSt] = useState<Stats | null>(null)
  const [err, setErr] = useState<string | null>(null)
  useEffect(() => {
    const ctl = new AbortController()
    setSt(null)
    setErr(null)
    api
      .stats(path, ctl.signal)
      .then(setSt)
      .catch(e => {
        if (e.name !== "AbortError") setErr(String(e.message ?? e))
      })
    return () => ctl.abort()
  }, [path])
  const L = st?.loudness,
    D = st?.dynamics
  const drTone = D ? (D.dr >= 14 ? "text-success" : D.dr <= 7 ? "text-destructive" : "text-warning") : ""
  return (
    <div>
      <h3 className="mb-2 text-xs font-medium tracking-wide text-muted-foreground uppercase">Loudness and dynamics</h3>
      {err && <p className="text-sm text-destructive">{err}</p>}
      {!st && !err && <p className="text-sm text-muted-foreground">Measuring (EBU R128, DR, true peak)...</p>}
      {st && (
        <>
          <div className="mb-3 grid grid-cols-3 gap-2">
            <Big label="DR" value={D ? `DR${D.dr}` : "-"} className={drTone} t="dr" />
            <Big label="Integrated" value={L?.lufs == null ? "-" : `${L.lufs.toFixed(1)}`} unit="LUFS" t="lufs" />
            <Big label="Range" value={L?.lra == null ? "-" : L.lra.toFixed(1)} unit="LU" t="lra" />
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
            <Stat
              t="quietFloor"
              k="Quiet floor"
              v={f1(st.quietFloorDb, " dBFS")}
              mono
              warn={bits != null && bits > 16 && (st.quietFloorDb ?? -200) > -100}
            />
            {D && D.flatTopEvents > 0 && <Stat t="flatTop" k="Flat tops" v={`${D.flatTopEvents} runs`} mono warn />}
            <Stat t="rumble" k="Rumble 5-20 Hz" v={f1(D?.rumbleDb, " dB")} mono />
            <Stat t="clicks" k="Isolated clicks" v={D ? `${D.clicksPerMin}/min` : "-"} mono />
          </dl>
          {D && (D.rumbleDb ?? -99) > -20 && D.clicksPerMin >= 10 && (
            <Badge variant="outline" className="mt-2">
              rumble + clicks: vinyl or other analogue source
            </Badge>
          )}
          {bits != null && bits > 16 && (st.quietFloorDb ?? -200) > -100 && (
            <p className="mt-2 text-xs text-warning">
              Quiet passages bottom out above -100 dBFS: a real {bits}-bit master usually goes lower. Could be a 16-bit
              source in a {bits}-bit file.
            </p>
          )}
          <ChannelCutoffs c={st.channelCutoffs} />
          {st.bitUsage && <BitChart u={st.bitUsage} />}
          {D && D.clipTimes.length > 0 && (
            <div className="mt-3">
              <div className="mb-1 text-[11px] text-muted-foreground">
                <Term term="clipping">Clipped and flat-top runs</Term>, select one to jump there
              </div>
              <div className="flex max-h-24 flex-wrap gap-1 overflow-auto">
                {D.clipTimes.slice(0, 120).map(t => (
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
          )}
          {D?.identicalChannels && channels > 1 && (
            <Badge variant="warning" className="mt-2">
              L and R are bit-identical (mono)
            </Badge>
          )}
          {D?.correlationSeries && D.correlationSeries.length > 1 && <Correlation series={D.correlationSeries} />}
        </>
      )}
    </div>
  )
}

function Big({
  label,
  value,
  unit,
  className,
  t,
}: {
  label: string
  value: string
  unit?: string
  className?: string
  t: TermKey
}) {
  return (
    <div className="rounded-md border bg-card px-2.5 py-2">
      <div className="text-[11px] text-muted-foreground">
        <Term term={t}>{label}</Term>
      </div>
      <div className={cn("font-mono text-lg leading-tight font-semibold", className)}>
        {value}
        {unit && <span className="ml-1 text-xs font-normal text-muted-foreground">{unit}</span>}
      </div>
    </div>
  )
}

function Correlation({ series }: { series: number[] }) {
  const ref = useRef<HTMLCanvasElement>(null)
  useEffect(() => {
    const c = ref.current
    if (!c) return
    const dpr = window.devicePixelRatio || 1,
      w = c.clientWidth,
      h = c.clientHeight
    c.width = w * dpr
    c.height = h * dpr
    const g = c.getContext("2d")!
    g.setTransform(dpr, 0, 0, dpr, 0, 0)
    g.fillStyle = "#000"
    g.fillRect(0, 0, w, h)
    const Y = (v: number) => (h / 2) * (1 - v)
    g.strokeStyle = "rgba(255,255,255,0.12)"
    g.beginPath()
    g.moveTo(0, Y(0))
    g.lineTo(w, Y(0))
    g.stroke()
    series.forEach((v, i) => {
      const x = (i / series.length) * w
      g.fillStyle = v < 0 ? "#ef4444" : "#a3a3a3"
      g.fillRect(x, Math.min(Y(v), Y(0)), Math.max(1, w / series.length), Math.abs(Y(v) - Y(0)))
    })
    g.fillStyle = "#737373"
    g.font = "10px 'Geist Mono Variable', monospace"
    g.fillText("+1", 2, 10)
    g.fillText("-1", 2, h - 3)
  }, [series])
  return (
    <div className="mt-3">
      <div className="mb-1 text-[11px] text-muted-foreground">
        <Term term="corrSeries">Stereo correlation per second</Term> (red = out of phase)
      </div>
      <canvas
        ref={ref}
        className="h-14 w-full rounded-md border"
        role="img"
        aria-label={`Stereo correlation over time, ${series.filter(v => v < 0).length} of ${series.length} seconds out of phase`}
      />
    </div>
  )
}

function ChannelCutoffs({ c }: { c: Stats["channelCutoffs"] }) {
  const k = (v: number | null) => (v ? `${(v / 1000).toFixed(2)} kHz` : "none")
  const lr = c.left && c.right ? Math.abs(c.left - c.right) : 0
  const sideLow = c.side && (!c.left || c.side < c.left - 700)
  return (
    <div className="mt-3">
      <div className="mb-1 text-[11px] text-muted-foreground">
        <Term term="channelCutoffs">Cut-off per channel</Term>
      </div>
      <div className="grid grid-cols-3 gap-2 font-mono text-xs">
        <div className="rounded border px-2 py-1">L {k(c.left)}</div>
        <div className="rounded border px-2 py-1">R {k(c.right)}</div>
        <div className={cn("rounded border px-2 py-1", sideLow && "border-warning text-warning")}>S {k(c.side)}</div>
      </div>
      {sideLow && (
        <p className="mt-1 text-xs text-warning">
          Side channel is cut lower than L/R: typical of joint-stereo lossy coding.
        </p>
      )}
      {lr > 700 && (
        <p className="mt-1 text-xs text-warning">
          L and R cut-offs differ by {(lr / 1000).toFixed(1)} kHz: channels from different sources?
        </p>
      )}
    </div>
  )
}

function BitChart({ u }: { u: NonNullable<Stats["bitUsage"]> }) {
  // MSB on the left, like reading a sample word.
  const bars = [...u.ones].reverse()
  return (
    <div className="mt-3">
      <div className="mb-1 flex justify-between text-[11px] text-muted-foreground">
        <Term term="bitUsage">Bit usage (MSB .. LSB)</Term>
        <span>{u.unusedLowBits ? `${u.unusedLowBits} low bits always 0` : "all bits used"}</span>
      </div>
      <div
        className="flex h-12 items-end gap-px rounded-md border bg-black p-1"
        role="img"
        aria-label={`Bit usage: ${u.unusedLowBits ? `${u.unusedLowBits} lowest bits never set` : `all ${u.bits} bits carry data`}`}
      >
        {bars.map((v, i) => {
          const bit = u.bits - 1 - i
          const dead = bit < u.unusedLowBits
          return (
            <div
              key={i}
              className="flex h-full flex-1 flex-col justify-end"
              title={`bit ${bit}: ${(v * 100).toFixed(1)}% ones`}
            >
              <div
                className={cn("w-full rounded-[1px]", dead ? "bg-destructive" : "bg-neutral-300")}
                style={{ height: `${Math.max(2, v * 200)}%`, maxHeight: "100%" }}
              />
            </div>
          )
        })}
      </div>
      {u.unusedLowBits >= 8 && u.bits >= 24 && (
        <p className="mt-1 text-xs text-warning">
          Padded: a {u.bits - u.unusedLowBits}-bit master in a {u.bits}-bit file.
        </p>
      )}
    </div>
  )
}

function Goniometer({ path, view }: { path: string; view: View }) {
  const ref = useRef<HTMLCanvasElement>(null)
  const [corr, setCorr] = useState<number | null>(null)
  useEffect(() => {
    const ctl = new AbortController()
    const t = setTimeout(() => {
      api
        .gonio({ path, t0: view.t0.toFixed(3), t1: view.t1.toFixed(3), size: 160 }, ctl.signal)
        .then(r => {
          const c = ref.current
          if (!c) return
          c.width = r.size
          c.height = r.size
          const g = c.getContext("2d")!
          const img = g.createImageData(r.size, r.size)
          for (let i = 0; i < r.data.length; i++) {
            const v = r.data[i]
            img.data[i * 4] = v
            img.data[i * 4 + 1] = v
            img.data[i * 4 + 2] = v
            img.data[i * 4 + 3] = 255
          }
          g.putImageData(img, 0, 0)
          g.strokeStyle = "rgba(255,255,255,0.15)"
          g.beginPath()
          g.moveTo(r.size / 2, 0)
          g.lineTo(r.size / 2, r.size)
          g.moveTo(0, r.size / 2)
          g.lineTo(r.size, r.size / 2)
          g.stroke()
          setCorr(r.correlation)
        })
        .catch(() => {})
    }, 250)
    return () => {
      clearTimeout(t)
      ctl.abort()
    }
  }, [path, view.t0, view.t1])
  return (
    <div className="flex items-center gap-3">
      <canvas
        ref={ref}
        className="size-40 rounded-md border bg-black [image-rendering:pixelated]"
        role="img"
        aria-label={`Goniometer for the current view, correlation ${corr == null ? "unknown" : corr.toFixed(2)}`}
      />
      <div className="space-y-1 text-xs text-muted-foreground">
        <div>Vertical: mid (L+R)</div>
        <div>Horizontal: side (L-R)</div>
        <div className="pt-1 font-mono text-sm text-foreground">r = {corr == null ? "-" : corr.toFixed(3)}</div>
        <div>A vertical line = mono; a horizontal one = out of phase.</div>
      </div>
    </div>
  )
}
