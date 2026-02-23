"""Tests for lock module."""

from __future__ import annotations

import fcntl
import time
from pathlib import Path
from threading import Thread

import pytest

from euler_files.lock import LockTimeout, acquire_lock


def test_basic_lock_acquire(tmp_path: Path) -> None:
    """Lock should be acquirable."""
    lock_path = tmp_path / "test.lock"
    with acquire_lock(lock_path, timeout=5):
        assert lock_path.exists()


def test_lock_creates_parent_dirs(tmp_path: Path) -> None:
    lock_path = tmp_path / "nested" / "dir" / "test.lock"
    with acquire_lock(lock_path, timeout=5):
        assert lock_path.exists()


def test_lock_timeout() -> None:
    """Should raise LockTimeout when lock is held."""
    import tempfile

    with tempfile.NamedTemporaryFile(suffix=".lock", delete=False) as f:
        lock_path = Path(f.name)

    # Hold the lock from outside
    holder = open(lock_path, "w")
    fcntl.flock(holder.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)

    try:
        with pytest.raises(LockTimeout):
            with acquire_lock(lock_path, timeout=1, poll_interval=0.2):
                pass  # Should not reach here
    finally:
        fcntl.flock(holder.fileno(), fcntl.LOCK_UN)
        holder.close()
        lock_path.unlink(missing_ok=True)


def test_lock_contention_threads(tmp_path: Path) -> None:
    """Two threads competing for the same lock."""
    lock_path = tmp_path / "test.lock"
    results: list = []

    def worker(worker_id: int, hold_time: float) -> None:
        with acquire_lock(lock_path, timeout=10, poll_interval=0.1):
            results.append((worker_id, "acquired", time.monotonic()))
            time.sleep(hold_time)
        results.append((worker_id, "released", time.monotonic()))

    t1 = Thread(target=worker, args=(1, 0.5))
    t2 = Thread(target=worker, args=(2, 0.0))

    t1.start()
    time.sleep(0.1)  # Ensure t1 gets lock first
    t2.start()

    t1.join(timeout=10)
    t2.join(timeout=10)

    # t1 should acquire before t2
    acquire_events = [(r[0], r[2]) for r in results if r[1] == "acquired"]
    assert len(acquire_events) == 2
    assert acquire_events[0][0] == 1  # t1 acquired first
    assert acquire_events[1][0] == 2  # t2 acquired second
    assert acquire_events[1][1] > acquire_events[0][1]  # t2 later
