"""
Claude Master — core/claude_master.py
מנוע ניהול מרכזי: מודלים, מסלולים, ניתוב per-workspace, audit

עקרונות קנוניים (מוצר 0–3):
  - Default: claude-sonnet-4-6, thinking off, effort high, מסלול ידני
  - Trigger מפורש של משתמש תמיד עובד
  - Parallel כ-default אגרסיבי
  - שקיפות מלאה — כל החלטה נרשמת

Memory Layer (V2 — נבנה 2026-04-24):
  - כל call מתחיל ב-MemoryInitializer.init_session(project_slug, user_id)
  - system_prompt מורכב מ-5 שכבות (L0..L4) דרך context_loader
  - memory_tool + beta_headers מגיעים מ-AutoMemory.as_request_params()
  - SessionContext מחזיק את כל המצב (lock, audit, pinned, tool)
"""

from __future__ import annotations

import json
import logging
import os
import time
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any

import anthropic
from dotenv import load_dotenv

# Memory layer (V2) — שכבת הזיכרון החדשה
from core.memory.initializer import MemoryInitializer, SessionContext

# ──────────────────────────────────────────────
# Config paths
# ──────────────────────────────────────────────
ROOT = Path(__file__).parent.parent
load_dotenv(ROOT / "setup" / ".env")

WORKSPACES_FILE = ROOT / "setup" / "workspaces_created.json"
LOG_DIR = ROOT / "logs"
LOG_DIR.mkdir(exist_ok=True)

logging.basicConfig(
    level=getattr(logging, os.getenv("LOG_LEVEL", "INFO")),
    format="%(asctime)s | %(levelname)s | %(message)s",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler(LOG_DIR / "claude_master.log", encoding="utf-8"),
    ],
)
log = logging.getLogger("claude_master")


# ──────────────────────────────────────────────
# 8 המוחות — Model Registry (מוצר 1, סעיף A)
# ──────────────────────────────────────────────
class Brain(str, Enum):
    HAIKU           = "claude-haiku-4-5-20251001"
    HAIKU_THINKING  = "claude-haiku-4-5-20251001"   # + manual budget
    SONNET          = "claude-sonnet-4-6"            # ← DEFAULT CANONICAL
    SONNET_THINKING = "claude-sonnet-4-6"            # + adaptive thinking
    OPUS_46         = "claude-opus-4-6"
    OPUS_46_THINKING= "claude-opus-4-6"              # + adaptive / manual budget
    OPUS_47         = "claude-opus-4-7"
    OPUS_47_THINKING= "claude-opus-4-7"              # + adaptive (xhigh/max)


BRAIN_CONFIG: dict[str, dict] = {
    "haiku": {
        "model": Brain.HAIKU,
        "thinking": False,
        "effort": None,
        "max_tokens": 8192,
        "note": "מכני, מהיר",
    },
    "haiku_thinking": {
        "model": Brain.HAIKU_THINKING,
        "thinking": True,
        "thinking_type": "manual",
        "budget_tokens": int(os.getenv("HAIKU_45_DEFAULT_BUDGET", "1024")),
        "max_tokens": 8192,
        "note": "Haiku + manual budget",
    },
    "sonnet": {
        "model": Brain.SONNET,
        "thinking": False,
        "effort": "high",
        "max_tokens": 8192,
        "note": "DEFAULT — סולו",
    },
    "sonnet_thinking": {
        "model": Brain.SONNET_THINKING,
        "thinking": True,
        "thinking_type": "adaptive",
        "effort": "high",
        "max_tokens": 16384,
        "note": "Sonnet + adaptive thinking",
    },
    "opus_46": {
        "model": Brain.OPUS_46,
        "thinking": False,
        "effort": "high",
        "max_tokens": 8192,
        "note": "Opus 4.6 סולו",
    },
    "opus_46_thinking": {
        "model": Brain.OPUS_46_THINKING,
        "thinking": True,
        "thinking_type": "adaptive",
        "effort": "high",
        "max_tokens": 32000,
        "note": "Opus 4.6 + adaptive / שליטה ב-budget",
    },
    "opus_47": {
        "model": Brain.OPUS_47,
        "thinking": False,
        "effort": "xhigh",
        "max_tokens": 8192,
        "note": "Opus 4.7 סולו",
    },
    "opus_47_thinking": {
        "model": Brain.OPUS_47_THINKING,
        "thinking": True,
        "thinking_type": "adaptive",   # adaptive בלבד — manual הוסר ב-4.7
        "effort": "xhigh",
        "max_tokens": 65536,
        "note": "Opus 4.7 + adaptive (xhigh default)",
    },
}

# Canonical default
DEFAULT_BRAIN = "sonnet"


# ──────────────────────────────────────────────
# Per-model pricing (USD per 1M tokens · input / output)
# Source: Anthropic public pricing 2026-04 · update on tier changes
# ──────────────────────────────────────────────
MODEL_PRICING: dict[str, tuple[float, float]] = {
    # Haiku 4.5
    "claude-haiku-4-5-20251001": (1.0, 5.0),
    # Sonnet 4.6
    "claude-sonnet-4-6":         (3.0, 15.0),
    # Opus 4.6
    "claude-opus-4-6":           (15.0, 75.0),
    # Opus 4.7
    "claude-opus-4-7":           (15.0, 75.0),
}
# Fallback if model id not in table — defaults to Sonnet rates + warning (do NOT crash).
DEFAULT_PRICING: tuple[float, float] = (3.0, 15.0)


