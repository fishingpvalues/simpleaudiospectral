"""Two-factor authentication for browser logins: RFC 6238 TOTP.

The *arr apps use exactly this shape: an API key keeps scripts and
integrations working without a second factor, while a browser login asks
for the key and a six-digit code from an authenticator app. The secret is
base32 in ``config.TOTP_FILE`` (mode 0600, written atomically); until a
secret is enrolled, login is key-only. Implemented on the standard
library: HMAC-SHA1 is what every authenticator app computes anyway, so
there is nothing to keep up to date.
"""

import base64
import contextlib
import hashlib
import hmac
import os
import re
import secrets
import struct
import time
import urllib.parse

from .. import config

PERIOD = 30
DIGITS = 6
# A phone and a server a few seconds apart must not lock each other out:
# the previous, the current and the next step are all accepted.
WINDOW = (-1, 0, 1)
_CODE = re.compile(r"^[0-9]{6}$")


def _digest(secret: bytes, step: int) -> bytes:
    return hmac.new(secret, struct.pack(">Q", step), hashlib.sha1).digest()


def code_at(secret: str, step: int) -> str:
    d = _digest(base64.b32decode(secret), step)
    o = d[-1] & 0x0F
    return f"{(struct.unpack('>I', d[o : o + 4])[0] & 0x7FFFFFFF) % 10**DIGITS:0{DIGITS}d}"


def step_at(now: float | None = None) -> int:
    return int((now or time.time()) // PERIOD)


def valid(secret: str, code: str, now: float | None = None) -> bool:
    """True when `code` is one of the codes the app accepts right now.
    Constant-time; a non-six-digit string is simply wrong."""
    if not _CODE.match(code or ""):
        return False
    s = step_at(now)
    return any(hmac.compare_digest(code, code_at(secret, s + d)) for d in WINDOW)


def new_secret() -> str:
    """160 bits, the length every authenticator app asks for."""
    return base64.b32encode(secrets.token_bytes(20)).decode()


def uri(secret: str, account: str) -> str:
    """The ``otpauth://`` link a QR code or an app's manual entry encodes."""
    return (
        f"otpauth://totp/simpleaudiospectral:{urllib.parse.quote(account)}"
        f"?secret={secret}&issuer=simpleaudiospectral"
        f"&algorithm=SHA1&digits={DIGITS}&period={PERIOD}"
    )


def _wellformed(secret: str) -> bool:
    try:
        return len(base64.b32decode(secret, casefold=True)) >= 16
    except (ValueError, TypeError):
        return False


def load() -> str | None:
    """The enrolled secret, or None when two-factor is not set up (or the
    file is corrupt, which is treated as not set up: the app still starts)."""
    try:
        with open(config.TOTP_FILE) as f:
            secret = f.read().strip()
    except OSError:
        return None
    return secret if _wellformed(secret) else None


def save(secret: str) -> None:
    """Atomically replace the secret with a 0600 file, so a crash never
    leaves a half-written or world-readable one."""
    tmp = config.TOTP_FILE + ".tmp"
    with open(tmp, "w") as f:
        f.write(secret + "\n")
    os.chmod(tmp, 0o600)
    os.replace(tmp, config.TOTP_FILE)


def revoke() -> None:
    with contextlib.suppress(FileNotFoundError):
        os.unlink(config.TOTP_FILE)
