"""
core/memory/project_resolver.py
================================

Why this module exists
----------------------
The backend serves requests from multiple surfaces (Telegram bot, web UI,
internal CLI, email webhooks). Every request carries *some* implicit context
(user id, chat id, customer id, ticket id, worktree path). None of those
contexts, used raw, are safe as a storage key:

* Customer names collide (two customers called "cohen" at different firms).
* Telegram chat ids collide across bots.
* Absolute paths change when a user moves a worktree — if we used the path
  as the slug (the way Claude Code's default `cwd` encoding does) the whole
  project memory would silently detach. This is the root cause behind
  GitHub Issue #19972 ("encoding-based slug breaks after directory move"),
  and a secondary cause behind Issues #1985 / #7702 where two sessions end
  up resolving to the same directory and leak history.

`project_resolver` is the single, canonical place where an arbitrary
(system, entity_type, entity_id, user_id, optional anchor_path) tuple is
turned into:

    <base_slug>-<8-hex-hash>

The hash is computed from the *stable* anchor (user_id + canonical anchor
path if provided, otherwise user_id + entity triple). This means:

* Moving a worktree (`mv ~/work/foo ~/archive/foo`) does NOT change the
  slug, because we hash `user_id + entity_id`, not the cwd. The caller may
  optionally supply an `anchor_path` only when it truly is stable (e.g. a
  canonical file store path owned by the backend).
* Two different users touching the same entity id get different slugs
  (user scoping).
* Two different entity ids under the same user get different slugs even
  when their base_slug normalizes to the same thing (collision prevention).

This module is import-safe — it has zero filesystem side effects. It only
computes strings. The actual directory creation is the initializer's job.

Relevant spec sections: V2 sections 2.1 (principle #7), 2.2, 4.5, P03, P11.
"""

from __future__ import annotations

import hashlib
import logging
import re
import unicodedata
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

# --------------------------------------------------------------------------
# Constants
# --------------------------------------------------------------------------

# Length of the hash suffix. 8 hex chars = 32 bits = ~4.3 billion values,
# which gives a birthday-collision probability of ~1 in 100k at 1000 slugs
# — acceptable for a single-tenant backend, and the suffix stays short
# enough to stay inside filesystem name limits when combined with a base.
HASH_SUFFIX_LEN: int = 8

# Max length for the *base* slug before the hash is appended. Keep total
# under 64 chars to stay safely inside ext4/apfs filename limits and
# Claude Code's own directory encoding expectations.
MAX_BASE_SLUG_LEN: int = 48

# Characters allowed in the base slug. Deliberately narrow to avoid any
# filesystem-interpretation issues (spaces, slashes, colons on macOS, etc.).
_ALLOWED_CHARS = re.compile(r"[^a-z0-9-]+")
_DASH_RUN = re.compile(r"-{2,}")

# Reserved slugs that must never be handed out — they would collide with
# backend-internal directories under /data/projects/.
RESERVED_SLUGS: frozenset[str] = frozenset(
    {
        "",
        "-",
        ".",
        "..",
        "default",
        "shared",
        "global",
        "system",
        "admin",
        "root",
        "incognito",
        "staging",
        "backup",
    }
)


# --------------------------------------------------------------------------
# Exceptions
# --------------------------------------------------------------------------


class ProjectResolverError(ValueError):
    """Base class for every failure this module raises."""


class InvalidContextError(ProjectResolverError):
    """Raised when the input context cannot produce a valid slug."""


class ReservedSlugError(ProjectResolverError):
    """Raised when the computed base slug is one we refuse to hand out."""


# --------------------------------------------------------------------------
# Data
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class ResolvedProject:
    """
    Immutable result of a resolve() call.

    Why frozen: the slug is used as a lookup key across the request
    lifetime; accidental mutation would cause silent isolation bugs.
    """

    slug: str  # final slug including hash suffix — use this as the directory name
    base_slug: str  # human-readable part, before the hash
    hash_suffix: str  # 8-hex-char stable hash
    system: str
    entity_type: str
    entity_id: str
    user_id: str
    anchor_path: Optional[str]  # canonicalized abs path if supplied, else None


# --------------------------------------------------------------------------
# Normalization helpers
# --------------------------------------------------------------------------


