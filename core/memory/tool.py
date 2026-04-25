"""
core.memory.tool — Client-side backend for Anthropic's ``memory_20250818``.

This is the concrete implementation of the tool protocol Anthropic announced
in September 2025. The API registers the tool with the stanza:

    {"type": "memory_20250818", "name": "memory"}

…plus the beta header ``anthropic-beta: context-management-2025-06-27``. No
tool-schema is sent; the ``type`` alone triggers the protocol. Every call
the model makes to ``memory`` is routed back to the client SDK, which
demuxes into one of six commands:

+----------------+----------------------------------------------------------+
| command        | payload                                                  |
+================+==========================================================+
| view           | ``{"path": "/memories/x.md"}``                           |
+----------------+----------------------------------------------------------+
| create         | ``{"path": "...", "file_text": "..."}``                  |
+----------------+----------------------------------------------------------+
| str_replace    | ``{"path": "...", "old_str": "...", "new_str": "..."}``  |
+----------------+----------------------------------------------------------+
| insert         | ``{"path": "...", "insert_line": N, "insert_text": ".."}``|
+----------------+----------------------------------------------------------+
| delete         | ``{"path": "..."}``                                      |
+----------------+----------------------------------------------------------+
| rename         | ``{"old_path": "...", "new_path": "..."}``               |
+----------------+----------------------------------------------------------+

All paths use the virtual prefix ``/memories``. This class maps that prefix
onto ``<project_root>/memory/auto/`` and enforces:

* :mod:`core.memory.scope_guard` for every path
* NFKC + URL-decode for every input
* Sanitization of *written* content (defence against Cisco memory-poisoning)
* Two-phase writes via ``.staging/`` (NEW-01)
* Per-command audit log entries with content diffs (NEW-04)
* ``AUTO_FILE_MAX_LINES`` cap on read output (prevents context blow-up)
* Atomic ``os.replace`` at commit

The class intentionally does NOT subclass anything from the ``anthropic``
SDK at import time — that dependency is wrapped in :mod:`core.memory.auto`
which performs a late import. This keeps ``core.memory.tool`` usable in
unit tests that don't have the SDK installed.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import tempfile
import threading
import time
import unicodedata
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Final

from core.memory.audit import AuditLogger
from core.memory.scope_guard import (
    ScopeViolation,
    VIRTUAL_PREFIX,
    normalize_virtual_path,
    safe_resolve,
)

__all__ = [
    "MemoryTool",
    "MemoryCommandError",
]

log = logging.getLogger(__name__)

# --------------------------------------------------------------------------- #
# Constants & defaults
# --------------------------------------------------------------------------- #

_DEFAULT_AUTO_FILE_MAX_LINES: Final[int] = 500
"""Hard cap on lines returned by ``view`` (env: AUTO_FILE_MAX_LINES)."""

_DEFAULT_MAX_FILE_BYTES: Final[int] = 1_000_000
"""Refuse to read/write files bigger than 1 MB via the tool."""

_DEFAULT_MAX_WRITES_PER_MIN: Final[int] = 60
"""Rate-limit per (project, session) to defeat write-loop attacks."""

_FORBIDDEN_LINE_PATTERNS: Final[tuple[re.Pattern[str], ...]] = (
    re.compile(r"^\s*<\|"),                       # Anthropic special tokens
    re.compile(r"^\s*\[INST\]", re.IGNORECASE),   # Llama-family prompt markers
    re.compile(r"^\s*<system>", re.IGNORECASE),
    re.compile(r"^\s*###\s*system", re.IGNORECASE),
    re.compile(r"\bBEGIN\s+INSTRUCTIONS\b", re.IGNORECASE),
    re.compile(r"<\|im_start\|>"),
    re.compile(r"<\|endoftext\|>"),
)

_COMMANDS: Final[frozenset[str]] = frozenset(
    {"view", "create", "str_replace", "insert", "delete", "rename"}
)


# --------------------------------------------------------------------------- #
# Exceptions & records
# --------------------------------------------------------------------------- #


class MemoryCommandError(ValueError):
    """Raised when a command's arguments are invalid or preconditions fail.

    Distinct from :class:`ScopeViolation` (security) so callers can
    differentiate "model sent a bad command" from "model tried to escape
    scope".
    """


# --------------------------------------------------------------------------- #
# Sanitizer (local; the fuller one lives in core.memory.sanitizer if needed)
# --------------------------------------------------------------------------- #


def _sanitize(text: str, *, max_chars: int | None = None) -> str:
    """Drop prompt-injection lines and enforce max-char cap.

    The sanitizer is deliberately conservative:

    * runs NFKC so the forbidden-pattern regex can't be bypassed with
      lookalike codepoints;
    * drops whole lines that match a forbidden pattern (we don't try to
      surgically edit — poisoned content is discarded entirely);
    * truncates at ``max_chars`` with a visible marker;
    * preserves Hebrew/RTL text because the patterns only look for ASCII
      prompt-markers.
    """
    if not isinstance(text, str):
        raise MemoryCommandError(f"content must be str, got {type(text).__name__}")

    text = unicodedata.normalize("NFKC", text)

    kept: list[str] = []
    dropped = 0
    for line in text.splitlines():
        if any(p.search(line) for p in _FORBIDDEN_LINE_PATTERNS):
            dropped += 1
            continue
        kept.append(line)

    out = "\n".join(kept)
    if dropped:
        log.warning("sanitizer dropped %d line(s) of forbidden patterns", dropped)

    if max_chars is not None and len(out) > max_chars:
        out = out[:max_chars] + "\n[... truncated by sanitizer ...]"
    return out


# --------------------------------------------------------------------------- #
# Rate limiter
# --------------------------------------------------------------------------- #


class _RateLimiter:
    """Sliding-window per-key counter. Thread-safe."""

    def __init__(self, max_per_minute: int):
        self._max = max_per_minute
        self._events: dict[str, list[float]] = {}
        self._lock = threading.Lock()

    def check(self, key: str) -> None:
        now = time.monotonic()
        with self._lock:
            bucket = self._events.setdefault(key, [])
            cutoff = now - 60.0
            while bucket and bucket[0] < cutoff:
                bucket.pop(0)
            if len(bucket) >= self._max:
                raise MemoryCommandError(
                    f"rate limit exceeded: {len(bucket)}/{self._max} writes in 60s"
                )
            bucket.append(now)


# --------------------------------------------------------------------------- #
# The tool
# --------------------------------------------------------------------------- #


class MemoryTool:
    """Client-side implementation of ``memory_20250818``.

    One instance serves exactly one (project, session, user) triple. Callers
    MUST construct a fresh tool per session — this guarantees session-lock
    (v1.0 layer 3).

    Parameters
    ----------
    project_slug:
        Hashed slug (see :mod:`core.projects.slug`). Used for audit.
    project_root:
        Directory containing ``memory/auto/``. Must exist.
    user:
        Acting user id. Used for audit; not for authorization (that's
        the initializer's job).
    session_id:
        UUID of the active session.
    policy:
        Parsed ``memory_policy.yaml`` dict. Recognized keys:

        * ``auto.auto_file_max_lines`` (int)
        * ``auto.max_file_bytes`` (int)
        * ``auto.max_writes_per_min`` (int)
        * ``auto.forbidden_patterns`` (list[str]) — appended to defaults
    audit_path:
        Optional override for the audit log location.
    clock:
        Optional callable returning an ISO-8601 string; defaults to
        ``datetime.now(timezone.utc).isoformat(timespec="seconds")``.
        Injected for tests.
    """

    VIRTUAL_PREFIX = VIRTUAL_PREFIX

    def __init__(
        self,
        *,
        project_slug: str,
        project_root: Path,
        user: str,
        session_id: str,
        policy: dict[str, Any] | None = None,
        audit_path: Path | None = None,
        clock: Callable[[], str] | None = None,
    ) -> None:
        if not project_slug:
            raise ValueError("project_slug required")
        if not session_id:
            raise ValueError("session_id required")

        self.slug = project_slug
        self.user = user or "unknown"
        self.session = session_id
        self.policy = policy or {}

        project_root = project_root.resolve(strict=True)
        self._auto_root = (project_root / "memory" / "auto")
        self._auto_root.mkdir(parents=True, exist_ok=True)
        self._auto_root = self._auto_root.resolve(strict=True)

        self._staging = project_root / "memory" / ".staging"
        self._staging.mkdir(parents=True, exist_ok=True)

        # Unified audit logger — same schema as initializer.py (AuditRecord JSONL).
        # Both paths write to <project_root>/.audit.log; schema is now canonical.
        self._audit = AuditLogger(project_root, audit_path=audit_path)

        auto_policy = (self.policy.get("auto") or {})
        self._max_lines = int(
            auto_policy.get("auto_file_max_lines", _DEFAULT_AUTO_FILE_MAX_LINES)
        )
        self._max_bytes = int(
            auto_policy.get("max_file_bytes", _DEFAULT_MAX_FILE_BYTES)
        )
        self._rate = _RateLimiter(
            int(auto_policy.get("max_writes_per_min",
                                _DEFAULT_MAX_WRITES_PER_MIN))
        )
        extra = auto_policy.get("forbidden_patterns") or []
        self._extra_patterns = tuple(
            re.compile(p, re.IGNORECASE) for p in extra
        )
        self._now = clock or (
            lambda: datetime.now(timezone.utc).isoformat(timespec="seconds")
        )
        self._write_lock = threading.Lock()  # serialise commits per-instance
        log.info(
            "MemoryTool ready slug=%s user=%s session=%s root=%s",
            self.slug, self.user, self.session, self._auto_root,
        )

    # ------------------------------------------------------------------ #
    # Dispatch
    # ------------------------------------------------------------------ #

    def dispatch(self, command: str, **kwargs: Any) -> dict[str, Any]:
        """Route an Anthropic-side ``{command, **args}`` call.

        Returns a JSON-serialisable dict; errors are converted into
        structured responses so the model sees them as a tool result
        rather than an exception.
        """
        if command not in _COMMANDS:
            return self._error(command, "", f"unknown command: {command!r}")
        handler = getattr(self, f"_cmd_{command}")
        try:
            return handler(**kwargs)
        except ScopeViolation as e:
            return self._error(command, kwargs.get("path", ""), str(e))
        except MemoryCommandError as e:
            return self._error(command, kwargs.get("path", ""), str(e))
        except FileNotFoundError as e:
            return self._error(command, kwargs.get("path", ""), f"not found: {e}")
        except Exception as e:  # pragma: no cover - safety net
            log.exception("memory tool crashed on %s", command)
            return self._error(command, kwargs.get("path", ""), f"internal: {e}")

    # ------------------------------------------------------------------ #
    # Commands
    # ------------------------------------------------------------------ #

    def _cmd_view(self, *, path: str, **_: Any) -> dict[str, Any]:
        real = self._to_real(path, must_exist=True)
        if real.is_dir():
            entries = sorted(p.name for p in real.iterdir()
                             if not p.name.startswith("."))
            self._audit_ok("view", path)
            return {"type": "directory", "path": path, "entries": entries}

        size = real.stat().st_size
        if size > self._max_bytes:
            raise MemoryCommandError(
                f"file too large ({size} > {self._max_bytes})"
            )
        content = real.read_text(encoding="utf-8")
        lines = content.splitlines()
        truncated = False
        if len(lines) > self._max_lines:
            lines = lines[: self._max_lines]
            truncated = True

        numbered = "\n".join(f"{i + 1}\t{line}" for i, line in enumerate(lines))
        if truncated:
            numbered += f"\n[... truncated at {self._max_lines} lines ...]"
        self._audit_ok("view", path)
        return {
            "type": "file",
            "path": path,
            "content": numbered,
            "truncated": truncated,
            "lines": len(lines),
        }

    def _cmd_create(self, *, path: str, file_text: str, **_: Any) -> dict[str, Any]:
        self._rate.check(f"{self.slug}:{self.session}")
        real = self._to_real(path, must_exist=False)
        clean = self._sanitize(file_text)
        if len(clean.encode("utf-8")) > self._max_bytes:
            raise MemoryCommandError(
                f"content too large ({len(clean)} > {self._max_bytes})"
            )
        self._stage_and_commit(real, clean)
        self._audit_ok("create", path, diff=clean)
        return {"ok": True, "path": path, "bytes": len(clean.encode("utf-8"))}

    def _cmd_str_replace(
        self, *, path: str, old_str: str, new_str: str, **_: Any
    ) -> dict[str, Any]:
        self._rate.check(f"{self.slug}:{self.session}")
        real = self._to_real(path, must_exist=True)
        content = real.read_text(encoding="utf-8")
        count = content.count(old_str)
        if count == 0:
            raise MemoryCommandError(f"old_str not found in {path}")
        if count > 1:
            raise MemoryCommandError(
                f"old_str not unique in {path}: {count} occurrences"
            )
        clean_new = self._sanitize(new_str)
        updated = content.replace(old_str, clean_new, 1)
        self._stage_and_commit(real, updated)
        diff = f"- {old_str[:200]}\n+ {clean_new[:200]}"
        self._audit_ok("str_replace", path, diff=diff)
        return {"ok": True, "path": path}

    def _cmd_insert(
        self, *, path: str, insert_line: int, insert_text: str, **_: Any
    ) -> dict[str, Any]:
        self._rate.check(f"{self.slug}:{self.session}")
        if not isinstance(insert_line, int) or insert_line < 0:
            raise MemoryCommandError(
                f"insert_line must be non-negative int, got {insert_line!r}"
            )
        real = self._to_real(path, must_exist=True)
        lines = real.read_text(encoding="utf-8").splitlines()
        if insert_line > len(lines):
            raise MemoryCommandError(
                f"insert_line {insert_line} beyond EOF ({len(lines)} lines)"
            )
        clean = self._sanitize(insert_text)
        lines[insert_line:insert_line] = clean.splitlines() or [clean]
        updated = "\n".join(lines) + ("\n" if lines else "")
        self._stage_and_commit(real, updated)
        self._audit_ok("insert", path, diff=f"+ {clean[:500]}")
        return {"ok": True, "path": path, "inserted_at": insert_line}

    def _cmd_delete(self, *, path: str, **_: Any) -> dict[str, Any]:
        real = self._to_real(path, must_exist=True)
        if real.is_dir():
            raise MemoryCommandError(
                "cannot delete directory via memory tool"
            )
        # capture content for audit before unlink (size-bounded).
        try:
            preview = real.read_text(encoding="utf-8")[:500]
        except Exception:  # noqa: BLE001
            preview = "<unreadable>"
        real.unlink()
        self._audit_ok("delete", path, diff=f"- {preview}")
        return {"ok": True, "path": path}

    def _cmd_rename(
        self, *, old_path: str, new_path: str, **_: Any
    ) -> dict[str, Any]:
        old_real = self._to_real(old_path, must_exist=True)
        new_real = self._to_real(new_path, must_exist=False)
        if new_real.exists():
            raise MemoryCommandError(f"destination exists: {new_path}")
        new_real.parent.mkdir(parents=True, exist_ok=True)
        with self._write_lock:
            old_real.rename(new_real)
        self._audit_ok("rename", f"{old_path} -> {new_path}")
        return {"ok": True, "old_path": old_path, "new_path": new_path}

    # ------------------------------------------------------------------ #
    # Helpers
    # ------------------------------------------------------------------ #

    def _to_real(self, virtual: str, *, must_exist: bool) -> Path:
        """Single chokepoint between model strings and the filesystem."""
        rel = normalize_virtual_path(virtual)
        return safe_resolve(self._auto_root, rel, must_exist=must_exist)

    def _sanitize(self, text: str) -> str:
        cleaned = _sanitize(text, max_chars=self._max_bytes)
        if self._extra_patterns:
            kept: list[str] = []
            for line in cleaned.splitlines():
                if any(p.search(line) for p in self._extra_patterns):
                    continue
                kept.append(line)
            cleaned = "\n".join(kept)
        return cleaned

    def _stage_and_commit(self, real: Path, content: str) -> None:
        """Two-phase write: stage → fsync → atomic replace."""
        real.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp_name = tempfile.mkstemp(
            prefix=".stage-", suffix=".md", dir=str(self._staging)
        )
        tmp_path = Path(tmp_name)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                f.write(content)
                f.flush()
                os.fsync(f.fileno())
            # Atomic within same filesystem. If _staging and auto/ are on
            # different mounts this will degrade to copy+unlink via
            # os.replace, still atomic at the destination.
            with self._write_lock:
                os.replace(tmp_path, real)
        except Exception:
            tmp_path.unlink(missing_ok=True)
            raise

    def _audit_ok(
        self,
        action: str,
        path: str,
        *,
        diff: str | None = None,
    ) -> None:
        # status="commit" is the canonical success status in AuditRecord.
        # Pass diff directly; AuditLogger truncates to DIFF_MAX_CHARS internally.
        self._audit.log(
            self.slug,
            self.user,
            action,
            path=path,
            session_id=self.session,
            status="commit",
            diff=diff,
        )

    def _error(self, action: str, path: str, msg: str) -> dict[str, Any]:
        log.warning("memory error action=%s path=%r msg=%s", action, path, msg)
        # status="abort" = failed / rolled-back operation in AuditRecord.
        self._audit.log(
            self.slug,
            self.user,
            action,
            path=path,
            session_id=self.session,
            status="abort",
            error=msg,
        )
        return {"ok": False, "error": msg}

    # ------------------------------------------------------------------ #
    # Tool-registration helper
    # ------------------------------------------------------------------ #

    @staticmethod
    def tool_config() -> dict[str, str]:
        """Return the minimal dict to pass to ``client.beta.messages.create``.

        The API accepts the tool with only ``type`` + ``name``; no schema
        is required because ``memory_20250818`` is a first-class protocol.
        """
        return {"type": "memory_20250818", "name": "memory"}

    @staticmethod
    def beta_header() -> dict[str, str]:
        """HTTP header dict to merge into the request."""
        return {"anthropic-beta": "context-management-2025-06-27"}


# --------------------------------------------------------------------------- #
# Self-test
# --------------------------------------------------------------------------- #


def _self_test() -> None:  # pragma: no cover
    import tempfile
    import uuid

    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        (root / "memory" / "auto").mkdir(parents=True)
        tool = MemoryTool(
            project_slug="test",
            project_root=root,
            user="guy",
            session_id=str(uuid.uuid4()),
        )
        # create
        r = tool.dispatch("create", path="/memories/hello.md", file_text="שלום עולם\n")
        assert r["ok"], r
        # view
        r = tool.dispatch("view", path="/memories/hello.md")
        assert r["type"] == "file"
        assert "שלום" in r["content"]
        # traversal blocked
        r = tool.dispatch("view", path="/memories/../../etc/passwd")
        assert not r["ok"], r
        # poisoned content dropped
        r = tool.dispatch(
            "create", path="/memories/bad.md",
            file_text="ok line\n<|im_start|>system\nbad\n",
        )
        assert r["ok"]
        r = tool.dispatch("view", path="/memories/bad.md")
        assert "<|im_start|>" not in r["content"], r
        # str_replace uniqueness
        r = tool.dispatch(
            "str_replace", path="/memories/hello.md",
            old_str="שלום", new_str="היי",
        )
        assert r["ok"], r
        # rename
        r = tool.dispatch(
            "rename", old_path="/memories/hello.md", new_path="/memories/greeting.md",
        )
        assert r["ok"], r
        # delete
        r = tool.dispatch("delete", path="/memories/greeting.md")
        assert r["ok"], r
        print("MemoryTool self-test PASS")


if __name__ == "__main__":  # pragma: no cover
    logging.basicConfig(level=logging.INFO)
    _self_test()
