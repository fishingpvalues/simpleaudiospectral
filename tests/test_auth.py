"""API key, sessions, lockout and HTTP hardening, over HTTP."""

import base64
import ipaddress
import json
import os
import subprocess
import urllib.error
import urllib.request

import pytest

from helpers import get, jget, post
from simpleaudiospectral import config, tools
from simpleaudiospectral.server import auth
from simpleaudiospectral.server.errors import public_error


@pytest.fixture
def api_key(server, monkeypatch):
    monkeypatch.setattr(config, "API_KEY", "s3cret-key-for-tests-0123456789")  # gitleaks:allow
    monkeypatch.setattr(auth, "LOCKOUT", auth.Lockout())
    return config.API_KEY


def test_auth_off_by_default(server):
    _code, d = jget(server, "/api/health")
    assert d["auth"] is False and d["authenticated"] is True
    assert get(server, "/api/ls?path=")[0] == 200


def test_startup_refuses_proxy_trust_without_key(monkeypatch):
    from simpleaudiospectral.server import app

    # Trusting a proxy's X-Forwarded-For without a key is a misconfiguration;
    # the process must refuse to start rather than serve unauthenticated.
    monkeypatch.setattr(config, "API_KEY", "")
    monkeypatch.setattr(config, "TRUSTED_PROXIES", [ipaddress.ip_network("172.18.0.0/16")])
    with pytest.raises(SystemExit) as e:
        app.startup_guard()
    assert "TRUSTED_PROXIES" in str(e.value)
    # And a short key still refuses to start.
    monkeypatch.setattr(config, "API_KEY", "short")
    with pytest.raises(SystemExit):
        app.startup_guard()
    # A proper key passes the guard.
    monkeypatch.setattr(config, "API_KEY", "a-key-long-enough-0123456789")
    app.startup_guard()


def test_auth_required_with_api_key(server, api_key):
    code, h, _ = get(server, "/api/ls?path=")
    assert code == 401 and h["WWW-Authenticate"].startswith("Bearer")
    assert get(server, "/api/ls?path=", {"Authorization": "Bearer wrong"})[0] == 401
    assert get(server, "/api/ls?path=", {"Authorization": f"Bearer {api_key}"})[0] == 200
    assert get(server, "/api/ls?path=", {"X-API-Key": api_key})[0] == 200
    # never from the query string, which lands in access logs
    assert get(server, f"/api/ls?path=&apikey={api_key}&api_key={api_key}")[0] == 401
    # the UI bundle and the SPA fallback stay public
    assert get(server, "/")[0] == 200


def test_health_signed_out_reveals_nothing(server, api_key):
    _code, _h, body = get(server, "/api/health")
    # The two-factor flag is visible signed out: the login form has to draw
    # the code field. Nothing else about the state is.
    assert json.loads(body) == {"status": "ok", "auth": True, "authenticated": False, "twofa": False}
    _code, _h, body = get(server, "/api/health", {"X-API-Key": api_key})
    d = json.loads(body)
    assert d["authenticated"] is True and d["version"]


def test_login_cookie_session(server, api_key):
    assert post(server, "/api/login", json.dumps({"key": "nope"}).encode())[0] == 401
    assert post(server, "/api/login", json.dumps({"key": api_key}).encode(), "text/plain")[0] == 400
    assert post(server, "/api/login", b"[1]")[0] == 400  # not a JSON object
    code, h, _ = post(server, "/api/login", json.dumps({"key": api_key}).encode())
    cookie = h["Set-Cookie"]
    assert code == 200 and "HttpOnly" in cookie and "SameSite=Strict" in cookie
    assert "Secure" not in cookie  # plain HTTP here; Secure behind an HTTPS proxy
    assert api_key not in cookie  # signed with the key, not the key
    session = cookie.split(";")[0]
    assert get(server, "/api/ls?path=", {"Cookie": session})[0] == 200
    assert get(server, "/api/ls?path=", {"Cookie": "sas_session=9999999999.forged"})[0] == 401
    _code, _h, body = get(server, "/api/health", {"Cookie": session})
    assert json.loads(body)["authenticated"] is True
    code, h, _ = post(server, "/api/logout", b"")
    assert code == 200 and "Max-Age=0" in h["Set-Cookie"]


