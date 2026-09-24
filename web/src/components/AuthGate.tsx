import { useEffect, useState, type ReactNode, type SubmitEvent } from "react"
import { AudioWaveform, Loader2 } from "lucide-react"
import { api, UNAUTHORIZED } from "@/lib/api"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"

type State = "checking" | "login" | "ok"

/** Renders the app once the server accepts us: always without API_KEY, else
 * after a login that sets the session cookie. A 401 later (key rotated,
 * cookie expired, logout) brings the login back and remounts the app after. */
export function AuthGate({ children }: { children: ReactNode }) {
  const [state, setState] = useState<State>("checking")

  useEffect(() => {
    api
      .health()
      .then(h => setState(h.auth && !h.authenticated ? "login" : "ok"))
      .catch(() => setState("ok")) // the app shows its own errors
    const onUnauthorized = () => setState("login")
    window.addEventListener(UNAUTHORIZED, onUnauthorized)
    return () => window.removeEventListener(UNAUTHORIZED, onUnauthorized)
  }, [])

  if (state === "ok") return children
  if (state === "checking")
    return (
      <div className="flex h-full items-center justify-center text-muted-foreground">
        <Loader2 className="size-6 animate-spin" aria-label="Connecting" />
      </div>
    )
  return <Login onDone={() => setState("ok")} />
}

function Login({ onDone }: { onDone: () => void }) {
  const [key, setKey] = useState("")
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const submit = (e: SubmitEvent<HTMLFormElement>) => {
    e.preventDefault()
    if (!key) return
    setBusy(true)
    setError(null)
    api
      .login(key)
      .then(ok => (ok ? onDone() : setError("Wrong API key.")))
      .catch(err => setError(String(err.message ?? err)))
      .finally(() => setBusy(false))
  }

  return (
    <main className="flex h-full items-center justify-center p-4">
      <form onSubmit={submit} className="flex w-full max-w-sm flex-col gap-3 rounded-lg border p-5">
        <div className="flex items-center gap-2 font-semibold tracking-tight">
          <AudioWaveform className="size-5" aria-hidden="true" />
          simpleaudiospectral
        </div>
        <label htmlFor="api-key" className="text-sm text-muted-foreground">
          This server needs its API key.
        </label>
        <Input
          id="api-key"
          type="password"
          autoComplete="current-password"
          value={key}
          onChange={e => setKey(e.target.value)}
          aria-invalid={error != null}
          aria-describedby={error ? "api-key-error" : undefined}
        />
        {error && (
          <p id="api-key-error" role="alert" className="text-sm text-destructive">
            {error}
          </p>
        )}
        <Button type="submit" disabled={busy || !key}>
          {busy && <Loader2 className="animate-spin" aria-hidden="true" />}
          Sign in
        </Button>
      </form>
    </main>
  )
}
