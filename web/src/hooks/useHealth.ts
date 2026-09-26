import { useEffect, useState } from "react"
import { api } from "@/lib/api"

/** Server version, whether it asks for a key (shows "Sign out") and whether
 * two-factor is enrolled (enroll/disarm control in the header). */
export function useHealth() {
  const [version, setVersion] = useState<string | null>(null)
  const [authOn, setAuthOn] = useState(false)
  const [twofa, setTwofa] = useState(false)
  useEffect(() => {
    api
      .health()
      .then(h => {
        setVersion(h.version ?? null)
        setAuthOn(h.auth)
        setTwofa(!!h.twofa)
      })
      .catch(() => {})
  }, [])
  return { version, authOn, twofa, setTwofa }
}
