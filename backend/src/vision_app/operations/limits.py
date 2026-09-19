"""Finite execution count, size, concurrency, and wall-clock limits."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable
from dataclasses import dataclass
from datetime import UTC, datetime


class LimitExceeded(RuntimeError):
    """A finite execution limit has been exhausted."""


class DeadlineExceeded(LimitExceeded):
    """The operation passed its absolute or relative deadline."""


@dataclass(frozen=True)
class ExecutionLimits:
    jobs: int = 1
    builds: int = 1
    frames: int = 10_000
    calls: int = 100
    output_bytes: int = 10_000_000
    concurrency: int = 4
    deadline: datetime | None = None

    def __post_init__(self) -> None:
        values = (
            self.jobs,
            self.builds,
            self.frames,
            self.calls,
            self.output_bytes,
            self.concurrency,
        )
        if any(value <= 0 for value in values):
            raise ValueError("all execution limits must be positive and finite")
        if self.deadline is not None and self.deadline.tzinfo is None:
            raise ValueError("deadline must be timezone-aware")


class _Permit:
    def __init__(self, guard: LimitGuard) -> None:
        self._guard = guard
        self._released = False

    def release(self) -> None:
        if not self._released:
            self._guard._active -= 1
            self._released = True

    def __enter__(self) -> _Permit:
        return self

    def __exit__(self, *_: object) -> None:
        self.release()


class LimitGuard:
    """Attempt-local deterministic enforcement; no sleeps or unbounded queues."""

    def __init__(self, limits: ExecutionLimits) -> None:
        self.limits = limits
        self._used = {"jobs": 0, "builds": 0, "frames": 0, "calls": 0, "output_bytes": 0}
        self._active = 0

    def consume_job(self, count: int = 1) -> None:
        self._consume("jobs", count)

    def consume_build(self, count: int = 1) -> None:
        self._consume("builds", count)

    def consume_frames(self, count: int = 1) -> None:
        self._consume("frames", count)

    def consume_call(self, count: int = 1) -> None:
        self._consume("calls", count)

    def consume_output(self, byte_count: int) -> None:
        self._consume("output_bytes", byte_count)

    def acquire(self) -> _Permit:
        self.check_deadline()
        if self._active >= self.limits.concurrency:
            raise LimitExceeded("concurrency limit exceeded")
        self._active += 1
        return _Permit(self)

    def check_deadline(self, now: datetime | None = None) -> None:
        current = now or datetime.now(UTC)
        if self.limits.deadline is not None and current >= self.limits.deadline:
            raise DeadlineExceeded("execution deadline exceeded")

    def _consume(self, name: str, count: int) -> None:
        if count < 0:
            raise ValueError("usage increment must be nonnegative")
        self.check_deadline()
        updated = self._used[name] + count
        limit = int(getattr(self.limits, name))
        if updated > limit:
            raise LimitExceeded(f"{name} limit exceeded")
        self._used[name] = updated


async def run_with_deadline[T](awaitable: Awaitable[T], *, timeout_seconds: float) -> T:
    """Run model/task work with a mandatory finite timeout."""
    if timeout_seconds <= 0:
        raise ValueError("timeout_seconds must be positive")
    try:
        async with asyncio.timeout(timeout_seconds):
            return await awaitable
    except TimeoutError as error:
        raise DeadlineExceeded("operation deadline exceeded") from error
