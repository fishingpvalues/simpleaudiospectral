"""HTTP helpers for the end-to-end tests."""

import json
import time
import urllib.error
import urllib.request


def get(base: str, path: str, headers: dict | None = None) -> tuple[int, dict, bytes]:
    req = urllib.request.Request(base + path, headers=headers or {})
    try:
        with urllib.request.urlopen(req, timeout=120) as r:
            return r.status, dict(r.headers), r.read()
    except urllib.error.HTTPError as e:
        return e.code, dict(e.headers), e.read()


def jget(base: str, path: str) -> tuple[int, dict]:
    """GET JSON, polling while the server answers 202 (analysis running)."""
    for _ in range(600):
        code, _, body = get(base, path)
        if code != 202:
            return code, json.loads(body)
        time.sleep(0.1)
    raise AssertionError("analysis never finished")


def post(base: str, path: str, body: bytes, ctype: str = "application/json", headers=None):
    req = urllib.request.Request(
        base + path, data=body, headers={"Content-Type": ctype, **(headers or {})}, method="POST"
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return r.status, dict(r.headers), r.read()
    except urllib.error.HTTPError as e:
        return e.code, dict(e.headers), e.read()
