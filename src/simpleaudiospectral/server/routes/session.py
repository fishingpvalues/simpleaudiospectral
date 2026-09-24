"""Health, login and logout: the only routes that work without the key."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

from ... import config
from ...library import INDEX
from .. import auth

if TYPE_CHECKING:
    from ..handler import Handler, Query


def health(h: Handler, q: Query) -> None:
    # Signed out, only what the login screen needs: no version to match
    # against advisories, no library state.
    if h.auth_state() == "ok":
        body = {"status": "ok", "version": config.VERSION, "indexed": INDEX.ready}
        body |= {"auth": bool(config.API_KEY), "authenticated": True}
    else:
        body = {"status": "ok", "auth": True, "authenticated": False}
    h.send(200, body, headers={"Cache-Control": "no-store"})


def login(h: Handler, q: Query) -> None:
    """POST {"key": ...}: sets the session cookie the UI and media elements use."""
    if not config.API_KEY:
        return h.send(200, {"ok": True, "auth": False})
    if "application/json" not in (h.headers.get("Content-Type") or ""):
        raise ValueError("expected application/json")
    n = int(h.headers.get("Content-Length") or 0)
    if not 0 < n <= 4096:
        raise ValueError("bad request body")
    body = json.loads(h.rfile.read(n))
    key = body.get("key") if isinstance(body, dict) else None
    state = h.check_key(key) if isinstance(key, str) and key else "wrong"
    if state != "ok":
        return h.deny(state)
    cookie = h.session_cookie(auth.new_session(), config.SESSION_MAX_AGE)
    return h.send(
        200, {"ok": True, "auth": True}, headers={"Set-Cookie": cookie, "Cache-Control": "no-store"}
    )


def logout(h: Handler, q: Query) -> None:
    h.send(200, {"ok": True}, headers={"Set-Cookie": h.session_cookie("", 0)})
