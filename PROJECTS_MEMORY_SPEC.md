# Projects + זיכרון רב-שכבתי — מסמך איפיון

**גרסה:** 1.0
**תאריך:** 24 אפריל 2026
**מטרה:** איפיון של שכבת הפרויקטים והזיכרון — עצמאי, לא תלוי במוצרים אחרים
**חל על:** שני הפרויקטים (Bina + CIDAH) — עקרוני, אחיד
**מקור:** Anthropic Claude Code docs + Cowork Projects + קהילה חזקה

---

# A. התובנה המרכזית

**תיקיית פרויקט = שכבת זיכרון בפני עצמה, לא מיכל שלה.**

**ציטוט Anthropic native (Cowork Projects):**

> "Projects add the fourth layer. They all compound. When you run a task inside a Cowork project, Claude reads everything in this order... **Five layers of context working together in a single task.**"

**ציטוט Claude Code native:**

> "Each project gets its own memory directory based on the git repository root: `~/.claude/projects/<project>/memory/` ... **MEMORY.md** — Main index, loaded every session."

**ציטוט Anthropic docs:**

> "**Files loaded later take precedence** because the model pays more attention to instructions that appear later in the context window."

## המשמעות

תיקיית פרויקט = **חבילה שלמה** שכוללת:
1. הוראות (CLAUDE.md)
2. קבצי הקשר (files)
3. זיכרון אוטומטי (Claude writes)
4. זיכרון מוצמד (user writes)

כל אלה ביחד = "Project Memory" = **שכבה אחת עם ארבעה פנים** (לא ארבעה דברים נפרדים).

---

# B. 5 השכבות הקנוניות

**סדר טעינה: מהכללי ביותר → הספציפי ביותר. מאוחר יותר גובר.**

| # | שכבה | מיקום | מי כותב | נטען מתי | דוגמה |
|---|---|---|---|---|---|
| **L0** | Global Conventions | `/data/CONVENTIONS.md` | אדמין | כל סשן, כל פרויקט | "לעולם אל תחשוף פרטי לקוח אחר" |
| **L1** | User Preferences | `/data/users/{user}/CLAUDE.md` | משתמש | סשן של המשתמש | "אני מעדיף תשובות קצרות" |
| **L2** | Skills / Recipes | `/data/skills/*.md` (path-scoped) | אדמין/משתמש | כשרלוונטי | "איך לנסח חוזה שכירות" |
| **L3** | 🎯 **Project Bundle** | `/data/projects/{slug}/` | משתמש + Claude | סשנים בתוך הפרויקט | (פירוט למטה) |
| **L4** | Session Memory | `{slug}/sessions/current.md` | Claude (volatile) | רק הסשן הנוכחי | "דיברנו על זה לפני 3 הודעות" |

## L3 — Project Bundle (הפירוט)

שכבה L3 = **4 תת-רכיבים באותה תיקייה**, כולם compound:

```
/data/projects/{slug}/
├── CLAUDE.md                 ← L3.a: הוראות פרויקט (slow-change)
├── files/                    ← L3.b: קבצי הקשר
│   ├── uploads/
│   ├── drafts/
│   └── final/
├── memory/                   ← L3.c+d: זיכרון דו-פנים
│   ├── INDEX.md              ← index, נטען תחילה (first 200 lines)
│   ├── auto/                 ← L3.c: Claude writes (auto memory)
│   │   ├── patterns.md
│   │   ├── corrections.md
│   │   └── decisions.md
│   └── pinned/               ← L3.d: User writes (explicit)
│       ├── preferences.md
│       ├── facts.md
│       └── constraints.md
├── sessions/                 ← L4: volatile
│   └── current.md
└── .audit.log                ← per-project access log
```

**עיקרון קנוני:** L3 נטען **כחבילה אחת** בתחילת סשן. כל 4 הרכיבים יחד.

---

# C. סדר טעינה בתחילת סשן

**זה הליך ה-init שמתרחש בכל סשן חדש:**

