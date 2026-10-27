"""Deterministic work limits for checking data-only submissions."""

from contextlib import contextmanager
from contextvars import ContextVar


WORK_LIMITS = {"matching_evaluations": 1_000_000, "push_transitions": 30_000_000}
PROCESS_LIMITS = {"memory_bytes": 2 * 1024**3, "cpu_seconds": 600, "wall_seconds": 900}
_active = ContextVar("sokogap_work_budget", default=None)


class Exhausted(RuntimeError):
    """Verification did not finish within the published resource allowance."""


def spend(kind: str, amount: int = 1):
    counts = _active.get()
    if counts is not None:
        counts[kind] = counts.get(kind, 0) + amount
        if counts[kind] > WORK_LIMITS[kind]:
            raise Exhausted(f"verification work limit exceeded: {kind}")


@contextmanager
def work_budget():
    counts = {}
    token = _active.set(counts)
    try:
        yield counts
    finally:
        _active.reset(token)
