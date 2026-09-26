import { AudioWaveform, LogOut, PanelLeft, PanelRight } from "lucide-react"
import { api, type Info } from "@/lib/api"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Separator } from "@/components/ui/separator"
import { Tip } from "@/components/ui/tooltip"
import { TwoFactor } from "@/components/app/TwoFactor"

interface HeaderProps {
  name: string | undefined
  info: Info | null
  version: string | null
  authOn: boolean
  twofa: boolean
  onTwofa: (on: boolean) => void
  onToggleLibrary: () => void
  onToggleAnalysis: () => void
}

export function Header({
  name,
  info,
  version,
  authOn,
  twofa,
  onTwofa,
  onToggleLibrary,
  onToggleAnalysis,
}: HeaderProps) {
  return (
    <header className="col-span-3 flex items-center gap-2 border-b px-3">
      <Tip label="Library">
        <Button variant="ghost" size="icon-sm" onClick={onToggleLibrary}>
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
          <span className="ml-2 text-muted-foreground">{[info.artist, info.album].filter(Boolean).join(" - ")}</span>
        )}
      </div>
      {info && <FormatBadges info={info} />}
      {authOn && (
        <>
          <TwoFactor enabled={twofa} onChange={onTwofa} />
          <Tip label="Sign out">
            <Button variant="ghost" size="icon-sm" onClick={() => void api.logout()}>
              <LogOut />
            </Button>
          </Tip>
        </>
      )}
      <Tip label="Analysis panel">
        <Button variant="ghost" size="icon-sm" onClick={onToggleAnalysis} disabled={!info}>
          <PanelRight />
        </Button>
      </Tip>
    </header>
  )
}

function FormatBadges({ info }: { info: Info }) {
  const a = info.analysis
  return (
    <div className="hidden items-center gap-1.5 lg:flex">
      <Badge variant="outline">{info.codecName?.toUpperCase()}</Badge>
      <Badge variant="outline">{(info.sampleRate / 1000).toFixed(1)} kHz</Badge>
      {info.bits && <Badge variant="outline">{info.bits} bit</Badge>}
      {info.bitrate > 0 && <Badge variant="outline">{Math.round(info.bitrate / 1000)} kbps</Badge>}
      {a && (
        <Badge variant={a.level === "ok" ? "success" : a.level === "bad" ? "destructive" : "warning"}>
          {a.cutoffHz ? `cut-off ${(a.cutoffHz / 1000).toFixed(1)} kHz` : "no lowpass"}
        </Badge>
      )}
    </div>
  )
}
