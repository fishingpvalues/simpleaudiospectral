import { useEffect, useState } from "react"
import { api } from "@/lib/api"

/** Server version and whether it asks for an API key (shows "Sign out"). */
export function useHealth() {
  const [version, setVersion] = useState<string | null>(null)
  const [authOn, setAuthOn] = useState(false)
  useEffect(() => {
    api
      .health()
      .then(h => {
        setVersion(h.version)
        setAuthOn(h.auth)
      })
      .catch(() => {})
  }, [])
  return { version, authOn }
}