# ──────────────────────────────────────────────
# 11 המסלולים (מוצר 1, סעיף C)
# ──────────────────────────────────────────────
ROUTES: dict[str, dict] = {
    # 0 — ידני (default)
    "manual": {
        "brain": "sonnet",
        "tool_choice": "auto",
        "search_preset": "standard",     # web_search + meili
        "intent_detection": True,
        "description": "ברירת מחדל — Sonnet 4.6, חיפוש auto",
    },

    # 1 — Plan/Execute
    "plan_execute": {
        "phases": [
            {"brain": "opus_47_thinking", "role": "plan"},
            {"brain": "sonnet",           "role": "execute"},
            {"brain": "opus_47_thinking", "role": "review", "optional": True},
        ],
        "search_preset": "full",
        "intent_detection": True,
        "description": "Opus 4.7 xhigh מתכנן → Sonnet מבצע",
    },

    # 2 — Advisor
    "advisor": {
        "brain": "sonnet",
        "advisor_brain": "opus_47_thinking",
        "escalation_triggers": ["tool_error", "ambiguity", "user_request"],
        "search_preset": "standard",
        "intent_detection": True,
        "description": "Sonnet רץ, Opus יועץ בעת צורך",
    },

    # 3 — Mechanical
    "mechanical": {
        "brain": "haiku",
        "tool_choice": "auto",
        "max_tokens": 4096,
        "search_preset": "none",
        "intent_detection": False,
        "description": "Haiku — rename, format, עבודה מכנית",
    },

    # 4 — Deep Thinking
    "deep_thinking": {
        "brain": "opus_47_thinking",
        "effort": "max",
        "tool_choice": "auto",
        "search_preset": "research",     # web + think tool
        "intent_detection": True,
        "max_tokens": 32000,
        "description": "Opus 4.7 max — חשיבה עמוקה",
    },

    # 5 — Fast Lane
    "fast_lane": {
        "brain": "haiku",
        "tool_choice": "auto",
        "max_tokens": 2048,
        "timeout_sec": 15,
        "search_preset": "web_only",
        "intent_detection": False,
        "description": "Haiku 4.5 — מהירות מקסימום",
    },

    # 6 — Review Mode
    "review_mode": {
        "phases": [
            {"brain": "sonnet",           "role": "create"},
            {"brain": "opus_47_thinking", "role": "review", "effort": "xhigh"},
        ],
        "max_iterations": 3,
        "search_preset": "none",
        "intent_detection": False,
        "description": "Sonnet יוצר → Opus סוקר",
    },

    # 7 — Triple Canon (DISABLED — Phase C: executor ignores phases, silently falls to Sonnet)
    "triple_canon": {
        "enabled": False,          # Phase C: hide from UI — BLK-N-05
        "phases": [
            {"brain": "opus_47_thinking", "role": "strategy", "effort": "xhigh"},
            {"brain": "sonnet",           "role": "draft"},
            {"brain": "haiku",            "role": "qa"},
        ],
        "search_preset": "full_per_phase",
        "intent_detection": True,
        "description": "DISABLED — executor broken (Phase C)",
    },

    # 8 — Research Deep
    "research_deep": {
        "brain": "opus_47_thinking",
        "effort": "xhigh",
        "tool_choice": "auto",
        "parallel_tools": True,
        "search_preset": "full_parallel",
        "intent_detection": True,
        "max_tokens": 32000,
        "description": "Opus 4.7 xhigh + כל כלי החיפוש, parallel אגרסיבי",
    },

    # 9 — Legal Draft (עתידי — CIDAH)
    "legal_draft": {
        "brain": "opus_47_thinking",
        "effort": "xhigh",
        "tool_choice": "auto",
        "search_preset": "legal",        # nevo + takdin + meili
        "intent_detection": True,
        "max_tokens": 32000,
        "description": "Opus xhigh + מחקר משפטי (נבו + תקדין + meili)",
    },

    # 10 — Budget-Controlled (Opus 4.6 בלבד)
    "budget_controlled": {
        "brain": "opus_46_thinking",
        "budget_tokens": 4000,           # manual budget מדויק
        "tool_choice": "auto",
        "search_preset": "standard",
        "intent_detection": True,
        "description": "Opus 4.6 manual budget — שליטה מדויקת בעלות",
    },
}

DEFAULT_ROUTE = "manual"


# ──────────────────────────────────────────────
# Search Presets (מוצר 2, סעיף F)
# ──────────────────────────────────────────────
SEARCH_PRESETS: dict[str, list[str]] = {
    "none":          [],
    "standard":      ["web_search", "meili_search"],
    "web_only":      ["web_search"],
    "internal":      ["meili_search"],
    "research":      ["web_search", "web_fetch", "tool_search"],
    "legal":         ["meili_search"],   # Phase C: nevo/takdin HARD-BLOCKED · re-add only when adapters wired (Phase E/F)
    "full":          ["web_search", "web_fetch", "code_execution", "tool_search",
                      "meili_search", "scrape"],
    "full_parallel": ["web_search", "web_fetch", "code_execution", "tool_search",
                      "meili_search", "scrape", "crawl"],
}

