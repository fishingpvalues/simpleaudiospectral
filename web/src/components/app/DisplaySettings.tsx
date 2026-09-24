import { Settings2 } from "lucide-react"
import { REF_SETS } from "@/lib/references"
import { DEFAULTS, WINDOWS, type SetSetting, type Settings } from "@/lib/settings"
import { Button } from "@/components/ui/button"
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover"
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select"
import { Separator } from "@/components/ui/separator"
import { Slider } from "@/components/ui/slider"
import { Switch } from "@/components/ui/switch"
import { Term, Tip } from "@/components/ui/tooltip"
import { SettingToggle } from "./SettingToggle"

/** The display range never gets narrower than this many dB. */
const MIN_RANGE_DB = 10

interface DisplaySettingsProps {
  settings: Settings
  setSettings: (fn: Settings | ((s: Settings) => Settings)) => void
  set: SetSetting
}

/** "Display" popover: dB range, window, overlays and the encoders to draw. */
export function DisplaySettings({ settings, setSettings, set }: DisplaySettingsProps) {
  return (
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
            onValueChange={([a, b]) => setSettings(s => ({ ...s, floor: Math.min(a, b - MIN_RANGE_DB), ceil: b }))}
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
        <SettingToggle label="Encoder lowpass lines (R)" t="refs" k="refs" settings={settings} set={set} />
        <RefSetSwitches settings={settings} set={set} />
        <SettingToggle label="Detected cut-off line" t="cutoffLine" k="cutoff" settings={settings} set={set} />
        <SettingToggle label="Grid" k="grid" settings={settings} set={set} />
        <SettingToggle label="Follow playhead" t="follow" k="follow" settings={settings} set={set} />
        <SettingToggle label="Highlight spectral holes (H)" t="holes" k="holes" settings={settings} set={set} />
        <SettingToggle label="99% rolloff line (O)" t="rolloff" k="rolloff" settings={settings} set={set} />
        <Button variant="secondary" size="sm" className="w-full" onClick={() => setSettings(DEFAULTS)}>
          Reset to defaults
        </Button>
      </PopoverContent>
    </Popover>
  )
}

/** One switch per encoder family; disabled while the lowpass lines are off. */
function RefSetSwitches({ settings, set }: { settings: Settings; set: SetSetting }) {
  return (
    <fieldset className="flex flex-col gap-1.5 pl-3" disabled={!settings.refs}>
      <legend className="sr-only">Encoders to draw</legend>
      {REF_SETS.map(r => (
        <div key={r.id} className="flex items-center justify-between text-xs text-muted-foreground">
          <Tip label={r.source}>
            <span>{r.name}</span>
          </Tip>
          <Switch
            aria-label={`${r.name} lowpass lines`}
            checked={settings.refSets.includes(r.id)}
            onCheckedChange={v =>
              set("refSets", v ? [...settings.refSets, r.id] : settings.refSets.filter(x => x !== r.id))
            }
          />
        </div>
      ))}
    </fieldset>
  )
}
