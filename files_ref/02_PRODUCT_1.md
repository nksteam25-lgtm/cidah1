# CIDAH — מוצר 1: המטריצה הטכנית

**גרסה:** 3.0 (קנוני — מתוקן לפי מוצר 2)
**תאריך:** 24 אפריל 2026
**מטרה:** הגדרות טכניות של המוחות, המסלולים וה-`.env` של בינה
**תלוי ב:** מוצר 0 (UX) — המסמך הזה טכני בלבד
**נשלט על-ידי:** מוצר 2 (מוח החיפוש) — layer עליון

---

## אינדקס קנוני — 4 המוצרים

**המוצרים האלה הם שכבות הירככיות. כל מוצר מניח את הקודם לו.**

### 🟦 מוצר 0 — Ground Zero + UX הבחירה
- נקודת ההתחלה (Sonnet 4.6, ידני)
- Welcome message, Status Bar
- 4 הלשוניות (מוח / חיפוש / מסלולים / מתקדם)
- כללי כניסה/יציאה ממסלולים
- Onboarding, שקיפות

### 🟩 מוצר 1 — המטריצה הטכנית (המסמך הזה)
- 8 המוחות (specs + API params + effort levels)
- 11 המסלולים (configs טכניים מלאים)
- Tools — API calls, schemas, strict
- `.env`, מבנה תיקיות
- 12 עקרונות קנוניים

### 🟨 מוצר 2 — מוח החיפוש (Search Orchestration)
- **LAYER מעל מוצרים 0 ו-1**
- Intent detection (מהות השאלה, לא מילים)
- Parallel/Sequential patterns
- Think tool, Fallback chains
- 10 הכלים + descriptions קנוניים
- **חל רוחבית על כל המסלולים** — גם ידני
- במקרה של סתירה — **מוצר 2 גובר**

### 🟪 מוצר 3 — Anthropic API Pure (Terminal / Dev)
- מראה של מוצר 1 **בלי שכבת חיפוש**
- Claude Code / CLI / Terminal
- `/model`, `/effort`, `opusplan` native
- Subagents במקום routes

---

## חלות רוחבית של מוצר 2 על המסמך הזה

מוצר 1 מגדיר **configs טכניים**.
מוצר 2 מוסיף לכל מסלול **שכבת חיפוש** — `default_search_preset` + `intent_detection_enabled`.

**הטבלה הקנונית מהמוצר 2 מוטמעת בסעיף C.**
**החוק העליון של מוצר 2:** Trigger מפורש תמיד פועל, גם במסלולים עם intent detection כבוי.

אם תמצא סתירה בין המסמך הזה למוצר 2 — **מוצר 2 גובר**.

---

# A. 8 המוחות — Specs מלא

| # | שם פנימי | Model ID | Thinking | Effort | Max Tokens |
|---|---|---|---|---|---|
| 1 | haiku | `claude-haiku-4-5-20251001` | off | — | 8192 |
| 2 | haiku-thinking | `claude-haiku-4-5-20251001` | manual (budget) | — | 8192 |
| 3 | **sonnet (default)** | `claude-sonnet-4-6` | off | — | 8192 |
| 4 | sonnet-thinking | `claude-sonnet-4-6` | adaptive | low / med / high / max | 16384 |
| 5 | opus-46 | `claude-opus-4-6` | off | — | 8192 |
| 6 | opus-46-thinking | `claude-opus-4-6` | adaptive / manual | low / med / high / max | 32000 |
| 7 | opus-47 | `claude-opus-4-7` | off | — | 8192 |
| 8 | opus-47-thinking | `claude-opus-4-7` | adaptive (בלבד) | low / med / high / **xhigh** / max | 65536 |

## כללים לפי מודל

**Haiku 4.5:**
- Thinking: manual בלבד (`budget_tokens`)
- אין effort parameter
- Default budget (אם thinking פעיל): 1024

**Sonnet 4.6:**
- Thinking: adaptive או manual (manual deprecated)
- Effort: low / medium / high / max (default: high)
- Default thinking mode: adaptive

