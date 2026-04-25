"""
core.memory.initializer — Load the 5 memory layers, return a ready prompt.

This is the top-level entry point used by every surface (Telegram bot,
web UI, CLI) at the *start* of a session. It turns a resolved project
into:

* a locked :class:`core.memory.session_lock.SessionLock` (layer 3 enforcement)
* a configured :class:`core.memory.tool.MemoryTool` scoped to that project
* a :class:`core.memory.pinned.PinnedMemoryAPI` for user-authored pins
* an :class:`core.memory.index.IndexBuilder` that keeps INDEX.md fresh
* the fully-assembled system prompt with L0..L4 concatenated in order
* the minimal tool-config + beta-header dict needed for the Anthropic API

The initializer is the load-bearing piece the spec calls out in §4.6. It:

* Runs **all 4 enforcement layers** (filesystem perms, path scoping,
  session lock, audit) before the first model call.
* Respects the **5-layer load order** (L0 → L4) so that "later overrides
  earlier" (Anthropic's own phrasing).
* Honours **incognito mode** (``memory_20250818`` disabled; pinned still
  loaded for user UX; audit still recorded).
* Caps INDEX.md at 200 lines / 25 KB on read (:mod:`core.memory.index`) so
  we never rely on Claude Code's silent truncation.
* Enforces the **session memory budget** (V2 NEW-02): the caller is
  notified when the assembled prompt exceeds ``SESSION_MEMORY_BUDGET_KB``.

All side effects (directory creation, ``chmod``, audit entries) happen in
:meth:`MemoryInitializer.init_session`. Construction is pure.

Layer sources
-------------
L0 — Global Conventions
    ``<conventions_path>`` (default ``/data/CONVENTIONS.md``).
    Always loaded. Admin-authored. Single source of truth for
    cross-project rules like "never reveal other clients".
L1 — User CLAUDE.md
    ``<users_root>/<user_id>/CLAUDE.md``. Loaded only in non-incognito.
L2 — Skills
    ``<skills_root>/*.md`` — optionally filtered by the relevance
    function the caller provides. If none provided, we skip L2 (the
    skills directory is typically large).
L3 — Project Bundle
    ``<project_root>/CLAUDE.md``           (L3.a)
    ``<project_root>/memory/INDEX.md``     (L3.c+d index, capped)
    pinned content block                   (L3.d)
L4 — Session scratch
    ``<project_root>/sessions/{session_id}.jsonl`` — NOT loaded here by
    default; the caller injects resumed messages into the message list,
    not the system prompt.
"""

from __future__ import annotations

import logging
import os
import stat
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Final

from core.memory.audit import AuditLogger
from core.memory.index import IndexBuilder, IndexWarning
from core.memory.pinned import PinnedMemoryAPI
from core.memory.project_resolver import ResolvedProject, resolve
from core.memory.session_lock import (
    DEFAULT_CLEANUP_PERIOD_DAYS,
    SessionLock,
    new_session_id,
)
from core.memory.tool import MemoryTool

# ``AutoMemory`` wraps the SDK if available; optional at import time.
try:
    from core.memory.auto import AutoMemory  # type: ignore
except Exception:  # pragma: no cover - defensive
    AutoMemory = None  # type: ignore

__all__ = [
    "MemoryInitializer",
    "SessionContext",
    "SESSION_MEMORY_BUDGET_KB",
    "SESSION_MEMORY_BUDGET_WARN_AT",
]

log = logging.getLogger(__name__)

# --------------------------------------------------------------------------- #
# Defaults
# --------------------------------------------------------------------------- #

SESSION_MEMORY_BUDGET_KB: Final[int] = int(
    os.environ.get("SESSION_MEMORY_BUDGET_KB", "30")
)
SESSION_MEMORY_BUDGET_WARN_AT: Final[int] = int(
    os.environ.get("SESSION_MEMORY_BUDGET_WARN_AT", "24")
)
_DEFAULT_PROJECTS_ROOT = Path(
    os.environ.get("PROJECTS_ROOT", "/data/projects")
)
_DEFAULT_USERS_ROOT = Path(os.environ.get("USERS_ROOT", "/data/users"))
_DEFAULT_SKILLS_ROOT = Path(os.environ.get("SKILLS_ROOT", "/data/skills"))
_DEFAULT_CONVENTIONS = Path(
    os.environ.get("CONVENTIONS_PATH", "/data/CONVENTIONS.md")
)
_EXPECTED_MODE: Final[int] = 0o700


