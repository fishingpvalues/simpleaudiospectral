"""Query-string parameters, validated and clamped."""

from ...formats import CHANNELS


def num(q: dict[str, str], k: str, default, lo, hi, cast=float):
    """q[k] as `cast`, clamped to [lo, hi]; the default when missing or malformed."""
    try:
        v = cast(q.get(k, default))
    except (TypeError, ValueError):
        v = cast(default)
    return min(hi, max(lo, v))


def channel(q: dict[str, str]) -> str:
    ch = q.get("ch", "mix")
    return ch if ch in CHANNELS else "mix"


def time_range(q: dict[str, str], duration: float) -> tuple[float, float]:
    """(t0, t1) inside the file, at least 1 ms long."""
    t0 = num(q, "t0", 0, 0, duration)
    return t0, num(q, "t1", duration, t0 + 1e-3, duration)
