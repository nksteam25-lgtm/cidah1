# CIDAH — מוצר 3: Anthropic API Pure (Terminal / Developer)

**גרסה:** 3.0 (קנוני)
**תאריך:** 24 אפריל 2026
**מטרה:** מראה של מוצר 1 לסביבת Claude Code / Terminal / API ישיר — **בלי שכבת חיפוש**
**מקור:** Anthropic Claude Code docs + blueprints

---

## אינדקס קנוני — 4 המוצרים

**המוצרים האלה הם שכבות הירככיות. כל מוצר מניח את הקודם לו.**

### 🟦 מוצר 0 — Ground Zero + UX הבחירה
- נקודת ההתחלה (Sonnet 4.6, ידני)
- Welcome message, Status Bar
- 4 הלשוניות (מוח / חיפוש / מסלולים / מתקדם)
- כללי כניסה/יציאה ממסלולים
- Onboarding, שקיפות

### 🟩 מוצר 1 — המטריצה הטכנית
- 8 המוחות (specs + API params + effort levels)
- 11 המסלולים (configs טכניים מלאים)
- Tools — API calls, schemas, strict
- `.env`, מבנה תיקיות
- 12 עקרונות קנוניים

### 🟨 מוצר 2 — מוח החיפוש (Search Orchestration)
- **LAYER מעל מוצרים 0 ו-1**
- Intent detection, parallel/sequential
- Think tool, Fallback chains
- 10 הכלים + descriptions קנוניים
- **חל רוחבית על כל המסלולים** — גם ידני
- במקרה של סתירה — **מוצר 2 גובר**

### 🟪 מוצר 3 — Anthropic API Pure (המסמך הזה)
- מראה של מוצר 1 **בלי שכבת חיפוש**
- Claude Code / CLI / Terminal
- `/model`, `/effort`, `opusplan` native
- Subagents במקום routes

---

# A. הקונספט

**מוצר 1** = בינה עם מוח + חיפוש + UI (טלגרם)
**מוצר 3** = Claude Code עם מוח + Terminal (**בלי חיפוש**)

**ההבדל היחיד:** אין שכבת search brain ב-CLI. המפתח מתקשר ישירות עם המוח.

**למה?**
- Claude Code רץ בטרמינל של המפתח, לא בטלגרם
- יש לו גישה לקוד המקומי שלו (בתוך הפרויקט) דרך filesystem
- חיפוש ברשת הוא אופציונלי ב-CLI, לא ברירת מחדל
- המפתח רוצה ייחוד של מודל + effort, בלי orchestration מורכב

---

# B. 8 המוחות — זהה למוצר 1

| # | מוח | Model ID | Thinking | Effort |
|---|---|---|---|---|
| 1 | haiku | `claude-haiku-4-5-20251001` | manual/off | — |
| 2 | **sonnet (default)** | `claude-sonnet-4-6` | off / adaptive | low/med/high/max |
| 3 | sonnet-thinking | `claude-sonnet-4-6` | adaptive | high (default) |
| 4 | opus-46 | `claude-opus-4-6` | off / adaptive / manual | low/med/high/max |
| 5 | opus-46-thinking | `claude-opus-4-6` | adaptive | high |
| 6 | opus-47 | `claude-opus-4-7` | off / adaptive | low/med/high/xhigh/max |
| 7 | opus-47-thinking | `claude-opus-4-7` | adaptive | xhigh (default) |
| 8 | opus-47-max | `claude-opus-4-7` | adaptive | max |

---

# C. אופני הגדרה (API Pure)

## 1. Environment Variable (המומלץ)

```bash
export ANTHROPIC_API_KEY="sk-ant-..."
export ANTHROPIC_MODEL="claude-sonnet-4-6"
export CLAUDE_CODE_EFFORT_LEVEL="high"
```

## 2. CLI Flag (לסשן בודד)

```bash
claude --model sonnet --effort high
claude --model opus --effort xhigh
claude --model opusplan          # hybrid mode
```

## 3. Settings File

```json
// ~/.claude/settings.json
{
 "env": {
 "ANTHROPIC_API_KEY": "sk-ant-...",
 "ANTHROPIC_MODEL": "claude-sonnet-4-6",
 "CLAUDE_CODE_EFFORT_LEVEL": "high"
 }
}
```

## 4. פקודות Runtime

```
/model sonnet            # החלפת מוח
/model opus
/model haiku
/model opusplan          # hybrid
/effort                  # פותח slider
/effort xhigh            # קביעה מפורשת
/effort auto             # חזרה ל-default
```

## 5. סדר עדיפות ההגדרה

```
1. CLAUDE_CODE_EFFORT_LEVEL env var (עליון)
2. Settings file
3. --effort flag
4. /effort runtime command
5. Model default
```

---

# D. 10 מסלולים — מראה של מוצר 1