# --------------------------------------------------------------------------- #
# Context object
# --------------------------------------------------------------------------- #


@dataclass
class SessionContext:
    """Everything a request handler needs to talk to the model.

    Returned by :meth:`MemoryInitializer.init_session`. Hold onto the
    whole object for the session lifetime — when the session ends, call
    :meth:`close`.
    """
    session_id: str
    resolved: ResolvedProject
    project_root: Path
    system_prompt: str
    tool_config: dict[str, str]
    beta_headers: dict[str, str]
    memory_tool: MemoryTool | None       # None in incognito
    auto_memory: Any | None              # AutoMemory wrapper or None
    pinned_api: PinnedMemoryAPI
    index_builder: IndexBuilder
    audit: AuditLogger
    session_lock: SessionLock
    warnings: list[str] = field(default_factory=list)
    incognito: bool = False
    prompt_bytes: int = 0

    # -- lifecycle --

    def close(self, *, reason: str = "session_end") -> None:
        """Release resources and record the session close in the audit log."""
        try:
            self.audit.log(
                self.resolved.slug,
                self.resolved.user_id,
                "session_end",
                session_id=self.session_id,
                meta={"reason": reason, "incognito": self.incognito},
            )
        except Exception:  # noqa: BLE001
            log.exception("audit on close failed")
        # AUDIT-MEM-005: Hook AutoDream to session lifecycle.
        # Runs only when MEMORY_AUTO_DREAM_ENABLED=true (default in .env).
        if os.getenv("MEMORY_AUTO_DREAM_ENABLED", "false").lower() == "true":
            try:
                from core.memory.auto_dream import AutoDream  # lazy import
                trigger = int(os.getenv("MEMORY_AUTO_DREAM_TRIGGER_LINES", "180"))
                hard = int(os.getenv("MEMORY_INDEX_MAX_LINES", "200"))
                dream = AutoDream(trigger_lines=trigger, hard_limit=hard)
                if dream.schedule_if_needed(self.resolved.root):
                    report = dream.run(self.resolved.root)
                    log.info("auto_dream ran: %s", report)
                    try:
                        self.audit.log(
                            self.resolved.slug,
                            self.resolved.user_id,
                            "auto_dream_run",
                            session_id=self.session_id,
                            meta={"report": str(report)},
                        )
                    except Exception:  # noqa: BLE001
                        pass
            except Exception:  # noqa: BLE001
                log.warning("auto_dream scheduling failed — non-fatal")
        try:
            self.session_lock.release()
        except Exception:  # noqa: BLE001
            log.exception("lock release failed")


# --------------------------------------------------------------------------- #
# Initializer
# --------------------------------------------------------------------------- #


