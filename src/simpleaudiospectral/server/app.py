"""The HTTP server process."""

import os
import sys
import threading
from http.server import ThreadingHTTPServer

from .. import config
from ..library import INDEX
from .handler import Handler


class Server(ThreadingHTTPServer):
    """At most MAX_CONNECTIONS handler threads; further connections are closed
    at once instead of each getting a thread."""

    daemon_threads = True

    def __init__(self, addr, handler=Handler, max_connections: int | None = None) -> None:
        self.slots = threading.BoundedSemaphore(max_connections or config.MAX_CONNECTIONS)
        super().__init__(addr, handler)

    def process_request(self, request, client_address) -> None:
        if not self.slots.acquire(blocking=False):
            self.shutdown_request(request)
            return
        try:
            super().process_request(request, client_address)
        except Exception:
            self.slots.release()
            raise

    def process_request_thread(self, request, client_address) -> None:
        try:
            super().process_request_thread(request, client_address)
        finally:
            self.slots.release()


def startup_guard() -> None:
    """Misconfigurations the process refuses to start with; called by main()."""
    if config.API_KEY and len(config.API_KEY) < 16:
        sys.exit("API_KEY is too short: use at least 16 random characters (openssl rand -hex 32)")
    if config.TRUSTED_PROXIES and not config.API_KEY:
        # Trusting a proxy's X-Forwarded-For without a key is a misconfiguration:
        # the app is meant to sit behind something, but nothing checks anything.
        sys.exit("TRUSTED_PROXIES is set without API_KEY: set the key, or remove the proxy")


def main() -> None:
    startup_guard()
    os.makedirs(config.CACHE, exist_ok=True)
    INDEX.start()
    # All interfaces inside the container only; compose publishes it on loopback.
    srv = Server(("0.0.0.0", config.PORT))  # noqa: S104
    print(f"simpleaudiospectral on :{config.PORT}, library {config.ROOT}, ui {config.WEB}", flush=True)
    if not config.API_KEY:
        print(
            "API_KEY unset: no authentication - keep the port on loopback or behind an "
            "authenticating proxy, and set the key before exposing it (LAN, tailnet, internet)",
            flush=True,
        )
    elif len(config.API_KEY) < 32:
        print("warning: API_KEY is short; use 32+ random characters (openssl rand -hex 32)", flush=True)
    if config.TOTP_FILE and os.path.exists(config.TOTP_FILE):
        print("two-factor is enrolled: browser logins need the authenticator code", flush=True)
    if config.TRUSTED_PROXIES:
        print(f"trusting X-Forwarded-For from {', '.join(map(str, config.TRUSTED_PROXIES))}", flush=True)
    srv.serve_forever()