**Opus 4.6:**
- Thinking: adaptive או manual
- Effort: low / medium / high / max (default: high)
- Manual budget אפשרי — הסיבה היחידה להשאיר במערכת

**Opus 4.7:**
- Thinking: adaptive בלבד (manual הוסר)
- Effort: low / medium / high / **xhigh** / max (default: xhigh)
- xhigh בלעדי למודל זה

---

# B. שכבת החיפוש — 2 קבוצות

**המסגרת הטכנית בלבד. הלוגיקה המלאה של הכלים והשילובים ביניהם — במוצר 2.**

## Server Tools (Anthropic native)

| כלי | שם API | תפקיד |
|---|---|---|
| web_search | `web_search_20250305` | חיפוש גוגל |
| web_fetch | `web_fetch` | הבאת URL |
| code_execution | `code_execution_20250825` | Python sandbox |
| tool_search | `tool_search` | חיפוש כלים אחרים |

## Local Tools (Hostinger)

| כלי | Endpoint | תפקיד |
|---|---|---|
| meili_search | `http://hostinger-internal:7700` | מאגר פנימי |
| scrape | `/api/tools/scrape` | דף יחיד |
| crawl | `/api/tools/crawl` | crawling רחב |
| memory | `http://hostinger-internal:8283` | Letta (עתידי) |
| nevo_search | `/api/tools/nevo` | פסיקה (עתידי) |
| takdin_search | `/api/tools/takdin` | פסיקה (עתידי) |

## כללים טכניים

- `tool_choice: auto` — default
- `parallel_tool_calls: true`
- `strict: true` לכל schema
- `anthropic_beta: context-management-2025-06-27` (auto tool clearing)
- `clear_tool_uses_20250919` פעיל
- לתיאורי כלים מלאים ו-descriptions קנוניים → **מוצר 2, סעיף C**

---

# C. 11 המסלולים — Specs טכני (כולל search overlay ממוצר 2)

**מבנה קנוני של כל מסלול:**
- `config` טכני (מודל + thinking + effort + tools + limits)
- `default_search_preset` (ממוצר 2, layer עליון)
- `intent_detection_enabled` (ממוצר 2, layer עליון)
- **`trigger_override: ALWAYS ✅`** — קנוני, לא ניתן לכבות

---

## 0. ידני (default)

```json
{
 "model": "claude-sonnet-4-6",
 "thinking": { "enabled": false },
 "effort": "high",
 "tools": "auto",
 "tool_choice": "auto"
}
```
- **Search preset:** `standard` (web_search + meili_search)
- **Intent detection:** ✅ ON
- **Trigger override:** ✅ Always works

---

## 1. Plan/Execute (opusplan)

```
Phase 1 (Plan):
 model: claude-opus-4-7
 thinking: adaptive, effort: xhigh
 output: plan.md

Phase 2 (Approval — human):
 wait for user confirmation

Phase 3 (Execute):
 model: claude-sonnet-4-6
 thinking: off
 context: plan.md + original prompt

Phase 4 (Review — optional):
 model: claude-opus-4-7
 thinking: adaptive, effort: high
```
- **Search preset:** `full` (כל הכלים זמינים)
- **Intent detection:** ✅ ON
- **Trigger override:** ✅ Always works

---

## 2. Advisor

```
Primary:
 model: claude-sonnet-4-6
 thinking: off, effort: high

Escalation trigger:
 - tool_error
 - ambiguity detected
 - user requests help

Advisor call:
 model: claude-opus-4-7
 thinking: adaptive, effort: xhigh
 role: advice only, no file writes
```
- **Search preset:** `standard`
- **Intent detection:** ✅ ON
- **Trigger override:** ✅ Always works

---

## 3. Mechanical

```json
{
 "model": "claude-haiku-4-5-20251001",
 "thinking": { "enabled": false },
 "tools": ["web_search"],
 "max_tokens": 4096
}
```
- **Search preset:** `none` (ללא חיפוש אוטומטי)
- **Intent detection:** ❌ OFF
- **Trigger override:** ✅ Always works — גם כאן, אם משתמש אמר במפורש "תחפש ב-X", הכלי מופעל

