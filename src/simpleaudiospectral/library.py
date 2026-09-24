"""The music library: path confinement, listings and the search index.

Everything under LIBRARY_ROOT is read-only. Paths are resolved with
realpath and must stay inside the root, so a symbolic link cannot escape it.
"""

import os
import sys
import threading
import time

from . import config
from .formats import is_audio


def resolve(rel: str | None) -> str:
    """Absolute path of `rel` inside the library; PermissionError outside it."""
    rel = (rel or "").lstrip("/")
    full = os.path.realpath(os.path.join(config.ROOT, rel))
    if full != config.ROOT and not full.startswith(config.ROOT + os.sep):
        raise PermissionError(rel)
    return full


def resolve_file(rel: str | None) -> str:
    full = resolve(rel)
    if not os.path.isfile(full):
        raise FileNotFoundError(rel)
    return full


def resolve_dir(rel: str | None) -> str:
    full = resolve(rel)
    if not os.path.isdir(full):
        raise FileNotFoundError(rel)
    return full


def relative(full: str) -> str:
    return "" if full == config.ROOT else os.path.relpath(full, config.ROOT)


def list_dir(full: str) -> dict:
    """Folders and audio files of one directory, sorted by name."""
    dirs, files = [], []
    with os.scandir(full) as it:
        for e in it:
            if e.name.startswith("."):
                continue
            try:
                if e.is_dir():
                    dirs.append({"name": e.name, "mtime": int(e.stat().st_mtime)})
                elif is_audio(e.name):
                    st = e.stat()
                    files.append({"name": e.name, "size": st.st_size, "mtime": int(st.st_mtime)})
            except OSError:
                continue  # broken symlink, vanished file
    by_name = lambda x: x["name"].lower()
    return {"path": relative(full), "dirs": sorted(dirs, key=by_name), "files": sorted(files, key=by_name)}


def audio_files(full: str) -> list[str]:
    """Audio files directly in a folder (an album), sorted case-insensitively."""
    return sorted((e.path for e in os.scandir(full) if e.is_file() and is_audio(e.name)), key=str.lower)


def volumes() -> list[dict]:
    """Top-level folders of the library (normally one per mounted volume) with disk usage."""
    out = []
    with os.scandir(config.ROOT) as it:
        for e in sorted(it, key=lambda e: e.name.lower()):
            if e.name.startswith(".") or not e.is_dir():
                continue
            try:
                v = os.statvfs(e.path)
                out.append(
                    {"name": e.name, "total": v.f_blocks * v.f_frsize, "free": v.f_bavail * v.f_frsize}
                )
            except OSError:
                out.append({"name": e.name, "total": None, "free": None})
    return out


class LibraryIndex:
    """Every folder and audio file under the root, for instant search. Built in
    a background thread and refreshed periodically; a walk of a large library
    on spinning disks takes seconds, which is too slow per keystroke."""

    def __init__(self) -> None:
        self.entries: list[tuple[str, str, bool]] = []  # (lower-case rel path, rel path, is_dir)
        self.ready = False
        self.lock = threading.Lock()

    def start(self) -> None:
        threading.Thread(target=self._loop, daemon=True, name="index").start()

    def _loop(self) -> None:
        while True:
            try:
                self.build()
            except Exception as e:
                sys.stderr.write(f"index: {e}\n")
            time.sleep(config.INDEX_INTERVAL)

    def build(self) -> None:
        root = config.ROOT
        out: list[tuple[str, str, bool]] = []
        first = not self.ready
        for dirpath, dirnames, filenames in os.walk(root):
            if first and len(out) - len(self.entries) > 5000:
                with self.lock:  # first build: publish as we go, search works early
                    self.entries = list(out)
            dirnames[:] = sorted(d for d in dirnames if not d.startswith("."))
            rel = os.path.relpath(dirpath, root)
            rel = "" if rel == "." else rel
            for d in dirnames:
                r = os.path.join(rel, d) if rel else d
                out.append((r.lower(), r, True))
            for f in filenames:
                if is_audio(f):
                    r = os.path.join(rel, f) if rel else f
                    out.append((r.lower(), r, False))
        with self.lock:
            self.entries, self.ready = out, True

    def search(self, query: str, limit: int) -> list[dict]:
        terms = [t for t in query.lower().split() if t]
        if not terms:
            return []
        with self.lock:
            entries = self.entries
        hits = []
        for low, rel, is_dir in entries:
            if all(t in low for t in terms):
                # Rank: name matches first, folders before files, shorter paths first.
                name = low.rsplit("/", 1)[-1]
                score = (0 if all(t in name for t in terms) else 1, 0 if is_dir else 1, len(rel))
                hits.append((score, rel, is_dir))
                if len(hits) > limit * 20:
                    break
        hits.sort()
        return [
            {"path": r, "name": os.path.basename(r), "dir": os.path.dirname(r), "isDir": d}
            for _, r, d in hits[:limit]
        ]


INDEX = LibraryIndex()
