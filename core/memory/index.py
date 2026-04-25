"""
core.memory.index — INDEX.md builder + silent-truncation warning system.

Why this exists
---------------
Claude Code's native behaviour (confirmed in GitHub Issue #39811) is to
load the *first 200 lines / 25 KB* of ``MEMORY.md`` and then **silently**
drop everything past that. No warning in the log, no hint in the UI — if
your index grew to 500 lines, 300 of them are invisible to Claude.

ARCHITECTURE_MEMORY_V2 locks this down with two numbers:

* ``MEMORY_INDEX_WARN_WHEN_LINES_ABOVE = 180``  (soft warning)
* ``MEMORY_INDEX_HARD_LIMIT           = 200``  (truncation boundary)

This module is the single source of truth for those limits. It:

1. **Builds** ``INDEX.md`` by scanning the ``auto/`` directory (optionally
   also ``pinned/`` and ``refs/``) and writing a compact summary block.
2. **Validates** an existing ``INDEX.md`` against the limits and returns
   a :class:`IndexWarning` (or ``None`` if clean).
3. **Emits a trigger** (``auto_dream=True`` on the return value) when
   the soft threshold is crossed, so callers can schedule cleanup.

The builder is deliberately idempotent and debounceable — it can be run
synchronously after every write or as an async cron; callers decide.

File format
-----------

The generated INDEX.md looks like::

    # Project Memory Index
    _generated 2026-04-24T08:15:02Z — 142/200 lines, 6.3/25.0 KB_

    ## Auto memories (model-authored)
    - `decisions.md` — 18 lines, updated 2026-04-23
    - `patterns.md`  — 42 lines, updated 2026-04-24
    - `corrections.md` — 7 lines, updated 2026-04-20

    ## Pinned memories (user-authored)
    _3 pins, see pinned/ block in system prompt for content._

    ## Notes
    _INDEX.md is auto-generated. Edits here are overwritten.
    Files past line 200 would be SILENTLY TRUNCATED by Claude Code._
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Final, Iterable

from core.memory.scope_guard import ScopeViolation, safe_resolve

__all__ = [
    "IndexBuilder",
    "IndexWarning",
    "IndexStats",
    "DEFAULT_WARN_AT",
    "DEFAULT_HARD_LIMIT",
    "DEFAULT_MAX_BYTES",
]

log = logging.getLogger(__name__)

# --------------------------------------------------------------------------- #
# Limits (exposed for tests + introspection)
# --------------------------------------------------------------------------- #

DEFAULT_WARN_AT: Final[int] = 180
DEFAULT_HARD_LIMIT: Final[int] = 200
DEFAULT_MAX_BYTES: Final[int] = 25_600  # 25 KB — matches Claude Code cap

# --------------------------------------------------------------------------- #
# Records
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class IndexStats:
    """Measurement of an INDEX.md file."""
    lines: int
    bytes: int
    auto_files: int
    pinned_count: int
    warn_at: int
    hard_limit: int
    max_bytes: int

    @property
    def over_soft(self) -> bool:
        return self.lines >= self.warn_at or self.bytes >= int(
            self.max_bytes * 0.9
        )

    @property
    def over_hard(self) -> bool:
        return self.lines >= self.hard_limit or self.bytes >= self.max_bytes


@dataclass(frozen=True)
class IndexWarning:
    """Returned by :meth:`IndexBuilder.check` when limits are approached."""
    level: str                 # "warn" | "critical"
    message: str
    stats: IndexStats
    auto_dream: bool           # True if cleanup should be triggered

    def __str__(self) -> str:
        return f"[{self.level}] {self.message}"


# --------------------------------------------------------------------------- #
# Builder
# --------------------------------------------------------------------------- #


class IndexBuilder:
    """Builds and validates ``<project>/memory/INDEX.md``.

    Parameters
    ----------
    project_root:
        Directory containing ``memory/``. Must exist.
    warn_at:
        Soft threshold (lines). Defaults to 180 per ARCHITECTURE_MEMORY_V2.
    hard_limit:
        Hard line limit. Defaults to 200 (Claude Code silent-truncation).
    max_bytes:
        Byte cap (25 KB default).
    include_refs:
        When True, a "Cross-project references" section is emitted if
        ``memory/refs/`` is non-empty.
    clock:
        Injected for tests; returns an ISO-8601 UTC string.
    """

    def __init__(
        self,
        *,
        project_root: Path,
        warn_at: int = DEFAULT_WARN_AT,
        hard_limit: int = DEFAULT_HARD_LIMIT,
        max_bytes: int = DEFAULT_MAX_BYTES,
        include_refs: bool = True,
        clock=None,
    ) -> None:
        if warn_at >= hard_limit:
            raise ValueError(
                f"warn_at ({warn_at}) must be < hard_limit ({hard_limit})"
            )

        project_root = project_root.resolve(strict=True)
        self._root = (project_root / "memory")
        self._root.mkdir(parents=True, exist_ok=True, mode=0o700)
        self._root = self._root.resolve(strict=True)

        self._index_path = self._root / "INDEX.md"
        self._auto_dir = self._root / "auto"
        self._pinned_dir = self._root / "pinned"
        self._refs_dir = self._root / "refs"
        self.warn_at = warn_at
        self.hard_limit = hard_limit
        self.max_bytes = max_bytes
        self.include_refs = include_refs
        self._now = clock or (
            lambda: datetime.now(timezone.utc).isoformat(timespec="seconds")
        )

    # ------------------------------------------------------------------ #
    # Public API
    # ------------------------------------------------------------------ #

    def rebuild(self) -> IndexStats:
        """Regenerate INDEX.md from scratch. Returns the new stats.

        The new file is written atomically (``.tmp`` + ``os.replace``).
        """
        body = self._render()
        tmp = self._index_path.with_suffix(".md.tmp")
        tmp.write_text(body, encoding="utf-8")
        tmp.replace(self._index_path)
        stats = self._measure(body)
        log.info(
            "index.rebuild lines=%d bytes=%d auto=%d pinned=%d",
            stats.lines, stats.bytes, stats.auto_files, stats.pinned_count,
        )
        if stats.over_hard:
            log.error(
                "INDEX.md EXCEEDS hard limit: lines=%d hard=%d bytes=%d max=%d",
                stats.lines, stats.hard_limit, stats.bytes, stats.max_bytes,
            )
        elif stats.over_soft:
            log.warning(
                "INDEX.md approaches limit: lines=%d warn_at=%d bytes=%d",
                stats.lines, stats.warn_at, stats.bytes,
            )
        return stats

    def check(self) -> IndexWarning | None:
        """Inspect the current INDEX.md (no rebuild). Returns a warning or None."""
        if not self._index_path.exists():
            stats = IndexStats(
                lines=0, bytes=0, auto_files=0, pinned_count=0,
                warn_at=self.warn_at, hard_limit=self.hard_limit,
                max_bytes=self.max_bytes,
            )
            return None if not self._has_content() else IndexWarning(
                "warn",
                "INDEX.md missing but auto/ has files — call rebuild().",
                stats, auto_dream=False,
            )

        content = self._index_path.read_text(encoding="utf-8")
        stats = self._measure(content)

        if stats.over_hard:
            return IndexWarning(
                "critical",
                (f"INDEX.md {stats.lines} lines / {stats.bytes} bytes "
                 f"exceeds hard limit ({self.hard_limit} / "
                 f"{self.max_bytes}); Claude Code will SILENTLY truncate. "
                 f"auto_dream triggered."),
                stats, auto_dream=True,
            )
        if stats.over_soft:
            return IndexWarning(
                "warn",
                (f"INDEX.md {stats.lines}/{self.hard_limit} lines — "
                 f"approaching silent-truncation boundary. auto_dream triggered."),
                stats, auto_dream=True,
            )
        return None

    def read(self) -> str:
        """Return the current INDEX.md content (empty string if missing)."""
        if not self._index_path.exists():
            return ""
        return self._index_path.read_text(encoding="utf-8")

    def load_capped(self) -> str:
        """Return INDEX.md content capped at the *hard* limits.

        Use this when building the system prompt — callers must pass the
        result to the model (not the raw file) so we never rely on
        Claude Code's silent-truncation.
        """
        text = self.read()
        if not text:
            return ""
        lines = text.splitlines()
        if len(lines) > self.hard_limit:
            lines = lines[: self.hard_limit]
        out = "\n".join(lines)
        encoded = out.encode("utf-8")
        if len(encoded) > self.max_bytes:
            # Back off one line at a time until within the byte cap.
            while lines and len(("\n".join(lines)).encode("utf-8")) > self.max_bytes:
                lines.pop()
            out = "\n".join(lines)
        return out

    # ------------------------------------------------------------------ #
    # Rendering
    # ------------------------------------------------------------------ #

    def _render(self) -> str:
        auto_rows = self._auto_rows()
        pinned_count = self._pinned_count()
        ref_rows = self._ref_rows() if self.include_refs else []

        lines: list[str] = []
        lines.append("# Project Memory Index")
        ts = self._now()

        # We need a placeholder for stats until we know the final size;
        # use a two-pass render.
        header_marker = "<<HEADER_STATS>>"
        lines.append(f"_generated {ts} — {header_marker}_")
        lines.append("")

        lines.append("## Auto memories (model-authored)")
        if auto_rows:
            lines.extend(auto_rows)
        else:
            lines.append("_empty — no auto memory files yet._")
        lines.append("")

        lines.append("## Pinned memories (user-authored)")
        if pinned_count:
            lines.append(
                f"_{pinned_count} pins — content is in system prompt, "
                f"not duplicated here._"
            )
        else:
            lines.append("_no pinned memories._")
        lines.append("")

        if ref_rows:
            lines.append("## Cross-project references")
            lines.extend(ref_rows)
            lines.append("")

        lines.append("## Notes")
        lines.append(
            "_INDEX.md is auto-generated. Edits here are overwritten._"
        )
        lines.append(
            f"_Do not exceed {self.hard_limit} lines or {self.max_bytes} bytes "
            f"— Claude Code silently truncates past this boundary._"
        )

        body = "\n".join(lines) + "\n"

        # Second pass: fill in size-aware header.
        measured = self._measure(body)
        header_text = (
            f"{measured.lines}/{self.hard_limit} lines, "
            f"{measured.bytes / 1024:.1f}/{self.max_bytes / 1024:.1f} KB, "
            f"{measured.auto_files} auto files, "
            f"{measured.pinned_count} pins"
        )
        return body.replace(header_marker, header_text, 1)

    # ------------------------------------------------------------------ #
    # Scanners
    # ------------------------------------------------------------------ #

    def _auto_rows(self) -> list[str]:
        if not self._auto_dir.exists():
            return []
        rows: list[str] = []
        for entry in sorted(self._auto_dir.iterdir()):
            if not entry.is_file():
                continue
            if entry.name.startswith("."):
                continue
            try:
                text = entry.read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError):
                log.warning("skipping unreadable auto file %s", entry)
                continue
            line_count = text.count("\n") + (0 if text.endswith("\n") else 1)
            mtime = datetime.fromtimestamp(
                entry.stat().st_mtime, tz=timezone.utc
            ).date().isoformat()
            rows.append(
                f"- `{entry.name}` — {line_count} lines, updated {mtime}"
            )
        return rows

    def _pinned_count(self) -> int:
        if not self._pinned_dir.exists():
            return 0
        return sum(
            1 for p in self._pinned_dir.iterdir()
            if p.is_file() and p.suffix == ".md" and not p.name.startswith(".")
        )

    def _ref_rows(self) -> list[str]:
        if not self._refs_dir.exists():
            return []
        rows: list[str] = []
        for entry in sorted(self._refs_dir.iterdir()):
            if entry.is_file() and entry.suffix == ".md":
                rows.append(f"- `refs/{entry.name}`")
        return rows

    def _has_content(self) -> bool:
        return (
            (self._auto_dir.exists() and any(self._auto_dir.iterdir()))
            or (self._pinned_dir.exists() and any(self._pinned_dir.iterdir()))
        )

    # ------------------------------------------------------------------ #
    # Measurement
    # ------------------------------------------------------------------ #

    def _measure(self, content: str) -> IndexStats:
        lines = content.count("\n") + (0 if content.endswith("\n") else 1)
        encoded = len(content.encode("utf-8"))
        return IndexStats(
            lines=lines,
            bytes=encoded,
            auto_files=len(self._auto_rows()),
            pinned_count=self._pinned_count(),
            warn_at=self.warn_at,
            hard_limit=self.hard_limit,
            max_bytes=self.max_bytes,
        )


# --------------------------------------------------------------------------- #
# Self-test
# --------------------------------------------------------------------------- #


def _self_test() -> None:  # pragma: no cover
    import tempfile

    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        (root / "memory" / "auto").mkdir(parents=True)
        (root / "memory" / "pinned").mkdir(parents=True)

        builder = IndexBuilder(project_root=root, warn_at=5, hard_limit=8)

        # empty project
        stats = builder.rebuild()
        assert stats.auto_files == 0
        assert builder.check() is None

        # add a file → rebuild → still clean
        (root / "memory" / "auto" / "decisions.md").write_text(
            "# decisions\n- we chose Sonnet\n"
        )
        stats = builder.rebuild()
        assert stats.auto_files == 1
        print("index size after one file:", stats.lines, "lines,", stats.bytes, "B")

        # force over-hard
        long_content = "\n".join([f"line {i}" for i in range(50)])
        (root / "memory" / "auto" / "big.md").write_text(long_content)
        stats = builder.rebuild()
        # our index itself won't be huge; force via hard_limit=5
        builder2 = IndexBuilder(
            project_root=root, warn_at=3, hard_limit=5, max_bytes=100,
        )
        stats = builder2.rebuild()
        warning = builder2.check()
        assert warning is not None, "warning should fire"
        print("warning:", warning)

        # capped load
        capped = builder2.load_capped()
        assert len(capped.splitlines()) <= 5
        print("IndexBuilder self-test PASS")


if __name__ == "__main__":  # pragma: no cover
    logging.basicConfig(level=logging.INFO)
    _self_test()