# Tool descriptions קנוניים (מוצר 2, סעיף C)
TOOL_DESCRIPTIONS: dict[str, str] = {
    "web_search": (
        "Search the web using Google for current information, news, facts about the world, "
        "or any topic requiring up-to-date public information. Use when the user asks about "
        "events, people, products, places, or any factual knowledge that may have changed recently. "
        "Do NOT use for: specific URLs (use web_fetch), internal firm documents (use meili_search), "
        "or Israeli case law (use nevo_search or takdin_search)."
    ),
    "web_fetch": (
        "Fetch the content of a specific URL provided by the user or found in previous context. "
        "Use when: (a) the user includes a URL in their message, (b) a previous tool call returned "
        "URLs that need deep reading. Do NOT use for general search — use web_search for that."
    ),
    "code_execution": (
        "Execute Python code in a sandboxed environment. Use for: calculations, data analysis, "
        "processing structured data, running algorithms, parsing JSON/CSV. "
        "Do NOT use for simple math (respond directly) or fetching external data (use web_* tools)."
    ),
    "tool_search": (
        "Meta-tool. Use when you are unsure which specific tool is best for the user's request, "
        "especially in ambiguous queries involving multiple possible data sources."
    ),
    "meili_search": (
        "Search the firm's internal document store (Meilisearch). Contains: client matters, "
        "contracts, memos, internal knowledge, firm precedents. Use when the user asks about "
        "specific clients, matters, or firm-private information. "
        "Do NOT use for public information (use web_search) or case law (use nevo/takdin)."
    ),
    "nevo_search": (
        "Search Israeli case law on Nevo database. Use for: Israeli court decisions, "
        "case precedents, legal rulings (ע\"א, ת\"א, דנ\"א, בג\"ץ). "
        "Primary tool for Israeli legal research. Pair with takdin_search for broader coverage."
    ),
    "takdin_search": (
        "Search Israeli case law on Takdin database. Alternative and complementary to nevo_search. "
        "Use for Israeli legal research, especially when nevo_search returns limited results. "
        "Often good to call in parallel with nevo_search."
    ),
    "scrape": (
        "Scrape a single page from a specific website. Use when user explicitly says "
        "'search on website X' or you need structured content from a known page."
    ),
    "crawl": (
        "Crawl a domain deeply for comprehensive coverage. Use ONLY for explicit deep research "
        "requests on a specific domain. Expensive — prefer web_search or scrape when possible."
    ),
}

# Fallback chains (מוצר 2, עקרון 9)
# Phase C: nevo/takdin entries removed — both are HARD-BLOCKED · no silent fallback allowed.
FALLBACK_CHAINS: dict[str, str] = {
    "web_search":   "scrape",
    "meili_search": "web_search",
}


# ──────────────────────────────────────────────
# Tool Definitions — Server vs. Client
#
# Server tools: מוגדרים כ-{"type": "<api_type>", "name": "<name>"}
#   — Anthropic מריץ אותם בצד שלהם. אין schema client-side.
#   מקור: docs.anthropic.com/en/docs/agents-and-tools/tool-use/web-search-tool
#
# Client/Local tools: מוגדרים עם name + description + input_schema
#   — הקוד שלנו מריץ אותם. Claude מחזיר tool_use block ואנחנו מבצעים.
#
# גרסאות עדכניות (מחקר 2026-04-24):
#   web_search_20260209  — חדש (עם dynamic filtering), 20250305 — ישן (עדיין עובד)
#   web_fetch_20260209   — עכשיו SERVER TOOL של Anthropic (לא local)
#   code_execution_20250825 — server sandbox
# ──────────────────────────────────────────────

# Server tools — נשלחים כ-{"type": "...", "name": "..."}
# Docs: tool_choice עם extended thinking = auto בלבד (לא any/tool)
SERVER_TOOL_TYPES: dict[str, dict] = {
    "web_search": {
        "type": "web_search_20260209",    # newest — with dynamic filtering
        "name": "web_search",
        "max_uses": int(os.getenv("WEB_SEARCH_MAX_USES", "5")),
    },
    "web_fetch": {
        "type": "web_fetch_20260209",     # server tool (Anthropic-hosted)
        "name": "web_fetch",
    },
    "code_execution": {
        "type": "code_execution_20250825",
        "name": "code_execution",
    },
    "tool_search": {
        "type": "tool_search_20250605",   # meta-tool
        "name": "tool_search",
    },
}

# Client/Local tools — נשלחים עם schema, מבוצעים על ידי הקוד שלנו
# input_schema מינימלי — query string לכולם (הנחיה: תמיד strict: true)
def _local_tool_def(name: str, description: str, extra_props: dict | None = None) -> dict:
    """בונה tool definition סטנדרטי עבור כלי local."""
    props = {"query": {"type": "string", "description": "Search query"}}
    if extra_props:
        props.update(extra_props)
    return {
        "name": name,
        "description": description,
        "input_schema": {
            "type": "object",
            "properties": props,
            "required": ["query"],
        },
    }


CLIENT_TOOL_DEFS: dict[str, dict] = {
    "meili_search": _local_tool_def(
        "meili_search",
        TOOL_DESCRIPTIONS["meili_search"],
    ),
    # Phase C: nevo/takdin are HARD-BLOCKED — zero implementation, no adapter, no API key.
    # DO NOT expose to model. Do NOT silent-fallback to web_search.
    # Legal integrity: partners must not receive results falsely attributed to Nevo/Takdin.
    # Re-enable only when real adapters + credentials are wired (Phase E/F).
    # "nevo_search": _local_tool_def(...),   # BLOCKED
    # "takdin_search": _local_tool_def(...), # BLOCKED
    "scrape": _local_tool_def(
        "scrape",
        TOOL_DESCRIPTIONS["scrape"],
        extra_props={"url": {"type": "string", "description": "URL to scrape"}},
    ),
    "crawl": _local_tool_def(
        "crawl",
        TOOL_DESCRIPTIONS["crawl"],
        extra_props={"domain": {"type": "string", "description": "Domain to crawl"}},
    ),
}


# Phase C: tools that are HARD-BLOCKED at adapter level — must never reach a model call.
# Legal integrity: partners must not receive results falsely attributed to Nevo/Takdin.
# Re-add to whitelist only after real adapters + credentials are wired (Phase E/F).
HARD_BLOCKED_TOOLS: frozenset[str] = frozenset({"nevo_search", "takdin_search"})