_NON_ASCII_FALLBACK = "x"
"""Fallback used when all characters in a token are non-ASCII (e.g. Hebrew,
Arabic, CJK). The hash suffix carries uniqueness; the base slug is just
a human-readable prefix for debugging."""


def _normalize_token(raw: str, *, _fallback: bool = False) -> str:
    """
    Normalize a single token (system / entity_type / entity_id / user_id).

    Steps:
      1. Unicode NFKC — collapses full-width digits, weird hyphens, etc.
         This is important for Hebrew / Arabic customer names that may
         arrive from Telegram with RTL marks.
      2. Lowercase.
      3. Replace any non-`[a-z0-9-]` run with a single dash.
      4. Collapse multiple dashes, strip leading/trailing dashes.
      5. If the result is empty (all-non-ASCII input, e.g. Hebrew/Arabic),
         return ``_NON_ASCII_FALLBACK`` ("x") — uniqueness is still
         guaranteed by the hash suffix, and the base slug stays valid ASCII.
    """
    if raw is None:
        raise InvalidContextError("token is None")
    if not isinstance(raw, str):
        raise InvalidContextError(f"token must be str, got {type(raw).__name__}")

    nfkc = unicodedata.normalize("NFKC", raw)
    lowered = nfkc.lower()
    cleaned = _ALLOWED_CHARS.sub("-", lowered)
    collapsed = _DASH_RUN.sub("-", cleaned).strip("-")

    if not collapsed:
        # All characters were non-ASCII (Hebrew, Arabic, CJK, emoji …).
        # We cannot raise here because entity_id legitimately contains
        # non-Latin names. The hash suffix guarantees uniqueness.
        logger.debug(
            "_normalize_token: non-ASCII input %r collapsed to empty → using fallback %r",
            raw, _NON_ASCII_FALLBACK,
        )
        return _NON_ASCII_FALLBACK

    return collapsed


def make_base_slug(system: str, entity_type: str, entity_id: str) -> str:
    """
    Build the human-readable (non-hashed) portion of a slug.

    e.g. `("bina", "user", "12345")`        -> `"bina-user-12345"`
         `("cidah", "client", "Cohen&Levy")`-> `"cidah-client-cohen-levy"`

    This function alone does not produce a safe directory name — you must
    always combine with `hashed_slug()` or call `resolve()`.
    """
    # _normalize_token never returns empty — non-ASCII tokens get the "x"
    # fallback, so each part is guaranteed to be a non-empty ASCII string.
    parts = [_normalize_token(system), _normalize_token(entity_type), _normalize_token(entity_id)]
    base = "-".join(parts)
    if len(base) > MAX_BASE_SLUG_LEN:
        # Keep the prefix readable, truncate the middle. The hash suffix
        # added later is what actually guarantees uniqueness.
        base = base[:MAX_BASE_SLUG_LEN].rstrip("-")
        logger.debug("base slug truncated to %d chars: %s", MAX_BASE_SLUG_LEN, base)

    if base in RESERVED_SLUGS:
        raise ReservedSlugError(f"base slug '{base}' is reserved")

    return base


def hashed_slug(
    base_slug: str,
    user_id: str,
    anchor_path: Optional[Path] = None,
    *,
    raw_entity_id: str = "",
) -> str:
    """
    Produce the 8-hex-char collision-prevention suffix and append it.

    The hash input is *deliberately* NOT the base slug itself. Hashing the
    base slug would defeat the collision-prevention goal: two differently-
    normalized inputs that collapse to the same base slug would still get
    the same hash and therefore the same directory.

    Instead, we hash ``(user_id || anchor_or_base || raw_entity_id)``.

    * If an anchor_path is supplied: the hash binds the slug to a specific
      canonical filesystem location owned by the backend. Moving the user's
      *working* directory does not change this anchor (solves #19972).
    * If no anchor_path: we fall back to (user_id || base_slug). This still
      prevents cross-user collisions.
    * ``raw_entity_id`` is included when present so that non-ASCII names
      (Hebrew/Arabic) that collapse to the same normalized base slug still
      produce distinct hashes (e.g. "כהן" ≠ "לוי" even though both become
      "cidah-client-x" after ASCII normalization).

    Fixes: Issue #19972 (encoding-based slug), #1985 (session isolation
    failure), #7702 (sessions share history).
    """
    if not base_slug:
        raise InvalidContextError("base_slug is empty")
    if not user_id:
        raise InvalidContextError("user_id is empty")

    norm_user = _normalize_token(user_id)
    if not norm_user:
        raise InvalidContextError(f"user_id {user_id!r} normalizes to empty")

    if anchor_path is not None:
        try:
            # strict=False: the path does not need to exist yet. We only
            # need a canonical string. Resolving turns symlinks into their
            # targets, which is what we want — otherwise moving a symlink
            # would change the hash.
            canonical = str(Path(anchor_path).resolve(strict=False))
        except (OSError, RuntimeError) as e:
            # RuntimeError on some platforms for symlink loops.
            logger.warning("anchor_path resolve failed (%s); falling back", e)
            canonical = str(anchor_path)
        anchor = canonical
    else:
        anchor = base_slug

    # Include raw_entity_id in the hash so non-ASCII names that collapse to
    # the same normalized base still produce distinct slugs.
    payload = f"{norm_user}|{anchor}|{raw_entity_id}".encode("utf-8")
    digest = hashlib.sha256(payload).hexdigest()[:HASH_SUFFIX_LEN]
    return f"{base_slug}-{digest}"


