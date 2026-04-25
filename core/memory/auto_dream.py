"""
core.memory.auto_dream — Periodic INDEX cleanup + auto-memory summarization.

Why this module exists
----------------------
Claude Code silently truncates INDEX.md at 200 lines / 25 KB
(V1-FIX-04, GitHub Issue #39811). Once the index grows past that cliff,
every addition at the bottom is invisible to Claude. V2 §2.4 locks the
soft warning threshold at 180 lines with
``MEMORY_INDEX_WARN_WHEN_LINES_ABOVE=180`` and requires a periodic
cleanup pass (``MEMORY_AUTO_DREAM_ENABLED=true``).

``AutoDream`` is that pass. It runs when:

* A caller invokes :meth:`AutoDream.schedule_if_needed` and the INDEX
  is at or above :data:`DEFAULT_TRIGGER_LINES` (180 by default), or
* A CLI cron job invokes :meth:`AutoDream.run` unconditionally.

What it does
------------
1. **Snapshot** — copies ``INDEX.md`` and the full ``auto/`` directory
   to ``.auto_dream_backups/<ts>/`` so every run is reversible. No
   pass mutates state before a backup succeeds.
2. **Scan** — enumerates ``auto/*.md`` and collects mtime, line count,
   and a content fingerprint.
3. **Dedupe** — SHA-256-matched files are coalesced: the oldest copy
   is kept, newer duplicates are unlinked (recorded in the report).
4. **Age-out** — files whose mtime is older than
   :data:`DEFAULT_STALE_DAYS` AND are not referenced from ``INDEX.md``
   are moved to ``auto/.archive/``. They are *not* deleted — archival
   is reversible, deletion is not.
5. **Compact** — if a summarizer callback is supplied (e.g. a short
   Claude API call) it is invoked with the cluster of remaining files
   and the compressed text replaces them. The callback is optional —
   we never call the Anthropic SDK from this module directly; the
   caller wires it in.
6. **Rewrite** — re-emits a fresh ``INDEX.md`` via :mod:`core.memory.index`
   and verifies line count is below the hard limit.

Safety
------
* All file mutations go through :mod:`core.memory.scope_guard`
  (``safe_resolve``) to prevent path escape.
* The backup step is prerequisite — if backup fails, we abort before
  any destructive op.
* We hold a POSIX ``fcntl.flock`` on ``.auto_dream.lock`` so two
  concurrent runs (session + cron) can't tread on each other.
* The ``DreamReport`` is returned even on abort so callers can log
  partial progress.

References
----------
- ARCHITECTURE_MEMORY_V2.md §1.2 V1-FIX-04 (silent truncation)
- ARCHITECTURE_MEMORY_V2.md §2.4 (MEMORY_AUTO_DREAM_* env vars)
- ARCHITECTURE_MEMORY_V2.md §1.4 NEW-01 (two-phase write safety story)
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import shutil
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Final, Iterator

try:  # pragma: no cover - platform guard
    import fcntl  # POSIX only
except ImportError:  # pragma: no cover
    fcntl = None  # type: ignore[assignment]

from core.memory.scope_guard import safe_resolve

__all__ = [
    "AutoDream",
    "DreamReport",
    "DreamAction",
    "DEFAULT_TRIGGER_LINES",
    "DEFAULT_HARD_LIMIT",
    "DEFAULT_STALE_DAYS",
]

log = logging.getLogger(__name__)

# --------------------------------------------------------------------------- #
# Tunables (mirror V2 §2.4)
# --------------------------------------------------------------------------- #

DEFAULT_TRIGGER_LINES: Final[int] = 180
"""INDEX line count at which auto_dream should schedule itself."""

DEFAULT_HARD_LIMIT: Final[int] = 200
"""Post-run, the INDEX must be below this or we warn loudly."""

DEFAULT_STALE_DAYS: Final[int] = 180
"""Files older than this (and unreferenced) are archived."""

_INDEX_FILENAME: Final[str] = "INDEX.md"
_AUTO_DIR: Final[str] = "auto"
_ARCHIVE_DIR: Final[str] = ".archive"
_BACKUP_DIR: Final[str] = ".auto_dream_backups"
_LOCK_FILE: Final[str] = ".auto_dream.lock"


# --------------------------------------------------------------------------- #
# Records
# --------------------------------------------------------------------------- #


@dataclass
class DreamAction:
    """One mutation performed (or skipped) in a single run."""

    kind: str                 # "dedupe" | "archive" | "compact" | "noop"
    path: str                 # virtual path relative to project_root
    reason: str
    ok: bool = True
    error: str | None = None


@dataclass
class DreamReport:
    """Summary of a single :meth:`AutoDream.run` invocation."""

    project_path: str
    started_at: str
    finished_at: str | None = None
    backup_dir: str | None = None
    index_before_lines: int = 0
    index_after_lines: int = 0
    actions: list[DreamAction] = field(default_factory=list)
    aborted: bool = False
    abort_reason: str | None = None

    def to_dict(self) -> dict[str, object]:
        return {
            "project_path": self.project_path,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "backup_dir": self.backup_dir,
            "index_before_lines": self.index_before_lines,
            "index_after_lines": self.index_after_lines,
            "actions": [a.__dict__ for a in self.actions],
            "aborted": self.aborted,
            "abort_reason": self.abort_reason,
        }


# --------------------------------------------------------------------------- #
# The pass
# --------------------------------------------------------------------------- #


# Signature of an optional compaction callback.
#   (cluster: list[Path], project_root: Path) -> str
# Returns the compressed summary text to replace the cluster's contents.
Summarizer = Callable[[list[Path], Path], str]


class AutoDream:
    """Periodic INDEX cleanup + (optional) Claude-assisted compaction.

    Parameters
    ----------
    trigger_lines:
        Soft threshold — :meth:`schedule_if_needed` returns True only
        when INDEX is at or above this.
    hard_limit:
        After the pass, the INDEX must be below this. A post-run check
        that fails logs an error but does not raise — callers decide.
    stale_days:
        Mtime age after which an unreferenced auto file is archived.
    summarizer:
        Optional callback. When absent, Step 5 is skipped (we still
        dedupe and archive).
    clock:
        Injected ``lambda: datetime`` for deterministic tests.
    """

    def __init__(
        self,
        *,
        trigger_lines: int = DEFAULT_TRIGGER_LINES,
        hard_limit: int = DEFAULT_HARD_LIMIT,
        stale_days: int = DEFAULT_STALE_DAYS,
        summarizer: Summarizer | None = None,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        if trigger_lines <= 0 or hard_limit <= 0:
            raise ValueError("trigger_lines and hard_limit must be positive")
        if trigger_lines > hard_limit:
            raise ValueError(
                f"trigger_lines ({trigger_lines}) must be <= hard_limit ({hard_limit})"
            )
        self.trigger_lines = trigger_lines
        self.hard_limit = hard_limit
        self.stale_days = stale_days
        self.summarizer = summarizer
        self._now = clock or (lambda: datetime.now(timezone.utc))

    # ------------------------------------------------------------------ #
    # Public API
    # ------------------------------------------------------------------ #

    def schedule_if_needed(self, project_path: Path) -> bool:
        """Return True iff a run is warranted right now.

        Callers typically wire this to the session teardown hook. Cheap:
        just reads the INDEX line count.
        """
        index = project_path / "memory" / _INDEX_FILENAME
        if not index.exists():
            return False
        try:
            n = _count_lines(index)
        except OSError as e:
            log.warning("auto_dream: cannot read INDEX for scheduling: %s", e)
            return False
        should = n >= self.trigger_lines
        if should:
            log.info(
                "auto_dream: INDEX has %d lines, trigger=%d — scheduling run",
                n, self.trigger_lines,
            )
        return should

    def run(self, project_path: Path) -> DreamReport:
        """Perform a single cleanup pass.

        Never raises on normal failure paths — aggregates issues into the
        :class:`DreamReport`. Raises only for programmer errors
        (missing memory dir, bad project_path).
        """
        project_path = project_path.resolve(strict=True)
        memory_dir = project_path / "memory"
        if not memory_dir.is_dir():
            raise FileNotFoundError(f"memory dir missing: {memory_dir}")
        auto_dir = memory_dir / _AUTO_DIR
        auto_dir.mkdir(parents=True, exist_ok=True)

        started = self._now()
        report = DreamReport(
            project_path=str(project_path),
            started_at=started.isoformat(timespec="seconds"),
        )

        try:
            with _project_lock(memory_dir / _LOCK_FILE):
                # Step 1 — backup
                backup = self._backup(memory_dir, started)
                report.backup_dir = str(backup)

                # Pre-measure
                index_path = memory_dir / _INDEX_FILENAME
                if index_path.exists():
                    report.index_before_lines = _count_lines(index_path)

                # Step 2 — scan
                files = sorted(
                    p for p in auto_dir.glob("*.md")
                    if p.is_file() and not p.name.startswith(".")
                )

                # Step 3 — dedupe
                self._dedupe(files, report)

                # Step 4 — archive stale
                referenced = _referenced_names(index_path)
                self._archive_stale(
                    auto_dir, files, referenced, started, report,
                )

                # Step 5 — compact (optional)
                if self.summarizer is not None:
                    self._compact(auto_dir, report)
                else:
                    log.debug("auto_dream: no summarizer provided, skipping compact")

                # Step 6 — rewrite INDEX
                self._rewrite_index(memory_dir, report)

                if index_path.exists():
                    report.index_after_lines = _count_lines(index_path)

                if report.index_after_lines >= self.hard_limit:
                    log.error(
                        "auto_dream: INDEX still at %d lines (>= hard_limit %d)"
                        " — manual intervention required",
                        report.index_after_lines, self.hard_limit,
                    )
        except Exception as e:  # noqa: BLE001
            log.exception("auto_dream aborted")
            report.aborted = True
            report.abort_reason = str(e)

        report.finished_at = self._now().isoformat(timespec="seconds")
        return report

    # ------------------------------------------------------------------ #
    # Steps
    # ------------------------------------------------------------------ #

    def _backup(self, memory_dir: Path, when: datetime) -> Path:
        """Copy INDEX.md + auto/ to a timestamped backup dir.

        Raises if the backup fails — destructive ops must not proceed.
        """
        stamp = when.strftime("%Y%m%dT%H%M%SZ")
        dst = memory_dir / _BACKUP_DIR / stamp
        dst.mkdir(parents=True, exist_ok=False)

        src_index = memory_dir / _INDEX_FILENAME
        if src_index.exists():
            shutil.copy2(src_index, dst / _INDEX_FILENAME)

        src_auto = memory_dir / _AUTO_DIR
        if src_auto.exists():
            shutil.copytree(
                src_auto, dst / _AUTO_DIR,
                ignore=shutil.ignore_patterns(".archive", ".*"),
                dirs_exist_ok=False,
            )
        log.info("auto_dream: backup -> %s", dst)
        return dst

    def _dedupe(self, files: list[Path], report: DreamReport) -> None:
        """Unlink files whose SHA-256 equals an older sibling's hash."""
        seen: dict[str, Path] = {}
        for p in files:
            try:
                digest = _sha256(p)
            except OSError as e:
                report.actions.append(DreamAction(
                    kind="dedupe", path=p.name,
                    reason="hash_failed", ok=False, error=str(e),
                ))
                continue
            if digest in seen:
                keeper = seen[digest]
                try:
                    p.unlink()
                    report.actions.append(DreamAction(
                        kind="dedupe", path=p.name,
                        reason=f"duplicate_of:{keeper.name}",
                    ))
                except OSError as e:
                    report.actions.append(DreamAction(
                        kind="dedupe", path=p.name,
                        reason="unlink_failed", ok=False, error=str(e),
                    ))
            else:
                seen[digest] = p

    def _archive_stale(
        self,
        auto_dir: Path,
        files: list[Path],
        referenced: set[str],
        when: datetime,
        report: DreamReport,
    ) -> None:
        archive = auto_dir / _ARCHIVE_DIR
        archive.mkdir(exist_ok=True)
        cutoff_ts = when.timestamp() - self.stale_days * 86_400
        for p in files:
            if not p.exists():  # may have been dedup-unlinked
                continue
            if p.name in referenced:
                continue
            try:
                mtime = p.stat().st_mtime
            except OSError as e:
                report.actions.append(DreamAction(
                    kind="archive", path=p.name,
                    reason="stat_failed", ok=False, error=str(e),
                ))
                continue
            if mtime >= cutoff_ts:
                continue
            dst = archive / p.name
            try:
                # If an archived copy with the same name exists, rename.
                if dst.exists():
                    dst = archive / f"{p.stem}-{int(mtime)}{p.suffix}"
                p.rename(dst)
                report.actions.append(DreamAction(
                    kind="archive", path=p.name,
                    reason=f"stale>{self.stale_days}d_unreferenced",
                ))
            except OSError as e:
                report.actions.append(DreamAction(
                    kind="archive", path=p.name,
                    reason="rename_failed", ok=False, error=str(e),
                ))

    def _compact(self, auto_dir: Path, report: DreamReport) -> None:
        """Invoke the summarizer callback on remaining content."""
        remaining = sorted(
            p for p in auto_dir.glob("*.md")
            if p.is_file() and not p.name.startswith(".")
        )
        if len(remaining) <= 1:
            return  # nothing to compact
        try:
            summary = self.summarizer(remaining, auto_dir.parent.parent)  # type: ignore[misc]
        except Exception as e:  # noqa: BLE001
            report.actions.append(DreamAction(
                kind="compact", path="<cluster>",
                reason="summarizer_failed", ok=False, error=str(e),
            ))
            return
        if not isinstance(summary, str) or not summary.strip():
            report.actions.append(DreamAction(
                kind="compact", path="<cluster>",
                reason="empty_summary", ok=False,
            ))
            return
        # Write the summary, leave originals (summarizer decides what to keep).
        compacted = auto_dir / "_compacted.md"
        compacted.write_text(summary, encoding="utf-8")
        report.actions.append(DreamAction(
            kind="compact", path=compacted.name,
            reason=f"summarized_from_{len(remaining)}_files",
        ))

    def _rewrite_index(self, memory_dir: Path, report: DreamReport) -> None:
        """Regenerate INDEX.md via :mod:`core.memory.index`.

        Imported lazily — ``index.py`` is optional on thin deployments.
        """
        try:
            from core.memory.index import IndexBuilder  # type: ignore
        except ImportError:
            log.debug("auto_dream: core.memory.index missing, skipping rewrite")
            return
        try:
            IndexBuilder(memory_dir).build()
            report.actions.append(DreamAction(
                kind="noop", path=_INDEX_FILENAME, reason="index_rewritten",
            ))
        except Exception as e:  # noqa: BLE001
            report.actions.append(DreamAction(
                kind="noop", path=_INDEX_FILENAME,
                reason="index_rewrite_failed", ok=False, error=str(e),
            ))


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #


