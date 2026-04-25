"""
core.memory.auto — Anthropic SDK bridge for the auto-memory store.

This module wraps :class:`core.memory.tool.MemoryTool` in the shape
expected by ``anthropic.lib.tools.BetaAbstractMemoryTool`` (Python SDK).
Why a separate file?

1. :mod:`core.memory.tool` stays SDK-independent so tests & CLI don't
   need the ``anthropic`` package at import time.
2. The SDK's class signature has shifted across minor releases (``0.39`` →
   ``0.4x``); all the version-sniffing lives here.
3. In some deployments we run without the SDK (e.g. when proxying raw
   JSON through a direct HTTP call). ``AutoMemory.is_sdk_available()``
   lets callers probe.

Usage
-----

::

    from core.memory.auto import AutoMemory

    auto = AutoMemory(
        project_slug="cidah-cohen-levy-a1b2",
        project_root=Path("/data/projects/cidah-cohen-levy-a1b2"),
        user="guy",
        session_id=session_uuid,
        policy=policy_dict,
    )

    tool_param, beta_headers = auto.as_request_params()
    # → tool_param   = {"type": "memory_20250818", "name": "memory"}
    # → beta_headers = {"anthropic-beta": "context-management-2025-06-27"}

    # Then when the SDK surfaces a tool_use block:
    result = auto.handle(command="view", path="/memories/decisions.md")
"""

from __future__ import annotations

import importlib
import logging
from pathlib import Path
from typing import Any

from core.memory.tool import MemoryTool

__all__ = ["AutoMemory", "AutoMemoryUnavailable"]

log = logging.getLogger(__name__)


class AutoMemoryUnavailable(RuntimeError):
    """Raised when the Anthropic SDK memory base class cannot be located."""


def _try_import_base() -> type | None:
    """Best-effort import of ``BetaAbstractMemoryTool`` across SDK versions.

    Known locations (in rough release order):

    * ``anthropic.lib.tools.BetaAbstractMemoryTool``
    * ``anthropic.lib.tools.memory.BetaAbstractMemoryTool``
    * ``anthropic.types.beta.BetaAbstractMemoryTool``

    We try each, log which one we found, and return None silently when
    none works — the wrapper keeps functioning via raw ``dispatch``.
    """
    candidates = (
        ("anthropic.lib.tools", "BetaAbstractMemoryTool"),
        ("anthropic.lib.tools.memory", "BetaAbstractMemoryTool"),
        ("anthropic.types.beta", "BetaAbstractMemoryTool"),
        ("anthropic.lib.tools.beta_abstract_memory_tool",
         "BetaAbstractMemoryTool"),
    )
    for mod_name, attr in candidates:
        try:
            mod = importlib.import_module(mod_name)
            base = getattr(mod, attr, None)
            if base is not None:
                log.debug("AutoMemory: using %s.%s", mod_name, attr)
                return base
        except ImportError:
            continue
    log.info(
        "anthropic.BetaAbstractMemoryTool not found; "
        "AutoMemory runs without SDK subclass (raw dispatch still works)."
    )
    return None


_BASE: type | None = _try_import_base()