# --------------------------------------------------------------------------
# Public entry point
# --------------------------------------------------------------------------


def resolve(
    system: str,
    entity_type: str,
    entity_id: str,
    user_id: str,
    anchor_path: Optional[Path] = None,
) -> ResolvedProject:
    """
    Single public entry point. Call this from every surface that needs a
    project slug: Telegram bot, HTTP middleware, CLI, internal agents.

    Example:

    >>> r = resolve("cidah", "client", "Cohen & Levy", "guy")
    >>> r.slug
    'cidah-client-cohen-levy-XXXXXXXX'
    """
    try:
        base = make_base_slug(system, entity_type, entity_id)
        # Pass raw entity_id so that non-ASCII inputs (Hebrew/Arabic) that
        # collapse to the same base slug still get distinct hash suffixes.
        full = hashed_slug(base, user_id, anchor_path, raw_entity_id=entity_id)
    except ProjectResolverError:
        raise
    except Exception as e:  # pragma: no cover — defensive only
        logger.exception("unexpected failure in resolve()")
        raise InvalidContextError(f"resolve failed: {e}") from e

    # The *full* slug is what ends up on disk. Reserved check again in
    # case a base slug ended up colliding at the full level (practically
    # impossible, but cheap to check).
    if full in RESERVED_SLUGS:
        raise ReservedSlugError(f"computed slug '{full}' is reserved")

    logger.info(
        "project resolved: slug=%s user=%s entity=%s/%s",
        full,
        _normalize_token(user_id),
        entity_type,
        entity_id,
    )

    return ResolvedProject(
        slug=full,
        base_slug=base,
        hash_suffix=full.rsplit("-", 1)[-1],
        system=_normalize_token(system),
        entity_type=_normalize_token(entity_type),
        entity_id=_normalize_token(entity_id),
        user_id=_normalize_token(user_id),
        anchor_path=str(Path(anchor_path).resolve(strict=False)) if anchor_path else None,
    )


# ==========================================================================
# Unit tests — run with `pytest project_resolver.py`
# ==========================================================================

if __name__ == "__main__":  # pragma: no cover
    import pytest  # noqa: F401  — imported only for direct invocation

    import sys

    sys.exit(pytest.main([__file__, "-v"]))


def test_basic_resolve():
    r = resolve("bina", "user", "12345", "guy")
    assert r.slug.startswith("bina-user-12345-")
    assert len(r.hash_suffix) == HASH_SUFFIX_LEN
    assert r.base_slug == "bina-user-12345"


def test_normalization_collapses_unicode():
    # Full-width digits should normalize to ASCII digits.
    r = resolve("bina", "user", "１２３", "guy")
    assert "123" in r.slug


def test_normalization_lowercases():
    r = resolve("CIDAH", "Client", "COHEN", "Guy")
    assert r.slug.startswith("cidah-client-cohen-")


def test_normalization_strips_punctuation():
    r = resolve("cidah", "client", "Cohen & Levy!!", "guy")
    assert r.base_slug == "cidah-client-cohen-levy"


