"""
core.memory.scope_guard — Path traversal + symlink defense for memory_20250818.

Threat model
------------
CVE-2026-34451 demonstrated that the TypeScript memory tool was vulnerable
to path traversal via:

1. Literal ``..`` segments
2. URL-encoded payloads (``%2E%2E`` → ``..`` after decoding)
3. Unicode-normalization tricks (fullwidth dot ``．`` collapsing to ``.``)
4. Windows drive letters (``C:\\``) and UNC paths (``\\\\server\\share``)
5. Symlinks that point outside the memory root
6. Symlinks inside directories that are themselves symlinks
7. TOCTOU races between ``resolve()`` and the actual ``open()`` call

The v1.0 spec used a naive ``rejectPattern(/\\.\\./g)`` regex which defeats
only (1) and gives a false sense of security. This module closes the
remaining vectors, in line with Python's canonical
``Path.resolve()`` + ``Path.relative_to()`` pattern.

Public API
----------
- :class:`ScopeViolation` — raised for any rejection.
- :func:`safe_resolve` — returns an absolute ``Path`` guaranteed to live
  underneath ``root``, or raises ``ScopeViolation``.
- :func:`normalize_virtual_path` — URL-decode + NFKC + strip virtual prefix.

All checks are string- and filesystem-level; callers must still hold a
flock during ``_commit`` to defeat true TOCTOU.
"""

from __future__ import annotations

import logging
import os
import re
import unicodedata
from pathlib import Path
from typing import Final
from urllib.parse import unquote

__all__ = [
    "ScopeViolation",
    "safe_resolve",
    "normalize_virtual_path",
    "VIRTUAL_PREFIX",
]

log = logging.getLogger(__name__)

# --------------------------------------------------------------------------- #
# Constants
# --------------------------------------------------------------------------- #

VIRTUAL_PREFIX: Final[str] = "/memories"
"""Anthropic-specified virtual prefix for ``memory_20250818`` paths."""

_WIN_DRIVE_RE: Final[re.Pattern[str]] = re.compile(r"^[A-Za-z]:[\\/]")
"""Matches ``C:\\`` / ``C:/`` / etc."""

_UNC_RE: Final[re.Pattern[str]] = re.compile(r"^\\\\")
"""Matches UNC paths (``\\\\server\\share``)."""

_NULL_BYTE: Final[str] = "\x00"

# Filenames that are never allowed as components of a memory path, even
# if ``safe_resolve`` would otherwise accept them.
_FORBIDDEN_NAMES: Final[frozenset[str]] = frozenset(
    {
        "",
        ".",
        "..",
        ".git",
        ".ssh",
        ".env",
        ".staging",  # the staging dir is backend-only
        ".audit.log",
    }
)

# Max component/segment length (filesystem-dependent; 255 is POSIX max on
# most ext4/APFS volumes — we go slightly under for safety margin).
_MAX_COMPONENT_LEN: Final[int] = 240


# --------------------------------------------------------------------------- #
# Exceptions
# --------------------------------------------------------------------------- #


class ScopeViolation(PermissionError):
    """Raised when a memory path escapes its root or is otherwise forbidden.

    Subclass of ``PermissionError`` so callers who ``except PermissionError``
    will still catch it; callers who care about the distinction can
    ``except ScopeViolation``.
    """

    def __init__(self, reason: str, offending: str, *, root: Path | None = None):
        self.reason = reason
        self.offending = offending
        self.root = root
        msg = f"scope violation ({reason}): {offending!r}"
        if root is not None:
            msg += f" — root={root!s}"
        super().__init__(msg)


# --------------------------------------------------------------------------- #
# Normalization
# --------------------------------------------------------------------------- #