class AutoMemory:
    """Thin adapter over :class:`MemoryTool`.

    Holds the underlying tool as an instance attribute; optionally also
    constructs an SDK-subclass instance bound to the same backend when
    ``anthropic`` is importable and a subclass can be synthesised.

    This class is the ONLY place in the codebase that imports anything
    from ``anthropic.lib.tools`` — everything else depends on the plain
    :class:`MemoryTool`.
    """

    def __init__(
        self,
        *,
        project_slug: str,
        project_root: Path,
        user: str,
        session_id: str,
        policy: dict[str, Any] | None = None,
        audit_path: Path | None = None,
    ) -> None:
        self._impl = MemoryTool(
            project_slug=project_slug,
            project_root=project_root,
            user=user,
            session_id=session_id,
            policy=policy,
            audit_path=audit_path,
        )
        self._sdk_obj: Any = None
        if _BASE is not None:
            try:
                self._sdk_obj = self._make_sdk_subclass()
            except Exception as e:  # noqa: BLE001
                log.warning(
                    "AutoMemory: failed to build SDK subclass (%s); "
                    "falling back to raw dispatch.", e,
                )
                self._sdk_obj = None

    # ------------------------------------------------------------------ #
    # SDK surface
    # ------------------------------------------------------------------ #

    @staticmethod
    def is_sdk_available() -> bool:
        """True if ``anthropic.BetaAbstractMemoryTool`` was importable."""
        return _BASE is not None

    def as_sdk_object(self) -> Any:
        """Return the SDK subclass instance, or raise.

        Callers who want to pass a Python object directly to
        ``client.beta.messages.create(..., memory_tool=auto.as_sdk_object())``
        (if/when the SDK exposes that kwarg) use this. Otherwise prefer
        :meth:`as_request_params` + manual dispatch.
        """
        if self._sdk_obj is None:
            raise AutoMemoryUnavailable(
                "BetaAbstractMemoryTool not importable — "
                "use as_request_params() + handle() instead."
            )
        return self._sdk_obj

    def as_request_params(self) -> tuple[dict[str, str], dict[str, str]]:
        """Return ``(tool_config, beta_headers)`` to merge into the request.

        These are stable regardless of SDK version, because they're the
        raw HTTP shape.
        """
        return MemoryTool.tool_config(), MemoryTool.beta_header()

    # ------------------------------------------------------------------ #
    # Dispatch — this is what the request loop actually calls.
    # ------------------------------------------------------------------ #

    def handle(self, *, command: str, **kwargs: Any) -> dict[str, Any]:
        """Run one memory command, returning a JSON-serialisable result."""
        return self._impl.dispatch(command, **kwargs)

    # Convenience per-command methods — let callers skip the dispatch
    # indirection when they already know the command. They delegate to
    # the underlying tool so behaviour stays identical.

    def view(self, path: str) -> dict[str, Any]:
        return self._impl.dispatch("view", path=path)

    def create(self, path: str, file_text: str) -> dict[str, Any]:
        return self._impl.dispatch("create", path=path, file_text=file_text)

    def str_replace(
        self, path: str, old_str: str, new_str: str
    ) -> dict[str, Any]:
        return self._impl.dispatch(
            "str_replace", path=path, old_str=old_str, new_str=new_str
        )

    def insert(
        self, path: str, insert_line: int, insert_text: str
    ) -> dict[str, Any]:
        return self._impl.dispatch(
            "insert",
            path=path,
            insert_line=insert_line,
            insert_text=insert_text,
        )

    def delete(self, path: str) -> dict[str, Any]:
        return self._impl.dispatch("delete", path=path)

    def rename(self, old_path: str, new_path: str) -> dict[str, Any]:
        return self._impl.dispatch(
            "rename", old_path=old_path, new_path=new_path
        )

    # ------------------------------------------------------------------ #
    # Internals
    # ------------------------------------------------------------------ #

    def _make_sdk_subclass(self) -> Any:
        """Dynamically synthesise a subclass of ``BetaAbstractMemoryTool``.

        We never know exactly which abstract methods the installed SDK
        requires — different releases have required different sets. We
        inspect the base and hook every abstract method we recognise
        into our :class:`MemoryTool` dispatch.
        """
        assert _BASE is not None
        impl = self._impl

        def _bridge(command: str):
            def _fn(self, **kwargs):
                return impl.dispatch(command, **kwargs)
            _fn.__name__ = command
            return _fn

        attrs: dict[str, Any] = {
            "view": _bridge("view"),
            "create": _bridge("create"),
            "str_replace": _bridge("str_replace"),
            "insert": _bridge("insert"),
            "delete": _bridge("delete"),
            "rename": _bridge("rename"),
        }
        # Some SDK revisions prefer a single entry point.
        def _run(self, command: str, **kwargs):
            return impl.dispatch(command, **kwargs)
        attrs["run"] = _run
        attrs["execute"] = _run

        sub = type("ProjectAutoMemoryTool", (_BASE,), attrs)
        try:
            return sub()
        except TypeError as e:
            # Base may require constructor args we don't know about.
            log.warning("SDK subclass construction failed: %s", e)
            raise


# --------------------------------------------------------------------------- #
# Self-test
# --------------------------------------------------------------------------- #


def _self_test() -> None:  # pragma: no cover
    import tempfile
    import uuid

    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        (root / "memory" / "auto").mkdir(parents=True)
        am = AutoMemory(
            project_slug="t",
            project_root=root,
            user="u",
            session_id=str(uuid.uuid4()),
        )
        cfg, hdr = am.as_request_params()
        assert cfg == {"type": "memory_20250818", "name": "memory"}
        assert hdr == {"anthropic-beta": "context-management-2025-06-27"}

        r = am.create("/memories/a.md", "hello")
        assert r["ok"], r
        r = am.view("/memories/a.md")
        assert r["type"] == "file"
        r = am.str_replace("/memories/a.md", "hello", "shalom")
        assert r["ok"], r
        r = am.rename("/memories/a.md", "/memories/b.md")
        assert r["ok"], r
        r = am.delete("/memories/b.md")
        assert r["ok"], r
        print(
            "AutoMemory self-test PASS (sdk_available=%s)" % am.is_sdk_available()
        )


if __name__ == "__main__":  # pragma: no cover
    logging.basicConfig(level=logging.INFO)
    _self_test()
