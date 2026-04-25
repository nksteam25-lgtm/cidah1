"""
core/memory/session_lock.py
============================

Why this module exists
----------------------
A session must be bound to exactly one project, from the very first message
until cleanup, and that binding MUST be immutable mid-session. If the
binding is mutable, or if two concurrent sessions share the same binding
record, we see the exact symptoms reported in:

* GitHub Issue #1985 — "session isolation failure": two concurrent sessions
  end up writing to the same directory and each overwrites the other's
  lock file, so the second session silently takes over the first.
* GitHub Issue #7702 — "sessions share history": because binding is not
  enforced atomically, resumed sessions pick up the newest session's
  transcript rather than their own.

`SessionLock` eliminates both bugs:

1. **Atomic binding** — `fcntl.flock(LOCK_EX | LOCK_NB)` is held for the
   *entire session lifetime*, on a per-session file. A second process
   that tries to take the same lock gets `BlockingIOError` and must back
   off or pick a different session id.
2. **Readonly-after-init** — once `freeze()` is called, any attempt to
   mutate `project_slug` / `user_id` / `session_id` raises
   `SessionLockFrozenError`. This is the contractual bit that prevents a
   session from silently switching projects mid-conversation.
3. **Per-session file** — the lock file is
   `<project>/sessions/.locks/<session_id>.lock`, not a shared
   `session.lock`. Two sessions in the same project can run in parallel
   without blocking each other, but they CANNOT share state because the
   lock file records `(project, user, session_id, pid, started_at)` and
   is checked on every `assert_bound()`.
4. **Clean shutdown** — `release()` both unlocks and unlinks the lock
   file. `SessionLock` is a context manager so `with SessionLock(...) as
   s:` guarantees cleanup even on unhandled exceptions.
5. **Stale lock detection** — if a process dies hard (SIGKILL, power
   loss) the lock file is left behind but the kernel drops the flock.
   On acquire we try a non-blocking flock on any existing file; if it
   succeeds, the previous owner is gone and we inherit the file.

Relevant spec sections: V2 sections 2.1 (principle #7 & #10), 2.4
(`SESSION_LOCK_PROJECT=true`, `SESSION_ID_STRATEGY=uuid4`), pitfalls P04,
P11, P18.
"""

from __future__ import annotations

import errno
import fcntl
import json
import logging
import os
import socket
import threading
import uuid
from contextlib import contextmanager
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from types import TracebackType
from typing import IO, Any, Iterator, Optional

logger = logging.getLogger(__name__)

# --------------------------------------------------------------------------
# Constants
# --------------------------------------------------------------------------

LOCK_DIR_NAME: str = ".locks"
LOCK_FILE_SUFFIX: str = ".lock"
LOCK_DIR_MODE: int = 0o700
LOCK_FILE_MODE: int = 0o600

# Default `cleanupPeriodDays` replacement for the Claude Code setting.
# `cleanupPeriodDays: 0` is a known bug — it disables transcripts entirely
# rather than keeping them forever (V2 spec §1.2 V1-FIX-07, pitfall P05).
# We pick 100 years as an effectively-forever default.
DEFAULT_CLEANUP_PERIOD_DAYS: int = 36500


# --------------------------------------------------------------------------
# Exceptions
# --------------------------------------------------------------------------


class SessionLockError(RuntimeError):
    """Base class for every failure from this module."""


class SessionAlreadyLockedError(SessionLockError):
    """Raised when a different live process already holds this session lock."""


class SessionLockFrozenError(SessionLockError):
    """Raised when something tries to mutate a frozen lock."""


class SessionLockBindingError(SessionLockError):
    """Raised when the on-disk lock does not match the expected binding."""


# --------------------------------------------------------------------------
# Utility
# --------------------------------------------------------------------------


def sanitize_cleanup_period_days(value: Any) -> int:
    """
    Apply the `cleanupPeriodDays: 0` fix. This helper exists so any caller
    that reads a raw config dict (e.g. Claude Code's settings.json) can
    normalize the value before it reaches the session lifecycle.
    """
    try:
        n = int(value)
    except (TypeError, ValueError):
        logger.warning(
            "cleanupPeriodDays=%r is not an int; using default %d",
            value,
            DEFAULT_CLEANUP_PERIOD_DAYS,
        )
        return DEFAULT_CLEANUP_PERIOD_DAYS

    if n <= 0:
        # 0 -> bug; negative -> nonsense; both become the forever default.
        logger.warning(
            "cleanupPeriodDays=%d is invalid (0 disables transcripts entirely); "
            "coercing to %d",
            n,
            DEFAULT_CLEANUP_PERIOD_DAYS,
        )
        return DEFAULT_CLEANUP_PERIOD_DAYS

    return n