def _build_tool_definitions(tool_names: list[str]) -> list[dict]:
    """
    ממיר רשימת שמות כלים ל-tool definitions מוכנות ל-API.

    Server tools — {"type": "web_search_20260209", "name": "web_search", ...}
    Client tools — {"name": "...", "description": "...", "input_schema": {...}}

    HARD-BLOCKED tools (nevo/takdin in Phase C) raise NotImplementedError — no silent fallback.
    כלים לא מוכרים אחרים → warning + מדולגים.
    """
    defs: list[dict] = []
    for name in tool_names:
        if name in HARD_BLOCKED_TOOLS:
            raise NotImplementedError(
                f"Tool '{name}' is HARD-BLOCKED in Phase C — no adapter, no credentials. "
                "Do not call. Legal integrity gate (CIDAH playbook · Israeli Bar disclosure)."
            )
        if name in SERVER_TOOL_TYPES:
            defs.append(dict(SERVER_TOOL_TYPES[name]))  # copy — בטוח לשינוי
        elif name in CLIENT_TOOL_DEFS:
            defs.append(CLIENT_TOOL_DEFS[name])
        else:
            log.warning("Unknown tool '%s' — skipped (not in SERVER_TOOL_TYPES or CLIENT_TOOL_DEFS)", name)
    return defs


# ──────────────────────────────────────────────
# Workspace Registry — per-member API keys
# ──────────────────────────────────────────────
@dataclass
class WorkspaceMember:
    name: str
    workspace_id: str
    workspace_name: str
    api_key: str
    role: str = "team_lawyer"
    client: anthropic.Anthropic = field(default=None, repr=False)

    def __post_init__(self):
        if self.api_key and self.api_key != "ERROR":
            self.client = anthropic.Anthropic(api_key=self.api_key)

    @property
    def is_admin(self) -> bool:
        return self.workspace_name == "claude-master-admin"


def _load_workspaces() -> dict[str, WorkspaceMember]:
    """טוען את כל ה-workspaces מהקובץ שנוצר."""
    if not WORKSPACES_FILE.exists():
        log.warning(f"workspaces_created.json לא נמצא: {WORKSPACES_FILE}")
        return {}

    with open(WORKSPACES_FILE, encoding="utf-8") as f:
        raw = json.load(f)

    members: dict[str, WorkspaceMember] = {}
    for entry in raw:
        m = WorkspaceMember(
            name=entry["member"],
            workspace_id=entry["id"],
            workspace_name=entry["name"],
            api_key=entry.get("api_key", "ERROR"),
        )
        members[entry["name"]] = m     # key by workspace_name
        log.debug(f"Loaded workspace: {m.name} ({m.workspace_name})")

    log.info(f"✅ {len(members)} workspaces נטענו")
    return members


WORKSPACES: dict[str, WorkspaceMember] = _load_workspaces()


def get_member(workspace_name: str) -> WorkspaceMember | None:
    return WORKSPACES.get(workspace_name)


def get_admin() -> WorkspaceMember | None:
    return WORKSPACES.get("claude-master-admin")


# ──────────────────────────────────────────────
# Route instructions builder — layer ABOVE the 5-layer memory context.
# נבנה בעקבות memory layer V2 (2026-04-24).
#
# התפקיד: להוסיף לשכבות L0..L4 (שמגיעות מ-context_loader) את ההנחיות
# התפעוליות הספציפיות למסלול — tool use, intent detection, parallel vs
# sequential, transparency. L0..L3 אחראים על זהות, עקרונות וידע לקוח —
# כאן רק "איך להריץ את הקריאה הזו".
# ──────────────────────────────────────────────
def _build_route_instructions(
    route_name: str,
    active_tools: list[str],
    extra_context: str = "",
) -> str:
    route = ROUTES.get(route_name, ROUTES[DEFAULT_ROUTE])
    brain_key = route.get("brain", DEFAULT_BRAIN)
    brain = BRAIN_CONFIG[brain_key]

    parts = [
        f"## Route: {route_name}",
        f"- Description: {route.get('description', '')}",
        f"- Brain: {brain['note']} ({brain['model']})",
        "",
        "## Tool Use Guidelines",
        "",
        "You have access to search tools. Decide based on the user's intent, not their words.",
        "",
        "### Intent Detection (by meaning, not keywords)",
        "- Question about the world / news / current events → web_search",
        "- URL in user's message → web_fetch",
        "- Firm / client / matter / internal-knowledge question → meili_search",
        "- Israeli case law (פסיקה · ע\"א · ת\"א · בג\"ץ · דנ\"א) → respond that case-law search is unavailable in Phase C; defer to attorney manual research. Do NOT call nevo_search or takdin_search — they are hard-blocked.",
        "- Calculations / data analysis / parsing structured data → code_execution",
        "- Ambiguous query, unsure which tool fits → tool_search (meta)",
        "",
        "### Explicit Triggers (HIGHEST PRIORITY)",
        "If user says 'search on X', 'check in Y', 'look up Z', or names a specific tool/database — use that tool. Override intent detection. Triggers always work, even on routes with intent detection OFF.",
        "",
        "### Parallel vs Sequential",
        "Default to parallel. Only go sequential when one tool's output is required as input to another.",
        "For example, when reading 3 files, run 3 tool calls in parallel.",
        "",
        "<use_parallel_tool_calls>",
        "For maximum efficiency, whenever you perform multiple independent operations,",
        "invoke all relevant tools simultaneously rather than sequentially.",
        "</use_parallel_tool_calls>",
        "",
        "### When NOT to use tools",
        "- Simple conversation",
        "- Questions you already know the answer to",
        "- Creative or analytical tasks that don't require external data",
        "- Mechanical work (rename, reformat, transform)",
        "",
        "### The think tool",
        "If you are in a chain of 5+ tool calls, invoke `think` (when present) to pause and reason about next steps before continuing.",
        "",
        "### Transparency",
        "Before each tool call, briefly explain what you're doing in one sentence (e.g., 'Checking web_search for current ruling on X…'). After the call, state what you found in one or two sentences before deciding the next step.",
    ]

    if active_tools:
        parts += ["", f"### Active tools: {', '.join(active_tools)}"]

    if extra_context:
        parts += ["", "## Extra context", extra_context]

    return "\n".join(parts)