```
Session N starts (user sends first message)
        ↓
1. RESOLVE PROJECT
   - Bina: from Telegram chat_id → project slug
   - CIDAH: from user's active context → project slug
        ↓
2. LOCK SESSION to project (readonly for session duration)
        ↓
3. CONFIGURE memory_20250818 tool:
   scope = /data/projects/{slug}/memory/auto/
        ↓
4. LOAD LAYERS (in order, later overrides earlier):
   
   L0: /data/CONVENTIONS.md                          (always loaded)
   L1: /data/users/{user}/CLAUDE.md                  (if exists)
   L2: /data/skills/*.md                              (path-scoped, only relevant)
   L3.a: /data/projects/{slug}/CLAUDE.md             (always for this project)
   L3.c+d INDEX: /data/projects/{slug}/memory/INDEX.md   (first 200 lines)
   L3.d PINNED: /data/projects/{slug}/memory/pinned/*.md  (ALL pinned, full)
   L4: /data/projects/{slug}/sessions/current.md     (if resuming)
        ↓
5. BUILD SYSTEM PROMPT — all layers assembled in order
        ↓
6. INCLUDE TOOLS:
   - memory_20250818 (Anthropic native, for auto)
   - memory_user_edits (ours, for pinned)
        ↓
7. MAIN AGENT runs
        ↓
8. ON SESSION END:
   - Claude auto-saves to memory/auto/ via memory_20250818
   - Session state saved to sessions/current.md
   - Pinned memories stay (unless user removed)
   - Audit log updated
```

**עיקרון Anthropic:** "Files loaded later take precedence." — לכן סדר הטעינה קריטי.

---

# D. 2 סוגי Memory בתוך L3

ההבחנה הכי חשובה, מבוססת Anthropic Team/Enterprise pattern:

## Auto Memory (L3.c)

- **מי כותב:** Claude (אוטומטית, via `memory_20250818`)
- **מה נשמר:** patterns, corrections, decisions, workflow habits
- **Cap:** ללא cap (מתנקה דרך Auto Dream)
- **איך נטען:** INDEX.md בלבד (first 200 lines), details on-demand
- **מתי Claude כותב:** כש-pattern חוזר, כשהמשתמש מתקן אותו, כשקיבלו החלטה

**דוגמאות:**
- "המשתמש מעדיף תשובות בעברית כל הזמן"
- "בפרויקט הזה, Terminal = macOS, לא Linux"
- "החלטנו להשתמש ב-Sonnet 4.6 ולא Opus"

## Pinned Memory (L3.d) — "תגיד לי לזכור"