def new_session_id() -> str:
    """
    Spec: `SESSION_ID_STRATEGY=uuid4`. Centralized so every call site
    uses the same generator.
    """
    return str(uuid.uuid4())


# --------------------------------------------------------------------------
# Data
# --------------------------------------------------------------------------


@dataclass
class SessionBinding:
    """
    Serializable on-disk record. Written to the lock file as JSON so an
    operator can `cat` the file and see who owns it.
    """

    project_slug: str
    user_id: str
    session_id: str
    pid: int
    hostname: str
    started_at: str  # ISO-8601 UTC
    cleanup_period_days: int

    def to_json(self) -> str:
        return json.dumps(asdict(self), sort_keys=True, ensure_ascii=False)

    @classmethod
    def from_json(cls, raw: str) -> "SessionBinding":
        data = json.loads(raw)
        return cls(**data)


# --------------------------------------------------------------------------
# SessionLock
# --------------------------------------------------------------------------


class SessionLock:
    """
    Acquire-on-enter, release-on-exit lock that binds one session to one
    project. Use as a context manager.

    Example
    -------
    >>> with SessionLock(project_root, slug, user, new_session_id()) as lock:
    ...     lock.freeze()
    ...     # ... run the session ...
    ...     lock.assert_bound(slug)  # will raise if anything tampered
    """

    # Fields that become immutable after freeze().
    _FROZEN_FIELDS = ("_project_slug", "_user_id", "_session_id")

    def __init__(
        self,
        project_root: Path,
        project_slug: str,
        user_id: str,
        session_id: str,
        cleanup_period_days: int = DEFAULT_CLEANUP_PERIOD_DAYS,
    ) -> None:
        if not project_slug:
            raise ValueError("project_slug is required")
        if not user_id:
            raise ValueError("user_id is required")
        if not session_id:
            raise ValueError("session_id is required")

        # These are private so we can gate writes through __setattr__.
        object.__setattr__(self, "_project_slug", project_slug)
        object.__setattr__(self, "_user_id", user_id)
        object.__setattr__(self, "_session_id", session_id)
        object.__setattr__(
            self, "_cleanup_period_days", sanitize_cleanup_period_days(cleanup_period_days)
        )
        object.__setattr__(self, "_project_root", Path(project_root))
        object.__setattr__(self, "_frozen", False)
        object.__setattr__(self, "_fh", None)  # type: Optional[IO[str]]
        object.__setattr__(self, "_acquired", False)
        object.__setattr__(self, "_thread_lock", threading.RLock())
        object.__setattr__(self, "_binding", None)  # type: Optional[SessionBinding]

    # ------------------------------------------------------------------
    # Properties
    # ------------------------------------------------------------------

    @property
    def project_slug(self) -> str:
        return self._project_slug

    @property
    def user_id(self) -> str:
        return self._user_id

    @property
    def session_id(self) -> str:
        return self._session_id

    @property
    def frozen(self) -> bool:
        return self._frozen

    @property
    def acquired(self) -> bool:
        return self._acquired

    @property
    def binding(self) -> Optional[SessionBinding]:
        return self._binding

    @property
    def lock_path(self) -> Path:
        return (
            self._project_root
            / "sessions"
            / LOCK_DIR_NAME
            / f"{self._session_id}{LOCK_FILE_SUFFIX}"
        )

    # ------------------------------------------------------------------
    # Mutation guard
    # ------------------------------------------------------------------

    def __setattr__(self, name: str, value: Any) -> None:
        # Once frozen, refuse to rebind the identity fields. Everything
        # else (internal state like `_acquired`) may still change.
        if getattr(self, "_frozen", False) and name in self._FROZEN_FIELDS:
            raise SessionLockFrozenError(
                f"cannot modify {name} after freeze(); session lock is readonly"
            )
        object.__setattr__(self, name, value)

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def acquire(self) -> "SessionLock":
        """
        Create lock dir, open the lock file, take an exclusive non-blocking
        flock, write the binding JSON, fsync. Raises
        SessionAlreadyLockedError if another live process holds it.
        """
        with self._thread_lock:
            if self._acquired:
                logger.debug("lock already acquired for %s", self._session_id)
                return self

            lock_path = self.lock_path
            try:
                lock_path.parent.mkdir(parents=True, exist_ok=True)
                # tighten dir perms — safe even if pre-existing.
                try:
                    os.chmod(lock_path.parent, LOCK_DIR_MODE)
                except OSError as e:
                    # Not fatal — the parent may be owned by another uid
                    # in the UID-per-project scheme. Log and continue.
                    logger.debug("chmod lock dir failed (%s): %s", lock_path.parent, e)
            except OSError as e:
                raise SessionLockError(
                    f"cannot create lock dir {lock_path.parent}: {e}"
                ) from e

            # Open with O_RDWR | O_CREAT so an orphaned file can be
            # re-locked by us if the previous owner died.
            try:
                fd = os.open(
                    str(lock_path),
                    os.O_RDWR | os.O_CREAT,
                    LOCK_FILE_MODE,
                )
            except OSError as e:
                raise SessionLockError(f"cannot open lock file {lock_path}: {e}") from e

            fh = os.fdopen(fd, "r+", encoding="utf-8")

            try:
                fcntl.flock(fh.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError as e:
                fh.close()
                raise SessionAlreadyLockedError(
                    f"session {self._session_id} is locked by another live process "
                    f"(pid unknown; check {lock_path})"
                ) from e
            except OSError as e:
                fh.close()
                if e.errno in (errno.EWOULDBLOCK, errno.EAGAIN):
                    raise SessionAlreadyLockedError(
                        f"session {self._session_id} already locked"
                    ) from e
                raise SessionLockError(f"flock failed: {e}") from e

            # We hold the lock. Write/overwrite the binding atomically.
            binding = SessionBinding(
                project_slug=self._project_slug,
                user_id=self._user_id,
                session_id=self._session_id,
                pid=os.getpid(),
                hostname=socket.gethostname(),
                started_at=datetime.now(timezone.utc).isoformat(),
                cleanup_period_days=self._cleanup_period_days,
            )

            try:
                fh.seek(0)
                fh.truncate()
                fh.write(binding.to_json())
                fh.write("\n")
                fh.flush()
                os.fsync(fh.fileno())
            except OSError as e:
                # Lock released automatically when fh closes.
                try:
                    fcntl.flock(fh.fileno(), fcntl.LOCK_UN)
                except OSError:
                    pass
                fh.close()
                raise SessionLockError(f"cannot write binding to {lock_path}: {e}") from e

            object.__setattr__(self, "_fh", fh)
            object.__setattr__(self, "_acquired", True)
            object.__setattr__(self, "_binding", binding)

            logger.info(
                "session lock acquired: project=%s user=%s session=%s pid=%d",
                self._project_slug,
                self._user_id,
                self._session_id,
                os.getpid(),
            )
            return self

    def freeze(self) -> None:
        """
        Make the identity fields immutable. Must be called after acquire()
        and before the first real model call. Idempotent.
        """
        with self._thread_lock:
            if not self._acquired:
                raise SessionLockError("cannot freeze a lock that was never acquired")
            if self._frozen:
                return
            object.__setattr__(self, "_frozen", True)
            logger.debug("session lock frozen: %s", self._session_id)

    def assert_bound(self, expected_project_slug: str) -> None:
        """
        Verify mid-session that nothing has tampered with our binding.
        Call this before any memory write: if the on-disk binding no
        longer matches what we think we're bound to, abort.
        """
        with self._thread_lock:
            if not self._acquired or self._fh is None:
                raise SessionLockError("lock not acquired")

            if expected_project_slug != self._project_slug:
                # This would only happen if calling code has a bug — the
                # in-memory slug is the source of truth, compare it first.
                raise SessionLockBindingError(
                    f"expected project={expected_project_slug}, "
                    f"bound project={self._project_slug}"
                )

            try:
                self._fh.seek(0)
                raw = self._fh.read()
            except OSError as e:
                raise SessionLockError(f"cannot re-read lock file: {e}") from e

            if not raw.strip():
                raise SessionLockBindingError("lock file is empty")

            try:
                disk = SessionBinding.from_json(raw.strip().splitlines()[0])
            except (json.JSONDecodeError, TypeError, KeyError) as e:
                raise SessionLockBindingError(f"lock file is corrupt: {e}") from e

            if (
                disk.project_slug != self._project_slug
                or disk.session_id != self._session_id
                or disk.user_id != self._user_id
            ):
                raise SessionLockBindingError(
                    f"on-disk binding drifted: disk={disk}, "
                    f"expected project={self._project_slug} "
                    f"session={self._session_id} user={self._user_id}"
                )

    def release(self) -> None:
        """
        Release the flock, close the file handle, unlink the lock file.
        Safe to call multiple times. Safe to call if acquire() failed.
        """
        with self._thread_lock:
            fh = self._fh
            if fh is None:
                object.__setattr__(self, "_acquired", False)
                return

            # flock is released when fh is closed, but unlock explicitly
            # first so any observer's non-blocking flock gets the right
            # errno ordering.
            try:
                fcntl.flock(fh.fileno(), fcntl.LOCK_UN)
            except OSError as e:
                logger.warning("flock unlock failed: %s", e)

            try:
                fh.close()
            except OSError as e:
                logger.warning("closing lock file failed: %s", e)

            try:
                self.lock_path.unlink(missing_ok=True)
            except OSError as e:
                logger.warning("unlinking lock file failed: %s", e)

            object.__setattr__(self, "_fh", None)
            object.__setattr__(self, "_acquired", False)

            logger.info(
                "session lock released: project=%s session=%s",
                self._project_slug,
                self._session_id,
            )

    # ------------------------------------------------------------------
    # Context manager
    # ------------------------------------------------------------------

    def __enter__(self) -> "SessionLock":
        return self.acquire()

    def __exit__(
        self,
        exc_type: Optional[type[BaseException]],
        exc: Optional[BaseException],
        tb: Optional[TracebackType],
    ) -> None:
        self.release()


# --------------------------------------------------------------------------
# Cleanup helper
# --------------------------------------------------------------------------


def cleanup_stale_locks(project_root: Path) -> int:
    """
    Scan `<project_root>/sessions/.locks/` and delete any lock file that
    NO process holds. This is safe to run at startup or on a cron: if
    another process holds the lock, the non-blocking flock attempt here
    fails and we leave the file untouched.

    Returns the count of files actually removed.
    """
    lock_dir = Path(project_root) / "sessions" / LOCK_DIR_NAME
    if not lock_dir.is_dir():
        return 0

    removed = 0
    for lock_file in lock_dir.glob(f"*{LOCK_FILE_SUFFIX}"):
        try:
            fd = os.open(str(lock_file), os.O_RDWR)
        except OSError as e:
            logger.debug("cannot open %s during cleanup: %s", lock_file, e)
            continue
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except (BlockingIOError, OSError):
            os.close(fd)
            logger.debug("%s still held; skipping", lock_file)
            continue

        # We have the lock — previous owner is gone.
        try:
            lock_file.unlink(missing_ok=True)
            removed += 1
            logger.info("removed stale lock %s", lock_file)
        except OSError as e:
            logger.warning("cannot unlink stale lock %s: %s", lock_file, e)
        finally:
            try:
                fcntl.flock(fd, fcntl.LOCK_UN)
            except OSError:
                pass
            os.close(fd)

    return removed


@contextmanager
def session_scope(
    project_root: Path,
    project_slug: str,
    user_id: str,
    session_id: Optional[str] = None,
    cleanup_period_days: int = DEFAULT_CLEANUP_PERIOD_DAYS,
) -> Iterator[SessionLock]:
    """
    Convenience wrapper. Generates a session id if none supplied, acquires,
    freezes, yields, releases.
    """
    sid = session_id or new_session_id()
    lock = SessionLock(
        project_root=project_root,
        project_slug=project_slug,
        user_id=user_id,
        session_id=sid,
        cleanup_period_days=cleanup_period_days,
    )
    lock.acquire()
    try:
        lock.freeze()
        yield lock
    finally:
        lock.release()


# ==========================================================================
# Unit tests — pytest
# ==========================================================================

if __name__ == "__main__":  # pragma: no cover
    import pytest
    import sys

    sys.exit(pytest.main([__file__, "-v"]))


def _make_project(tmp_path):
    root = tmp_path / "proj-abc"
    (root / "sessions").mkdir(parents=True)
    return root


def test_acquire_and_release(tmp_path):
    root = _make_project(tmp_path)
    lock = SessionLock(root, "proj-abc", "guy", new_session_id())
    lock.acquire()
    assert lock.acquired is True
    assert lock.lock_path.exists()
    lock.release()
    assert lock.acquired is False
    assert not lock.lock_path.exists()


def test_context_manager_cleans_up(tmp_path):
    root = _make_project(tmp_path)
    sid = new_session_id()
    with SessionLock(root, "proj-abc", "guy", sid) as lock:
        assert lock.lock_path.exists()
    # After exit -> gone.
    assert not (root / "sessions" / LOCK_DIR_NAME / f"{sid}.lock").exists()


def test_double_acquire_same_session_raises(tmp_path):
    import pytest

    root = _make_project(tmp_path)
    sid = new_session_id()
    first = SessionLock(root, "proj-abc", "guy", sid)
    second = SessionLock(root, "proj-abc", "guy", sid)
    first.acquire()
    try:
        with pytest.raises(SessionAlreadyLockedError):
            second.acquire()
    finally:
        first.release()


def test_issue_1985_two_sessions_isolated(tmp_path):
    # Two different session ids coexist in the same project without collision.
    root = _make_project(tmp_path)
    with SessionLock(root, "proj-abc", "guy", new_session_id()) as a:
        with SessionLock(root, "proj-abc", "guy", new_session_id()) as b:
            assert a.lock_path != b.lock_path
            assert a.acquired and b.acquired


def test_freeze_prevents_rebinding(tmp_path):
    import pytest

    root = _make_project(tmp_path)
    lock = SessionLock(root, "proj-abc", "guy", new_session_id())
    lock.acquire()
    lock.freeze()
    try:
        with pytest.raises(SessionLockFrozenError):
            lock._project_slug = "other-proj"  # type: ignore[misc]
    finally:
        lock.release()


def test_freeze_idempotent(tmp_path):
    root = _make_project(tmp_path)
    with SessionLock(root, "proj-abc", "guy", new_session_id()) as lock:
        lock.freeze()
        lock.freeze()  # no raise


def test_assert_bound_detects_on_disk_tamper(tmp_path):
    import pytest

    root = _make_project(tmp_path)
    with SessionLock(root, "proj-abc", "guy", new_session_id()) as lock:
        # corrupt the file under our feet.
        lock.lock_path.write_text(
            json.dumps(
                {
                    "project_slug": "other",
                    "user_id": "x",
                    "session_id": "y",
                    "pid": 1,
                    "hostname": "h",
                    "started_at": "z",
                    "cleanup_period_days": 1,
                }
            )
        )
        with pytest.raises(SessionLockBindingError):
            lock.assert_bound("proj-abc")


def test_assert_bound_rejects_wrong_expected(tmp_path):
    import pytest

    root = _make_project(tmp_path)
    with SessionLock(root, "proj-abc", "guy", new_session_id()) as lock:
        with pytest.raises(SessionLockBindingError):
            lock.assert_bound("NOT-MY-PROJECT")


def test_cleanup_period_zero_becomes_default(tmp_path):
    root = _make_project(tmp_path)
    lock = SessionLock(root, "proj-abc", "guy", new_session_id(), cleanup_period_days=0)
    lock.acquire()
    try:
        assert lock.binding is not None
        assert lock.binding.cleanup_period_days == DEFAULT_CLEANUP_PERIOD_DAYS
    finally:
        lock.release()


def test_cleanup_period_negative_becomes_default(tmp_path):
    root = _make_project(tmp_path)
    lock = SessionLock(root, "proj-abc", "guy", new_session_id(), cleanup_period_days=-5)
    lock.acquire()
    try:
        assert lock.binding is not None
        assert lock.binding.cleanup_period_days == DEFAULT_CLEANUP_PERIOD_DAYS
    finally:
        lock.release()


def test_sanitize_cleanup_period_days():
    assert sanitize_cleanup_period_days(0) == DEFAULT_CLEANUP_PERIOD_DAYS
    assert sanitize_cleanup_period_days(-1) == DEFAULT_CLEANUP_PERIOD_DAYS
    assert sanitize_cleanup_period_days("abc") == DEFAULT_CLEANUP_PERIOD_DAYS
    assert sanitize_cleanup_period_days(30) == 30


def test_cleanup_stale_locks_removes_orphans(tmp_path):
    root = _make_project(tmp_path)
    sid = new_session_id()
    # manufacture an orphaned lock file (no flock held).
    lock_dir = root / "sessions" / LOCK_DIR_NAME
    lock_dir.mkdir(parents=True, exist_ok=True)
    orphan = lock_dir / f"{sid}.lock"
    orphan.write_text("{}")
    removed = cleanup_stale_locks(root)
    assert removed >= 1
    assert not orphan.exists()


def test_cleanup_stale_locks_keeps_live(tmp_path):
    root = _make_project(tmp_path)
    with SessionLock(root, "proj-abc", "guy", new_session_id()) as live:
        removed = cleanup_stale_locks(root)
        assert live.lock_path.exists()
        assert removed == 0


def test_session_scope_helper(tmp_path):
    root = _make_project(tmp_path)
    with session_scope(root, "proj-abc", "guy") as lock:
        assert lock.acquired
        assert lock.frozen
    assert not lock.acquired


def test_missing_required_inputs_raise():
    import pytest

    with pytest.raises(ValueError):
        SessionLock(Path("/tmp"), "", "u", "s")
    with pytest.raises(ValueError):
        SessionLock(Path("/tmp"), "p", "", "s")
    with pytest.raises(ValueError):
        SessionLock(Path("/tmp"), "p", "u", "")