# ──────────────────────────────────────────────
# API call builder
# ──────────────────────────────────────────────
def _build_api_params(
    route_name: str,
    messages: list[dict],
    system_prompt: str,
    override_brain: str | None = None,
    override_effort: str | None = None,
    override_budget: int | None = None,
) -> dict:
    route = ROUTES.get(route_name, ROUTES[DEFAULT_ROUTE])
    brain_key = override_brain or route.get("brain", DEFAULT_BRAIN)
    brain = BRAIN_CONFIG[brain_key]

    params: dict[str, Any] = {
        "model": brain["model"],
        "max_tokens": route.get("max_tokens", brain.get("max_tokens", 8192)),
        "system": system_prompt,
        "messages": messages,
    }

    # ── Thinking / Effort ────────────────────────────────────────────────────
    # API canonical rules (2026):
    #   • Adaptive thinking  (Sonnet 4.6, Opus 4.6, Opus 4.7):
    #       params["thinking"] = {"type": "adaptive"}   ← thinking object
    #       params["effort"]   = "high" / "xhigh" / …  ← TOP-LEVEL, not inside thinking
    #   • Manual budget (Haiku 4.5, Opus 4.6 budget_controlled):
    #       params["thinking"] = {"type": "enabled", "budget_tokens": N}
    #       NO top-level effort
    #   • No thinking but model accepts effort (Sonnet/Opus non-thinking brains):
    #       params["effort"]   = "high" / …            ← only top-level
    #       NO thinking object at all
    #
    # NOTE: budget_tokens inside thinking{} is deprecated for adaptive models.
    # --------------------------------------------------------------------------
    effort = override_effort or route.get("effort") or brain.get("effort")
    thinking_enabled: bool = brain.get("thinking", False)
    thinking_type: str = brain.get("thinking_type", "")  # "adaptive" | "manual" | ""

    if thinking_enabled and thinking_type == "adaptive":
        # Adaptive: thinking object + top-level effort (Sonnet/Opus with thinking)
        params["thinking"] = {"type": "adaptive"}
        eff = effort or "high"
        params["effort"] = eff

    elif thinking_enabled and thinking_type == "manual":
        # Manual budget: Haiku 4.5 (and budget_controlled Opus 4.6 if requested)
        budget = override_budget or brain.get("budget_tokens", 1024)
        params["thinking"] = {"type": "enabled", "budget_tokens": budget}
        # No top-level effort for manual-budget models

    else:
        # No thinking — but model still accepts effort (e.g. Sonnet 4.6, Opus 4.6/4.7 no-think)
        if effort and brain_key not in ("haiku",):
            params["effort"] = effort

    # budget_controlled override: caller passes override_budget explicitly
    # on a non-haiku brain → switch to manual budget mode
    if override_budget and not (thinking_enabled and thinking_type == "manual"):
        params.pop("effort", None)
        params["thinking"] = {"type": "enabled", "budget_tokens": override_budget}

    return params


def _effort_to_budget(effort: str) -> int:
    """ממיר effort level ל-budget_tokens."""
    return {
        "low":    1024,
        "medium": 4096,
        "high":   10000,
        "xhigh":  32000,
        "max":    65536,
    }.get(effort, 10000)


# ──────────────────────────────────────────────
# Audit logger
# ──────────────────────────────────────────────
AUDIT_FILE = LOG_DIR / "audit.jsonl"


def _audit(event: dict) -> None:
    event["ts"] = time.strftime("%Y-%m-%dT%H:%M:%S")
    with open(AUDIT_FILE, "a", encoding="utf-8") as f:
        f.write(json.dumps(event, ensure_ascii=False) + "\n")


