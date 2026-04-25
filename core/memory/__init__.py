"""
core.memory — L3 Project Bundle memory backend (V2).

Implements the client-side backend for Anthropic's ``memory_20250818`` tool,
plus the custom PinnedMemory API, project resolver, session lock, and
path-scope guard.

Canonical references
--------------------
- ARCHITECTURE_MEMORY_V2.md           (this bundle's normative spec)
- memory/CONVENTIONS.md               (L0 Global Conventions — always loaded)
- Anthropic docs:
  https://docs.anthropic.com/en/docs/build-with-claude/tools/memory
- CVE-2026-34451 (TS SDK path traversal) — mitigated in ``scope_guard``
- GitHub Issue #39811 (silent truncation) — mitigated via INDEX caps in tool
- GitHub Issue #1985 / #7702             — mitigated in ``session_lock``
- GitHub Issue #19972                    — mitigated in ``project_resolver``
- Cisco "Memory Poisoning" (2025)        — mitigated via sanitizer in ``tool``

Modules (current V2 scope)
--------------------------
- scope_guard      : Path traversal + symlink + URL-decode + NFKC defense.
- tool             : ``MemoryTool`` — 6-command dispatcher over ``/memories``.
- pinned           : ``PinnedMemoryAPI`` — user-authored pinned entries.
- project_resolver : ``resolve()`` — context -> hashed slug (worktree-safe).
- session_lock     : ``SessionLock`` + ``session_scope`` — readonly binding.

Reserved for future modules (not yet present; import-safe if missing)
---------------------------------------------------------------------
- auto             : BetaAbstractMemoryTool wrapper (SDK-dependent).
- index            : IndexBuilder + 180/200-line truncation warn.
- sanitizer        : Standalone sanitizer (currently inlined in tool/pinned).
- initializer      : MemoryInitializer that loads L0..L4 and returns a prompt.
- staging          : Two-phase .staging/ helpers (currently inlined in tool).
- auto_dream       : Periodic INDEX cleanup / summarization.
- budget           : SESSION_MEMORY_BUDGET_KB enforcement.
- acl              : access.json reader.

Why conditional imports
-----------------------
We expose stable symbols eagerly, and treat the "future" modules as optional
so that tests and thin deployments can import ``core.memory`` without pulling
in the Anthropic Python SDK or any code that isn't on-disk yet.
"""

from __future__ import annotations

from importlib import import_module as _import_module
from types import ModuleType as _ModuleType
from typing import Any as _Any

# --------------------------------------------------------------------------- #
# Eager exports — modules that are present today.
# --------------------------------------------------------------------------- #

# scope_guard ---------------------------------------------------------------
from core.memory.scope_guard import (  # noqa: F401
    ScopeViolation,
    VIRTUAL_PREFIX,
    normalize_virtual_path,
    safe_resolve,
)

# tool ----------------------------------------------------------------------
from core.memory.tool import (  # noqa: F401
    MemoryCommandError,
    MemoryTool,
)

# pinned --------------------------------------------------------------------
from core.memory.pinned import (  # noqa: F401
    PinnedCapExceeded,
    PinnedContentRejected,
    PinnedMemory,
    PinnedMemoryAPI,
    PinnedNotFound,
)

# project_resolver ----------------------------------------------------------
from core.memory.project_resolver import (  # noqa: F401
    HASH_SUFFIX_LEN,
    InvalidContextError,
    MAX_BASE_SLUG_LEN,
    ProjectResolverError,
    ReservedSlugError,
    ResolvedProject,
    hashed_slug,
    make_base_slug,
    resolve,
)

# session_lock --------------------------------------------------------------
from core.memory.session_lock import (  # noqa: F401
    DEFAULT_CLEANUP_PERIOD_DAYS,
    SessionAlreadyLockedError,
    SessionBinding,
    SessionLock,
    SessionLockBindingError,
    SessionLockError,
    SessionLockFrozenError,
    cleanup_stale_locks,
    new_session_id,
    sanitize_cleanup_period_days,
    session_scope,
)


# --------------------------------------------------------------------------- #
# Lazy / optional — future modules. Tolerate absence so ``import core.memory``
# never explodes on a partial checkout or an SDK-less unit-test environment.
# --------------------------------------------------------------------------- #


def _try_optional(module_suffix: str, names: tuple[str, ...]) -> dict[str, _Any]:
    """Attempt to import ``core.memory.<module_suffix>`` and pluck ``names``.

    Returns an empty dict if the module is missing; logs a debug note. Any
    import-time error that is NOT ``ModuleNotFoundError`` re-raises, because
    that indicates a real bug (not an absent module).
    """
    try:
        mod: _ModuleType = _import_module(f"core.memory.{module_suffix}")
    except ModuleNotFoundError:
        return {}
    out: dict[str, _Any] = {}
    for n in names:
        if hasattr(mod, n):
            out[n] = getattr(mod, n)
    return out


_optional_exports: dict[str, _Any] = {}
_optional_exports.update(_try_optional("auto", ("AutoMemory",)))
_optional_exports.update(_try_optional("index", ("IndexBuilder", "IndexWarning")))
_optional_exports.update(
    _try_optional("initializer", ("MemoryInitializer", "SessionContext"))
)
_optional_exports.update(_try_optional("sanitizer", ("sanitize",)))
_optional_exports.update(_try_optional("staging", ("StagingArea",)))
_optional_exports.update(_try_optional("auto_dream", ("AutoDream",)))
_optional_exports.update(_try_optional("budget", ("MemoryBudget",)))
_optional_exports.update(_try_optional("acl", ("ACL", "AccessCheck")))

# Publish optional symbols into this module's namespace.
globals().update(_optional_exports)


# --------------------------------------------------------------------------- #
# __all__ — stable symbol surface
# --------------------------------------------------------------------------- #

__all__: list[str] = [
    # scope_guard
    "ScopeViolation",
    "VIRTUAL_PREFIX",
    "normalize_virtual_path",
    "safe_resolve",
    # tool
    "MemoryCommandError",
    "MemoryTool",
    # pinned
    "PinnedCapExceeded",
    "PinnedContentRejected",
    "PinnedMemory",
    "PinnedMemoryAPI",
    "PinnedNotFound",
    # project_resolver
    "HASH_SUFFIX_LEN",
    "InvalidContextError",
    "MAX_BASE_SLUG_LEN",
    "ProjectResolverError",
    "ReservedSlugError",
    "ResolvedProject",
    "hashed_slug",
    "make_base_slug",
    "resolve",
    # session_lock
    "DEFAULT_CLEANUP_PERIOD_DAYS",
    "SessionAlreadyLockedError",
    "SessionBinding",
    "SessionLock",
    "SessionLockBindingError",
    "SessionLockError",
    "SessionLockFrozenError",
    "cleanup_stale_locks",
    "new_session_id",
    "sanitize_cleanup_period_days",
    "session_scope",
]

# Extend __all__ with whichever optional symbols actually loaded.
__all__.extend(sorted(_optional_exports.keys()))


# --------------------------------------------------------------------------- #
# Package metadata
# --------------------------------------------------------------------------- #

__version__ = "2.0.0"
"""Matches ARCHITECTURE_MEMORY_V2.md version."""

__spec_doc__ = "ARCHITECTURE_MEMORY_V2.md"
"""Pointer to the canonical spec for this package."""
