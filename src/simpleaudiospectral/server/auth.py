"""API key, signed sessions, brute-force lockout, trusted proxies.

With API_KEY set, every /api/ route except health, login and logout needs the
key in a header ("Authorization: Bearer ..." or "X-API-Key"), or the session
cookie from POST /api/login, which browsers also send for <audio> and <img>.
The key is never read from the query string, which ends up in logs.
"""

import base64
import hashlib
import hmac
import ipaddress
import math
import threading
import time

from .. import config

PUBLIC_API = frozenset({"/api/health", "/api/login", "/api/logout"})


def _sign(msg: str) -> str:
    return hmac.new(
        config.API_KEY.encode(), b"simpleaudiospectral session v2|" + msg.encode(), hashlib.sha256
    ).hexdigest()


def new_session(now: float | None = None) -> str:
    """Cookie value "<expiry>.<hmac>": signed with the key, so the key itself
    never sits in the browser, the server enforces the expiry, and changing
    API_KEY ends every session."""
    exp = str(int((now or time.time()) + config.SESSION_MAX_AGE))
    return f"{exp}.{_sign(exp)}"


def session_valid(value: str | None) -> bool:
    value = value or ""
    exp, _, sig = value.partition(".")
    if not (exp.isascii() and exp.isdigit()) or int(exp) < time.time():
        return False
    if not hmac.compare_digest(sig.encode(), _sign(exp).encode()):
        return False
    return not REVOKED.is_revoked(value)


def key_matches(key: str | None) -> bool:
    return bool(key) and hmac.compare_digest(key.encode(), config.API_KEY.encode())


# A signed cookie cannot be recalled once it is out, so logout records a short
# fingerprint of the session in-process until its natural expiry. A key
# rotation still ends every session at once.
class Revoked:
    def __init__(self) -> None:
        self.ids: dict[str, float] = {}  # fingerprint -> expiry
        self.lock = threading.Lock()

    def add(self, value: str, expires: float) -> None:
        fp = base64.urlsafe_b64encode(hashlib.sha256(value.encode()).digest()[:12]).decode()
        with self.lock:
            self.ids[fp] = expires
            if len(self.ids) > 4096:  # drop the already-expired, keep the rest
                now = time.time()
                self.ids = {k: v for k, v in self.ids.items() if v > now}

    def is_revoked(self, value: str) -> bool:
        fp = base64.urlsafe_b64encode(hashlib.sha256(value.encode()).digest()[:12]).decode()
        now = time.time()
        with self.lock:
            exp = self.ids.get(fp)
            return exp is not None and exp > now


REVOKED = Revoked()


def is_trusted_proxy(ip: str) -> bool:
    try:
        a = ipaddress.ip_address(ip)
    except ValueError:
        return False
    return any(a in n for n in config.TRUSTED_PROXIES)


def client_ip(peer: str, forwarded_for: str | None) -> str:
    """The peer, or behind a trusted proxy the last X-Forwarded-For hop that is
    not a trusted proxy (the earlier hops are client-controlled)."""
    if not is_trusted_proxy(peer):
        return peer
    hops = [h.strip() for h in (forwarded_for or "").split(",") if h.strip()]
    for hop in reversed(hops):
        if not is_trusted_proxy(hop):
            return hop
    return peer


class Lockout:
    """Recent failed key checks per client. After LOCKOUT_FAILS failures within
    LOCKOUT_WINDOW seconds, key checks from that client are refused until the
    oldest failure ages out. An IPv6 /64 counts as one client. Nothing sleeps,
    so a flood of guesses holds no threads."""

    def __init__(self) -> None:
        self.fails: dict[str, list[float]] = {}
        self.lock = threading.Lock()

    @staticmethod
    def bucket(ip: str) -> str:
        try:
            a = ipaddress.ip_address(ip)
        except ValueError:
            return ip
        return str(ipaddress.ip_network(f"{a}/64", strict=False)) if a.version == 6 else str(a)

    def retry_after(self, ip: str) -> int:
        """Seconds until this client may try a key again (0 = now)."""
        now = time.time()
        with self.lock:
            ts = [t for t in self.fails.get(self.bucket(ip), ()) if t > now - config.LOCKOUT_WINDOW]
            if len(ts) < config.LOCKOUT_FAILS:
                return 0
            return math.ceil(ts[-config.LOCKOUT_FAILS] + config.LOCKOUT_WINDOW - now)

    def fail(self, ip: str) -> None:
        now = time.time()
        with self.lock:
            b = self.bucket(ip)
            ts = [t for t in self.fails.get(b, ()) if t > now - config.LOCKOUT_WINDOW][
                -config.LOCKOUT_FAILS :
            ]
            self.fails[b] = [*ts, now]
            if len(self.fails) > 10000:  # a spray from many addresses: drop the aged-out ones
                self.fails = {k: v for k, v in self.fails.items() if v[-1] > now - config.LOCKOUT_WINDOW}


LOCKOUT = Lockout()
