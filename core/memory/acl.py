"""
core.memory.acl — per-project Access Control List.

Why this module exists
----------------------
V2 §MISSING-09 and §2.4 introduce ``access.json`` in every project
directory so multiple users can share a legal matter. In the law-firm
use case, Guy is the project owner, Lilach edits drafts, Barak reads
the file. Without ACL we had two options and both were bad:

* **Option A** — share the uid. Kernel-level isolation is gone.
* **Option B** — clone the project for each user. Memory drifts apart
  within days.

The ACL gives us a third way: one filesystem directory, one uid, one
``memory/`` bundle — but with a YAML/JSON policy that the application
checks before any ``MemoryTool`` write or any ``view`` of files
outside ``memory/auto/``.

access.json format
------------------
The file is a single JSON object written atomically. **All keys are
lowercase.** Unknown keys are ignored (forward-compat).

::

    {
      "version": 1,
      "owner": "guyn",
      "created_at": "2026-04-24T10:00:00Z",
      "entries": {
        "guyn":   ["read", "write", "admin"],
        "lilach": ["read", "write"],
        "barak":  ["read"]
      },
      "defaults": {
        "unlisted_user": "deny"
      }
    }

* ``owner`` is always implicitly ``["read", "write", "admin"]`` even
  if missing from ``entries``.
* ``entries[user]`` is a list of permission strings. Unknown strings
  are dropped silently and logged at debug.
* ``defaults.unlisted_user`` is ``"deny"`` (default) or ``"read"`` —
  the latter is **explicit opt-in** and generates an ``access.json``
  warning every time it's loaded, to make accidental exposure loud.

Missing or unreadable ``access.json`` = **owner only**. The
owner is inferred from (in priority order):

1. An explicit ``owner_fallback`` passed to :class:`ACL`.
2. The filesystem owner of the project directory (``os.stat().st_uid``
   mapped through ``pwd`` on POSIX).
3. ``"unknown"`` — which means no one can read or write.

We never silently grant access to anyone when the file is missing.

References
----------
- ARCHITECTURE_MEMORY_V2.md §MISSING-09 (shared project ACL)
- ARCHITECTURE_MEMORY_V2.md §2.4 (ACL_ENABLED, ACL_FILE_NAME, ACL_DEFAULT_ROLE)
- ARCHITECTURE_MEMORY_V2.md §2.3 (per-project UID at the kernel level —
  ACL is defense-in-depth on top, not a replacement).
"""

from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Final, Iterable

__all__ = [
    "ACL",
    "AccessCheck",
    "AccessDenied",
    "ACLFileError",
    "Permission",
    "ACL_FILENAME",
    "VALID_PERMISSIONS",
    "DEFAULT_UNLISTED_POLICY",
]

log = logging.getLogger(__name__)

# --------------------------------------------------------------------------- #
# Constants
# --------------------------------------------------------------------------- #

ACL_FILENAME: Final[str] = "access.json"
"""Lives at ``<project_root>/access.json``."""

VALID_PERMISSIONS: Final[frozenset[str]] = frozenset({"read", "write", "admin"})
"""Anything else is dropped with a debug log."""

DEFAULT_UNLISTED_POLICY: Final[str] = "deny"
"""What happens to users not in ``entries``. 'deny' is the safe default."""


# --------------------------------------------------------------------------- #
# Types
# --------------------------------------------------------------------------- #


Permission = str  # "read" | "write" | "admin"


class AccessDenied(PermissionError):
    """Raised by :meth:`AccessCheck.require` when access is rejected."""


class ACLFileError(ValueError):
    """``access.json`` is present but malformed. Policy: fail closed."""


@dataclass
class AccessCheck:
    """Result of a single policy lookup.

    Attributes
    ----------
    user:
        The id we checked.
    project_slug:
        Project that owns the policy.
    permission:
        One of :data:`VALID_PERMISSIONS`.
    allowed:
        True iff the user holds the permission.
    reason:
        Human-readable diagnosis for logs and audit.
    source:
        ``"owner"`` | ``"entry"`` | ``"default"`` | ``"missing_file"`` |
        ``"malformed_file"``.
    """

    user: str
    project_slug: str
    permission: Permission
    allowed: bool
    reason: str
    source: str

    def require(self) -> None:
        """Raise :class:`AccessDenied` if not allowed."""
        if not self.allowed:
            raise AccessDenied(
                f"{self.user} cannot {self.permission} {self.project_slug}: "
                f"{self.reason}"
            )


# --------------------------------------------------------------------------- #
# The ACL
# --------------------------------------------------------------------------- #