def test_session_expires_and_dies_with_key(server, api_key, monkeypatch):
    old = auth.new_session(now=1000)  # expired long ago, correctly signed
    assert not auth.session_valid(old)
    live = auth.new_session()
    assert auth.session_valid(live)
    monkeypatch.setattr(config, "API_KEY", "a-rotated-key-0123456789abcdef")  # gitleaks:allow
    assert not auth.session_valid(live)


def test_cross_site_post_refused(server, api_key):
    req = urllib.request.Request(
        server + "/api/login",
        data=json.dumps({"key": api_key}).encode(),
        headers={"Content-Type": "application/json", "Sec-Fetch-Site": "cross-site"},
        method="POST",
    )
    with pytest.raises(urllib.error.HTTPError) as e:
        urllib.request.urlopen(req, timeout=30)
    assert e.value.code == 403


def test_lockout_after_repeated_wrong_keys(server, api_key):
    for _ in range(5):
        assert get(server, "/api/ls?path=", {"X-API-Key": "wrong"})[0] == 401
    code, h, _ = get(server, "/api/ls?path=", {"X-API-Key": api_key})
    assert code == 429 and int(h["Retry-After"]) > 0  # even the right key waits
    assert post(server, "/api/login", json.dumps({"key": api_key}).encode())[0] == 429


def test_session_survives_lockout(server, api_key):
    _c, h, _ = post(server, "/api/login", json.dumps({"key": api_key}).encode())
    session = h["Set-Cookie"].split(";")[0]
    for _ in range(6):
        get(server, "/api/ls?path=", {"X-API-Key": "wrong"})
    assert get(server, "/api/ls?path=", {"Cookie": session})[0] == 200


def test_forwarded_for_only_from_trusted_proxy(server, api_key, monkeypatch):
    # Untrusted peer: a forged X-Forwarded-For does not dodge the lockout.
    for i in range(5):
        get(server, "/api/ls?path=", {"X-API-Key": "wrong", "X-Forwarded-For": f"203.0.113.{i}"})
    assert get(server, "/api/ls?path=", {"X-API-Key": api_key, "X-Forwarded-For": "198.51.100.9"})[0] == 429
    # Trusted proxy: clients are told apart by the hop it appends.
    monkeypatch.setattr(auth, "LOCKOUT", auth.Lockout())
    monkeypatch.setattr(config, "TRUSTED_PROXIES", [ipaddress.ip_network("127.0.0.0/8")])
    for _ in range(5):
        get(server, "/api/ls?path=", {"X-API-Key": "wrong", "X-Forwarded-For": "1.2.3.4, 203.0.113.7"})
    assert get(server, "/api/ls?path=", {"X-API-Key": api_key, "X-Forwarded-For": "203.0.113.7"})[0] == 429
    assert get(server, "/api/ls?path=", {"X-API-Key": api_key, "X-Forwarded-For": "203.0.113.8"})[0] == 200


def test_security_headers_everywhere(server):
    for path in ("/", "/api/health", "/api/nope"):
        _c, h, _ = get(server, path)
        assert h["X-Frame-Options"] == "DENY" and h["X-Content-Type-Options"] == "nosniff"
        assert "frame-ancestors 'none'" in h["Content-Security-Policy"]
        assert h["Referrer-Policy"] == "no-referrer"
        assert "Python" not in h["Server"]
    _c, h, _ = get(server, "/api/health", {"X-Forwarded-Proto": "https"})
    assert h["Strict-Transport-Security"].startswith("max-age=")


def test_errors_hide_host_paths(server, api_key):
    assert config.ROOT not in public_error(RuntimeError(f"decode failed: {config.ROOT}/x.flac: bad"))


# ------------------------------------------------------------ two-factor


@pytest.fixture
def twofa_secret(monkeypatch, api_key):
    from pathlib import Path

    from simpleaudiospectral.server import totp

    secret = base64.b32encode(b"testsecret1234567890test").decode()
    monkeypatch.setattr(config, "TOTP_FILE", str(Path(config.PCM_DIR) / ".totp-test"))
    totp.save(secret)
    yield secret
    totp.revoke()


def _code(secret, step=None):
    from simpleaudiospectral.server import totp

    return totp.code_at(secret, totp.step_at() if step is None else step)


