import { SHORTCUT_HELP } from "@/lib/shortcuts"
import { Button } from "@/components/ui/button"
import { Kbd } from "@/components/ui/kbd"
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover"

/** "?" popover listing keys and pointer gestures. */
export function Shortcuts() {
  return (
    <Popover>
      <PopoverTrigger asChild>
        <Button variant="ghost" size="sm" className="font-mono" aria-label="Keyboard shortcuts">
          ?
        </Button>
      </PopoverTrigger>
      <PopoverContent className="w-80">
        <div className="space-y-1.5 text-sm">
          {SHORTCUT_HELP.map(([k, v]) => (
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
