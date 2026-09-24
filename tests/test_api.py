"""End-to-end over HTTP against a temp library of ffmpeg-generated files."""

import importlib
import json
import os
import subprocess
import sys
import threading
import urllib.error
import urllib.request

import numpy as np
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


def ff(*args):
    subprocess.run(["ffmpeg", "-v", "error", "-y", *args], check=True)


@pytest.fixture(scope="module")
def server(tmp_path_factory):
    lib = tmp_path_factory.mktemp("library")
    album = lib / "Artist" / "Album"
    album.mkdir(parents=True)
    src = "anoisesrc=d=12:c=pink:a=0.3,aformat=channel_layouts=stereo"
    ff("-f", "lavfi", "-i", src, "-sample_fmt", "s16", str(album / "01 real.flac"))
    ff("-f", "lavfi", "-i", src, "-c:a", "libmp3lame", "-b:a", "128k", str(lib / "tmp.mp3"))
    ff("-i", str(lib / "tmp.mp3"), "-sample_fmt", "s16", str(album / "02 transcode.flac"))
    ff(
        "-i",
        str(album / "01 real.flac"),
        "-sample_fmt",
        "s32",
        "-bits_per_raw_sample",
        "24",
        str(lib / "padded24.flac"),
    )
    (lib / "tmp.mp3").unlink()
    os.environ["LIBRARY_ROOT"] = str(lib)
    os.environ["CACHE_DIR"] = str(tmp_path_factory.mktemp("cache"))
    os.environ["WEB_DIR"] = str(tmp_path_factory.mktemp("web"))
    (tmp_path_factory.getbasetemp() / "web0" / "index.html").write_text("<!doctype html><title>t</title>")
    import app as mod

    mod = importlib.reload(mod)
    srv = mod.Server(("127.0.0.1", 0), mod.Handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{srv.server_address[1]}"
    srv.shutdown()


def get(base, path, headers=None):
    req = urllib.request.Request(base + path, headers=headers or {})
    try:
        with urllib.request.urlopen(req, timeout=120) as r:
            return r.status, dict(r.headers), r.read()
    except urllib.error.HTTPError as e:
        return e.code, dict(e.headers), e.read()


def jget(base, path):
    """GET JSON, polling while the server answers 202 (analysis running)."""
    import time

    for _ in range(600):
        code, _, body = get(base, path)
        if code != 202:
            return code, json.loads(body)
        time.sleep(0.1)
    raise AssertionError("analysis never finished")


def test_info_is_202_then_200(server):
    code, _, body = get(server, "/api/info?path=Artist/Album/02%20transcode.flac")
    assert code in (200, 202)
    if code == 202:
        assert json.loads(body)["pending"] is True
    code, d = jget(server, "/api/info?path=Artist/Album/02%20transcode.flac")
    assert code == 200 and d["analysis"]["level"] == "bad"


def test_ls(server):
    code, d = jget(server, "/api/ls?path=Artist/Album")
    assert code == 200 and [f["name"] for f in d["files"]] == ["01 real.flac", "02 transcode.flac"]
    assert d["files"][0]["size"] > 0


def test_roots_and_search(server, monkeypatch):
    import app

    app.INDEX._build()
    code, r = jget(server, "/api/roots")
    assert code == 200 and [x["name"] for x in r["roots"]] == ["Artist"]
    code, r = jget(server, "/api/search?q=album%20transcode")
    assert r["ready"] and [x["path"] for x in r["results"]] == ["Artist/Album/02 transcode.flac"]
    code, r = jget(server, "/api/search?q=album")
    assert r["results"][0] == {"path": "Artist/Album", "name": "Album", "dir": "Artist", "isDir": True}


def test_traversal_blocked(server):
    for p in (
        "/api/ls?path=../..",
        "/api/info?path=../../../etc/passwd",
        "/api/audio?path=%2e%2e/%2e%2e/etc/passwd",
    ):
        assert get(server, p)[0] == 403


def test_info_verdicts(server):
    _, real = jget(server, "/api/info?path=Artist/Album/01%20real.flac")
    _, fake = jget(server, "/api/info?path=Artist/Album/02%20transcode.flac")
    assert real["analysis"]["level"] == "ok"
    assert fake["analysis"]["level"] == "bad" and 15500 < fake["analysis"]["cutoffHz"] < 17100


def test_stats_padded_24bit(server):
    code, st = jget(server, "/api/stats?path=padded24.flac")
    assert code == 200
    assert st["bitUsage"]["bits"] == 24 and st["bitUsage"]["unusedLowBits"] == 8
    assert st["loudness"]["lufs"] is not None and st["dynamics"]["dr"] >= 0


def test_scan_streams_every_track(server):
    code, _h, body = get(server, "/api/scan?path=Artist/Album")
    lines = [json.loads(x) for x in body.decode().splitlines() if x.strip()]
    assert code == 200 and lines[0] == {"total": 2}
    rows = {r["name"]: r for r in lines[1:]}
    assert rows["01 real.flac"]["level"] == "ok"
    assert rows["02 transcode.flac"]["level"] == "bad"


def test_stft_binary(server):
    code, h, body = get(server, "/api/stft?path=Artist/Album/01%20real.flac&cols=300&rows=200&fft=2048")
    meta = json.loads(h["X-Meta"])
    assert code == 200 and len(body) == meta["cols"] * meta["rows"] == 300 * 200


def test_gonio(server):
    code, h, body = get(server, "/api/gonio?path=Artist/Album/01%20real.flac&size=64")
    assert code == 200 and len(body) == 64 * 64
    assert -1 <= json.loads(h["X-Meta"])["correlation"] <= 1


def test_audio_range(server):
    code, h, body = get(server, "/api/audio?path=Artist/Album/01%20real.flac", {"Range": "bytes=0-99"})
    assert code == 206 and len(body) == 100 and h["Content-Range"].startswith("bytes 0-99/")
    assert get(server, "/api/audio?path=Artist/Album/01%20real.flac", {"Range": "bytes=999999999-"})[0] == 416


def test_sox_png(server):
    code, _h, body = get(server, "/api/spectrogram?path=Artist/Album/01%20real.flac&x=600")
    assert code == 200 and body[:8] == b"\x89PNG\r\n\x1a\n"


def test_spa_fallback_and_404(server):
    assert get(server, "/some/client/route")[0] == 200
    assert get(server, "/api/nope")[0] == 404


def test_audio_transcode_stream(server):
    code, _h, body = get(server, "/api/audio?path=Artist/Album/01%20real.flac&format=flac")
    assert code == 200 and body[:4] == b"fLaC"


def test_health_reports_version(server):
    code, d = jget(server, "/api/health")
    assert code == 200 and d["status"] == "ok" and d["version"]


def test_pcm_is_disk_backed_memmap(server):
    import app

    mm, sr = app.PCM.open(os.path.join(app.ROOT, "Artist/Album/01 real.flac"))
    assert isinstance(mm, np.memmap) and mm.shape[1] == 2 and sr == 48000


def post(base, path, body, ctype="application/json"):
    req = urllib.request.Request(base + path, data=body, headers={"Content-Type": ctype}, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return r.status, dict(r.headers), r.read()
    except urllib.error.HTTPError as e:
        return e.code, dict(e.headers), e.read()


@pytest.fixture
def api_key(server, monkeypatch):
    import app

    monkeypatch.setattr(app, "API_KEY", "s3cret-key-for-tests-0123456789")  # gitleaks:allow
    monkeypatch.setattr(app, "LOCKOUT", app.Lockout())
    return app.API_KEY


def test_auth_off_by_default(server):
    _code, d = jget(server, "/api/health")
    assert d["auth"] is False and d["authenticated"] is True
    assert get(server, "/api/ls?path=")[0] == 200


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
    assert json.loads(body) == {"status": "ok", "auth": True, "authenticated": False}
    _code, _h, body = get(server, "/api/health", {"X-API-Key": api_key})
    d = json.loads(body)
    assert d["authenticated"] is True and d["version"]


def test_login_cookie_session(server, api_key):
    assert post(server, "/api/login", json.dumps({"key": "nope"}).encode())[0] == 401
    assert post(server, "/api/login", json.dumps({"key": api_key}).encode(), "text/plain")[0] == 400
    assert post(server, "/api/login", b"[1]")[0] == 401
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
    import app

    old = app.new_session(now=1000)  # expired long ago, correctly signed
    assert not app.session_valid(old)
    live = app.new_session()
    assert app.session_valid(live)
    monkeypatch.setattr(app, "API_KEY", "a-rotated-key-0123456789abcdef")  # gitleaks:allow
    assert not app.session_valid(live)


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
    import ipaddress

    import app

    # Untrusted peer: a forged X-Forwarded-For does not dodge the lockout.
    for i in range(5):
        get(server, "/api/ls?path=", {"X-API-Key": "wrong", "X-Forwarded-For": f"203.0.113.{i}"})
    assert get(server, "/api/ls?path=", {"X-API-Key": api_key, "X-Forwarded-For": "198.51.100.9"})[0] == 429
    # Trusted proxy: clients are told apart by the hop it appends.
    monkeypatch.setattr(app, "LOCKOUT", app.Lockout())
    monkeypatch.setattr(app, "TRUSTED_PROXIES", [ipaddress.ip_network("127.0.0.0/8")])
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


def test_errors_hide_host_paths(server):
    import app

    assert app.ROOT not in app.public_error(RuntimeError(f"decode failed: {app.ROOT}/x.flac: bad"))


def test_ffmpeg_refuses_network_and_other_files(server):
    """A library file that is really a playlist must not reach out."""
    import app

    evil = os.path.join(app.ROOT, "evil.mp3")
    with open(evil, "w") as f:
        f.write("#EXTM3U\n#EXTINF:5,\nhttp://127.0.0.1:9/x.ts\n#EXT-X-ENDLIST\n")
    try:
        p = subprocess.run(
            ["ffmpeg", "-v", "error", *app.NO_NET, "-f", "hls", "-i", evil, "-f", "null", "-"],
            capture_output=True,
            timeout=30,
            check=False,
        )
        assert p.returncode != 0 and b"not on whitelist" in p.stderr
    finally:
        os.unlink(evil)