**שים לב:** הרשימה כמעט זהה ל-11 המסלולים במוצר 1. חסר `Research Deep` (שדורש חיפוש).

## 1. ידני (default)

```bash
claude --model sonnet
```

Sonnet 4.6 סולו. המפתח שולט בכל דבר.

## 2. Plan/Execute (opusplan) — Native

```bash
claude --model opusplan
```

Anthropic native alias. Opus 4.7 xhigh מתכנן → Sonnet 4.6 מבצע.

## 3. Advisor

```bash
claude --model sonnet
# כשנתקעים:
/model opus
# ואז:
/model sonnet
```

Manual switch לפי צורך. ב-Claude Code יש plugin שעושה את זה אוטומטית.

## 4. Mechanical

```bash
claude --model haiku --effort low
```

Haiku למשימות מכניות.

## 5. Deep Thinking

```bash
claude --model opus --effort max
```

Opus 4.7 עם thinking max לחשיבה עמוקה.

## 6. Fast Lane

```bash
claude --model haiku
# או
export CLAUDE_CODE_EFFORT_LEVEL=low
```

מהירות מעל הכל.

## 7. Review Mode — Writer/Reviewer pattern

```bash
# Terminal 1 (Writer)
claude --model sonnet

# Terminal 2 (Reviewer, fresh context)
claude --model opus --effort xhigh
```

Anthropic's Writer/Reviewer pattern — שני sessions נפרדים.

## 8. Triple Canon

Session chain:

```bash
# Phase 1 — Strategy
claude --model opus --effort xhigh

# Phase 2 — Draft
claude --model sonnet

# Phase 3 — QA
claude --model haiku
```

## 9. Legal Draft (עתידי)

```bash
claude --model opus --effort xhigh
# + CLAUDE.md עם הקשר משפטי
```

## 10. Budget-Controlled

```bash
claude --model opus-4-6 --effort medium
# שימוש ב-Opus 4.6 (תומך manual budget)
```

**חסר כאן:** `Research Deep` — כי דורש חיפוש וזה שייך למוצר 1.

---

# E. שלוש שכבות הגדרה

## Enterprise / Organization level

```markdown
// /etc/claude-code/CLAUDE.md (managed)
ANTHROPIC_MODEL: claude-sonnet-4-6
CLAUDE_CODE_EFFORT_LEVEL: high
```

## Project level

```markdown
// ./CLAUDE.md in repo root
## Model Preferences
- Default: Sonnet 4.6 high
- For architectural decisions: Opus 4.7 xhigh
- For rename/boilerplate: Haiku 4.5
```

## User level

```json
// ~/.claude/settings.json
{
 "env": {
 "ANTHROPIC_MODEL": "claude-sonnet-4-6",
 "CLAUDE_CODE_EFFORT_LEVEL": "high"
 }
}
```

**סדר עדיפות:** User > Project > Enterprise (overrides יורדים מטה)

---

# F. Subagents (בלי חיפוש)

Claude Code תומך ב-subagents — זה מקבילה ל-"מסלולים" של מוצר 1 אבל בלי search orchestration.

## Structure

```
~/.claude/agents/
├── reviewer.md       # Reviewer subagent
├── planner.md        # Planner subagent
├── tester.md         # Test writer
└── refactorer.md     # Refactoring specialist
```

## Agent frontmatter

```yaml
---
name: reviewer
model: opus-4-7
effort: xhigh
description: "Fresh-context code reviewer. No prior context bias."
---

# Reviewer Agent

You are a code reviewer. Read the diff cold. Check for:
- Missing imports
- Hallucinated APIs
- Spec compliance
- Edge cases
```

## Usage

```bash
claude --agent reviewer "Review the changes in src/auth.ts"
```

---

# G. `.env` סופי למוצר 3

```bash
# ============================================
# API ACCESS
# ============================================
ANTHROPIC_API_KEY=sk-ant-xxx
ANTHROPIC_BASE_URL=                          # אם משתמש בגייטוויי
ANTHROPIC_AUTH_TOKEN=                        # אם משתמש ב-auth token

# ============================================
# DEFAULT MODEL
# ============================================
ANTHROPIC_MODEL=claude-sonnet-4-6
CLAUDE_CODE_EFFORT_LEVEL=high

# ============================================
# OPUS-SPECIFIC
# ============================================
ANTHROPIC_DEFAULT_OPUS_MODEL=claude-opus-4-7
ANTHROPIC_DEFAULT_OPUS_MODEL_SUPPORTED_CAPABILITIES=effort,xhigh_effort,max_effort,thinking,adaptive_thinking,interleaved_thinking

# ============================================
# BEHAVIOR
# ============================================
CLAUDE_CODE_DISABLE_ADAPTIVE_THINKING=0       # 0=adaptive, 1=manual budget
MAX_THINKING_TOKENS=10000                     # רק אם adaptive off
API_TIMEOUT_MS=3000000

# ============================================
# PERMISSIONS
# ============================================
CLAUDE_ALLOWED_TOOLS=                         # רשימה לבנה אופציונלית
CLAUDE_DISALLOWED_TOOLS=                      # רשימה שחורה אופציונלית
```

