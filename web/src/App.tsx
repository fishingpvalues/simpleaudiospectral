import { useCallback, useEffect, useState } from "react"
import { api, type Info } from "@/lib/api"
import { baseName, parentDir } from "@/lib/path"
import { pushRecent } from "@/lib/recent"
import { fullView } from "@/lib/view"
import { Analysis } from "@/components/analysis/Analysis"
import { EmptyState } from "@/components/app/EmptyState"
import { Header } from "@/components/app/Header"
import { StatusBar } from "@/components/app/StatusBar"
import { Toolbar } from "@/components/app/Toolbar"
import { ErrorBoundary } from "@/components/ErrorBoundary"
import { Library } from "@/components/library/Library"
import { AlbumScan } from "@/components/scan/AlbumScan"
import { TooltipProvider } from "@/components/ui/tooltip"
import type { Cursor, Spectrum } from "@/components/viewer/types"
import { Viewer } from "@/components/viewer/Viewer"
import { useAnnouncer } from "@/hooks/useAnnouncer"
import { useFileInfo } from "@/hooks/useFileInfo"
import { useHashRoute } from "@/hooks/useHashRoute"
import { useHealth } from "@/hooks/useHealth"
import { useKeyboardShortcuts } from "@/hooks/useKeyboardShortcuts"
import { usePlayback } from "@/hooks/usePlayback"
import { usePngExport } from "@/hooks/usePngExport"
import { useSettings } from "@/hooks/useSettings"
import { useViewActions } from "@/hooks/useViewActions"
import { useViewHistory } from "@/hooks/useViewHistory"
import { cn } from "@/lib/utils"

export function App() {
  const { dir, setDir, path, setPath } = useHashRoute()
  const { settings, setSettings, set } = useSettings()
  const { view, setView, back, reset: resetView } = useViewHistory({ t0: 0, t1: 1, f0: 0, f1: 22050 })
  const onLoaded = useCallback((i: Info) => resetView(fullView(i.duration, i.sampleRate)), [resetView])
  const { info, error, analysing, progress } = useFileInfo(path, onLoaded)
  const player = usePlayback(path)
  const { version, authOn } = useHealth()
  const announce = useAnnouncer(info, view)
  const { zoom, fit, pan, detailZoom, jump } = useViewActions(info, setView, player.seek)
  const { exportPng, registerExport } = usePngExport(path, view)

  const [scanDir, setScanDir] = useState<string | null>(null)
  const [viewSpec, setViewSpec] = useState<Spectrum | null>(null)
  const [cursor, setCursor] = useState<Cursor | null>(null)
  const [loading, setLoading] = useState(false)
  const [left, setLeft] = useState(true)
  const [right, setRight] = useState(true)

  // The previous file's view spectrum must not show against the next file.
  useEffect(() => {
    if (path) setViewSpec(null)
  }, [path])

  const { setPlaying } = player
  const open = useCallback(
    (p: string) => {
      setPath(p)
      setPlaying(false)
      setScanDir(null)
      setDir(parentDir(p)) // search hits and recents land in their folder
      pushRecent(p)
    },
    [setPath, setPlaying, setDir],
  )

  const togglePlay = () => info && player.togglePlay(view)
  const toStart = () => player.seek(view.t0)

  useKeyboardShortcuts({
    togglePlay,
    zoomIn: () => zoom(0.5),
    zoomOut: () => zoom(2),
    fit,
    back,
    detailZoom,
    toggleHoles: () => set("holes", !settings.holes),
    toggleRolloff: () => set("rolloff", !settings.rolloff),
    exportPng,
    panLeft: () => pan(-0.25),
    panRight: () => pan(0.25),
    toStart: () => player.seek(0),
    toggleScale: () => set("scale", settings.scale === "log" ? "linear" : "log"),
    toggleRefs: () => set("refs", !settings.refs),
    toggleGrid: () => set("grid", !settings.grid),
    chMix: () => set("ch", "mix"),
    chLeft: () => set("ch", "left"),
    chRight: () => set("ch", "right"),
    chSide: () => set("ch", "side"),
  })

  // SoX has no side channel; its export falls back to the mix.
  const soxCh = settings.ch === "side" ? "mix" : settings.ch
  const soxFull = path ? api.soxUrl({ path, ch: soxCh }) : "#"
  const soxZoom = path
    ? api.soxUrl({ path, ch: soxCh, start: view.t0.toFixed(2), dur: Math.min(60, view.t1 - view.t0).toFixed(2) })
    : "#"
  const name = path ? baseName(path) : undefined

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
        <Header
          name={name}
          info={info}
          version={version}
          authOn={authOn}
          onToggleLibrary={() => setLeft(v => !v)}
          onToggleAnalysis={() => setRight(v => !v)}
        />

        <nav aria-label="Library" className={cn("min-h-0 overflow-hidden border-r", !left && "border-r-0")}>
          {left && (
            <ErrorBoundary label="Library">
              <Library dir={dir} setDir={setDir} current={path} onOpen={open} onScan={setScanDir} />
            </ErrorBoundary>
          )}
        </nav>

        <main id="main" className="flex min-h-0 min-w-0 flex-col">
          {info && scanDir == null && (
            <Toolbar
              settings={settings}
              setSettings={setSettings}
              set={set}
              playing={player.playing}
              playError={player.playError}
              loading={loading}
              onTogglePlay={togglePlay}
              onToStart={toStart}
              onDetailZoom={detailZoom}
              onExportPng={exportPng}
              onBack={back}
              onZoom={zoom}
              onFit={fit}
            />
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
                  audio={player.audioEl}
                  playing={player.playing}
                  onCursor={setCursor}
                  onLoading={setLoading}
                  onViewSpectrum={setViewSpec}
                  registerExport={registerExport}
                />
              ) : (
                <EmptyState analysing={analysing} error={error} name={name} progress={progress} />
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

        <StatusBar info={info} view={view} cursor={cursor} settings={settings} />
      </div>
      {path && (
        // Music playback: there is no speech to caption.
        // eslint-disable-next-line jsx-a11y/media-has-caption
        <audio {...player.audioProps} />
      )}
    </TooltipProvider>
  )
}
