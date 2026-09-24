import type { Term as TermKey } from "@/lib/glossary"
import type { BooleanSetting, SetSetting, Settings } from "@/lib/settings"
import { Switch } from "@/components/ui/switch"
import { Term } from "@/components/ui/tooltip"

interface SettingToggleProps {
  label: string
  k: BooleanSetting
  /** Glossary entry explaining the setting, shown on hover. */
  t?: TermKey
  settings: Settings
  set: SetSetting
}

/** One on/off row of the Display popover. */
export function SettingToggle({ label, k, t, settings, set }: SettingToggleProps) {
  return (
    <label className="flex items-center justify-between text-sm">
      {t ? <Term term={t}>{label}</Term> : label}
      <Switch checked={settings[k]} onCheckedChange={v => set(k, v)} />
    </label>
  )
}