---

## 4. Deep Thinking

```json
{
 "model": "claude-opus-4-7",
 "thinking": { "type": "adaptive" },
 "effort": "max",
 "tools": ["tool_search", "web_search"],
 "max_tokens": 32000
}
```
- **Search preset:** `research` (web + think tool)
- **Intent detection:** ✅ ON
- **Trigger override:** ✅ Always works

---

## 5. Fast Lane

```json
{
 "model": "claude-haiku-4-5-20251001",
 "thinking": { "enabled": false },
 "tools": ["web_search"],
 "max_tokens": 2048,
 "timeout_sec": 15
}
```
- **Search preset:** `web_search only`
- **Intent detection:** ❌ OFF (למהירות מקסימום)
- **Trigger override:** ✅ Always works

---

## 6. Review Mode

```
Phase 1 (Create):
 model: claude-sonnet-4-6
 thinking: off

Phase 2 (Review):
 model: claude-opus-4-7
 thinking: adaptive, effort: xhigh
 returns: approved | revisions_needed

Max iterations: 3
```
- **Search preset:** `none`
- **Intent detection:** ❌ OFF (סוקר, לא חוקר)
- **Trigger override:** ✅ Always works

---

## 7. Triple Canon

```
Phase 1 (Strategy):
 model: claude-opus-4-7
 thinking: adaptive, effort: xhigh

Phase 2 (Draft):
 model: claude-sonnet-4-6
 thinking: off

Phase 3 (QA):
 model: claude-haiku-4-5-20251001
 thinking: off
 task: verify format, citations, anti-AI words
```
- **Search preset:** `full per phase` (כל שלב עם preset משלו)
- **Intent detection:** ✅ ON
- **Trigger override:** ✅ Always works

---

## 8. Research Deep

```json
{
 "model": "claude-opus-4-7",
 "thinking": { "type": "adaptive" },
 "effort": "xhigh",
 "tools": ["ALL_AVAILABLE"],
 "parallel_tool_calls": true,
 "max_tokens": 32000
}
```
- **Search preset:** `full + parallel` (הכל, אגרסיבי)
- **Intent detection:** ✅ ON
- **Trigger override:** ✅ Always works

---

## 9. Legal Draft (עתידי — CIDAH)

```json
{
 "model": "claude-opus-4-7",
 "thinking": { "type": "adaptive" },
 "effort": "xhigh",
 "tools": ["nevo_search", "takdin_search", "meili_search"],
 "system_prompt": "CIDAH legal context + CLAUDE.md of matter",
 "max_tokens": 32000
}
```
- **Search preset:** `legal` (nevo + takdin + meili)
- **Intent detection:** ✅ ON
- **Trigger override:** ✅ Always works

---

## 10. Budget-Controlled (Opus 4.6)

```json
{
 "model": "claude-opus-4-6",
 "thinking": { 
 "type": "enabled", 
 "budget_tokens": 4000 
 },
 "tools": "auto",
 "purpose": "precise cost control"
}
```
- **Search preset:** `standard`
- **Intent detection:** ✅ ON
- **Trigger override:** ✅ Always works
- **הסיבה היחידה ש-Opus 4.6 נשאר במערכת:** manual budget מדויק

---

# D. סדר עדיפות החלטה

```
1. User explicit override (route / model / tools / trigger)
2. Active route's configuration
3. Intent detection (for tool activation) ← ממוצר 2
4. System defaults (Sonnet 4.6, thinking off, effort high)
```

---

# E. מבנה תיקיות — קוד