# ──────────────────────────────────────────────
# ClaudeMaster — ממשק ראשי
# ──────────────────────────────────────────────
class ClaudeMaster:
    """
    ממשק מרכזי לניהול קריאות Claude per-workspace.

    שימוש בסיסי (עם memory layer):
        cm = ClaudeMaster()
        response = cm.call(
            workspace="team-member-01",
            project_slug="cohen-levy",
            prompt="מה הפסיקה האחרונה בנושא פיצויי פיטורין?",
            route="legal_draft",
        )

    כל call:
      1. resolve project → hashed slug
      2. MemoryInitializer.init_session() → SessionContext
      3. system_prompt = L0..L4 מהקשר 5-שכבות
      4. beta_headers + memory_tool מ-auto.as_request_params()
      5. audit + session_lock → release בסוף
    """

    def __init__(self, memory_initializer: MemoryInitializer | None = None):
        self.workspaces = WORKSPACES
        self.admin = get_admin()
        # MemoryInitializer singleton — משותף לכל ה-calls
        self.memory = memory_initializer or MemoryInitializer()
        log.info(
            f"ClaudeMaster initialized — {len(self.workspaces)} workspaces, "
            f"memory layer: active"
        )

    # ── ניתוב בסיסי ──────────────────────────
    def call(
        self,
        workspace: str,
        project_slug: str,
        prompt: str,
        route: str = DEFAULT_ROUTE,
        user_id: str | None = None,
        messages_history: list[dict] | None = None,
        override_brain: str | None = None,
        override_effort: str | None = None,
        override_budget: int | None = None,
        extra_context: str = "",
        incognito: bool = False,
        system: str = "cidah",
        entity_type: str = "client",
        anchor_path: Path | None = None,
    ) -> dict:
        """
        שולח בקשה דרך ה-workspace של המשתמש עם memory layer מלא.

        Parameters
        ----------
        workspace : str
            שם ה-workspace (למשל "team-member-01" או "claude-master-admin").
        project_slug : str
            slug של הפרויקט / לקוח — מבודד את ה-memory store (V2 §4).
        prompt : str
            ההודעה מהמשתמש.
        route : str
            אחד מ-ROUTES (manual, plan_execute, legal_draft, ...).
        user_id : str | None
            מזהה המשתמש. ברירת מחדל — שם ה-member של ה-workspace.
        incognito : bool
            במצב incognito: אין auto-memory, pinned נטען ל-readonly.
        system, entity_type, anchor_path :
            מועברים ישירות ל-project_resolver.resolve() — רוב הקריאות
            צריכות רק את project_slug ולכן הברירות עובדות.

        Returns
        -------
        dict עם: text, model, route, usage, thinking, session_id, warnings.
        """
        member = self.workspaces.get(workspace)
        if not member:
            raise ValueError(f"Workspace לא נמצא: {workspace}")
        if not member.client:
            raise RuntimeError(f"API key חסר/שגוי עבור: {workspace}")

        if route not in ROUTES:
            log.warning(f"מסלול '{route}' לא מוגדר — חוזר ל-manual")
            route = DEFAULT_ROUTE
        route_cfg = ROUTES[route]

        # user_id — נגזר מה-member אם לא הוזן
        resolved_user_id = user_id or member.name

        # ── 1. Memory layer — init session ───────────────
        ctx: SessionContext = self.memory.init_session(
            system=system,
            entity_type=entity_type,
            entity_id=project_slug,
            user_id=resolved_user_id,
            anchor_path=anchor_path,
            incognito=incognito,
            ctx={
                "route": route,
                "workspace": workspace,
                # ARB-R2: incognito_lite for mechanical/fast_lane — no auto memory,
                # but pinned + L0 + L1 always loaded (context_loader honours this).
                "incognito_lite": route in ("mechanical", "fast_lane"),
            },
        )

        try:
            # ── 2. כלים פעילים לפי preset ────────────────
            preset_name = route_cfg.get("search_preset", "standard")
            active_tools = SEARCH_PRESETS.get(preset_name, [])

            # ── 3. messages ──────────────────────────────
            messages = list(messages_history or [])
            messages.append({"role": "user", "content": prompt})

            # ── 4. system_prompt מ-context_loader (L0..L4) ─
            # ה-MemoryInitializer כבר הרכיב את ה-prompt ב-ctx.system_prompt.
            # מוסיפים עליו את ההנחיות התפעוליות של המסלול + extra_context.
            route_instructions = _build_route_instructions(
                route, active_tools, extra_context
            )
            system_prompt = ctx.system_prompt + "\n\n" + route_instructions

            # ── 5. API params ────────────────────────────
            params = _build_api_params(
                route_name=route,
                messages=messages,
                system_prompt=system_prompt,
                override_brain=override_brain,
                override_effort=override_effort,
                override_budget=override_budget,
            )

            # ── 5b. Search + client tool definitions ─────
            # active_tools → tool definitions list (server tools + client tools).
            # Search tools go FIRST so the model sees them before the memory tool.
            tool_defs = _build_tool_definitions(active_tools)
            if tool_defs:
                params.setdefault("tools", [])
                params["tools"] = tool_defs + params["tools"]

            # ── 5c. disable_parallel_tool_use ────────────
            # Some routes prefer sequential tool use (e.g. budget_controlled, legal_draft).
            if route_cfg.get("disable_parallel_tool_use"):
                params["disable_parallel_tool_use"] = True

            # ── 6. Memory tool + beta headers ────────────
            # ב-non-incognito: AutoMemory זמין ב-ctx.auto_memory.
            # אחרת: משתמשים ישירות ב-ctx.tool_config / ctx.beta_headers.
            extra_headers: dict[str, str] = {}
            if not incognito and ctx.auto_memory is not None:
                tool_config, beta_headers = ctx.auto_memory.as_request_params()
                # שילוב ה-memory_tool בתוך tools (בנוסף לכלי החיפוש)
                params.setdefault("tools", [])
                params["tools"].append(tool_config)
                extra_headers.update(beta_headers)
            elif not incognito:
                # fallback: משתמשים ישירות ב-config מ-ctx
                params.setdefault("tools", [])
                params["tools"].append(ctx.tool_config)
                extra_headers.update(ctx.beta_headers)

            # ── 6b. tool_choice + thinking safety guard ──
            # With extended thinking, only "auto" and "none" are valid.
            # Any other tool_choice (like "any" or specific tool) causes API errors.
            if params.get("thinking"):
                current_tc = route_cfg.get("tool_choice")
                if current_tc not in (None, "auto", "none"):
                    log.warning(
                        "tool_choice='%s' is incompatible with extended thinking — "
                        "forcing tool_choice='auto'",
                        current_tc,
                    )
                    params["tool_choice"] = {"type": "auto"}
                elif current_tc == "auto":
                    params["tool_choice"] = {"type": "auto"}
                # None → don't send tool_choice at all (API default = auto)
            elif route_cfg.get("tool_choice") and params.get("tools"):
                tc = route_cfg["tool_choice"]
                if tc == "auto":
                    params["tool_choice"] = {"type": "auto"}
                elif tc == "any":
                    params["tool_choice"] = {"type": "any"}
                elif tc == "none":
                    params["tool_choice"] = {"type": "none"}

            if extra_headers:
                params["extra_headers"] = extra_headers

            log.info(
                f"→ {member.name} | slug={project_slug} | route={route} | "
                f"model={params['model']} | tools={active_tools} | "
                f"session={ctx.session_id[:8]} | incognito={incognito}"
            )
            _audit({
                "event": "call_start",
                "workspace": workspace,
                "member": member.name,
                "project_slug": project_slug,
                "session_id": ctx.session_id,
                "route": route,
                "model": params["model"],
                "tools": active_tools,
                "incognito": incognito,
                "prompt_preview": prompt[:100],
            })

            # ── 7. API call ──────────────────────────────
            start = time.time()
            try:
                response = member.client.messages.create(**params)
            except anthropic.APIError as e:
                log.error(f"API error: {e}")
                _audit({
                    "event": "call_error",
                    "workspace": workspace,
                    "project_slug": project_slug,
                    "session_id": ctx.session_id,
                    "error": str(e),
                })
                raise

            elapsed = round(time.time() - start, 2)

            # ── 8. parse ─────────────────────────────────
            result = self._parse_response(response, workspace, route, elapsed)
            result["session_id"] = ctx.session_id
            result["project_slug"] = project_slug
            result["memory_warnings"] = list(ctx.warnings)
            log.info(
                f"✓ {member.name} | slug={project_slug} | {elapsed}s | "
                f"${result['cost_usd']:.4f}"
            )
            return result

        finally:
            # ── 9. Release session (audit + lock) ────────
            ctx.close(reason="call_complete")

    # ── Admin call (משתמש ב-admin key) ───────
    def admin_call(
        self,
        project_slug: str,
        prompt: str,
        route: str = DEFAULT_ROUTE,
        **kwargs,
    ) -> dict:
        """קריאה דרך ה-admin workspace (Guy Neeman) עם memory layer."""
        return self.call(
            workspace="claude-master-admin",
            project_slug=project_slug,
            prompt=prompt,
            route=route,
            **kwargs,
        )

    # ── Multi-phase routes ───────────────────
    def plan_and_execute(
        self,
        workspace: str,
        project_slug: str,
        prompt: str,
        extra_context: str = "",
    ) -> dict:
        """
        Plan/Execute — Phase 1: Opus 4.7 מתכנן → Phase 2: Sonnet מבצע.
        מחזיר dict עם plan + execution.
        """
        log.info(f"Plan/Execute → {workspace} | slug={project_slug}")

        # Phase 1: Plan
        plan_result = self.call(
            workspace=workspace,
            project_slug=project_slug,
            prompt=f"צור תוכנית עבודה מפורטת:\n\n{prompt}",
            route="plan_execute",
            override_brain="opus_47_thinking",
            override_effort="xhigh",
            extra_context=extra_context,
        )
        plan_text = plan_result["text"]
        log.info(f"Plan ready ({len(plan_text)} chars)")

        # Phase 2: Execute
        execute_result = self.call(
            workspace=workspace,
            project_slug=project_slug,
            prompt=prompt,
            route="manual",
            override_brain="sonnet",
            extra_context=f"## תוכנית עבודה שאושרה\n{plan_text}\n\n{extra_context}",
        )

        return {
            "plan": plan_text,
            "execution": execute_result["text"],
            "plan_usage": plan_result["usage"],
            "execute_usage": execute_result["usage"],
            "total_cost_usd": plan_result["cost_usd"] + execute_result["cost_usd"],
        }

    def review_mode(
        self,
        workspace: str,
        project_slug: str,
        prompt: str,
        max_iterations: int = 3,
    ) -> dict:
        """
        Review Mode — Sonnet יוצר, Opus סוקר. עד max_iterations.
        """
        log.info(f"Review Mode → {workspace} | slug={project_slug} | max={max_iterations}")
        history: list[dict] = []
        total_cost = 0.0

        for i in range(1, max_iterations + 1):
            # Create
            create_result = self.call(
                workspace=workspace,
                project_slug=project_slug,
                prompt=prompt if i == 1 else f"תקן לפי ההערות:\n{history[-1]['content']}",
                route="review_mode",
                override_brain="sonnet",
                messages_history=history,
            )
            draft = create_result["text"]
            total_cost += create_result["cost_usd"]
            history.append({"role": "assistant", "content": draft})

            # Review
            review_result = self.call(
                workspace=workspace,
                project_slug=project_slug,
                prompt=f"סקור ביקורתית:\n\n{draft}\n\nהחזר: approved | revisions_needed + הערות",
                route="review_mode",
                override_brain="opus_47_thinking",
                override_effort="xhigh",
            )
            review_text = review_result["text"]
            total_cost += review_result["cost_usd"]

            if "approved" in review_text.lower():
                log.info(f"Review approved on iteration {i}")
                return {"result": draft, "review": review_text,
                        "iterations": i, "total_cost_usd": total_cost}

            history.append({"role": "user", "content": review_text})

        log.warning(f"Review Mode: max iterations ({max_iterations}) reached")
        return {"result": draft, "review": "max iterations reached",
                "iterations": max_iterations, "total_cost_usd": total_cost}

    # ── Broadcast (שולח לכל ה-workspaces) ────
    def broadcast(
        self,
        project_slug: str,
        prompt: str,
        route: str = DEFAULT_ROUTE,
        workspaces: list[str] | None = None,
    ) -> dict[str, dict]:
        """
        שולח אותה בקשה לכמה workspaces במקביל, כולם על אותו project_slug.
        מחזיר dict של תוצאות per workspace.
        """
        import concurrent.futures

        targets = workspaces or list(self.workspaces.keys())
        results: dict[str, dict] = {}

        def _call(ws: str) -> tuple[str, dict]:
            try:
                return ws, self.call(
                    workspace=ws,
                    project_slug=project_slug,
                    prompt=prompt,
                    route=route,
                )
            except Exception as e:
                return ws, {"error": str(e)}

        with concurrent.futures.ThreadPoolExecutor(max_workers=min(10, len(targets))) as ex:
            futures = {ex.submit(_call, ws): ws for ws in targets}
            for future in concurrent.futures.as_completed(futures):
                ws, result = future.result()
                results[ws] = result
                log.info(f"Broadcast ✓ {ws}")

        return results

    # ── Spend monitoring ─────────────────────
    def usage_report(self) -> dict:
        """קורא את ה-audit log ומחשב usage מצטבר per workspace."""
        if not AUDIT_FILE.exists():
            return {"total_calls": 0, "workspaces": {}}

        calls_by_ws: dict[str, list] = {}
        with open(AUDIT_FILE, encoding="utf-8") as f:
            for line in f:
                try:
                    ev = json.loads(line)
                    if ev.get("event") == "call_end":
                        ws = ev.get("workspace", "unknown")
                        calls_by_ws.setdefault(ws, []).append(ev)
                except json.JSONDecodeError:
                    continue

        report: dict[str, Any] = {"workspaces": {}}
        total_cost = 0.0
        total_calls = 0

        for ws, calls in calls_by_ws.items():
            cost = sum(c.get("cost_usd", 0) for c in calls)
            member = self.workspaces.get(ws)
            report["workspaces"][ws] = {
                "member": member.name if member else ws,
                "calls": len(calls),
                "total_cost_usd": round(cost, 4),
            }
            total_cost += cost
            total_calls += len(calls)

        report["total_calls"] = total_calls
        report["total_cost_usd"] = round(total_cost, 4)
        return report

    # ── Internal helpers ─────────────────────
    @staticmethod
    def _parse_response(
        response: anthropic.types.Message,
        workspace: str,
        route: str,
        elapsed: float,
    ) -> dict:
        text_parts = []
        thinking_parts = []

        for block in response.content:
            if hasattr(block, "text"):
                text_parts.append(block.text)
            elif hasattr(block, "thinking"):
                thinking_parts.append(block.thinking)

        # Cost estimation — per-model pricing (Phase C: was flat-Sonnet · now differentiated)
        usage = response.usage
        in_rate, out_rate = MODEL_PRICING.get(response.model, DEFAULT_PRICING)
        if response.model not in MODEL_PRICING:
            log.warning("MODEL_PRICING missing entry for '%s' — falling back to Sonnet rates", response.model)
        input_cost  = (usage.input_tokens  / 1_000_000) * in_rate
        output_cost = (usage.output_tokens / 1_000_000) * out_rate
        cost_usd = input_cost + output_cost

        result = {
            "text": "\n".join(text_parts),
            "thinking": "\n".join(thinking_parts) if thinking_parts else None,
            "model": response.model,
            "route": route,
            "workspace": workspace,
            "elapsed_sec": elapsed,
            "usage": {
                "input_tokens": usage.input_tokens,
                "output_tokens": usage.output_tokens,
            },
            "cost_usd": round(cost_usd, 6),
            "stop_reason": response.stop_reason,
        }

        _audit({
            "event": "call_end",
            "workspace": workspace,
            "route": route,
            "model": response.model,
            "elapsed_sec": elapsed,
            "input_tokens": usage.input_tokens,
            "output_tokens": usage.output_tokens,
            "cost_usd": result["cost_usd"],
        })

        return result


