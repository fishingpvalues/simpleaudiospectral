import { useEffect, useState, type ReactNode, type SubmitEvent } from "react"
import { AudioWaveform, Loader2 } from "lucide-react"
import { api, UNAUTHORIZED } from "@/lib/api"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"

type State = "checking" | "login" | "ok"

/** Renders the app once the server accepts us: always without API_KEY, else
 * after a login that sets the session cookie. A 401 later (key rotated,
 * cookie expired, logout) brings the login back and remounts the app after.
 * The signed-out health already says whether a two-factor code is part of
 * the login, so the form knows to draw the field. */
export function AuthGate({ children }: { children: ReactNode }) {
  const [state, setState] = useState<State>("checking")
  const [twofa, setTwofa] = useState(false)

  useEffect(() => {
    api
      .health()
      .then(h => {
        setTwofa(!!h.twofa)
        setState(h.auth && !h.authenticated ? "login" : "ok")
      })
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
  return <Login twofa={twofa} onTwofa={setTwofa} onDone={() => setState("ok")} />
}

function Login({ twofa, onTwofa, onDone }: { twofa: boolean; onTwofa: (on: boolean) => void; onDone: () => void }) {
  const [key, setKey] = useState("")
  const [code, setCode] = useState("")
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  // Re-check the two-factor flag whenever the login comes back: it may have
  // been enrolled on another device in the meantime.
  useEffect(() => {
    api
      .health()
      .then(h => onTwofa(!!h.twofa))
      .catch(() => {})
  }, [onTwofa])

  const submit = (e: SubmitEvent<HTMLFormElement>) => {
    e.preventDefault()
    if (!key || (twofa && code.length < 6)) return
    setBusy(true)
    setError(null)
    api
      .login(key, code)
      .then(ok => (ok ? onDone() : setError(twofa ? "Wrong API key or two-factor code." : "Wrong API key.")))
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
          This server needs its API key{twofa ? " and a two-factor code." : "."}
        </label>
        <Input
          id="api-key"
          type="password"
          autoComplete="current-password"
          value={key}
          onChange={e => setKey(e.target.value)}
          aria-invalid={error != null}
          aria-describedby={error ? "login-error" : undefined}
        />
        {twofa && (
          <Input
            id="twofa-code"
            type="text"
            inputMode="numeric"
            autoComplete="one-time-code"
            placeholder="123456"
            maxLength={6}
            className="text-center font-mono tracking-[0.4em]"
            value={code}
            onChange={e => setCode(e.target.value.replace(/\D/g, ""))}
          />
        )}
        {error && (
          <p id="login-error" role="alert" className="text-sm text-destructive">
            {error}
          </p>
        )}
        <Button type="submit" disabled={busy || !key || (twofa && code.length < 6)}>
          {busy && <Loader2 className="animate-spin" aria-hidden="true" />}
          Sign in
        </Button>
      </form>
    </main>
  )
}
