"""Settings from the environment.

Every other module reads these as ``config.NAME`` at call time, never copies
them at import, so a test (or a reload after changing the environment) sees
the current value.
"""

import ipaddress
import os
import threading
from pathlib import Path

PACKAGE_DIR = Path(__file__).resolve().parent
REPO_DIR = PACKAGE_DIR.parent.parent

# Seconds for one external tool call; decodes and analyses get multiples of it.
TIMEOUT = 180
# Seconds a client may stall one read or write (slowloris).
SOCKET_TIMEOUT = 60
SESSION_COOKIE = "sas_session"
SESSION_MAX_AGE = 30 * 24 * 3600
# LOCKOUT_FAILS wrong keys from one client within LOCKOUT_WINDOW seconds lock
# that client's key checks until the oldest failure ages out.
LOCKOUT_FAILS = 5
LOCKOUT_WINDOW = 300
# A right key with a wrong two-factor code is not a key failure, so it does not
# feed the key lockout - but it must still be throttled per client, or a leaked
# key allows an unlimited online brute-force of the six-digit code.
CODE_LOCKOUT_FAILS = 5
CODE_LOCKOUT_WINDOW = 300


def _secret(name: str) -> str:
    """NAME, or the contents of the file named by NAME_FILE (Docker secrets),
    so the key need not sit in the environment or `docker inspect`."""
    path = os.environ.get(name + "_FILE")
    if path:
        return Path(path).read_text().strip()
    return os.environ.get(name, "")


def _version() -> str:
    """Image builds pass APP_VERSION; a checkout reads version.txt."""
    if os.environ.get("APP_VERSION"):
        return os.environ["APP_VERSION"]
    try:
        return (REPO_DIR / "version.txt").read_text().strip()
    except OSError:
        return "dev"


def _networks(spec: str) -> list[ipaddress.IPv4Network | ipaddress.IPv6Network]:
    return [ipaddress.ip_network(n.strip(), strict=False) for n in spec.split(",") if n.strip()]


def reload() -> None:
    """(Re)read every setting from the environment."""
    global ROOT, CACHE, PORT, WEB, PCM_DIR, PCM_DISK_BUDGET, INDEX_INTERVAL
    global API_KEY, TRUSTED_PROXIES, MAX_CONNECTIONS, ACCESS_LOG, VERSION, JOBS
    global TOTP_FILE, LOCKOUT_FAILS, LOCKOUT_WINDOW, CODE_LOCKOUT_FAILS, CODE_LOCKOUT_WINDOW

    ROOT = os.path.realpath(os.environ.get("LIBRARY_ROOT", "/library"))
    CACHE = os.environ.get("CACHE_DIR", "/cache")
    PORT = int(os.environ.get("PORT", "4748"))
    WEB = os.path.realpath(os.environ.get("WEB_DIR", str(REPO_DIR / "web" / "dist")))
    # Decoded audio lives on disk as memory-mapped float32, never in the heap:
    # a 3 h DJ set is 1.9 GB per channel, and holding one in RAM OOM-killed a
    # 1.5 GB container. Page cache of a memmap is reclaimable.
    PCM_DIR = os.environ.get("PCM_DIR", "/pcm")
    PCM_DISK_BUDGET = int(float(os.environ.get("PCM_DISK_GB", "20")) * 1024**3)
    INDEX_INTERVAL = int(os.environ.get("INDEX_INTERVAL", "900"))
    # Empty: no authentication (loopback, a VPN or an authenticating proxy in front).
    API_KEY = _secret("API_KEY")
    # Reverse proxies whose X-Forwarded-For is believed.
    TRUSTED_PROXIES = _networks(os.environ.get("TRUSTED_PROXIES", ""))
    # The two-factor secret lives next to the decoded-audio cache, where the
    # container already has one writable place; 0600, and it only matters
    # because API_KEY is needed first. Unset file: two-factor is not enrolled.
    TOTP_FILE = os.environ.get("TOTP_FILE") or os.path.join(PCM_DIR, ".totp")
    LOCKOUT_FAILS = int(os.environ.get("LOCKOUT_FAILS", "5"))
    LOCKOUT_WINDOW = int(os.environ.get("LOCKOUT_WINDOW", "300"))
    CODE_LOCKOUT_FAILS = int(os.environ.get("CODE_LOCKOUT_FAILS", "5"))
    CODE_LOCKOUT_WINDOW = int(os.environ.get("CODE_LOCKOUT_WINDOW", "300"))
    MAX_CONNECTIONS = int(os.environ.get("MAX_CONNECTIONS", "128"))
    ACCESS_LOG = bool(os.environ.get("ACCESS_LOG"))
    VERSION = _version()
    JOBS = threading.BoundedSemaphore(int(os.environ.get("MAX_JOBS", "3")))


ROOT: str
CACHE: str
PORT: int
WEB: str
PCM_DIR: str
PCM_DISK_BUDGET: int
INDEX_INTERVAL: int
API_KEY: str
TRUSTED_PROXIES: list[ipaddress.IPv4Network | ipaddress.IPv6Network]
TOTP_FILE: str
MAX_CONNECTIONS: int
ACCESS_LOG: bool
VERSION: str
JOBS: threading.BoundedSemaphore

reload()
