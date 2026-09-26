import { useEffect, useState } from "react"
import * as QRCode from "qrcode"
import { KeyRound, Loader2, QrCode } from "lucide-react"
import { api } from "@/lib/api"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover"

/** Two-factor setup and teardown, next to the sign-out button. Enrollment
 * shows the secret once as a QR code and as plain base32; a code from the
 * freshly enrolled app activates it. Disarm needs a valid current code. */
export function TwoFactor({ enabled, onChange }: { enabled: boolean; onChange: (on: boolean) => void }) {
  const [open, setOpen] = useState(false)
  const [setup, setSetup] = useState<{ secret: string; uri: string } | null>(null)
  const [qr, setQr] = useState("")
  const [code, setCode] = useState("")
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [done, setDone] = useState<string | null>(null)

  useEffect(() => {
    if (!setup) return
    QRCode.toDataURL(setup.uri, { width: 160, margin: 1 })
      .then(setQr)
      .catch(() => setQr(""))
  }, [setup])

  const close = () => {
    setOpen(false)
    setSetup(null)
    setCode("")
    setError(null)
    setBusy(false)
    setDone(null)
  }

  const begin = async () => {
    setError(null)
    setDone(null)
    setBusy(true)
    try {
      setSetup(await api.twofaSetup())
    } catch (e) {
      setError(String((e as Error).message ?? e))
    } finally {
      setBusy(false)
    }
  }

  const verify = async () => {
    if (!setup || code.length < 6) return
    setError(null)
    setBusy(true)
    try {
      if (await api.twofaVerify(setup.secret, code)) {
        setDone("Two-factor is on: browser logins now need the code from your app.")
        setSetup(null)
        setCode("")
        onChange(true)
      } else setError("Wrong two-factor code.")
    } catch (e) {
      setError(String((e as Error).message ?? e))
    } finally {
      setBusy(false)
    }
  }

  const remove = async () => {
    if (code.length < 6) return
    setError(null)
    setBusy(true)
    try {
      if (await api.twofaRemove(code)) {
        setDone("Two-factor is off: browser logins need only the API key.")
        setCode("")
        onChange(false)
      } else setError("Wrong two-factor code.")
    } catch (e) {
      setError(String((e as Error).message ?? e))
    } finally {
      setBusy(false)
    }
  }

  return (
    <Popover open={open} onOpenChange={o => (o ? setOpen(true) : close())}>
      <PopoverTrigger asChild>
        <Button variant="ghost" size="icon-sm" aria-label="Two-factor authentication">
          <KeyRound />
        </Button>
      </PopoverTrigger>
      <PopoverContent className="w-80">
        <h2 className="mb-1 font-semibold">Two-factor authentication</h2>
        {enabled && !setup && (
          <p className="mb-3 text-sm text-muted-foreground">
            On: browser logins need the API key and a code from your authenticator app.
          </p>
        )}
        {!enabled && !setup && !done && (
          <p className="mb-3 text-sm text-muted-foreground">
            Add a second factor so a stolen API key alone cannot open the browser session. API clients keep working with
            the key only.
          </p>
        )}
        {done && <p className="mb-3 text-sm">{done}</p>}
        {!enabled && !setup && !done && (
          <Button onClick={() => void begin()} disabled={busy} size="sm">
            {busy ? <Loader2 className="animate-spin" aria-hidden="true" /> : <QrCode />}
            Enroll an authenticator app
          </Button>
        )}
        {setup && (
          <div className="mb-3 flex flex-col items-center gap-2">
            {qr ? (
              <img src={qr} alt="Two-factor enrollment QR code" className="size-40 rounded border" />
            ) : (
              <QrCode className="size-16 text-muted-foreground" aria-hidden="true" />
            )}
            <p className="text-center text-xs text-muted-foreground">
              Scan it into your authenticator app, or enter the key manually:
            </p>
            <code className="w-full rounded bg-muted p-2 text-center font-mono text-xs break-all select-all">
              {setup.secret}
            </code>
          </div>
        )}
        {(setup || enabled) && (
          <div className="flex flex-col gap-2">
            <Input
              type="text"
              inputMode="numeric"
              autoComplete="one-time-code"
              placeholder={setup ? "Code from the app" : "Current code"}
              maxLength={6}
              className="text-center font-mono tracking-[0.4em]"
              value={code}
              onChange={e => setCode(e.target.value.replace(/\D/g, ""))}
              aria-label="Two-factor code"
            />
            {error && (
              <p role="alert" className="text-sm text-destructive">
                {error}
              </p>
            )}
            <div className="flex gap-2">
              {setup ? (
                <>
                  <Button size="sm" onClick={() => void verify()} disabled={busy || code.length < 6} className="flex-1">
                    {busy && <Loader2 className="animate-spin" aria-hidden="true" />}
                    Verify and enable
                  </Button>
                  <Button size="sm" variant="outline" onClick={close}>
                    Cancel
                  </Button>
                </>
              ) : (
                <Button
                  size="sm"
                  variant="outline"
                  className="flex-1 text-destructive hover:bg-destructive/10 hover:text-destructive"
                  onClick={() => void remove()}
                  disabled={busy || code.length < 6}
                >
                  {busy && <Loader2 className="animate-spin" aria-hidden="true" />}
                  Disable two-factor
                </Button>
              )}
            </div>
          </div>
        )}
        {(done || (!setup && !busy)) && (
          <Button size="sm" variant="outline" className="mt-3" onClick={close}>
            Close
          </Button>
        )}
      </PopoverContent>
    </Popover>
  )
}
