import { useCallback, useEffect, useState } from "react"
import { loadSettings, saveSettings, type SetSetting, type Settings } from "@/lib/settings"

/** Display settings, persisted to localStorage on every change. */
export function useSettings() {
  const [settings, setSettings] = useState<Settings>(loadSettings)
  const set: SetSetting = useCallback((k, v) => setSettings(s => ({ ...s, [k]: v })), [])
  useEffect(() => saveSettings(settings), [settings])
  return { settings, setSettings, set }
}
