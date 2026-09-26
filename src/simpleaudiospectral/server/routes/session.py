"""Health, login, logout and two-factor setup: the only routes that work
without a valid session or key.

Login mirrors the *arr apps: the API key proves who you are, and when
two-factor is enrolled a six-digit code from an authenticator app proves the
request comes from a person at a keyboard, not from a key that leaked into a
log. The key alone still opens every API route, exactly like Prowlarr and
Sonarr; the second factor only gates the browser session.
"""

from __future__ import annotations

import contextlib
import http.cookies
import json
from typing import TYPE_CHECKING

from ... import config
from ...library import INDEX
from .. import auth, totp

if TYPE_CHECKING:
    from ..handler import Handler, Query


def health(h: Handler, q: Query) -> None:
    # Signed out, only what the login screen needs: no version to match
    # against advisories, no library state. Whether a two-factor code is part
    # of a login is not a secret - the form has to draw the field.
    body = {"status": "ok", "auth": bool(config.API_KEY), "twofa": totp.load() is not None}
    if h.auth_state() == "ok":
        body |= {"version": config.VERSION, "indexed": INDEX.ready, "authenticated": True}
    else:
        body["authenticated"] = False
    h.send(200, body, headers={"Cache-Control": "no-store"})


def _cookie_of(h: Handler) -> str | None:
    """The value of a valid session cookie of this request, if any."""
    jar = http.cookies.SimpleCookie()
    with contextlib.suppress(http.cookies.CookieError):
        jar.load(h.headers.get("Cookie") or "")
    m = jar.get(config.SESSION_COOKIE)
    return m.value if m and auth.session_valid(m.value) else None


def _json(h: Handler) -> dict:
    """The JSON request body; login and the two-factor routes only."""
    if "application/json" not in (h.headers.get("Content-Type") or ""):
        raise ValueError("expected application/json")
    n = int(h.headers.get("Content-Length") or 0)
    if not 0 < n <= 4096:
        raise ValueError("bad request body")
    body = json.loads(h.rfile.read(n))
    if not isinstance(body, dict):
        raise ValueError("expected a JSON object")
    return body


def login(h: Handler, q: Query) -> None:
    """POST {"key": ..., "code": ...}: sets the session cookie the UI and
    media elements use. The code is required only when two-factor is
    enrolled and the request carries no valid session yet."""
    if not config.API_KEY:
        return h.send(200, {"ok": True, "auth": False})
    body = _json(h)
    key = body.get("key")
    state = h.check_key(key) if isinstance(key, str) and key else "wrong"
    if state != "ok":
        return h.deny(state)
    secret = totp.load()
    if secret and not _cookie_of(h):
        code = body.get("code")
        if not totp.valid(secret, code if isinstance(code, str) else ""):
            # The key was right, so this is not a key failure: do not feed the
            # lockout, and say the code - not the key - was wrong.
            headers = {
                "Cache-Control": "no-store",
                "WWW-Authenticate": 'Bearer realm="simpleaudiospectral"',
            }
            return h.send(401, {"error": "wrong two-factor code"}, headers=headers)
    cookie = h.session_cookie(auth.new_session(), config.SESSION_MAX_AGE)
    return h.send(
        200,
        {"ok": True, "auth": True, "twofa": secret is not None},
        headers={"Set-Cookie": cookie, "Cache-Control": "no-store"},
    )


def logout(h: Handler, q: Query) -> None:
    """Ends this browser's session; the cookie is also remembered until its
    expiry, so it cannot be replayed from a captured response."""
    value = _cookie_of(h)
    if value:
        with contextlib.suppress(ValueError):
            auth.REVOKED.add(value, int(value.split(".", 1)[0]))
    h.send(200, {"ok": True}, headers={"Set-Cookie": h.session_cookie("", 0)})


def twofa_setup(h: Handler, q: Query) -> None:
    """One-time: the secret to enroll in an authenticator app, shown once and
    returned with its otpauth link. It only becomes active at /verify."""
    secret = totp.new_secret()
    return h.send(
        200,
        {"secret": secret, "uri": totp.uri(secret, "simpleaudiospectral")},
        headers={"Cache-Control": "no-store"},
    )


def twofa_verify(h: Handler, q: Query) -> None:
    """POST {"secret": ..., "code": ...}: the code must be one the app
    generated from the freshly enrolled secret; only then is it saved."""
    body = _json(h)
    secret, code = body.get("secret"), body.get("code")
    if not isinstance(secret, str) or not isinstance(code, str):
        raise ValueError("secret and code are required")
    if not totp.valid(secret, code):
        return h.send(401, {"error": "wrong two-factor code"}, headers={"Cache-Control": "no-store"})
    totp.save(secret)
    return h.send(200, {"ok": True, "twofa": True}, headers={"Cache-Control": "no-store"})


def twofa_remove(h: Handler, q: Query) -> None:
    """Disarm two-factor; the current code proves a person, not a script, did it."""
    secret = totp.load()
    if secret is None:
        return h.send(404, {"error": "two-factor is not set up"}, headers={"Cache-Control": "no-store"})
    body = _json(h)
    code = body.get("code")
    if not totp.valid(secret, code if isinstance(code, str) else ""):
        return h.send(401, {"error": "wrong two-factor code"}, headers={"Cache-Control": "no-store"})
    totp.revoke()
    return h.send(200, {"ok": True, "twofa": False}, headers={"Cache-Control": "no-store"})