```
apps_bot/
├── src/
│ ├── bina.ts                       # Brain core
│ ├── models/
│ │ ├── registry.ts                # 8 models registered
│ │ ├── defaults.ts                # Sonnet 4.6 as default
│ │ ├── effort.ts                  # effort levels logic
│ │ └── thinking.ts                # adaptive vs manual
│ ├── routes/
│ │ ├── manual.ts                  # route 0 (default)
│ │ ├── planExecute.ts             # route 1
│ │ ├── advisor.ts                 # route 2
│ │ ├── mechanical.ts              # route 3
│ │ ├── deepThinking.ts            # route 4
│ │ ├── fastLane.ts                # route 5
│ │ ├── reviewMode.ts              # route 6
│ │ ├── tripleCanon.ts             # route 7
│ │ ├── researchDeep.ts            # route 8
│ │ ├── legalDraft.ts              # route 9 (future)
│ │ └── budgetControlled.ts        # route 10
│ ├── ai/
│ │ ├── search-brain/              # ← כל מוצר 2 כאן
│ │ │ ├── intentDetector.ts
│ │ │ ├── toolSelector.ts
│ │ │ ├── orchestrator.ts
│ │ │ ├── fallbackChain.ts
│ │ │ ├── thinkTool.ts
│ │ │ ├── budgetTracker.ts
│ │ │ ├── routeOverrides.ts
│ │ │ ├── systemPromptBuilder.ts
│ │ │ └── patterns/
│ │ │     ├── simple.ts
│ │ │     ├── parallel.ts
│ │ │     ├── sequential.ts
│ │ │     ├── thinkGuided.ts
│ │ │     └── splitMerge.ts
│ │ ├── tools/
│ │ │ ├── server/
│ │ │ │ ├── webSearch.ts
│ │ │ │ ├── webFetch.ts
│ │ │ │ ├── codeExecution.ts
│ │ │ │ └── toolSearch.ts
│ │ │ └── local/
│ │ │     ├── meiliSearch.ts
│ │ │     ├── scrape.ts
│ │ │     ├── crawl.ts
│ │ │     ├── memory.ts            # future
│ │ │     ├── nevo.ts              # future
│ │ │     └── takdin.ts            # future
│ │ └── presets.ts                 # search presets
│ └── audit/
│     └── logger.ts                # every decision logged
└── .env
```

---

# F. `.env` סופי (ממוזג עם מוצר 2)

```bash
# ============================================
# DEFAULT MODEL & BEHAVIOR
# ============================================
ANTHROPIC_DEFAULT_MODEL=claude-sonnet-4-6
ANTHROPIC_DEFAULT_THINKING=off
ANTHROPIC_DEFAULT_EFFORT=high
ANTHROPIC_DEFAULT_ROUTE=manual

# ============================================
# MODEL-SPECIFIC
# ============================================
HAIKU_45_MODEL=claude-haiku-4-5-20251001
HAIKU_45_DEFAULT_BUDGET=1024

SONNET_46_MODEL=claude-sonnet-4-6
SONNET_46_DEFAULT_EFFORT=high
SONNET_46_THINKING_MODE=adaptive

OPUS_46_MODEL=claude-opus-4-6
OPUS_46_DEFAULT_EFFORT=high
OPUS_46_THINKING_MODE=adaptive
OPUS_46_MANUAL_BUDGET_AVAILABLE=true

OPUS_47_MODEL=claude-opus-4-7
OPUS_47_DEFAULT_EFFORT=xhigh
OPUS_47_THINKING_MODE=adaptive
OPUS_47_MANUAL_BUDGET_AVAILABLE=false

# ============================================
# TOOL EXECUTION (כללי מוצר 1)
# ============================================
TOOL_CHOICE_DEFAULT=auto
PARALLEL_TOOLS=true
STRICT_SCHEMA=true
AUTO_TOOL_CLEARING=true

# ============================================
# SEARCH BRAIN (ממוצר 2)
# ============================================
INTENT_DETECTION_ENABLED=true
INTENT_DETECTION_STRENGTH=balanced     # conservative | balanced | aggressive
PARALLEL_PROMPT_ENABLED=true           # adds <use_parallel_tool_calls>
SEQUENTIAL_DEPENDENCY_CHECK=true
THINK_TOOL_ENABLED=true
THINK_TOOL_AUTO_ACTIVATE_AT=5
TRIGGER_OVERRIDE_ALWAYS=true           # חוק עליון — לא ניתן לכבות

# ============================================
# FALLBACK CHAINS (ממוצר 2)
# ============================================
FALLBACK_NEVO=takdin
FALLBACK_TAKDIN=nevo
FALLBACK_WEB_SEARCH=scrape
FALLBACK_MEILI=memory

# ============================================
# LIMITS
# ============================================
MAX_TOKENS_DEFAULT=8192
MAX_TOKENS_OPUS_XHIGH=32000
MAX_TOKENS_OPUS_MAX=65536
MAX_ITERATIONS=10
REQUEST_TIMEOUT_SEC=60
TOOL_TIMEOUT_SEC=30
TOOL_RETRY_ON_FAILURE=1

# ============================================
# BUDGET TRACKING (ממוצר 2)
# ============================================
SHOW_TOOL_COSTS=true
WARN_ON_SESSION_TOOL_BUDGET=1.00       # USD
WARN_ON_CRAWL=true                     # crawl is expensive

# ============================================
# DISPLAY
# ============================================
THINKING_DISPLAY=summarized
LANGUAGE=he

# ============================================
# API KEYS (WORKSPACES)
# ============================================
ANTHROPIC_KEY_DEFAULT=sk-ant-xxx
ANTHROPIC_KEY_OPUS_HEAVY=sk-ant-yyy
ANTHROPIC_KEY_FAST=sk-ant-zzz
ANTHROPIC_KEY_DEV=sk-ant-aaa

# ============================================
# LOCAL TOOLS
# ============================================
MEILI_HOST=http://hostinger-internal:7700
MEILI_KEY=xxx
LETTA_HOST=http://hostinger-internal:8283
LETTA_PASSWORD=xxx
NEVO_API_URL=https://api.nevo.co.il        # future
TAKDIN_API_URL=https://api.takdin.co.il    # future
```