def normalize_virtual_path(virtual_path: str) -> str:
    """URL-decode, NFKC-normalize, and strip the ``/memories`` prefix.

    Parameters
    ----------
    virtual_path:
        Path as supplied by the model — e.g. ``/memories/decisions.md``,
        ``/memories/%2E%2E/%2E%2E/etc/passwd`` (blocked downstream).

    Returns
    -------
    str
        Relative path with the prefix stripped and any leading slashes
        removed. The return value is still untrusted — feed it to
        :func:`safe_resolve`.

    Raises
    ------
    ScopeViolation
        If the input contains NUL bytes, is a Windows drive/UNC path,
        or does not start with ``/memories``.
    """
    if not isinstance(virtual_path, str):
        raise ScopeViolation("non-str path", repr(virtual_path))
    if _NULL_BYTE in virtual_path:
        raise ScopeViolation("NUL byte in path", virtual_path)

    # Decode percent-escapes (CVE-2026-34451 vector 2).
    decoded = unquote(virtual_path)
    if _NULL_BYTE in decoded:
        raise ScopeViolation("NUL byte after decode", virtual_path)

    # NFKC folds fullwidth/compatibility codepoints (vector 3).
    normalized = unicodedata.normalize("NFKC", decoded)

    # Reject Windows drive letters and UNC paths (vector 4).
    if _WIN_DRIVE_RE.match(normalized) or _UNC_RE.match(normalized):
        raise ScopeViolation("windows-style absolute path", virtual_path)

    # Must begin with the virtual prefix (optionally with leading slash
    # stripped after normalization).
    if not normalized.startswith(VIRTUAL_PREFIX):
        raise ScopeViolation(
            f"path must start with {VIRTUAL_PREFIX!r}", virtual_path
        )

    rel = normalized[len(VIRTUAL_PREFIX):]
    # Strip all leading slashes (both ``/`` and ``\`` after NFKC).
    rel = rel.lstrip("/").lstrip("\\")

    if _WIN_DRIVE_RE.match(rel):  # defence-in-depth, shouldn't happen
        raise ScopeViolation("drive letter after prefix strip", virtual_path)

    return rel


# --------------------------------------------------------------------------- #
# Resolver
# --------------------------------------------------------------------------- #


def _check_components(rel: str, original: str) -> None:
    """Reject bad per-component patterns before we touch the filesystem."""
    # os.path.normpath would collapse "a/../b" silently — we want to SEE
    # the "..", so split on both separators manually.
    parts = re.split(r"[\\/]", rel)
    for part in parts:
        if part in _FORBIDDEN_NAMES:
            raise ScopeViolation(
                f"forbidden path component {part!r}", original
            )
        if len(part) > _MAX_COMPONENT_LEN:
            raise ScopeViolation(
                f"component too long ({len(part)} > {_MAX_COMPONENT_LEN})",
                original,
            )
        # NFKC can leave combining marks; reject unassigned/control chars.
        for ch in part:
            cat = unicodedata.category(ch)
            if cat.startswith("C") and ch not in ("\t",):
                # Cc, Cf, Cs, Co, Cn — all control/format/private/unassigned.
                raise ScopeViolation(
                    f"control character U+{ord(ch):04X} in component",
                    original,
                )


