"""The HTTP request handler: responses, security headers, the auth gate,
error mapping and dispatch to the route functions in server.routes."""

import contextlib
import gzip
import http.cookies
import json
import sys
import urllib.parse
from http.server import BaseHTTPRequestHandler

from .. import config
from . import auth
from .errors import public_error
from .routes import GET_ROUTES, POST_ROUTES, static

SECURITY_HEADERS = {
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "no-referrer",
    "Cross-Origin-Opener-Policy": "same-origin",
    "Cross-Origin-Resource-Policy": "same-origin",
    "Permissions-Policy": "camera=(), microphone=(), geolocation=(), payment=(), usb=()",
    # Radix injects <style> for scroll locking, hence style-src 'unsafe-inline';
    # scripts are only the bundle.
    "Content-Security-Policy": (
        "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; "
        "img-src 'self' data: blob:; media-src 'self' blob:; font-src 'self'; connect-src 'self'; "
        "object-src 'none'; base-uri 'none'; form-action 'self'; frame-ancestors 'none'"
    ),
}

Query = dict[str, str]


class Handler(BaseHTTPRequestHandler):
    server_version = "simpleaudiospectral"
    protocol_version = "HTTP/1.1"
    timeout = config.SOCKET_TIMEOUT

    # ------------------------------------------------------------ responses

    def version_string(self) -> str:
        return self.server_version  # no Python version in the Server header

    def end_headers(self) -> None:
        for k, v in SECURITY_HEADERS.items():
            self.send_header(k, v)
        if self.https():
            self.send_header("Strict-Transport-Security", "max-age=31536000")
        super().end_headers()

    def https(self) -> bool:
        """Behind a TLS-terminating *trusted* proxy that says so.

        The header drives the ``Secure`` cookie flag and HSTS, so it is only
        believed from a peer in ``TRUSTED_PROXIES`` - exactly as ``X-Forwarded-For``
        is. A direct (unproxied) client cannot make the server claim the
        connection was TLS by sending the header itself.
        """
        h = getattr(self, "headers", None)  # absent when the request line itself was bad
        return (
            bool(h)
            and h.get("X-Forwarded-Proto") == "https"
            and auth.is_trusted_proxy(self.client_address[0])
        )

    def log_message(self, format: str, *args) -> None:
        if config.ACCESS_LOG:
            sys.stderr.write(f"{self.address_string()} {format % args}\n")

    def send(self, code: int, body, ctype="application/json", headers=None, compress=False) -> None:
        """One complete response; dicts and lists are sent as JSON."""
        if isinstance(body, dict | list):
            body = json.dumps(body).encode()
        elif isinstance(body, str):
            body = body.encode()
        if compress and "gzip" in (self.headers.get("Accept-Encoding") or ""):
            body = gzip.compress(body, compresslevel=1)
            headers = dict(headers or {}, **{"Content-Encoding": "gzip"})
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        for k, v in (headers or {}).items():
            self.send_header(k, v)
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def start_chunked(self, ctype: str, headers=None) -> None:
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Transfer-Encoding", "chunked")
        for k, v in (headers or {}).items():
            self.send_header(k, v)
        self.end_headers()

    def write_chunk(self, data: bytes) -> None:
        self.wfile.write(b"%x\r\n%s\r\n" % (len(data), data))

    def end_chunked(self) -> None:
        self.wfile.write(b"0\r\n\r\n")

    # ------------------------------------------------------------ auth

    def client_ip(self) -> str:
        return auth.client_ip(self.client_address[0], self.headers.get("X-Forwarded-For"))

    def check_key(self, key: str) -> str:
        """ "ok", "wrong" or "locked" for a presented key, counting failures per client."""
        ip = self.client_ip()
        if auth.LOCKOUT.retry_after(ip):
            return "locked"
        if auth.key_matches(key):
            return "ok"
        auth.LOCKOUT.fail(ip)
        # One line per failure, with the client, for fail2ban or CrowdSec.
        sys.stderr.write(f"auth failure from {ip}: {self.command} {urllib.parse.urlparse(self.path).path}\n")
        return "wrong"

    def auth_state(self) -> str:
        """ "ok" without API_KEY or with a valid session cookie or key, else
        "missing", "wrong" or "locked"."""
        if not config.API_KEY:
            return "ok"
        jar = http.cookies.SimpleCookie()
        with contextlib.suppress(http.cookies.CookieError):
            jar.load(self.headers.get("Cookie") or "")
        m = jar.get(config.SESSION_COOKIE)
        if m and auth.session_valid(m.value):
            return "ok"  # a valid session works even while its address is locked out
        h = self.headers.get("Authorization") or ""
        key = h[7:].strip() if h[:7].lower() == "bearer " else self.headers.get("X-API-Key", "")
        return self.check_key(key) if key else "missing"

    def deny(self, state: str) -> None:
        if state == "locked":
            wait = auth.LOCKOUT.retry_after(self.client_ip())
            return self.send(
                429,
                {"error": "too many wrong keys, try again later"},
                headers={"Retry-After": str(max(1, wait)), "Cache-Control": "no-store"},
            )
        return self.send(
            401,
            {"error": "API key required" if state == "missing" else "wrong API key"},
            headers={"WWW-Authenticate": 'Bearer realm="simpleaudiospectral"', "Cache-Control": "no-store"},
        )

    def session_cookie(self, value: str, max_age: int) -> str:
        attrs = f"Max-Age={max_age}; Path=/api; HttpOnly; SameSite=Strict" + (
            "; Secure" if self.https() else ""
        )
        return f"{config.SESSION_COOKIE}={value}; {attrs}"

    # ------------------------------------------------------------ dispatch

    def do_HEAD(self) -> None:
        self.do_GET()

    def do_GET(self) -> None:
        u = urllib.parse.urlparse(self.path)
        q = {k: v[0] for k, v in urllib.parse.parse_qs(u.query).items()}
        with self.errors_as_responses():
            if u.path.startswith("/api/") and u.path not in auth.PUBLIC_API:
                state = self.auth_state()
                if state != "ok":
                    return self.deny(state)
            route = GET_ROUTES.get(u.path)
            if route:
                return route(self, q)
            if u.path.startswith("/api/"):
                return self.send(404, {"error": "not found"})
            return static(self, u.path)

    def do_POST(self) -> None:
        u = urllib.parse.urlparse(self.path)
        # Login and logout forgery: browsers mark requests from other sites;
        # only this origin (or a non-browser client) may post.
        if self.headers.get("Sec-Fetch-Site", "same-origin") not in ("same-origin", "none"):
            return self.send(403, {"error": "cross-site request"})
        with self.errors_as_responses():
            if u.path.startswith("/api/") and u.path not in auth.PUBLIC_API:
                state = self.auth_state()
                if state != "ok":
                    return self.deny(state)
            route = POST_ROUTES.get(u.path)
            if route:
                return route(self, {})
            return self.send(404, {"error": "not found"})

    @contextlib.contextmanager
    def errors_as_responses(self):
        """Map exceptions from a route to status codes."""
        try:
            yield
        except PermissionError:
            self.send(403, {"error": "outside library"})
        except FileNotFoundError:
            self.send(404, {"error": "no such file"})
        except (ValueError, KeyError) as e:
            self.send(400, {"error": str(e)})
        except (BrokenPipeError, ConnectionResetError, TimeoutError):
            pass  # the client went away
        except Exception as e:
            self.send(500, {"error": public_error(e)})