---

# G. 12 העקרונות הקנוניים של מוצר 1

1. ✅ Sonnet 4.6 = default
2. ✅ Haiku לעבודה מכנית בלבד
3. ✅ Opus = specialist on-demand (4.6 או 4.7)
4. ✅ Plan/Execute = מסלול קנוני
5. ✅ Advisor = מסלול קנוני
6. ✅ Thinking OFF default, ON לפי מסלול
7. ✅ נשאר עם Sonnet גם אם Anthropic שינו default
8. ✅ מעבר בין מודלים שומר context
9. ✅ Tool Choice = auto + parallel
10. ✅ Server + Local tools (2 שכבות נפרדות)
11. ✅ Intent detection — חיפוש אוטומטי לפי מהות השאלה (→ מוצר 2)
12. ✅ Measure, adjust (audit + סקירה דו-שבועית)

---

# H. הבדלים בין Opus 4.6 ו-4.7

| קריטריון | Opus 4.6 | Opus 4.7 |
|---|---|---|
| Manual thinking (budget) | ✅ | ❌ |
| Adaptive thinking | ✅ | ✅ (בלבד) |
| Effort levels | low/med/high/max | low/med/high/**xhigh**/max |
| Context window | 200K | **1M** |
| SWE-bench | 80.8% | 87.6% |
| Vision resolution | רגיל | **3.3×** |
| מחיר | $5/$25 | $5/$25 (זהה) |

**4.6 נשאר במערכת רק בשביל:** שליטה מדויקת ב-budget (מסלול #10 — Budget-Controlled).

---

# I. מה לא כאן

### שייך למוצר 0 (UX):
- Welcome message
- 4 הלשוניות (מבנה UX)
- Status Bar
- Onboarding
- כללי כניסה/יציאה ממסלולים
- חוויית המשתמש הכללית

### שייך למוצר 2 (Search Brain):
- Intent detection logic מפורטת
- 10 tool descriptions קנוניים
- Parallel/Sequential patterns
- Think tool details
- Fallback chains
- 14 עקרונות של מוח החיפוש

### שייך למוצר 3 (API Pure):
- Claude Code CLI
- Subagents native
- CLAUDE.md hierarchy

---

**מוצר 1 סגור — מטריצה טכנית, ממוזגת עם overlays של מוצר 2.**