---

# H. מבנה תיקיות — מוצר 3

```
~/.claude/
├── settings.json           # User-level config
├── CLAUDE.md               # User-level context
├── agents/                 # User-level subagents
│ ├── reviewer.md
│ ├── planner.md
│ └── refactorer.md
└── hooks/                  # Pre/post execution hooks
 ├── pre-commit.sh
 └── post-write.sh

./your-project/
├── .claude/
│ ├── settings.json         # Project-level config (override user)
│ └── agents/               # Project-level subagents
└── CLAUDE.md               # Project context (prepended to every session)
```

---

# I. השוואה מוצר 1 ↔ מוצר 3

| קריטריון | מוצר 1 (Bina) | מוצר 3 (Claude Code) |
|---|---|---|
| **פלטפורמה** | טלגרם | Terminal / IDE |
| **שכבת חיפוש** | ✅ כן (10 כלים) | ❌ לא |
| **Orchestration** | ✅ מסלולים עם intent detection | Manual via `/model`, subagents |
| **UI** | 4 לשוניות + Status bar | CLI commands |
| **Default model** | Sonnet 4.6 | Sonnet 4.6 |
| **Context persistence** | Session-based | CLAUDE.md + resume |
| **Multi-user** | ✅ (כל משתמש בטלגרם) | ❌ (single developer) |
| **File access** | ❌ לא | ✅ כן (filesystem) |
| **Bash execution** | ❌ לא | ✅ כן |
| **Hooks** | ❌ לא | ✅ כן |
| **Memory** | Letta (עתידי) | Built-in memory tool |
| **מטרת שימוש** | עו"ד / משתמשים רגילים | מפתחים |

---

# J. 8 העקרונות הקנוניים של מוצר 3

1. ✅ **Sonnet 4.6 = default** (נשארים עם Sonnet גם כש-Anthropic עברו ל-Opus 4.7 ב-Enterprise)
2. ✅ **Haiku למכני** (rename, format, boilerplate)
3. ✅ **Opus on-demand** (architectural decisions, hard debug)
4. ✅ **opusplan = מסלול קנוני native**
5. ✅ **Context נשמר במעבר בין מודלים** (`/model` לא מוחק)
6. ✅ **אין שכבת חיפוש** — המפתח שולט ישירות
7. ✅ **Subagents = מקבילה למסלולים**
8. ✅ **3 רמות הגדרה** (User / Project / Enterprise)

---

# K. מה שונה מוצר 3 ממוצר 1

## חסר במוצר 3:
- שכבת search brain (10 כלי חיפוש — הכל של מוצר 2)
- Intent detection
- Tool orchestration (parallel/sequential patterns)
- UI עם 4 לשוניות (מוצר 0)
- Status bar ויזואלי
- Welcome message

## יש במוצר 3 שאין במוצר 1:
- גישה ל-filesystem
- Bash execution
- Hooks (pre/post)
- Native `/model` command
- Subagents native (ולא דרך routes)
- CLAUDE.md hierarchy (Enterprise / Project / User)

---

# L. ההגדרה הקנונית של מוצר 3

**הסטארטר פאק לכל מפתח ב-CIDAH:**

```json
// ~/.claude/settings.json
{
 "env": {
 "ANTHROPIC_API_KEY": "${SECRET}",
 "ANTHROPIC_MODEL": "claude-sonnet-4-6",
 "CLAUDE_CODE_EFFORT_LEVEL": "high"
 }
}
```

```markdown
// ~/.claude/CLAUDE.md

## Defaults
- Model: Sonnet 4.6 high (unless task requires otherwise)
- For architecture/planning: `/model opus` then `/effort xhigh`
- For rename/boilerplate: `/model haiku`
- For complex multi-file changes: `/model opusplan`

## Style
- Concise responses
- Code blocks with language hints
- No unnecessary preamble

## Constraints
- Always write tests alongside code
- Never force push to main
- Ask before destructive operations
```

---

# M. סיכום מוצר 3

- **מוצר 3 = מוצר 1 ללא חיפוש**, מיועד לטרמינל / CLI
- **אותם 8 מוחות**, אותם עקרונות של effort ו-thinking
- **10 מסלולים** במקום 11 (חסר Research Deep)
- **Native Anthropic tools:** `/model`, `/effort`, `opusplan`, subagents
- **3 רמות הגדרה** (User / Project / Enterprise)
- **Default = Sonnet 4.6 high** גם ב-API הישיר (override את Anthropic's Opus 4.7 default)

---

**מוצר 3 סגור.**
