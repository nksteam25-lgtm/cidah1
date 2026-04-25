"""
core.memory.budget — per-session context budget tracking.

Why this module exists
----------------------
V2 §1.4 NEW-02 and §2.4 establish a hard rule: every session that loads
the 5-layer compound must fit within a budget, defaulting to
``SESSION_MEMORY_BUDGET_KB=30`` with a soft warning at
``SESSION_MEMORY_BUDGET_WARN_AT=24`` (or, equivalently, WARN_AT_PERCENT=80%).

Without the budget:

* Token-cost creeps upward silently as pinned memories and auto files grow.
* INDEX silent truncation (V1-FIX-04) can coexist with "we loaded
  everything we meant to" — the budget counter would have caught it.
* There is no artefact for post-mortem: "what was in the prompt when the
  model went off?".

This module is deliberately *just accounting*. It does not decide what
to drop — that's the context loader's job (L0 and L1 are mandatory, L3
auto files are evictable by recency, etc.). Callers:

1. Create one ``MemoryBudget`` per session (cheap).
2. Call :meth:`add_layer` for every chunk they load; the budget records
   the size in bytes AND notes the UTF-8-safe KB figure.
3. Read :meth:`total_kb` to compare against the cap.
4. Call :meth:`warn_if_needed` which logs a structured warning (does
   *not* raise). Callers that want hard-fail behaviour compose it
   themselves.
5. Serialize via :meth:`to_dict` for the audit log and the session
   transcript.

Why we do NOT use ``sys.getsizeof``
-----------------------------------
Python's in-memory size is unrelated to the tokens an API consumes.
The authoritative unit for Anthropic's context-management-2025-06-27 is
bytes-of-UTF-8 text. We measure there and document the gap: "1 byte ≈ 1
token only for ASCII; Hebrew doubles that, emoji can be 4×. Tokens are
still the real currency — this counter is an approximation tuned to
warn conservatively."

References
----------
- ARCHITECTURE_MEMORY_V2.md §1.4 NEW-02 (memory budget per session)
- ARCHITECTURE_MEMORY_V2.md §2.4 (SESSION_MEMORY_BUDGET_KB, _WARN_AT)
- ARCHITECTURE_MEMORY_V2.md §4.6 (initializer integration)
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable, Final

__all__ = [
    "MemoryBudget",
    "LayerEntry",
    "DEFAULT_BUDGET_KB",
    "DEFAULT_WARN_AT_PERCENT",
    "BUDGET_ENV_VAR",
    "WARN_ENV_VAR",
]

log = logging.getLogger(__name__)

# --------------------------------------------------------------------------- #
# Defaults + env keys
# --------------------------------------------------------------------------- #

DEFAULT_BUDGET_KB: Final[int] = 30
"""Matches SESSION_MEMORY_BUDGET_KB in V2 §2.4."""

DEFAULT_WARN_AT_PERCENT: Final[int] = 80
"""80% of budget = 24 KB at the default. Matches _WARN_AT=24 KB."""

BUDGET_ENV_VAR: Final[str] = "SESSION_MEMORY_BUDGET_KB"
WARN_ENV_VAR: Final[str] = "SESSION_MEMORY_BUDGET_WARN_AT_PERCENT"


# --------------------------------------------------------------------------- #
# Records
# --------------------------------------------------------------------------- #


@dataclass
class LayerEntry:
    """One chunk contributing to the budget.

    Attributes
    ----------
    name:
        Stable identifier (e.g. ``"L0:conventions"``, ``"L3c:auto/decisions.md"``).
    bytes:
        UTF-8 byte count of the loaded content.
    added_at:
        ISO-8601 timestamp — helps debug "when did we cross the cap?".
    """

    name: str
    bytes: int
    added_at: str = field(default_factory=lambda: datetime.now(timezone.utc)
                          .isoformat(timespec="seconds"))

    @property
    def kb(self) -> float:
        return self.bytes / 1024.0

    def to_dict(self) -> dict[str, Any]:
        return {"name": self.name, "bytes": self.bytes,
                "kb": round(self.kb, 3), "added_at": self.added_at}


# --------------------------------------------------------------------------- #
# Budget
# --------------------------------------------------------------------------- #


class MemoryBudget:
    """Track and report per-session memory usage.

    Parameters
    ----------
    budget_kb:
        Overrides the env-var / default.
    warn_at_percent:
        Integer 1..100. The warning fires when ``total_kb >=
        budget_kb * warn_at_percent / 100``.
    on_warn:
        Optional callback receiving the :class:`MemoryBudget`. Useful
        for pushing a UI toast or recording to the audit log. The
        default is ``None`` — a log.warning is always emitted regardless.

    Raises
    ------
    ValueError
        If ``budget_kb <= 0`` or ``warn_at_percent`` is outside (0, 100].
    """

    def __init__(
        self,
        *,
        budget_kb: int | None = None,
        warn_at_percent: int | None = None,
        on_warn: Callable[["MemoryBudget"], None] | None = None,
    ) -> None:
        self.budget_kb = int(budget_kb if budget_kb is not None
                             else _env_int(BUDGET_ENV_VAR, DEFAULT_BUDGET_KB))
        self.warn_at_percent = int(
            warn_at_percent if warn_at_percent is not None
            else _env_int(WARN_ENV_VAR, DEFAULT_WARN_AT_PERCENT)
        )
        if self.budget_kb <= 0:
            raise ValueError(f"budget_kb must be > 0, got {self.budget_kb}")
        if not (0 < self.warn_at_percent <= 100):
            raise ValueError(
                f"warn_at_percent must be in (0, 100], got {self.warn_at_percent}"
            )
        self._layers: list[LayerEntry] = []
        self._on_warn = on_warn
        self._warned = False

    # ------------------------------------------------------------------ #
    # Mutation
    # ------------------------------------------------------------------ #

    def add_layer(self, name: str, content: str | bytes) -> LayerEntry:
        """Record a chunk. Returns the created :class:`LayerEntry`.

        ``content`` can be ``str`` or pre-encoded ``bytes``; we measure
        the UTF-8 byte count either way.
        """
        if not name:
            raise ValueError("layer name required")
        if isinstance(content, str):
            size = len(content.encode("utf-8"))
        elif isinstance(content, (bytes, bytearray)):
            size = len(content)
        else:
            raise TypeError(
                f"content must be str or bytes, got {type(content).__name__}"
            )
        entry = LayerEntry(name=name, bytes=size)
        self._layers.append(entry)
        log.debug("budget: +%s (%.2f KB)  total=%.2f/%d KB",
                  name, entry.kb, self.total_kb(), self.budget_kb)
        return entry

    def reset(self) -> None:
        """Zero the counter — useful between turns if callers want per-turn limits."""
        self._layers.clear()
        self._warned = False

    # ------------------------------------------------------------------ #
    # Query
    # ------------------------------------------------------------------ #

    @property
    def layers(self) -> tuple[LayerEntry, ...]:
        return tuple(self._layers)

    def total_bytes(self) -> int:
        return sum(le.bytes for le in self._layers)

    def total_kb(self) -> float:
        return self.total_bytes() / 1024.0

    def percent_used(self) -> float:
        return 100.0 * self.total_kb() / self.budget_kb

    def is_over(self) -> bool:
        """True once the session exceeds the hard budget."""
        return self.total_kb() > self.budget_kb

    def should_warn(self) -> bool:
        return self.percent_used() >= self.warn_at_percent

    # ------------------------------------------------------------------ #
    # Side-effectful
    # ------------------------------------------------------------------ #

    def warn_if_needed(self) -> bool:
        """Emit (at most once per instance) a structured warning.

        Returns
        -------
        bool
            True iff the warning was emitted on this call. Callers can
            chain this into a UI toast without double-firing.
        """
        if self._warned or not self.should_warn():
            return False
        self._warned = True
        log.warning(
            "memory budget: %.2f/%d KB (%.0f%%) — %d layers loaded",
            self.total_kb(), self.budget_kb, self.percent_used(),
            len(self._layers),
        )
        if self._on_warn is not None:
            try:
                self._on_warn(self)
            except Exception:  # noqa: BLE001
                log.exception("budget on_warn callback raised")
        return True

    # ------------------------------------------------------------------ #
    # Serialization
    # ------------------------------------------------------------------ #

    def to_dict(self) -> dict[str, Any]:
        """Structured snapshot for audit log + session transcript."""
        return {
            "budget_kb": self.budget_kb,
            "warn_at_percent": self.warn_at_percent,
            "total_bytes": self.total_bytes(),
            "total_kb": round(self.total_kb(), 3),
            "percent_used": round(self.percent_used(), 1),
            "over_budget": self.is_over(),
            "warned": self._warned,
            "layers": [le.to_dict() for le in self._layers],
        }


# --------------------------------------------------------------------------- #
# context_loader integration helper
# --------------------------------------------------------------------------- #


def attach_to_context_loader(budget: MemoryBudget, loader: Any) -> None:
    """Best-effort wiring of a budget into a ``context_loader`` instance.

    The context_loader exposes a hook interface we can duck-type into:

    * ``loader.on_layer_loaded(callback)`` — register a callable that
      receives ``(layer_name, content)`` after each load, OR
    * ``loader.budget = budget`` — direct attribute injection.

    We try the hook first; fall back to the attribute. Either way the
    helper never raises on a missing API — it just logs.
    """
    hook = getattr(loader, "on_layer_loaded", None)
    if callable(hook):
        hook(lambda name, content: budget.add_layer(name, content))
        budget_hook = getattr(loader, "on_loading_done", None)
        if callable(budget_hook):
            budget_hook(lambda: budget.warn_if_needed())
        return
    if hasattr(loader, "budget"):
        setattr(loader, "budget", budget)
        return
    log.debug(
        "attach_to_context_loader: no hook or attr found on %s — skipping",
        type(loader).__name__,
    )


# --------------------------------------------------------------------------- #
# helpers
# --------------------------------------------------------------------------- #


def _env_int(key: str, default: int) -> int:
    raw = os.environ.get(key)
    if raw is None or raw == "":
        return default
    try:
        return int(raw)
    except ValueError:
        log.warning("env %s=%r not an int, using default %d", key, raw, default)
        return default


# --------------------------------------------------------------------------- #
# Unit tests — pytest-compatible
# --------------------------------------------------------------------------- #


def _tests() -> None:  # pragma: no cover - executed by pytest
    import pytest

    def test_defaults_from_constants() -> None:
        b = MemoryBudget()
        assert b.budget_kb == DEFAULT_BUDGET_KB
        assert b.warn_at_percent == DEFAULT_WARN_AT_PERCENT

    def test_explicit_override() -> None:
        b = MemoryBudget(budget_kb=10, warn_at_percent=50)
        assert b.budget_kb == 10
        assert b.warn_at_percent == 50

    def test_invalid_args() -> None:
        with pytest.raises(ValueError):
            MemoryBudget(budget_kb=0)
        with pytest.raises(ValueError):
            MemoryBudget(warn_at_percent=0)
        with pytest.raises(ValueError):
            MemoryBudget(warn_at_percent=101)

    def test_add_layer_str_and_bytes() -> None:
        b = MemoryBudget(budget_kb=100)
        e1 = b.add_layer("L0", "abc")       # 3 bytes
        e2 = b.add_layer("L1", b"\x00\x01") # 2 bytes
        assert e1.bytes == 3 and e2.bytes == 2
        assert b.total_bytes() == 5

    def test_add_layer_hebrew_multibyte() -> None:
        b = MemoryBudget(budget_kb=100)
        entry = b.add_layer("L1", "שלום")
        # Hebrew chars = 2 bytes each in UTF-8
        assert entry.bytes == 8

    def test_add_layer_invalid_name() -> None:
        b = MemoryBudget()
        with pytest.raises(ValueError):
            b.add_layer("", "x")

    def test_add_layer_invalid_type() -> None:
        b = MemoryBudget()
        with pytest.raises(TypeError):
            b.add_layer("L0", 123)  # type: ignore[arg-type]

    def test_total_kb_and_percent() -> None:
        b = MemoryBudget(budget_kb=1)  # 1 KB budget
        b.add_layer("L0", "x" * 512)
        assert abs(b.total_kb() - 0.5) < 1e-6
        assert abs(b.percent_used() - 50.0) < 1e-6
        assert b.is_over() is False

    def test_is_over() -> None:
        b = MemoryBudget(budget_kb=1)
        b.add_layer("big", "x" * 2048)
        assert b.is_over() is True

    def test_warn_once() -> None:
        b = MemoryBudget(budget_kb=1, warn_at_percent=80)
        b.add_layer("L0", "x" * 900)          # ~88%
        assert b.should_warn() is True
        assert b.warn_if_needed() is True
        # second call is a no-op
        assert b.warn_if_needed() is False

    def test_warn_callback_invoked() -> None:
        calls: list[MemoryBudget] = []
        b = MemoryBudget(
            budget_kb=1, warn_at_percent=50,
            on_warn=lambda x: calls.append(x),
        )
        b.add_layer("L0", "x" * 700)
        b.warn_if_needed()
        assert calls and calls[0] is b

    def test_warn_callback_exception_swallowed() -> None:
        def boom(_b: MemoryBudget) -> None:
            raise RuntimeError("oops")
        b = MemoryBudget(budget_kb=1, warn_at_percent=50, on_warn=boom)
        b.add_layer("L0", "x" * 700)
        # must NOT raise
        b.warn_if_needed()

    def test_to_dict_roundtrip() -> None:
        import json
        b = MemoryBudget(budget_kb=5, warn_at_percent=60)
        b.add_layer("L0", "abc")
        b.add_layer("L3", "דוגמה")
        d = b.to_dict()
        s = json.dumps(d, ensure_ascii=False)
        parsed = json.loads(s)
        assert parsed["budget_kb"] == 5
        assert len(parsed["layers"]) == 2

    def test_reset() -> None:
        b = MemoryBudget(budget_kb=1, warn_at_percent=50)
        b.add_layer("L0", "x" * 800)
        b.warn_if_needed()
        b.reset()
        assert b.total_bytes() == 0
        assert b.layers == ()
        # can warn again after reset
        b.add_layer("L0", "x" * 800)
        assert b.warn_if_needed() is True

    def test_env_var_pickup(monkeypatch: Any | None = None) -> None:
        # Manual env manipulation (monkeypatch may not be available).
        old = os.environ.get(BUDGET_ENV_VAR)
        try:
            os.environ[BUDGET_ENV_VAR] = "77"
            b = MemoryBudget()
            assert b.budget_kb == 77
        finally:
            if old is None:
                os.environ.pop(BUDGET_ENV_VAR, None)
            else:
                os.environ[BUDGET_ENV_VAR] = old

    def test_env_var_bad_value_falls_back() -> None:
        old = os.environ.get(BUDGET_ENV_VAR)
        try:
            os.environ[BUDGET_ENV_VAR] = "not-a-number"
            b = MemoryBudget()
            assert b.budget_kb == DEFAULT_BUDGET_KB
        finally:
            if old is None:
                os.environ.pop(BUDGET_ENV_VAR, None)
            else:
                os.environ[BUDGET_ENV_VAR] = old

    def test_attach_to_context_loader_via_hook() -> None:
        class FakeLoader:
            def __init__(self) -> None:
                self._cb: Callable[[str, str], None] | None = None
                self._done: Callable[[], None] | None = None
            def on_layer_loaded(self, cb):
                self._cb = cb
            def on_loading_done(self, cb):
                self._done = cb
            def load(self):
                self._cb("L0", "abcdef")
                if self._done:
                    self._done()

        loader = FakeLoader()
        b = MemoryBudget(budget_kb=1, warn_at_percent=50)
        attach_to_context_loader(b, loader)
        loader.load()
        assert b.total_bytes() == 6

    def test_attach_to_context_loader_via_attr() -> None:
        class AttrLoader:
            budget: MemoryBudget | None = None
        loader = AttrLoader()
        b = MemoryBudget()
        attach_to_context_loader(b, loader)
        assert loader.budget is b

    def test_attach_missing_api_ok() -> None:
        class Nothing:
            pass
        # Must not raise.
        attach_to_context_loader(MemoryBudget(), Nothing())

    for fn in [
        test_defaults_from_constants,
        test_explicit_override,
        test_invalid_args,
        test_add_layer_str_and_bytes,
        test_add_layer_hebrew_multibyte,
        test_add_layer_invalid_name,
        test_add_layer_invalid_type,
        test_total_kb_and_percent,
        test_is_over,
        test_warn_once,
        test_warn_callback_invoked,
        test_warn_callback_exception_swallowed,
        test_to_dict_roundtrip,
        test_reset,
        test_env_var_pickup,
        test_env_var_bad_value_falls_back,
        test_attach_to_context_loader_via_hook,
        test_attach_to_context_loader_via_attr,
        test_attach_missing_api_ok,
    ]:
        fn()
    print("budget self-test PASS")


if __name__ == "__main__":  # pragma: no cover
    logging.basicConfig(level=logging.INFO)
    _tests()
