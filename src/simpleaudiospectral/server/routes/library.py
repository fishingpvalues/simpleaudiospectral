"""Browsing and searching the library."""

from __future__ import annotations

from typing import TYPE_CHECKING

from ... import library
from ...library import INDEX
from .params import num

if TYPE_CHECKING:
    from ..handler import Handler, Query


def ls(h: Handler, q: Query) -> None:
    h.send(200, library.list_dir(library.resolve_dir(q.get("path", ""))), compress=True)


def roots(h: Handler, q: Query) -> None:
    h.send(200, {"roots": library.volumes(), "indexed": INDEX.ready, "entries": len(INDEX.entries)})


def search(h: Handler, q: Query) -> None:
    limit = num(q, "limit", 100, 1, 500, int)
    h.send(200, {"ready": INDEX.ready, "results": INDEX.search(q.get("q", ""), limit)}, compress=True)