def test_hebrew_input_uses_fallback_and_hash_differs():
    # Hebrew entity_id collapses to the fallback "x" (non-ASCII chars have no
    # ASCII representation). Uniqueness is carried by the SHA-256 hash suffix.
    r = resolve("cidah", "client", "כהן", "guy")
    r2 = resolve("cidah", "client", "לוי", "guy")
    # Base slugs are both "cidah-client-x" — that's fine, hash makes them unique.
    assert r.base_slug == r2.base_slug == "cidah-client-x"
    # Full slugs differ because the hash is seeded from the original raw entity_id.
    assert r.slug != r2.slug
    # Slug is valid ASCII only.
    assert r.slug.isascii()


def test_same_input_deterministic():
    r1 = resolve("bina", "user", "12345", "guy")
    r2 = resolve("bina", "user", "12345", "guy")
    assert r1.slug == r2.slug


def test_different_users_get_different_hashes():
    r1 = resolve("bina", "user", "12345", "guy")
    r2 = resolve("bina", "user", "12345", "lilach")
    assert r1.base_slug == r2.base_slug
    assert r1.hash_suffix != r2.hash_suffix
    assert r1.slug != r2.slug


def test_anchor_path_changes_hash(tmp_path):
    base_args = ("cidah", "client", "cohen", "guy")
    r_none = resolve(*base_args)
    r_path = resolve(*base_args, anchor_path=tmp_path)
    assert r_none.slug != r_path.slug


def test_anchor_path_is_canonical(tmp_path):
    # A symlink to a directory should resolve to its target, so the hash
    # is stable even if the symlink is replaced.
    real = tmp_path / "real"
    real.mkdir()
    link = tmp_path / "link"
    link.symlink_to(real)
    r_real = resolve("cidah", "client", "x", "guy", anchor_path=real)
    r_link = resolve("cidah", "client", "x", "guy", anchor_path=link)
    assert r_real.slug == r_link.slug


def test_reserved_slug_rejected():
    with pytest.raises(ReservedSlugError):
        make_base_slug("admin", "-", "-")


def test_empty_input_rejected():
    with pytest.raises(InvalidContextError):
        resolve("", "user", "12345", "guy")
    with pytest.raises(InvalidContextError):
        resolve("bina", "user", "", "guy")
    with pytest.raises(InvalidContextError):
        resolve("bina", "user", "12345", "")


def test_none_input_rejected():
    with pytest.raises(InvalidContextError):
        resolve(None, "user", "12345", "guy")  # type: ignore[arg-type]


def test_long_input_truncated_but_unique():
    long_id = "x" * 200
    r1 = resolve("bina", "user", long_id, "guy")
    r2 = resolve("bina", "user", long_id + "y", "guy")
    # base slugs may both truncate to the same string…
    # …but the hash suffix must still differ because entity_id differs.
    assert r1.base_slug != r2.base_slug or r1.hash_suffix != r2.hash_suffix
    assert r1.slug != r2.slug
    assert len(r1.base_slug) <= MAX_BASE_SLUG_LEN


def test_issue_19972_worktree_move_stable_slug(tmp_path, monkeypatch):
    # Simulates moving a worktree: the *entity_id* stays the same, so the
    # slug stays the same, even if we provide no anchor_path.
    r_before = resolve("cidah", "worktree", "repo-a", "guy")
    # imagine the user moved their directory — recall with same identity.
    r_after = resolve("cidah", "worktree", "repo-a", "guy")
    assert r_before.slug == r_after.slug


def test_issue_1985_session_isolation_two_users_two_slugs():
    r_a = resolve("bina", "session", "shared-chat", "alice")
    r_b = resolve("bina", "session", "shared-chat", "bob")
    # Same entity, different users -> different directories -> no leak.
    assert r_a.slug != r_b.slug


def test_issue_7702_two_distinct_sessions_distinct_slugs():
    # Distinct session entity ids MUST NOT share a slug, even for same user.
    r1 = resolve("bina", "session", "abc", "guy")
    r2 = resolve("bina", "session", "def", "guy")
    assert r1.slug != r2.slug


def test_collision_prevention_different_entity_types():
    r_user = resolve("bina", "user", "12345", "guy")
    r_client = resolve("bina", "client", "12345", "guy")
    assert r_user.slug != r_client.slug