class ACL:
    """Read and enforce an ``access.json`` policy.

    This class is **read-only** by design. Writes go through a separate
    admin CLI; mixing read-path and mutation in one class is a frequent
    source of auth bugs (TOCTOU, accidental broadening).

    Parameters
    ----------
    project_root:
        Directory containing ``access.json``. Must exist.
    project_slug:
        Used only for log + :class:`AccessCheck` population.
    owner_fallback:
        Used when ``access.json`` is missing. If ``None`` we try the
        filesystem owner, then give up with ``"unknown"``.
    """

    def __init__(
        self,
        *,
        project_root: Path,
        project_slug: str | None = None,
        owner_fallback: str | None = None,
    ) -> None:
        self.project_root = project_root.resolve(strict=True)
        self.slug = project_slug or self.project_root.name
        self._owner_fallback = owner_fallback
        self._policy: dict[str, Any] | None = None
        self._source: str = "unloaded"
        self._owner: str = ""
        self._load()

    # ------------------------------------------------------------------ #
    # Load
    # ------------------------------------------------------------------ #

    def _load(self) -> None:
        path = self.project_root / ACL_FILENAME
        if not path.exists():
            self._policy = None
            self._source = "missing_file"
            self._owner = self._infer_owner()
            log.info(
                "ACL[%s]: no access.json — defaulting to owner-only (%s)",
                self.slug, self._owner,
            )
            return

        try:
            raw = path.read_text(encoding="utf-8")
            data = json.loads(raw)
        except (OSError, json.JSONDecodeError) as e:
            self._policy = None
            self._source = "malformed_file"
            self._owner = self._infer_owner()
            log.error(
                "ACL[%s]: access.json unreadable (%s) — failing closed",
                self.slug, e,
            )
            raise ACLFileError(f"invalid access.json: {e}") from e

        if not isinstance(data, dict):
            self._source = "malformed_file"
            self._owner = self._infer_owner()
            raise ACLFileError("access.json must be a JSON object")

        self._policy = data
        self._source = "entry"
        self._owner = str(data.get("owner") or self._infer_owner())
        if data.get("defaults", {}).get("unlisted_user") == "read":
            log.warning(
                "ACL[%s]: unlisted_user=read — project is world-readable within tenancy",
                self.slug,
            )

    def _infer_owner(self) -> str:
        """Best-effort filesystem-owner mapping."""
        if self._owner_fallback:
            return self._owner_fallback
        try:
            st_uid = self.project_root.stat().st_uid
        except OSError:
            return "unknown"
        try:
            import pwd  # POSIX only
            return pwd.getpwuid(st_uid).pw_name
        except (ImportError, KeyError):
            return f"uid:{st_uid}"

    # ------------------------------------------------------------------ #
    # Queries
    # ------------------------------------------------------------------ #

    @property
    def owner(self) -> str:
        return self._owner

    @property
    def source(self) -> str:
        """``"entry" | "missing_file" | "malformed_file"``."""
        return self._source

    def list_users(self) -> tuple[str, ...]:
        """All users listed in the policy (owner is included)."""
        users: set[str] = {self._owner} if self._owner and self._owner != "unknown" else set()
        if self._policy:
            entries = self._policy.get("entries") or {}
            users.update(str(u) for u in entries.keys())
        return tuple(sorted(users))

    def permissions_of(self, user: str) -> frozenset[Permission]:
        """The permissions held by ``user``.

        Owner always has all three. Unknown users get whatever the
        ``defaults.unlisted_user`` policy prescribes (``"deny"`` ==
        empty set, ``"read"`` == ``{"read"}``).
        """
        if not user:
            return frozenset()
        if user == self._owner and self._owner and self._owner != "unknown":
            return frozenset(VALID_PERMISSIONS)
        if self._policy is None:
            # Missing / malformed file: only owner wins (handled above).
            return frozenset()
        entries = self._policy.get("entries") or {}
        if user in entries:
            raw = entries[user]
            if not isinstance(raw, list):
                log.debug(
                    "ACL[%s]: entries[%s] is not a list — dropping",
                    self.slug, user,
                )
                return frozenset()
            clean: set[Permission] = set()
            for p in raw:
                if not isinstance(p, str):
                    continue
                p_low = p.lower()
                if p_low in VALID_PERMISSIONS:
                    clean.add(p_low)
                else:
                    log.debug(
                        "ACL[%s]: dropping unknown permission %r for %s",
                        self.slug, p, user,
                    )
            return frozenset(clean)

        # Unlisted
        defaults = self._policy.get("defaults") or {}
        unlisted = str(defaults.get("unlisted_user", DEFAULT_UNLISTED_POLICY)).lower()
        if unlisted == "read":
            return frozenset({"read"})
        return frozenset()

    # ------------------------------------------------------------------ #
    # Per-permission helpers
    # ------------------------------------------------------------------ #

    def check(self, user: str, permission: Permission) -> AccessCheck:
        """Structured lookup. Does not raise."""
        permission = permission.lower()
        if permission not in VALID_PERMISSIONS:
            return AccessCheck(
                user=user, project_slug=self.slug, permission=permission,
                allowed=False, reason=f"unknown permission {permission!r}",
                source=self._source,
            )
        perms = self.permissions_of(user)
        if user == self._owner and self._owner and self._owner != "unknown":
            return AccessCheck(
                user=user, project_slug=self.slug, permission=permission,
                allowed=True, reason="owner",
                source="owner",
            )
        allowed = permission in perms
        return AccessCheck(
            user=user, project_slug=self.slug, permission=permission,
            allowed=allowed,
            reason="granted by entry" if allowed else "not granted",
            source=self._source,
        )

    def can_read(self, user: str, project: str | None = None) -> bool:
        if project and project != self.slug:
            log.debug("ACL[%s]: can_read called with mismatched project %s",
                      self.slug, project)
            return False
        return self.check(user, "read").allowed

    def can_write(self, user: str, project: str | None = None) -> bool:
        if project and project != self.slug:
            return False
        return self.check(user, "write").allowed

    def is_admin(self, user: str) -> bool:
        return self.check(user, "admin").allowed

    def require(self, user: str, permission: Permission) -> None:
        """Raise :class:`AccessDenied` if ``user`` lacks ``permission``."""
        self.check(user, permission).require()

    # ------------------------------------------------------------------ #
    # Introspection
    # ------------------------------------------------------------------ #

    def to_dict(self) -> dict[str, Any]:
        """Snapshot for logging / CLI display. Never includes raw file."""
        return {
            "project": self.slug,
            "owner": self._owner,
            "source": self._source,
            "users": list(self.list_users()),
            "unlisted_policy": (
                (self._policy or {}).get("defaults", {})
                .get("unlisted_user", DEFAULT_UNLISTED_POLICY)
                if self._policy else DEFAULT_UNLISTED_POLICY
            ),
        }

    # ------------------------------------------------------------------ #
    # Factory helper
    # ------------------------------------------------------------------ #

    @classmethod
    def write_default(
        cls,
        *,
        project_root: Path,
        owner: str,
        extra_entries: dict[str, Iterable[Permission]] | None = None,
        unlisted_user: str = DEFAULT_UNLISTED_POLICY,
    ) -> Path:
        """Create a minimal ``access.json`` for a fresh project.

        This is the *only* place this module writes. It is intentionally
        atomic (write temp + os.replace) and refuses to overwrite an
        existing file — callers must delete the old one first.
        """
        target = project_root / ACL_FILENAME
        if target.exists():
            raise FileExistsError(f"{target} already exists; refusing to overwrite")

        entries: dict[str, list[Permission]] = {
            owner: ["read", "write", "admin"],
        }
        if extra_entries:
            for u, perms in extra_entries.items():
                clean = [p.lower() for p in perms if isinstance(p, str)
                         and p.lower() in VALID_PERMISSIONS]
                if clean:
                    entries[u] = clean

        payload: dict[str, Any] = {
            "version": 1,
            "owner": owner,
            "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "entries": entries,
            "defaults": {"unlisted_user": unlisted_user},
        }

        tmp = target.with_suffix(".json.tmp")
        tmp.write_text(
            json.dumps(payload, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        os.replace(tmp, target)
        try:
            os.chmod(target, 0o600)  # match V2 §2.3 permissions matrix
        except OSError:
            pass
        log.info("ACL: wrote default access.json -> %s", target)
        return target


# --------------------------------------------------------------------------- #
# Unit tests — pytest-compatible
# --------------------------------------------------------------------------- #


def _tests() -> None:  # pragma: no cover - executed by pytest
    import pytest
    import tempfile

    def _mk(root: Path, payload: dict[str, Any] | str | None) -> None:
        if payload is None:
            return
        content = payload if isinstance(payload, str) else json.dumps(payload)
        (root / ACL_FILENAME).write_text(content, encoding="utf-8")

    def test_missing_file_owner_only() -> None:
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            acl = ACL(project_root=root, owner_fallback="guy")
            assert acl.source == "missing_file"
            assert acl.can_read("guy") is True
            assert acl.can_write("guy") is True
            assert acl.is_admin("guy") is True
            assert acl.can_read("lilach") is False
            assert acl.can_write("lilach") is False

    def test_full_policy_read_write_admin() -> None:
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            _mk(root, {
                "version": 1,
                "owner": "guy",
                "entries": {
                    "guy": ["read", "write", "admin"],
                    "lilach": ["read", "write"],
                    "barak": ["read"],
                },
                "defaults": {"unlisted_user": "deny"},
            })
            acl = ACL(project_root=root)
            assert acl.owner == "guy"
            assert acl.can_read("lilach")
            assert acl.can_write("lilach")
            assert acl.is_admin("lilach") is False
            assert acl.can_read("barak")
            assert acl.can_write("barak") is False
            assert acl.can_read("stranger") is False

    def test_unlisted_read_policy() -> None:
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            _mk(root, {
                "version": 1,
                "owner": "guy",
                "entries": {},
                "defaults": {"unlisted_user": "read"},
            })
            acl = ACL(project_root=root)
            assert acl.can_read("stranger") is True
            assert acl.can_write("stranger") is False

    def test_malformed_json_fails_closed() -> None:
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            _mk(root, "{not: valid json")
            with pytest.raises(ACLFileError):
                ACL(project_root=root, owner_fallback="guy")

    def test_non_object_root() -> None:
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            _mk(root, json.dumps([1, 2, 3]))
            with pytest.raises(ACLFileError):
                ACL(project_root=root, owner_fallback="guy")

    def test_unknown_permission_dropped() -> None:
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            _mk(root, {
                "version": 1,
                "owner": "guy",
                "entries": {"lilach": ["read", "SUPER_USER"]},
            })
            acl = ACL(project_root=root)
            assert acl.permissions_of("lilach") == frozenset({"read"})

    def test_require_raises() -> None:
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            _mk(root, {"version": 1, "owner": "guy", "entries": {}})
            acl = ACL(project_root=root)
            with pytest.raises(AccessDenied):
                acl.require("barak", "read")
            # owner does not raise
            acl.require("guy", "admin")

    def test_owner_implicit_admin_even_if_missing_from_entries() -> None:
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            _mk(root, {
                "version": 1, "owner": "guy",
                "entries": {"lilach": ["read"]},
            })
            acl = ACL(project_root=root)
            assert acl.is_admin("guy")
            assert acl.can_write("guy")

    def test_project_mismatch_denies() -> None:
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            _mk(root, {
                "version": 1, "owner": "guy",
                "entries": {"lilach": ["read"]},
            })
            acl = ACL(project_root=root, project_slug="matter-001")
            assert acl.can_read("lilach", project="matter-001") is True
            assert acl.can_read("lilach", project="matter-002") is False

    def test_unknown_permission_string() -> None:
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            _mk(root, {"version": 1, "owner": "guy", "entries": {}})
            acl = ACL(project_root=root)
            result = acl.check("guy", "teleport")
            assert result.allowed is False

    def test_write_default_creates_file() -> None:
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            path = ACL.write_default(
                project_root=root, owner="guy",
                extra_entries={"lilach": ["read", "write"]},
            )
            assert path.exists()
            acl = ACL(project_root=root)
            assert acl.owner == "guy"
            assert acl.can_write("lilach")

    def test_write_default_refuses_overwrite() -> None:
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            ACL.write_default(project_root=root, owner="guy")
            with pytest.raises(FileExistsError):
                ACL.write_default(project_root=root, owner="guy")

    def test_list_users_includes_owner() -> None:
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            _mk(root, {
                "version": 1, "owner": "guy",
                "entries": {"lilach": ["read"], "barak": ["read"]},
            })
            acl = ACL(project_root=root)
            assert set(acl.list_users()) == {"guy", "lilach", "barak"}

    def test_to_dict_shape() -> None:
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            _mk(root, {"version": 1, "owner": "guy", "entries": {}})
            acl = ACL(project_root=root)
            d2 = acl.to_dict()
            assert d2["project"] == acl.slug
            assert d2["owner"] == "guy"
            assert d2["unlisted_policy"] == "deny"

    def test_empty_user_denied() -> None:
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            _mk(root, {"version": 1, "owner": "guy", "entries": {}})
            acl = ACL(project_root=root)
            assert acl.can_read("") is False
            assert acl.permissions_of("") == frozenset()

    for fn in [
        test_missing_file_owner_only,
        test_full_policy_read_write_admin,
        test_unlisted_read_policy,
        test_malformed_json_fails_closed,
        test_non_object_root,
        test_unknown_permission_dropped,
        test_require_raises,
        test_owner_implicit_admin_even_if_missing_from_entries,
        test_project_mismatch_denies,
        test_unknown_permission_string,
        test_write_default_creates_file,
        test_write_default_refuses_overwrite,
        test_list_users_includes_owner,
        test_to_dict_shape,
        test_empty_user_denied,
    ]:
        fn()
    print("acl self-test PASS")


if __name__ == "__main__":  # pragma: no cover
    logging.basicConfig(level=logging.INFO)
    _tests()