class MemoryInitializer:
    """Builds a :class:`SessionContext` from a context dict.

    Parameters
    ----------
    projects_root, users_root, skills_root:
        Override storage roots (default to env vars).
    conventions_path:
        Location of the L0 CONVENTIONS.md.
    policy:
        Parsed ``memory_policy.yaml`` dict passed down to MemoryTool /
        PinnedMemoryAPI. Optional — each callee has sensible defaults.
    skill_selector:
        Optional callable ``(ctx_dict, available_paths) -> list[Path]``.
        Gives the caller control over which L2 skills load (path-scoped
        — the spec's term). When omitted, we skip L2.
    cleanup_period_days:
        Forwarded to :class:`SessionLock`; passed through
        ``sanitize_cleanup_period_days`` so ``0`` becomes forever.
    """

    def __init__(
        self,
        *,
        projects_root: Path | None = None,
        users_root: Path | None = None,
        skills_root: Path | None = None,
        conventions_path: Path | None = None,
        policy: dict[str, Any] | None = None,
        skill_selector: Callable[
            [dict[str, Any], list[Path]], list[Path]
        ] | None = None,
        cleanup_period_days: int = DEFAULT_CLEANUP_PERIOD_DAYS,
    ) -> None:
        self.projects_root = (projects_root or _DEFAULT_PROJECTS_ROOT)
        self.users_root = (users_root or _DEFAULT_USERS_ROOT)
        self.skills_root = (skills_root or _DEFAULT_SKILLS_ROOT)
        self.conventions_path = (conventions_path or _DEFAULT_CONVENTIONS)
        self.policy = policy or {}
        self.skill_selector = skill_selector
        self.cleanup_period_days = cleanup_period_days

    # ------------------------------------------------------------------ #
    # Public API
    # ------------------------------------------------------------------ #

    def init_session(
        self,
        *,
        system: str,
        entity_type: str,
        entity_id: str,
        user_id: str,
        anchor_path: Path | None = None,
        incognito: bool = False,
        ctx: dict[str, Any] | None = None,
        session_id: str | None = None,
    ) -> SessionContext:
        """Resolve → lock → load layers → assemble prompt.

        Parameters
        ----------
        system, entity_type, entity_id:
            Passed straight to :func:`project_resolver.resolve`.
        user_id:
            Acting user.
        anchor_path:
            Stable filesystem anchor (see project_resolver docstring).
        incognito:
            When True: auto-memory tool is NOT built, the memory
            directory is still readable (for pinned), but no auto
            writes take place. Audit stays on per V2 MISSING-07.
        ctx:
            Free-form context dict — passed to ``skill_selector`` for L2
            filtering and otherwise ignored.
        session_id:
            Optional pre-allocated UUID (for resume). Defaults to a
            fresh uuid4 via :func:`new_session_id`.
        """
        ctx = ctx or {}
        session_id = session_id or new_session_id()

        # 1. Resolve → hashed slug
        resolved = resolve(
            system=system,
            entity_type=entity_type,
            entity_id=entity_id,
            user_id=user_id,
            anchor_path=anchor_path,
        )
        project_root = self.projects_root / resolved.slug
        project_root.mkdir(parents=True, exist_ok=True, mode=_EXPECTED_MODE)

        # 2. Layer-1 enforcement: filesystem perms
        warnings: list[str] = []
        self._enforce_permissions(project_root, warnings)

        # 3. Audit: always, even in incognito
        audit = AuditLogger(project_root)
        audit.log(
            resolved.slug,
            user_id,
            "session_start",
            session_id=session_id,
            meta={"incognito": incognito, "system": system},
        )

        # 4. Layer-3 enforcement: session lock (readonly after freeze)
        lock = SessionLock(
            project_root=project_root,
            project_slug=resolved.slug,
            user_id=user_id,
            session_id=session_id,
            cleanup_period_days=self.cleanup_period_days,
        )
        lock.acquire()
        lock.freeze()

        # 5. Core APIs (memory dirs are created here)
        self._ensure_memory_dirs(project_root)

        pinned = PinnedMemoryAPI(
            project_slug=resolved.slug,
            project_root=project_root,
            policy=self.policy,
        )
        index = IndexBuilder(project_root=project_root)

        memory_tool: MemoryTool | None = None
        auto_mem: Any | None = None
        if not incognito:
            memory_tool = MemoryTool(
                project_slug=resolved.slug,
                project_root=project_root,
                user=user_id,
                session_id=session_id,
                policy=self.policy,
                audit_path=project_root / ".audit.log",
            )
            if AutoMemory is not None:
                try:
                    auto_mem = AutoMemory(
                        project_slug=resolved.slug,
                        project_root=project_root,
                        user=user_id,
                        session_id=session_id,
                        policy=self.policy,
                        audit_path=project_root / ".audit.log",
                    )
                except Exception as e:  # noqa: BLE001
                    log.warning("AutoMemory unavailable: %s", e)
                    auto_mem = None

        # 6. Layer assembly (L0 → L4)
        parts: list[str] = []
        self._append(parts, self._load_l0(), "L0 CONVENTIONS")
        if not incognito:
            self._append(parts, self._load_l1(user_id), "L1 user prefs")
        self._append(parts, self._load_l2(ctx), "L2 skills")
        self._append(
            parts, self._load_l3_project_claude(project_root), "L3.a project CLAUDE.md"
        )
        self._append(
            parts, self._load_l3_index(index, warnings), "L3 INDEX.md"
        )
        self._append(
            parts, self._load_l3_pinned(pinned), "L3.d pinned"
        )
        # L4 (session transcript resume) is returned as a note only — the
        # caller is responsible for injecting transcript messages as
        # `messages=` not as part of the system prompt.

        system_prompt = "\n\n".join(p for p in parts if p).strip() + "\n"
        prompt_bytes = len(system_prompt.encode("utf-8"))
        self._check_budget(prompt_bytes, warnings)

        log.info(
            "session init slug=%s user=%s session=%s incognito=%s bytes=%d",
            resolved.slug, user_id, session_id, incognito, prompt_bytes,
        )

        return SessionContext(
            session_id=session_id,
            resolved=resolved,
            project_root=project_root,
            system_prompt=system_prompt,
            tool_config=MemoryTool.tool_config(),
            beta_headers=MemoryTool.beta_header(),
            memory_tool=memory_tool,
            auto_memory=auto_mem,
            pinned_api=pinned,
            index_builder=index,
            audit=audit,
            session_lock=lock,
            warnings=warnings,
            incognito=incognito,
            prompt_bytes=prompt_bytes,
        )

    # ------------------------------------------------------------------ #
    # Layer loaders
    # ------------------------------------------------------------------ #

    def _load_l0(self) -> str:
        return self._read_if_exists(self.conventions_path, label="L0")

    def _load_l1(self, user_id: str) -> str:
        p = self.users_root / user_id / "CLAUDE.md"
        return self._read_if_exists(p, label=f"L1 user={user_id}")

    def _load_l2(self, ctx: dict[str, Any]) -> str:
        if self.skill_selector is None or not self.skills_root.exists():
            return ""
        candidates = sorted(
            p for p in self.skills_root.glob("*.md") if p.is_file()
        )
        if not candidates:
            return ""
        try:
            chosen = self.skill_selector(ctx, candidates)
        except Exception:  # noqa: BLE001
            log.exception("skill_selector raised; skipping L2")
            return ""

        if not chosen:
            return ""

        # Always prepend a section header so the model knows the boundary.
        blocks = ["## Skills (L2 — path-scoped)"]
        for path in chosen:
            # defence-in-depth: each chosen path must still live under skills_root
            try:
                path.resolve().relative_to(self.skills_root.resolve())
            except (ValueError, FileNotFoundError):
                log.warning("L2 skill %s escapes skills_root; skipped", path)
                continue
            blocks.append(f"### {path.stem}\n")
            blocks.append(self._read_if_exists(path, label=f"L2 skill {path.name}"))
        return "\n".join(b for b in blocks if b)

    def _load_l3_project_claude(self, project_root: Path) -> str:
        return self._read_if_exists(
            project_root / "CLAUDE.md", label="L3.a project CLAUDE.md"
        )

    def _load_l3_index(
        self, index: IndexBuilder, warnings: list[str]
    ) -> str:
        w: IndexWarning | None = index.check()
        if w:
            warnings.append(str(w))
            log.warning("%s", w)
            if w.auto_dream:
                # Non-blocking: caller can inspect warnings and decide.
                log.info("auto_dream recommended for slug")
        capped = index.load_capped()
        if not capped:
            return ""
        return "## Project memory index (L3 — capped at 200 lines / 25 KB)\n" + capped

    def _load_l3_pinned(self, pinned: PinnedMemoryAPI) -> str:
        block = pinned.render_system_prompt_block()
        return block if block else ""

    # ------------------------------------------------------------------ #
    # Helpers
    # ------------------------------------------------------------------ #

    def _enforce_permissions(
        self, project_root: Path, warnings: list[str]
    ) -> None:
        """Check 0700 on the project dir; chmod if we can, warn if we can't."""
        try:
            st = project_root.stat()
            current = stat.S_IMODE(st.st_mode)
            if current != _EXPECTED_MODE:
                try:
                    project_root.chmod(_EXPECTED_MODE)
                    log.info(
                        "chmod project_root %s from %o to %o",
                        project_root, current, _EXPECTED_MODE,
                    )
                except PermissionError:
                    warnings.append(
                        f"project_root {project_root} has mode {current:o} "
                        f"(expected {_EXPECTED_MODE:o}); chmod failed"
                    )
        except FileNotFoundError:
            # mkdir just above us would have created it; re-raise real issues.
            raise

    def _ensure_memory_dirs(self, project_root: Path) -> None:
        for sub in (
            "memory",
            "memory/auto",
            "memory/pinned",
            "memory/refs",
            "memory/.staging",
            "sessions",
            "files/uploads",
            "files/drafts",
            "files/final",
        ):
            (project_root / sub).mkdir(parents=True, exist_ok=True, mode=0o700)

    def _read_if_exists(self, path: Path, *, label: str) -> str:
        try:
            if not path.exists():
                return ""
            if not path.is_file():
                log.debug("%s at %s is not a file; skipping", label, path)
                return ""
            return path.read_text(encoding="utf-8").rstrip() + "\n"
        except (OSError, UnicodeDecodeError) as e:
            log.warning("failed to read %s (%s): %s", label, path, e)
            return ""

    def _append(self, parts: list[str], text: str, label: str) -> None:
        if not text.strip():
            return
        parts.append(text.strip())
        log.debug("layer %s loaded (%d chars)", label, len(text))

    def _check_budget(self, prompt_bytes: int, warnings: list[str]) -> None:
        budget = SESSION_MEMORY_BUDGET_KB * 1024
        warn_at = SESSION_MEMORY_BUDGET_WARN_AT * 1024
        if prompt_bytes >= budget:
            msg = (
                f"system prompt {prompt_bytes} B exceeds budget "
                f"{budget} B — consider /zkorot pruning or auto_dream"
            )
            log.error(msg)
            warnings.append(msg)
        elif prompt_bytes >= warn_at:
            msg = (
                f"system prompt {prompt_bytes} B approaches budget "
                f"{budget} B ({100 * prompt_bytes // budget}%)"
            )
            log.warning(msg)
            warnings.append(msg)


