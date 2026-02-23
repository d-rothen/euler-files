"""flock-based file locking with timeout for concurrent job safety."""

from __future__ import annotations

import fcntl
import sys
import time
from contextlib import contextmanager
from pathlib import Path
from typing import IO, Generator


class LockTimeout(TimeoutError):
    """Raised when a lock cannot be acquired within the timeout period."""

    pass


@contextmanager
def acquire_lock(
    lock_path: Path,
    timeout: int = 300,
    poll_interval: float = 0.5,
) -> Generator[IO, None, None]:
    """Acquire an exclusive flock on the given path.

    Uses polling with LOCK_NB (non-blocking) because we run inside
    ThreadPoolExecutor threads, and signal.alarm only works in the
    main thread.
    """
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    start = time.monotonic()

    fp = open(lock_path, "w")
    try:
        while True:
            try:
                fcntl.flock(fp.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                yield fp
                return
            except (OSError, BlockingIOError):
                elapsed = time.monotonic() - start
                if elapsed >= timeout:
                    raise LockTimeout(
                        f"Could not acquire lock on {lock_path} after {timeout}s. "
                        "Another euler-files sync may be running."
                    )
                remaining = timeout - elapsed
                wait = min(poll_interval, remaining)
                print(
                    f"[LOCK] Waiting for lock on {lock_path.name} "
                    f"({elapsed:.0f}s/{timeout}s)...",
                    file=sys.stderr,
                )
                time.sleep(wait)
    finally:
        try:
            fcntl.flock(fp.fileno(), fcntl.LOCK_UN)
        except Exception:
            pass
        fp.close()