def safe_resolve(
    root: Path,
    user_path: str,
    *,
    must_exist: bool = False,
    allow_symlinks: bool = False,
) -> Path:
    """Resolve ``user_path`` under ``root``, rejecting any escape attempt.

    This is the single chokepoint between a model-supplied path and any
    filesystem syscall. All six commands (``view``, ``create``,
    ``str_replace``, ``insert``, ``delete``, ``rename``) must funnel through
    here for every path they touch.

    Parameters
    ----------
    root:
        Absolute directory the candidate path must live beneath. Must
        already exist; will be ``.resolve(strict=True)``'d — which means
        any symlink in the root's own chain is followed once up front.
    user_path:
        Path as supplied by the caller. May be absolute (``/foo/bar``) or
        relative (``foo/bar``). Leading slashes are stripped. URL-encoded
        input should be decoded by :func:`normalize_virtual_path` *before*
        calling this function.
    must_exist:
        If ``True``, the resolved path must already exist. Useful for
        ``view`` / ``str_replace`` / ``insert`` / ``delete`` / ``rename``
        (source). For ``create`` and ``rename`` (destination), pass False.
    allow_symlinks:
        Default ``False`` — any symlink anywhere in the resolved chain is
        treated as suspect, and we additionally verify its ultimate target
        is still under ``root``. When True, only the final-component
        symlink is dereferenced (still bounded by ``root``).

    Returns
    -------
    pathlib.Path
        Absolute resolved path, guaranteed ``Path.is_relative_to(root)``.

    Raises
    ------
    ScopeViolation
        For any traversal, symlink escape, forbidden component, or
        (if ``must_exist``) missing target.
    """
    if not isinstance(root, Path):
        raise TypeError(f"root must be pathlib.Path, got {type(root).__name__}")

    # Resolve root strictly — if it doesn't exist we FAIL LOUD, never silently
    # write under a new directory we created ourselves.
    root = root.resolve(strict=True)
    if not root.is_dir():
        raise ScopeViolation("root is not a directory", str(root), root=root)

    original = user_path

    # --- stage 1: normalize & reject cheap bad inputs --------------------- #
    if _NULL_BYTE in user_path:
        raise ScopeViolation("NUL byte in path", original, root=root)

    user_path = unicodedata.normalize("NFKC", unquote(user_path))

    # Reject absolute OS paths (Windows drive / POSIX absolute after strip).
    if _WIN_DRIVE_RE.match(user_path) or _UNC_RE.match(user_path):
        raise ScopeViolation("OS-absolute path", original, root=root)
    user_path = user_path.lstrip("/").lstrip("\\")

    # Reject empty after strip — empty path would resolve to root itself.
    if not user_path:
        raise ScopeViolation("empty path", original, root=root)

    _check_components(user_path, original)

    # --- stage 2: resolve ------------------------------------------------- #
    candidate = (root / user_path).resolve(strict=False)

    # --- stage 3: containment check (the load-bearing one) --------------- #
    try:
        candidate.relative_to(root)
    except ValueError as e:
        log.warning(
            "scope_violation path=%r root=%s resolved=%s",
            original, root, candidate,
        )
        raise ScopeViolation(
            "path escapes root", original, root=root
        ) from e

    # --- stage 4: symlink handling --------------------------------------- #
    # Walk every intermediate component and reject if any is a symlink
    # whose ultimate target leaves ``root``. os.path.realpath handles
    # the chain, but we need the fine-grained per-link check to produce
    # good error messages and to honour allow_symlinks=False.
    cur = root
    for part in candidate.relative_to(root).parts:
        cur = cur / part
        if cur.is_symlink():
            if not allow_symlinks:
                raise ScopeViolation(
                    f"symlink not permitted at {part!r}", original, root=root
                )
            target = os.readlink(cur)
            target_abs = (cur.parent / target).resolve(strict=False)
            try:
                target_abs.relative_to(root)
            except ValueError as e:
                log.warning(
                    "symlink_escape path=%r link=%s target=%s root=%s",
                    original, cur, target_abs, root,
                )
                raise ScopeViolation(
                    f"symlink target {target!r} escapes root",
                    original, root=root,
                ) from e

    # --- stage 5: existence (optional) ----------------------------------- #
    if must_exist and not candidate.exists():
        raise ScopeViolation(
            "target does not exist", original, root=root
        )

    return candidate


# --------------------------------------------------------------------------- #
# Self-test — runnable via ``python -m core.memory.scope_guard``
# --------------------------------------------------------------------------- #


def _self_test() -> None:  # pragma: no cover - manual harness
    """Smoke tests mapped to V2 acceptance tests T01-T03."""
    import tempfile

    with tempfile.TemporaryDirectory() as td:
        root = Path(td).resolve()
        (root / "ok.md").write_text("ok")

        # T01 — literal traversal
        try:
            safe_resolve(root, "../../../etc/passwd")
        except ScopeViolation:
            print("T01 PASS literal ..")
        else:
            raise AssertionError("T01 FAIL")

        # T03 — url-encoded traversal (via normalize_virtual_path)
        decoded = normalize_virtual_path("/memories/%2E%2E/%2E%2E/secret")
        try:
            safe_resolve(root, decoded)
        except ScopeViolation:
            print("T03 PASS url-encoded ..")
        else:
            raise AssertionError("T03 FAIL")

        # T02 — symlink escape
        outside = Path(td).parent / "outside.md"
        outside.write_text("secret")
        link = root / "escape.md"
        try:
            link.symlink_to(outside)
            try:
                safe_resolve(root, "escape.md")
            except ScopeViolation:
                print("T02 PASS symlink blocked")
            else:
                raise AssertionError("T02 FAIL")
        finally:
            link.unlink(missing_ok=True)
            outside.unlink(missing_ok=True)

        # happy path
        r = safe_resolve(root, "ok.md", must_exist=True)
        assert r == (root / "ok.md")
        print("happy PASS")


if __name__ == "__main__":  # pragma: no cover
    logging.basicConfig(level=logging.DEBUG)
    _self_test()