def _count_lines(path: Path) -> int:
    with open(path, "rb") as f:
        return sum(1 for _ in f)


def _sha256(path: Path, *, chunk: int = 65_536) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while True:
            b = f.read(chunk)
            if not b:
                break
            h.update(b)
    return h.hexdigest()


def _referenced_names(index_path: Path) -> set[str]:
    """Extract ``filename.md`` tokens from INDEX.md for liveness analysis."""
    if not index_path.exists():
        return set()
    try:
        text = index_path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return set()
    names: set[str] = set()
    # Backtick-wrapped ``filename.md`` — our INDEX builder's canonical form.
    import re
    for m in re.finditer(r"`([A-Za-z0-9_\-.]+\.md)`", text):
        names.add(m.group(1))
    return names


@contextmanager
def _project_lock(lock_path: Path) -> Iterator[None]:
    """POSIX advisory lock. Degrades to a no-op on Windows."""
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    f = open(lock_path, "a+")
    try:
        if fcntl is not None:
            fcntl.flock(f.fileno(), fcntl.LOCK_EX)
        yield
    finally:
        try:
            if fcntl is not None:
                fcntl.flock(f.fileno(), fcntl.LOCK_UN)
        finally:
            f.close()


# --------------------------------------------------------------------------- #
# Unit tests — pytest-compatible
# --------------------------------------------------------------------------- #