# ──────────────────────────────────────────────
# Singleton
# ──────────────────────────────────────────────
_instance: ClaudeMaster | None = None


def get_master() -> ClaudeMaster:
    global _instance
    if _instance is None:
        _instance = ClaudeMaster()
    return _instance


# ──────────────────────────────────────────────
# CLI quick-test
# ──────────────────────────────────────────────
if __name__ == "__main__":
    import sys

    cm = get_master()

    if len(sys.argv) < 3:
        print("Usage: python claude_master.py [workspace] [project_slug] [prompt] [route]")
        print(f"\nWorkspaces: {list(cm.workspaces.keys())}")
        print(f"Routes:     {list(ROUTES.keys())}")
        sys.exit(0)

    ws = sys.argv[1]
    slug = sys.argv[2]
    prompt = sys.argv[3] if len(sys.argv) > 3 else "שלום, מה אתה יכול לעשות?"
    route = sys.argv[4] if len(sys.argv) > 4 else DEFAULT_ROUTE

    print(f"\n→ {ws} | slug={slug} | {route} | {prompt[:60]}...\n")
    result = cm.call(
        workspace=ws,
        project_slug=slug,
        prompt=prompt,
        route=route,
    )
    print(result["text"])
    print(
        f"\n[model={result['model']} | {result['elapsed_sec']}s | "
        f"${result['cost_usd']:.4f} | session={result.get('session_id', '-')[:8]}]"
    )
    if result.get("memory_warnings"):
        print(f"\n[memory warnings: {result['memory_warnings']}]")
