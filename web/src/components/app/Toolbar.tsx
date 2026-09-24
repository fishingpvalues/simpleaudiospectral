import {
  Crosshair,
  Grid3x3,
  ImageDown,
  Loader2,
  Maximize2,
  Pause,
  Play,
  Ruler,
  SkipBack,
  Undo2,
  ZoomIn,
  ZoomOut,
} from "lucide-react"
import type { Channel, Scale } from "@/lib/api"
import { COLORMAP_GROUPS } from "@/lib/colormaps"
import { GLOSSARY } from "@/lib/glossary"
import { FFTS, type SetSetting, type Settings } from "@/lib/settings"
import { Button } from "@/components/ui/button"
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
import { ToggleGroup, ToggleGroupItem } from "@/components/ui/toggle-group"
import { Tip } from "@/components/ui/tooltip"
import { DisplaySettings } from "./DisplaySettings"
import { Shortcuts } from "./Shortcuts"

interface ToolbarProps {
  settings: Settings
  setSettings: (fn: Settings | ((s: Settings) => Settings)) => void
  set: SetSetting
  playing: boolean
  playError: string | null
  /** A spectrogram tile is being fetched. */
  loading: boolean
  onTogglePlay: () => void
  onToStart: () => void
  onDetailZoom: () => void
  onExportPng: () => void
  onBack: () => void
  onZoom: (factor: number) => void
  onFit: () => void
}

export function Toolbar({
  settings,
  setSettings,
  set,
  playing,
  playError,
  loading,
  onTogglePlay,
  onToStart,
  onDetailZoom,
  onExportPng,
  onBack,
  onZoom,
  onFit,
}: ToolbarProps) {
  return (
    <div className="flex flex-wrap items-center gap-2 border-b px-3 py-2">
      <Tip label="Play / pause (Space)">
        <Button size="icon-sm" onClick={onTogglePlay}>
          {playing ? <Pause /> : <Play />}
        </Button>
      </Tip>
      {playError && (
        <span role="alert" className="text-xs text-destructive">
          {playError}
        </span>
      )}
      <Tip label="Back to start (Home)">
        <Button variant="ghost" size="icon-sm" onClick={onToStart}>
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
      <DisplaySettings settings={settings} setSettings={setSettings} set={set} />
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
        <Button variant="outline" size="sm" onClick={onDetailZoom}>
          <Crosshair />
          Detail zoom
        </Button>
      </Tip>
      <Tip label={`${GLOSSARY.exportPng} (E)`}>
        <Button variant="outline" size="sm" onClick={onExportPng}>
          <ImageDown />
          PNG
        </Button>
      </Tip>
      <div className="ml-auto flex items-center gap-1">
        {loading && <Loader2 className="size-4 animate-spin text-muted-foreground" />}
        <Tip label="Previous view (Backspace)">
          <Button variant="ghost" size="icon-sm" onClick={onBack}>
            <Undo2 />
          </Button>
        </Tip>
        <Tip label="Zoom out (-)">
          <Button variant="ghost" size="icon-sm" onClick={() => onZoom(2)}>
            <ZoomOut />
          </Button>
        </Tip>
        <Tip label="Zoom in (+)">
          <Button variant="ghost" size="icon-sm" onClick={() => onZoom(0.5)}>
            <ZoomIn />
          </Button>
        </Tip>
        <Tip label="Fit whole track (F / double-click)">
          <Button variant="ghost" size="icon-sm" onClick={onFit}>
            <Maximize2 />
          </Button>
        </Tip>
        <Shortcuts />
      </div>
    </div>
  )
}