# --------------------------------------------------------------------------- #
# Self-test
# --------------------------------------------------------------------------- #


def _self_test() -> None:  # pragma: no cover
    import tempfile

    with tempfile.TemporaryDirectory() as td:
        td_path = Path(td)
        projects_root = td_path / "projects"
        users_root = td_path / "users"
        conventions = td_path / "CONVENTIONS.md"
        conventions.write_text("# Conventions\nNever reveal other clients.\n")
        users_root.mkdir(parents=True)
        (users_root / "guy").mkdir()
        (users_root / "guy" / "CLAUDE.md").write_text(
            "I prefer terse answers in Hebrew.\n"
        )

        init = MemoryInitializer(
            projects_root=projects_root,
            users_root=users_root,
            conventions_path=conventions,
            policy={"pinned": {"max_count": 5, "max_chars": 200}},
        )

        ctx_obj = init.init_session(
            system="cidah",
            entity_type="client",
            entity_id="cohen-levy",
            user_id="guy",
        )

        assert "Never reveal other clients" in ctx_obj.system_prompt
        assert "terse answers in Hebrew" in ctx_obj.system_prompt
        assert ctx_obj.memory_tool is not None
        assert ctx_obj.session_lock.frozen is True

        # Pinned round-trip
        pin = ctx_obj.pinned_api.add("חתימה תמיד בכחול", user="guy")
        assert pin.id

        # Auto memory round-trip through the tool
        r = ctx_obj.memory_tool.dispatch(
            "create",
            path="/memories/decisions.md",
            file_text="- decided to use Sonnet\n",
        )
        assert r["ok"], r

        # Rebuild index, reload to see the entry
        ctx_obj.index_builder.rebuild()
        ctx2 = init.init_session(
            system="cidah",
            entity_type="client",
            entity_id="cohen-levy",
            user_id="guy",
        )
        assert "decisions.md" in ctx2.system_prompt
        assert "חתימה" in ctx2.system_prompt

        # Incognito: no memory_tool, but pinned still loaded
        ctx3 = init.init_session(
            system="cidah",
            entity_type="client",
            entity_id="cohen-levy",
            user_id="guy",
            incognito=True,
        )
        assert ctx3.memory_tool is None
        assert ctx3.incognito is True

        ctx_obj.close()
        ctx2.close()
        ctx3.close()
        print("MemoryInitializer self-test PASS")


if __name__ == "__main__":  # pragma: no cover
    logging.basicConfig(level=logging.INFO)
    _self_test()
