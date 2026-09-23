import { useCallback, useEffect, useLayoutEffect, useRef, useState } from "react"
import {
  AudioWaveform,
  Crosshair,
  Grid3x3,
  ImageDown,
  Loader2,
  Maximize2,
  PanelLeft,
  PanelRight,
  Pause,
  Play,
  Ruler,
  Settings2,
  SkipBack,
  Undo2,
  ZoomIn,
  ZoomOut,
} from "lucide-react"
import { api, type Channel, type Info, type Progress, type Scale } from "@/lib/api"
import { COLORMAP_GROUPS } from "@/lib/colormaps"
import { fmtHz, fmtTime, type View } from "@/lib/scale"
import { Analysis } from "@/components/Analysis"
import { AlbumScan } from "@/components/AlbumScan"
import { ErrorBoundary } from "@/components/ErrorBoundary"
import { Library } from "@/components/Library"
import { Viewer, type Cursor } from "@/components/Viewer"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Kbd } from "@/components/ui/kbd"
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover"
import {
  Select,
  SelectContent,
  SelectGroup,
  SelectItem,
  SelectLabel,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select"
import { Separator } from "@/components/ui/separator"
import { Slider } from "@/components/ui/slider"
import { Switch } from "@/components/ui/switch"
import { ToggleGroup, ToggleGroupItem } from "@/components/ui/toggle-group"
import { Term, Tip, TooltipProvider } from "@/components/ui/tooltip"
import { GLOSSARY } from "@/lib/glossary"
import { cn } from "@/lib/utils"

export interface Settings {
  ch: Channel
  scale: Scale
  fft: number
  win: string
  cmap: string
  floor: number
  ceil: number
  refs: boolean
  cutoff: boolean
  grid: boolean
  follow: boolean
  holes: boolean
  rolloff: boolean
}

const DEFAULTS: Settings = {
  ch: "mix",
  scale: "linear",
  fft: 4096,
  win: "blackman-harris",
  cmap: "audition",
  floor: -120,
  ceil: 0,
  refs: true,
  cutoff: true,
  grid: true,
  follow: true,
  holes: false,
  rolloff: false,
}
const FFTS = [512, 1024, 2048, 4096, 8192, 16384, 32768]
const WINDOWS = ["blackman-harris", "kaiser", "hann", "hamming", "blackman"]
const STORE = "spectrals.settings.v1"

function loadSettings(): Settings {
  try {
    return { ...DEFAULTS, ...JSON.parse(localStorage.getItem(STORE) ?? "{}") }
  } catch {
    return DEFAULTS
  }
}

function readHash() {
  const p = new URLSearchParams(location.hash.slice(1))
  return { dir: p.get("dir") ?? "", file: p.get("file") }
}

export function App() {
  const [init] = useState(readHash)
  const [dir, setDir] = useState(init.dir)
  const [path, setPath] = useState<string | null>(init.file)
  const [info, setInfo] = useState<Info | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [analysing, setAnalysing] = useState(false)
  const [progress, setProgress] = useState<Progress | null>(null)
  const [loading, setLoading] = useState(false)
  const [settings, setSettings] = useState<Settings>(loadSettings)
  const [view, setViewRaw] = useState<View>({ t0: 0, t1: 1, f0: 0, f1: 22050 })
  const [scanDir, setScanDir] = useState<string | null>(null)
  const [viewSpec, setViewSpec] = useState<{ hz: Float32Array; db: Float32Array } | null>(null)
  const [transcode, setTranscode] = useState(false)
  const exporter = useRef<(() => string | null) | null>(null)
  // Zoom history: a burst of wheel events is one step, so only push when the
  // previous change is more than 400 ms old.
  const viewHistory = useRef<View[]>([])
  const lastPush = useRef(0)
  const viewRef = useRef(view)
  useLayoutEffect(() => {
    viewRef.current = view
  }, [view])
  const setView = useCallback((v: View | ((v: View) => View)) => {
    const now = performance.now()
    if (now - lastPush.current > 400) {
      viewHistory.current.push(viewRef.current)
      if (viewHistory.current.length > 100) viewHistory.current.shift()
    }
    lastPush.current = now
    setViewRaw(v)
  }, [])
  const back = useCallback(() => {
    const v = viewHistory.current.pop()
    if (v) {
      lastPush.current = 0
      setViewRaw(v)
    }
  }, [])
  const [cursor, setCursor] = useState<Cursor | null>(null)
  const [left, setLeft] = useState(true)
  const [right, setRight] = useState(true)
  const audioRef = useRef<HTMLAudioElement>(null)
  // The Viewer needs the element as a prop; a ref's .current cannot be read during render.
  const [audioEl, setAudioEl] = useState<HTMLAudioElement | null>(null)
  const [playing, setPlaying] = useState(false)

  // Screen readers: announce the verdict when a file is analysed and the view
  // after zoom/pan settles, instead of every intermediate frame.
  const [announce, setAnnounce] = useState("")
  const [version, setVersion] = useState<string | null>(null)
  useEffect(() => {
    fetch("/api/health")
      .then(r => r.json())
      .then(h => setVersion(h.version))
      .catch(() => {})
  }, [])
  useEffect(() => {
    if (!info) return
    const a = info.analysis
    setAnnounce(`${info.path.split("/").pop()} loaded. ${a ? a.verdict : "No analysis."}`)
  }, [info])
  useEffect(() => {
    if (!info) return
    const t = setTimeout(
      () =>
        setAnnounce(
          `View ${fmtTime(view.t0, 0.1)} to ${fmtTime(view.t1, 0.1)}, ${fmtHz(view.f0)} to ${fmtHz(view.f1)} hertz.`,
        ),
      700,
    )
    return () => clearTimeout(t)
  }, [view, info])

  const set = useCallback(<K extends keyof Settings>(k: K, v: Settings[K]) => setSettings(s => ({ ...s, [k]: v })), [])
  useEffect(() => {
    try {
      localStorage.setItem(STORE, JSON.stringify(settings))
    } catch {
      /* private mode */
    }
  }, [settings])

  useEffect(() => {
    const p = new URLSearchParams()
    if (dir) p.set("dir", dir)
    if (path) p.set("file", path)
    history.replaceState(null, "", `#${p}`)
  }, [dir, path])
  // A pasted deep link in an already open tab only changes the hash.
  useEffect(() => {
    const onHash = () => {
      const h = readHash()
      setDir(h.dir)
      if (h.file) setPath(h.file)
    }
    window.addEventListener("hashchange", onHash)
    return () => window.removeEventListener("hashchange", onHash)
  }, [])

  useEffect(() => {
    if (!path) return
    const ctl = new AbortController()
    setAnalysing(true)
    setError(null)
    setInfo(null)
    setTranscode(false)
    setViewSpec(null)
    setProgress(null)
    api
      .info(path, ctl.signal, setProgress)
      .then(i => {
        setInfo(i)
        viewHistory.current = []
        setViewRaw({ t0: 0, t1: i.duration, f0: 0, f1: i.sampleRate / 2 })
      })
      .catch(e => {
        if (e.name !== "AbortError") setError(String(e.message ?? e))
      })
      .finally(() => setAnalysing(false))
    return () => ctl.abort()
  }, [path])

  const open = useCallback((p: string) => {
    setPath(p)
    setPlaying(false)
    setScanDir(null)
    setDir(p.split("/").slice(0, -1).join("/")) // search hits and recents land in their folder
    try {
      const rec = JSON.parse(localStorage.getItem("spectrals.recent") ?? "[]") as string[]
      localStorage.setItem("spectrals.recent", JSON.stringify([p, ...rec.filter(x => x !== p)].slice(0, 20)))
    } catch {
      /* storage unavailable */
    }
  }, [])

  // RED-style zoomed spectral: the loudest 8 s, top of the band.
  const redZoom = useCallback(() => {
    if (!info) return
    const t0 = info.analysis?.loudestAt ?? 0,
      nyq = info.sampleRate / 2
    setView({ t0, t1: Math.min(info.duration, t0 + 8), f0: Math.max(0, Math.min(15000, nyq - 7000)), f1: nyq })
  }, [info, setView])

  const jump = useCallback(
    (t: number) => {
      if (!info) return
      setView(v => ({ ...v, t0: Math.max(0, t - 0.25), t1: Math.min(info.duration, t + 0.25) }))
      if (audioRef.current) audioRef.current.currentTime = t
    },
    [info, setView],
  )

  const exportPng = useCallback(() => {
    const url = exporter.current?.()
    if (!url || !path) return
    const a = document.createElement("a")
    a.href = url
    a.download = `${path
      .split("/")
      .pop()
      ?.replace(/\.[^.]+$/, "")}.${view.t0.toFixed(1)}-${view.t1.toFixed(1)}s.png`
    a.click()
  }, [path, view])
  const registerExport = useCallback((fn: (() => string | null) | null) => {
    exporter.current = fn
  }, [])

  const togglePlay = useCallback(() => {
    const a = audioRef.current
    if (!a || !info) return
    if (a.paused) {
      if (a.currentTime < view.t0 || a.currentTime > view.t1) a.currentTime = view.t0
      void a.play()
    } else a.pause()
  }, [info, view])

  const zoom = useCallback(
    (f: number) =>
      setView(v => {
        if (!info) return v
        const c = (v.t0 + v.t1) / 2,
          span = Math.min(info.duration, Math.max(0.02, (v.t1 - v.t0) * f))
        const t0 = Math.max(0, Math.min(info.duration - span, c - span / 2))
        return { ...v, t0, t1: t0 + span }
      }),
    [info, setView],
  )
  const fit = useCallback(
    () => info && setView({ t0: 0, t1: info.duration, f0: 0, f1: info.sampleRate / 2 }),
    [info, setView],
  )
  const pan = useCallback(
    (frac: number) =>
      setView(v => {
        if (!info) return v
        const span = v.t1 - v.t0,
          t0 = Math.max(0, Math.min(info.duration - span, v.t0 + span * frac))
        return { ...v, t0, t1: t0 + span }
      }),
    [info, setView],
  )

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if ((e.target as HTMLElement).closest("input,textarea,[role=combobox],[role=listbox]")) return
      if (e.metaKey || e.ctrlKey) return
      const k = e.key
      if (k === " ") {
        e.preventDefault()
        togglePlay()
      } else if (k === "+" || k === "=") zoom(0.5)
      else if (k === "-" || k === "_") zoom(2)
      else if (k === "0" || k === "f") fit()
      else if (k === "Backspace" || k === "u") back()
      else if (k === "z") redZoom()
      else if (k === "h") set("holes", !settings.holes)
      else if (k === "o") set("rolloff", !settings.rolloff)
      else if (k === "e") exportPng()
      else if (k === "ArrowLeft") pan(-0.25)
      else if (k === "ArrowRight") pan(0.25)
      else if (k === "Home" && audioRef.current) audioRef.current.currentTime = 0
      else if (k === "l") set("scale", settings.scale === "log" ? "linear" : "log")
      else if (k === "r") set("refs", !settings.refs)
      else if (k === "g") set("grid", !settings.grid)
      else if (k === "1") set("ch", "mix")
      else if (k === "2") set("ch", "left")
      else if (k === "3") set("ch", "right")
      else if (k === "4") set("ch", "side")
      else return
      e.preventDefault()
    }
    window.addEventListener("keydown", onKey)
    return () => window.removeEventListener("keydown", onKey)
  }, [togglePlay, zoom, fit, pan, set, settings, back, redZoom, exportPng])

  const soxFull = path ? api.soxUrl({ path, ch: settings.ch === "side" ? "mix" : settings.ch }) : "#"
  const soxZoom = path
    ? api.soxUrl({
        path,
        ch: settings.ch === "side" ? "mix" : settings.ch,
        start: view.t0.toFixed(2),
        dur: Math.min(60, view.t1 - view.t0).toFixed(2),
      })
    : "#"
  const name = path?.split("/").pop()

  return (
    <TooltipProvider delayDuration={300}>
      <a
        href="#main"
        className="sr-only focus:not-sr-only focus:absolute focus:top-2 focus:left-2 focus:z-50 focus:rounded-md focus:bg-primary focus:px-3 focus:py-2 focus:text-primary-foreground"
      >
        Skip to spectrogram
      </a>
      <div className="sr-only" aria-live="polite" aria-atomic="true">
        {announce}
      </div>
      <div
        className="grid h-full"
        style={{
          gridTemplateColumns: `${left ? "300px" : "0px"} 1fr ${right && info ? "340px" : "0px"}`,
          gridTemplateRows: "48px 1fr 28px",
        }}
      >
        {/* header */}
        <header className="col-span-3 flex items-center gap-2 border-b px-3">
          <Tip label="Library">
            <Button variant="ghost" size="icon-sm" onClick={() => setLeft(v => !v)}>
              <PanelLeft />
            </Button>
          </Tip>
          <div className="flex items-center gap-2 pr-2 font-semibold tracking-tight">
            <AudioWaveform className="size-5" aria-hidden="true" />
            simpleaudiospectral
            {version && <span className="font-mono text-[11px] font-normal text-muted-foreground">{version}</span>}
          </div>
          <Separator orientation="vertical" className="!h-6" />
          <div className="min-w-0 flex-1 truncate text-sm">
            {name ? (
              <span className="font-medium">{name}</span>
            ) : (
              <span className="text-muted-foreground">Pick a file from the library</span>
            )}
            {info && (
              <span className="ml-2 text-muted-foreground">
                {[info.artist, info.album].filter(Boolean).join(" - ")}
              </span>
            )}
          </div>
          {info && (
            <div className="hidden items-center gap-1.5 lg:flex">
              <Badge variant="outline">{info.codecName?.toUpperCase()}</Badge>
              <Badge variant="outline">{(info.sampleRate / 1000).toFixed(1)} kHz</Badge>
              {info.bits && <Badge variant="outline">{info.bits} bit</Badge>}
              {info.bitrate > 0 && <Badge variant="outline">{Math.round(info.bitrate / 1000)} kbps</Badge>}
              {info.analysis && (
                <Badge
                  variant={
                    info.analysis.level === "ok" ? "success" : info.analysis.level === "bad" ? "destructive" : "warning"
                  }
                >
                  {info.analysis.cutoffHz ? `cut-off ${(info.analysis.cutoffHz / 1000).toFixed(1)} kHz` : "no lowpass"}
                </Badge>
              )}
            </div>
          )}
          <Tip label="Analysis panel">
            <Button variant="ghost" size="icon-sm" onClick={() => setRight(v => !v)} disabled={!info}>
              <PanelRight />
            </Button>
          </Tip>
        </header>

        <nav aria-label="Library" className={cn("min-h-0 overflow-hidden border-r", !left && "border-r-0")}>
          {left && (
            <ErrorBoundary label="Library">
              <Library dir={dir} setDir={setDir} current={path} onOpen={open} onScan={setScanDir} />
            </ErrorBoundary>
          )}
        </nav>

        <main id="main" className="flex min-h-0 min-w-0 flex-col">
          {info && scanDir == null && (
            <div className="flex flex-wrap items-center gap-2 border-b px-3 py-2">
              <Tip label="Play / pause (Space)">
                <Button size="icon-sm" onClick={togglePlay}>
                  {playing ? <Pause /> : <Play />}
                </Button>
              </Tip>
              <Tip label="Back to start (Home)">
                <Button
                  variant="ghost"
                  size="icon-sm"
                  onClick={() => {
                    if (audioRef.current) audioRef.current.currentTime = view.t0
                  }}
                >
                  <SkipBack />
                </Button>
              </Tip>
              <Separator orientation="vertical" className="!h-6" />
              <Tip label={GLOSSARY.channel}>
                <span className="flex">
                  <ToggleGroup
                    type="single"
                    aria-label="Channel"
                    value={settings.ch}
                    onValueChange={v => v && set("ch", v as Channel)}
                  >
                    <ToggleGroupItem value="mix">Mix</ToggleGroupItem>
                    <ToggleGroupItem value="left">L</ToggleGroupItem>
                    <ToggleGroupItem value="right">R</ToggleGroupItem>
                    <ToggleGroupItem value="side">Side</ToggleGroupItem>
                  </ToggleGroup>
                </span>
              </Tip>
              <Tip label={GLOSSARY.scale}>
                <span className="flex">
                  <ToggleGroup
                    type="single"
                    aria-label="Frequency scale"
                    value={settings.scale}
                    onValueChange={v => v && set("scale", v as Scale)}
                  >
                    <ToggleGroupItem value="linear">Lin</ToggleGroupItem>
                    <ToggleGroupItem value="log">Log</ToggleGroupItem>
                  </ToggleGroup>
                </span>
              </Tip>
              <Select value={String(settings.fft)} onValueChange={v => set("fft", Number(v))}>
                <Tip label={GLOSSARY.fft}>
                  <SelectTrigger className="w-[112px]" aria-label="FFT size">
                    <SelectValue />
                  </SelectTrigger>
                </Tip>
                <SelectContent>
                  {FFTS.map(f => (
                    <SelectItem key={f} value={String(f)}>
                      FFT {f}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
              <Select value={settings.cmap} onValueChange={v => set("cmap", v)}>
                <Tip label={GLOSSARY.colormap}>
                  <SelectTrigger className="w-[112px] capitalize" aria-label="Colour map">
                    <SelectValue />
                  </SelectTrigger>
                </Tip>
                <SelectContent>
                  {COLORMAP_GROUPS.map(gr => (
                    <SelectGroup key={gr.label}>
                      <SelectLabel>{gr.label}</SelectLabel>
                      {gr.maps.map(c => (
                        <SelectItem key={c} value={c} className="capitalize">
                          {c}
                        </SelectItem>
                      ))}
                    </SelectGroup>
                  ))}
                </SelectContent>
              </Select>
              <Popover>
                <PopoverTrigger asChild>
                  <Button variant="outline" size="sm">
                    <Settings2 />
                    Display
                  </Button>
                </PopoverTrigger>
                <PopoverContent className="w-80 space-y-4">
                  <div className="space-y-2">
                    <div className="flex justify-between text-sm">
                      <Term term="range">Range</Term>
                      <span className="font-mono text-muted-foreground">
                        {settings.floor} .. {settings.ceil} dB
                      </span>
                    </div>
                    <Slider
                      aria-label="Display range in dB"
                      min={-160}
                      max={0}
                      step={1}
                      value={[settings.floor, settings.ceil]}
                      onValueChange={([a, b]) => setSettings(s => ({ ...s, floor: Math.min(a, b - 10), ceil: b }))}
                    />
                  </div>
                  <div className="space-y-2">
                    <div className="text-sm">
                      <Term term="window">Window</Term>
                    </div>
                    <Select value={settings.win} onValueChange={v => set("win", v)}>
                      <SelectTrigger className="w-full capitalize" aria-label="Window function">
                        <SelectValue />
                      </SelectTrigger>
                      <SelectContent>
                        {WINDOWS.map(w => (
                          <SelectItem key={w} value={w} className="capitalize">
                            {w}
                          </SelectItem>
                        ))}
                      </SelectContent>
                    </Select>
                  </div>
                  <Separator />
                  <Toggle label="RED lowpass references" t="refs" k="refs" settings={settings} set={set} />
                  <Toggle label="Detected cut-off line" t="cutoffLine" k="cutoff" settings={settings} set={set} />
                  <Toggle label="Grid" k="grid" settings={settings} set={set} />
                  <Toggle label="Follow playhead" t="follow" k="follow" settings={settings} set={set} />
                  <Toggle label="Highlight spectral holes (H)" t="holes" k="holes" settings={settings} set={set} />
                  <Toggle label="99% rolloff line (O)" t="rolloff" k="rolloff" settings={settings} set={set} />
                  <Button variant="secondary" size="sm" className="w-full" onClick={() => setSettings(DEFAULTS)}>
                    Reset to defaults
                  </Button>
                </PopoverContent>
              </Popover>
              <Tip label={`${GLOSSARY.refs} (R)`}>
                <Button
                  variant={settings.refs ? "secondary" : "ghost"}
                  size="icon-sm"
                  onClick={() => set("refs", !settings.refs)}
                >
                  <Ruler />
                </Button>
              </Tip>
              <Tip label="Toggle grid (G)">
                <Button
                  variant={settings.grid ? "secondary" : "ghost"}
                  size="icon-sm"
                  onClick={() => set("grid", !settings.grid)}
                >
                  <Grid3x3 />
                </Button>
              </Tip>
              <Tip label={`${GLOSSARY.redZoom} (Z)`}>
                <Button variant="outline" size="sm" onClick={redZoom}>
                  <Crosshair />
                  RED zoom
                </Button>
              </Tip>
              <Tip label={`${GLOSSARY.exportPng} (E)`}>
                <Button variant="outline" size="sm" onClick={exportPng}>
                  <ImageDown />
                  PNG
                </Button>
              </Tip>
              <div className="ml-auto flex items-center gap-1">
                {loading && <Loader2 className="size-4 animate-spin text-muted-foreground" />}
                <Tip label="Previous view (Backspace)">
                  <Button variant="ghost" size="icon-sm" onClick={back}>
                    <Undo2 />
                  </Button>
                </Tip>
                <Tip label="Zoom out (-)">
                  <Button variant="ghost" size="icon-sm" onClick={() => zoom(2)}>
                    <ZoomOut />
                  </Button>
                </Tip>
                <Tip label="Zoom in (+)">
                  <Button variant="ghost" size="icon-sm" onClick={() => zoom(0.5)}>
                    <ZoomIn />
                  </Button>
                </Tip>
                <Tip label="Fit whole track (F / double-click)">
                  <Button variant="ghost" size="icon-sm" onClick={fit}>
                    <Maximize2 />
                  </Button>
                </Tip>
                <Shortcuts />
              </div>
            </div>
          )}
          <div className="min-h-0 flex-1">
            <ErrorBoundary label="Viewer">
              {scanDir != null ? (
                <AlbumScan dir={scanDir} onOpen={open} onClose={() => setScanDir(null)} />
              ) : info ? (
                <Viewer
                  info={info}
                  settings={settings}
                  view={view}
                  setView={setView}
                  audio={audioEl}
                  playing={playing}
                  onCursor={setCursor}
                  onLoading={setLoading}
                  onViewSpectrum={setViewSpec}
                  registerExport={registerExport}
                />
              ) : (
                <Empty analysing={analysing} error={error} name={name} progress={progress} />
              )}
            </ErrorBoundary>
          </div>
        </main>

        <aside
          aria-label="Analysis"
          className={cn("min-h-0 overflow-hidden border-l", !(right && info) && "border-l-0")}
        >
          {right && info && (
            <ErrorBoundary label="Analysis">
              <Analysis
                info={info}
                cursor={cursor}
                settings={settings}
                soxFull={soxFull}
                soxZoom={soxZoom}
                view={view}
                viewSpec={viewSpec}
                onJump={jump}
              />
            </ErrorBoundary>
          )}
        </aside>

        {/* status bar */}
        <footer
          aria-label="Cursor readout"
          className="col-span-3 flex items-center gap-5 border-t px-3 font-mono text-xs text-muted-foreground"
        >
          {info ? (
            <>
              <span>
                view {fmtTime(view.t0, 0.01)} - {fmtTime(view.t1, 0.01)}
              </span>
              <span>
                {fmtHz(view.f0)} - {fmtHz(view.f1)} Hz
              </span>
              {cursor && <span className="text-foreground">t {fmtTime(cursor.t, 0.001)}</span>}
              {cursor && Number.isFinite(cursor.f) && (
                <span className="text-foreground">f {fmtHz(cursor.f, true)}Hz</span>
              )}
              {cursor?.db != null && <span className="text-foreground">{cursor.db.toFixed(1)} dBFS</span>}
              <span className="ml-auto">
                <Term term="hzPerBin">
                  FFT {settings.fft} = {(info.sampleRate / settings.fft).toFixed(1)} Hz/bin,{" "}
                  {((settings.fft / info.sampleRate) * 1000).toFixed(1)} ms
                </Term>
              </span>
            </>
          ) : (
            <span>drag = box zoom - shift+drag = pan - wheel = zoom - alt+wheel = frequency zoom</span>
          )}
        </footer>
      </div>
      {path && (
        // Music playback: there is no speech to caption.
        // eslint-disable-next-line jsx-a11y/media-has-caption
        <audio
          ref={el => {
            audioRef.current = el
            setAudioEl(el)
          }}
          src={api.audioUrl(path, transcode)}
          preload="none"
          onError={() => {
            if (!transcode) {
              setTranscode(true)
              setTimeout(() => void audioRef.current?.play().catch(() => {}), 50)
            }
          }}
          onPlay={() => setPlaying(true)}
          onPause={() => setPlaying(false)}
          onEnded={() => setPlaying(false)}
        />
      )}
    </TooltipProvider>
  )
}

function Toggle({
  label,
  k,
  t,
  settings,
  set,
}: {
  label: string
  k: "refs" | "cutoff" | "grid" | "follow" | "holes" | "rolloff"
  t?: import("@/lib/glossary").Term
  settings: Settings
  set: <K extends keyof Settings>(k: K, v: Settings[K]) => void
}) {
  return (
    <label className="flex items-center justify-between text-sm">
      {t ? <Term term={t}>{label}</Term> : label}
      <Switch checked={settings[k]} onCheckedChange={v => set(k, v)} />
    </label>
  )
}

function Empty({
  analysing,
  error,
  name,
  progress,
}: {
  analysing: boolean
  error: string | null
  name?: string
  progress: Progress | null
}) {
  return (
    <div className="flex h-full flex-col items-center justify-center gap-3 text-center text-muted-foreground">
      {analysing ? (
        <>
          <Loader2 className="size-6 animate-spin" aria-hidden="true" />
          <p className="text-sm" role="status">
            {progress ? `${progress.stage}` : "Decoding"} - {name}
          </p>
          {progress && progress.done > 0 && (
            <div
              className="h-1 w-64 overflow-hidden rounded-full bg-muted"
              role="progressbar"
              aria-valuemin={0}
              aria-valuemax={100}
              aria-valuenow={Math.round(progress.done * 100)}
            >
              <div className="h-full bg-foreground/70" style={{ width: `${progress.done * 100}%` }} />
            </div>
          )}
          <p className="max-w-sm text-xs">
            Every frame of the file is analysed. The first analysis of a long file takes a while; the result is kept, so
            opening it again is instant.
          </p>
        </>
      ) : error ? (
        <p className="text-sm text-destructive">{error}</p>
      ) : (
        <>
          <AudioWaveform className="size-10" />
          <p className="max-w-md text-sm">
            Open a FLAC, MP3, WAV, ALAC, Opus, Ogg, AIFF, WavPack or APE file to see its spectral, waveform and lowpass
            analysis.
          </p>
        </>
      )}
    </div>
  )
}

function Shortcuts() {
  const rows: [string, string][] = [
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
    ["Z", "RED zoom"],
    ["Backspace / U", "previous view"],
    ["H / O", "holes / rolloff overlay"],
    ["E", "export PNG"],
  ]
  return (
    <Popover>
      <PopoverTrigger asChild>
        <Button variant="ghost" size="sm" className="font-mono" aria-label="Keyboard shortcuts">
          ?
        </Button>
      </PopoverTrigger>
      <PopoverContent className="w-80">
        <div className="space-y-1.5 text-sm">
          {rows.map(([k, v]) => (
            <div key={k} className="flex justify-between gap-4">
              <Kbd className="h-auto py-0.5">{k}</Kbd>
              <span className="text-muted-foreground">{v}</span>
            </div>
          ))}
        </div>
      </PopoverContent>
    </Popover>
  )
}