- **מי כותב:** משתמש (explicit, via `memory_user_edits` או UI)
- **מה נשמר:** truths חשובות, הוראות קבועות, העדפות קריטיות
- **Cap:** **30 edits × 200 chars** (קנוני מ-Anthropic)
- **איך נטען:** כל ה-pinned נטענים, תמיד, בסשן הפרויקט
- **מטאפורה:** "Post-it note collection, not notebook" (Jonathan's memory guide)

### 4 דרכי הפעלה:

```
1. שיחתית (Telegram/Web):
   משתמש: "תזכור שלפני כל טיוטה תבדוק את תיק 2026-001"
   Bina: [calls memory_user_edits] ✅ נרשם

2. פקודה בטלגרם:
   /zkor [טקסט]       ← שמור
   /shkach [טקסט]     ← מחק
   /zkorot             ← הצג את כל ה-pinned

3. כפתור 📌 ב-UI:
   לחיצה על הודעה → dialog "מה לזכור?" → נשמר

4. מקש # (Claude Code / terminal):
   # משתמש מעדיף Bun על npm
```

---

# E. הפרדה קשיחה — 4 רמות Enforcement

**ציטוט Anthropic:**

> "Memory helps continuity, but **memory does not enforce scope**. If your only scope control is a note the model read earlier, **you do not have scope control**."

**המסקנה:** scope ב-prompt לא מספיק. חייבים enforcement פיזי.

## 4 הרמות הקנוניות

| רמה | מנגנון | מה מונע | מימוש |
|---|---|---|---|
| **1. Filesystem** | `chmod 700` + UID-per-project | משתמש X לא רואה קבצים של Y | Unix permissions |
| **2. Path validation** | memory tool scoped ל-path בלבד | path traversal (`../`) נדחה | code-level validator |
| **3. Session binding** | project נקבע בפתיחת סשן, readonly | שינוי project באמצע סשן | session state lock |
| **4. Audit log** | כל גישה נרשמת per-project | forensics אחרי אירוע | `.audit.log` append-only |

## מימוש קוד

```typescript
// apps/src/projects/isolation.ts

export function initProjectSession(projectSlug: string, user: string) {
  // Layer 1: Filesystem
  const projectPath = `/data/projects/${projectSlug}`;
  assertPermissions(projectPath, 0o700);
  
  // Layer 2: Path scoping
  memoryTool.setRoot(`${projectPath}/memory/`);
  memoryTool.rejectPattern(/\.\./g);
  
  // Layer 3: Session lock
  const session = {
    projectId: projectSlug,
    userId: user,
    startedAt: Date.now(),
  };
  Object.freeze(session);  // readonly
  
  // Layer 4: Audit
  auditLog.append({
    project: projectSlug,
    user,
    action: "session_start",
    timestamp: Date.now(),
  });
  
  return session;
}
```

---

# F. Project Resolver — איזה project נטען

**בשני הפרויקטים, הלוגיקה זהה עקרונית:**

## Bina (Telegram)

```typescript
function resolveProject(telegramCtx): string {
  if (telegramCtx.chat.type === "private") {
    return `bina-user-${telegramCtx.from.id}`;
  }
  if (telegramCtx.chat.type === "group") {
    return `bina-group-${telegramCtx.chat.id}`;
  }
  if (telegramCtx.chat.type === "channel") {
    return `bina-channel-${telegramCtx.chat.id}`;
  }
}
```

## CIDAH (Legal firm)

```typescript
function resolveProject(request): string {
  // Room → Client mapping
  const room = request.roomId;
  const client = db.rooms_to_clients.get(room);
  if (client) return `cidah-${client.slug}`;
  
  // Attorney private workspace
  const attorney = request.userId;
  return `cidah-attorney-${attorney}`;
}
```

**הקנוני לשניהם:**
- Slug format: `{system}-{entity-type}-{entity-id}`
- Resolver פועל פעם אחת בפתיחת הסשן
- Session locked ל-slug עד סופה

---

# G. UX — מה המשתמש רואה

## שדות תצוגה

המשתמש תמיד רואה:
- **שם הפרויקט הנוכחי** (`📂 cohen-levy`)
- **מספר pinned memories** (`📌 3 pinned`)

## פאנל Project

```
┌────────────────────────────────────────────────┐
│ 📂 פרויקט נוכחי: cohen-levy                      │
│ [הגדרות] [החלף פרויקט] [📥 ארכיון]               │
├────────────────────────────────────────────────┤
│ 📌 Pinned memories (3/30)                       │
│  1. מעדיף טיוטות ב-Word                          │
│     [עריכה] [מחק]                                │
│  2. לפני כל טיוטה — בדוק תיק 2026-001            │
│     [עריכה] [מחק]                                │
│  3. משלב משפטי גבוה                              │
│     [עריכה] [מחק]                                │
│ [+ הוסף תזכורת חדשה]                             │
├────────────────────────────────────────────────┤
│ 🧠 Auto memories (gist):                         │
│  • 15 patterns learned                          │
│  • 8 corrections noted                          │
│  • 4 decisions recorded                         │
│ [📖 ראה הכל]  [🧹 Auto Dream — ניקוי]            │
├────────────────────────────────────────────────┤
│ 📁 Context files                                 │
│  • CLAUDE.md                                    │
│  • 12 files in /files/uploads                   │
│  • 5 drafts                                     │
│ [📂 פתח תיקייה]                                  │
├────────────────────────────────────────────────┤
│ 🔒 Privacy                                       │
│  [🕵️ Incognito mode]  ← סשן שלא נשמר              │
│  [🗑️ נקה auto memory]                            │
│  [📤 Export project]                             │
└────────────────────────────────────────────────┘
```

---

# H. פקודות Telegram קנוניות

| פקודה | פעולה | דוגמה |
|---|---|---|
| `/zkor {text}` | הוסף pinned memory | `/zkor אני מעדיף טיוטות ב-Word` |
| `/shkach {id\|text}` | מחק pinned | `/shkach 2` |
| `/zkorot` | הצג את כל ה-pinned | — |
| `/project` | הצג את ה-project הנוכחי | — |
| `/project switch` | החלף project (admin only) | — |
| `/incognito` | הפעל/כבה incognito mode | — |
| `/export` | ייצא את כל הפרויקט | — |

---

# I. `.env` הגדרות

```bash
# ============================================
# PROJECTS ROOT
# ============================================
PROJECTS_ROOT=/data/projects
USERS_ROOT=/data/users
SKILLS_ROOT=/data/skills
CONVENTIONS_PATH=/data/CONVENTIONS.md

# ============================================
# ISOLATION — 4 רמות
# ============================================
PROJECT_DIR_PERMISSIONS=700
ENFORCE_PATH_TRAVERSAL_PROTECTION=true
SESSION_LOCK_PROJECT=true
AUDIT_PROJECT_ACCESS=true
AUDIT_LOG_FORMAT=jsonl
AUDIT_LOG_APPEND_ONLY=true

# ============================================
# MEMORY LAYERS
# ============================================
LOAD_L0_ALWAYS=true                     # CONVENTIONS.md
LOAD_L1_USER=true                       # user CLAUDE.md
LOAD_L2_SKILLS=path_scoped              # only relevant
LOAD_L3_PROJECT_BUNDLE=true             # entire project
LOAD_L3_INDEX_LINES=200                 # MEMORY.md first 200
LOAD_L3_PINNED_ALL=true                 # ALL pinned always
LOAD_L4_SESSION_ON_RESUME=true

# ============================================
# AUTO MEMORY (L3.c — Anthropic native)
# ============================================
AUTO_MEMORY_ENABLED=true
MEMORY_TOOL_TYPE=memory_20250818
MEMORY_TOOL_BETA_HEADER=context-management-2025-06-27
MEMORY_MAX_SIZE_MB_PER_PROJECT=100
MEMORY_FILE_MAX_LINES=200               # אזהרה מעל זה

# ============================================
# PINNED MEMORY (L3.d — our tool, Anthropic pattern)
# ============================================
PINNED_MEMORY_ENABLED=true
PINNED_MEMORY_MAX_COUNT=30
PINNED_MEMORY_MAX_CHARS=200
PINNED_ALWAYS_LOAD=true
PINNED_UI_BUTTON_ENABLED=true
PINNED_COMMAND_NAMES=zkor,shkach,zkorot

# ============================================
# INCOGNITO
# ============================================
INCOGNITO_MODE_ENABLED=true
INCOGNITO_AUTO_CLEAR=true
INCOGNITO_NO_AUDIT=false                # עדיין audit, גם ב-incognito
```

---

# J. מבנה קוד

```
apps/src/
├── projects/
│   ├── resolver.ts                  ← context → project slug
│   ├── initializer.ts               ← טעינת 5 שכבות
│   ├── isolation.ts                 ← 4 רמות enforcement
│   ├── lock.ts                      ← session-project binding
│   ├── lifecycle.ts                 ← create / archive / delete
│   ├── incognito.ts
│   └── audit.ts
│
├── memory/
│   ├── layers/
│   │   ├── L0_conventions.ts        ← global
│   │   ├── L1_user.ts               ← user preferences
│   │   ├── L2_skills.ts             ← path-scoped
│   │   ├── L3_project.ts            ← project bundle
│   │   └── L4_session.ts            ← volatile
│   ├── auto.ts                      ← memory_20250818 wrapper
│   ├── pinned.ts                    ← user-directed API
│   ├── index.ts                     ← INDEX.md management
│   ├── scopeGuard.ts                ← path traversal protection
│   ├── autoDream.ts                 ← periodic cleanup
│   └── ui.ts                        ← buttons / commands
│
└── commands/
    ├── zkor.ts
    ├── shkach.ts
    ├── zkorot.ts
    ├── project.ts
    ├── incognito.ts
    └── hashtag.ts                   ← # quick-add
```

---

# K. API — Pinned Memory

```typescript
// apps/src/memory/pinned.ts

export interface PinnedMemory {
  id: string;
  project: string;
  content: string;       // max 200 chars
  created_at: Date;
  created_by: string;    // user id
}

export const pinnedAPI = {
  add: (project, content, user) => void,
  remove: (project, id) => void,
  list: (project) => PinnedMemory[],
  edit: (project, id, newContent) => void,
};
```

## Tool definition (ל-Claude):

```json
{
  "name": "memory_user_edits",
  "description": "Store explicit user memory instructions. Use ONLY when the user says 'remember that...', 'don't forget that...', 'save this...', or similar. Do NOT use for your own observations — use `memory` (memory_20250818) tool for that. Max 200 chars per memory.",
  "strict": true,
  "input_schema": {
    "type": "object",
    "properties": {
      "action": { "enum": ["add", "remove", "list"] },
      "content": { "type": "string", "maxLength": 200 }
    }
  }
}
```

---

# L. 10 עקרונות קנוניים

1. ✅ **Project = Full Memory Layer** (not just isolation container)
2. ✅ **5 layers compound** (L0 → L4, later overrides earlier)
3. ✅ **L3 = 4 sub-components** (CLAUDE.md + files + auto + pinned)
4. ✅ **Auto + Pinned = 2 faces of same memory** (not separate systems)
5. ✅ **Pinned cap: 30 × 200 chars** (Anthropic canonical)
6. ✅ **4 activation paths for pinned** (chat / command / button / #)
7. ✅ **4-level enforcement** (filesystem + path + session + audit)
8. ✅ **Memory tool `memory_20250818` native** (Anthropic Sep 2025)
9. ✅ **Incognito always available** (per-session opt-out)
10. ✅ **Same principles — Bina + CIDAH** (אחד קנוני)

---

# M. ההבדל בין Bina ל-CIDAH

**העקרונות זהים. המימוש זהה. רק ה-slug נוזלי.**

| | Bina | CIDAH |
|---|---|---|
| **Project =** | Telegram user/group | Client (לא matter) |
| **Slug format** | `bina-user-{id}` / `bina-group-{id}` | `cidah-{client-slug}` |
| **Users table** | Telegram users | Attorneys + staff |
| **Skills** | כלליים | משפטיים |
| **Memory layers** | **זהים — L0-L4** | **זהים — L0-L4** |
| **Enforcement** | **זהה — 4 רמות** | **זהה — 4 רמות** |
| **Pinned UI** | `/zkor` + 📌 button | `/zkor` + 📌 button |
| **Auto memory** | `memory_20250818` | `memory_20250818` |

**מסקנה:** מימוש אחד, עם אבסטרקציה של `system` (bina/cidah).

---

# N. מה זה פותר

| בעיה | פתרון |
|---|---|
| נזילת מידע בין לקוחות | 4 רמות enforcement |
| Context cold-start בכל סשן | L3 Project Bundle נטען אוטומטית |
| "זה חשוב — תזכור!" | Pinned memory (L3.d) |
| Claude לא זוכר patterns | Auto memory (L3.c) + memory_20250818 |
| מחיקת קבצים בטעות | Audit log + permissions |
| מעבר בין לקוחות באמצע סשן | Session lock (readonly) |
| "אני רוצה לנסות משהו בלי שייזכר" | Incognito mode |

---

# O. סיכום — 6 עקרונות ליבה

1. **Project = Memory Layer** (not just folder)
2. **5 layers compound** — Anthropic native order
3. **Pinned + Auto = 2 faces of L3** (יחד, לא נפרד)
4. **30 × 200 chars** for pinned (Anthropic cap)
5. **4-level enforcement** (not prompt-level only)
6. **Same principles — Bina + CIDAH** (אחד קנוני)

---

**מסמך עצמאי. מבוסס Anthropic native + קהילה חזקה. לא תלוי במוצרים אחרים.**