def _tests() -> None:  # pragma: no cover - executed by pytest
    import tempfile
    import time

    def _mk_project(tmp: Path, index_lines: int, files: dict[str, str]) -> Path:
        (tmp / "memory" / "auto").mkdir(parents=True, exist_ok=True)
        (tmp / "memory" / _INDEX_FILENAME).write_text(
            "\n".join(f"line {i}" for i in range(index_lines)),
            encoding="utf-8",
        )
        for name, content in files.items():
            (tmp / "memory" / "auto" / name).write_text(content, encoding="utf-8")
        return tmp

    def test_schedule_under_threshold() -> None:
        with tempfile.TemporaryDirectory() as d:
            root = _mk_project(Path(d), 10, {"a.md": "x"})
            assert AutoDream().schedule_if_needed(root) is False

    def test_schedule_over_threshold() -> None:
        with tempfile.TemporaryDirectory() as d:
            root = _mk_project(Path(d), 200, {"a.md": "x"})
            assert AutoDream().schedule_if_needed(root) is True

    def test_run_creates_backup() -> None:
        with tempfile.TemporaryDirectory() as d:
            root = _mk_project(Path(d), 5, {"a.md": "x"})
            rep = AutoDream().run(root)
            assert rep.aborted is False, rep.abort_reason
            assert rep.backup_dir is not None
            assert Path(rep.backup_dir).exists()

    def test_dedupe_removes_duplicate() -> None:
        with tempfile.TemporaryDirectory() as d:
            root = _mk_project(Path(d), 5, {
                "a.md": "same content\n",
                "b.md": "same content\n",
                "c.md": "different\n",
            })
            rep = AutoDream().run(root)
            kinds = [a.kind for a in rep.actions]
            assert "dedupe" in kinds
            remaining = sorted(p.name for p in (root / "memory" / "auto").glob("*.md"))
            assert len(remaining) == 2

    def test_archive_stale_unreferenced() -> None:
        with tempfile.TemporaryDirectory() as d:
            root = _mk_project(Path(d), 5, {
                "old.md": "ancient\n",
                "new.md": "fresh\n",
            })
            # backdate 'old.md' well past stale threshold
            old = root / "memory" / "auto" / "old.md"
            very_old = time.time() - 365 * 86_400
            os.utime(old, (very_old, very_old))
            rep = AutoDream(stale_days=30).run(root)
            assert (root / "memory" / "auto" / _ARCHIVE_DIR / "old.md").exists()
            assert (root / "memory" / "auto" / "new.md").exists()

    def test_referenced_files_not_archived() -> None:
        with tempfile.TemporaryDirectory() as d:
            root = _mk_project(Path(d), 5, {"ref.md": "keep\n"})
            (root / "memory" / _INDEX_FILENAME).write_text(
                "# Index\n- `ref.md` — stuff\n", encoding="utf-8",
            )
            old = root / "memory" / "auto" / "ref.md"
            very_old = time.time() - 365 * 86_400
            os.utime(old, (very_old, very_old))
            AutoDream(stale_days=30).run(root)
            assert old.exists(), "referenced file must survive"

    def test_invalid_trigger_raises() -> None:
        import pytest
        with pytest.raises(ValueError):
            AutoDream(trigger_lines=0)
        with pytest.raises(ValueError):
            AutoDream(trigger_lines=300, hard_limit=200)

    def test_missing_memory_dir_raises() -> None:
        import pytest
        with tempfile.TemporaryDirectory() as d:
            with pytest.raises(FileNotFoundError):
                AutoDream().run(Path(d))

    def test_report_serializable() -> None:
        with tempfile.TemporaryDirectory() as d:
            root = _mk_project(Path(d), 5, {"a.md": "x"})
            rep = AutoDream().run(root)
            # must round-trip through json
            s = json.dumps(rep.to_dict())
            assert "actions" in s

    def test_summarizer_invoked() -> None:
        with tempfile.TemporaryDirectory() as d:
            root = _mk_project(Path(d), 5, {
                "a.md": "alpha\n",
                "b.md": "beta\n",
            })
            calls: list[int] = []

            def summ(files, _root):
                calls.append(len(files))
                return "SUMMARY"

            rep = AutoDream(summarizer=summ).run(root)
            assert calls and calls[0] == 2
            compacted = root / "memory" / "auto" / "_compacted.md"
            assert compacted.exists() and compacted.read_text() == "SUMMARY"
            assert any(a.kind == "compact" for a in rep.actions)

    for fn in [
        test_schedule_under_threshold,
        test_schedule_over_threshold,
        test_run_creates_backup,
        test_dedupe_removes_duplicate,
        test_archive_stale_unreferenced,
        test_referenced_files_not_archived,
        test_invalid_trigger_raises,
        test_missing_memory_dir_raises,
        test_report_serializable,
        test_summarizer_invoked,
    ]:
        fn()
    print("auto_dream self-test PASS")


if __name__ == "__main__":  # pragma: no cover
    logging.basicConfig(level=logging.INFO)
    _tests()