def test_twofa_flow(server, twofa_secret):
    from simpleaudiospectral.server import totp

    # Without the code, a right key is refused for a new session.
    assert post(server, "/api/login", json.dumps({"key": API_KEY(), "code": ""}).encode())[0] == 401
    # A wrong code is refused too, without feeding the key lockout: five
    # wrong codes leave the correct key + code working.
    for _ in range(5):
        post(server, "/api/login", json.dumps({"key": API_KEY(), "code": "000000"}).encode())
    code, h, _ = post(
        server, "/api/login", json.dumps({"key": API_KEY(), "code": _code(twofa_secret)}).encode()
    )
    assert code == 200 and h["Set-Cookie"]
    session = h["Set-Cookie"].split(";")[0]
    assert get(server, "/api/ls?path=", {"Cookie": session})[0] == 200
    # The API key alone still opens API routes - like the *arr apps, the
    # second factor only gates the browser session.
    assert get(server, "/api/ls?path=", {"X-API-Key": API_KEY()})[0] == 200
    # Health now says a code is part of a login.
    assert json.loads(get(server, "/api/health")[2])["twofa"] is True
    # A valid session re-login needs no code (the browser already proved it).
    assert (
        post(
            server,
            "/api/login",
            json.dumps({"key": API_KEY()}).encode(),
            "application/json",
            {"Cookie": session},
        )[0]
        == 200
    )
    # Remove needs a live code.
    assert (
        post(
            server,
            "/api/twofa/remove",
            json.dumps({"code": _code(twofa_secret)}).encode(),
            "application/json",
            {"X-API-Key": API_KEY(), "Cookie": session},
        )[0]
        == 200
    )
    assert totp.load() is None
    assert json.loads(get(server, "/api/health")[2])["twofa"] is False


def test_twofa_setup_requires_auth(server, api_key):
    assert post(server, "/api/twofa/setup", b"")[0] == 401
    assert get(server, "/api/twofa/setup", {"X-API-Key": api_key})[0] == 404  # POST-only route


def test_twofa_verify_rejects_other_secret(server, api_key, twofa_secret):
    from simpleaudiospectral.server import totp

    other = base64.b32encode(b"anothersecret0123456789").decode()
    # A code valid for one secret is not valid for another: the enrolled
    # secret is unchanged.
    r = post(
        server,
        "/api/twofa/verify",
        json.dumps({"secret": other, "code": _code(twofa_secret)}).encode(),
        "application/json",
        {"X-API-Key": api_key},
    )
    assert r[0] == 401
    assert totp.load() == twofa_secret


def test_logout_revokes_the_session(server, api_key, twofa_secret):
    code, h, _ = post(
        server, "/api/login", json.dumps({"key": api_key, "code": _code(twofa_secret)}).encode()
    )
    session = h["Set-Cookie"].split(";")[0]
    assert get(server, "/api/ls?path=", {"Cookie": session})[0] == 200
    assert post(server, "/api/logout", b"", "application/json", {"Cookie": session})[0] == 200
    # The same cookie, replayed from a captured response, is dead.
    assert get(server, "/api/ls?path=", {"Cookie": session})[0] == 401
    # A fresh login still works.
    code, _, _ = post(
        server, "/api/login", json.dumps({"key": api_key, "code": _code(twofa_secret)}).encode()
    )
    assert code == 200


# ------------------------------------------------------------ range


def test_malformed_range_is_not_a_crash(server):
    for bad in ("bytes=abc-", "bytes=10-20-30", "bytes=-5-"):
        code, _, _ = get(server, "/api/audio?path=Artist/Album/01%20real.flac", {"Range": bad})
        assert code == 416, (bad, code)  # unsatisfiable, not a 500


def API_KEY() -> str:
    return config.API_KEY


def test_ffmpeg_refuses_network_and_other_files(server):
    """A library file that is really a playlist must not reach out."""
    evil = os.path.join(config.ROOT, "evil.mp3")
    with open(evil, "w") as f:
        f.write("#EXTM3U\n#EXTINF:5,\nhttp://127.0.0.1:9/x.ts\n#EXT-X-ENDLIST\n")
    try:
        p = subprocess.run(
            ["ffmpeg", "-v", "error", *tools.NO_NET, "-f", "hls", "-i", evil, "-f", "null", "-"],
            capture_output=True,
            timeout=30,
            check=False,
        )
        assert p.returncode != 0 and b"not on whitelist" in p.stderr
    finally:
        os.unlink(evil)
