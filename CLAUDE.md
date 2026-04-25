# Claude Master — CLAUDE.md
# קובץ זה נטען אוטומטית בכל סשן. קרא לפני כל פעולה.
# עודכן: 2026-04-24 (סוף סשן — memory layer V2 מלא + 10 API keys)

---

## סטטוס 2026-04-24 (סוף סשן) — נקודת התחלה לסשן הבא

### הושלם היום
- **10 API keys** נוצרו ונשמרו ב-`setup/workspaces_created.json`
- **core/claude_master.py** — 8 מוחות, 11 מסלולים, ניתוב per-workspace, משולב memory layer
- **core/memory/** — 15 קבצים מלאים:
  - `scope_guard.py`, `tool.py`, `pinned.py`, `auto.py`, `index.py`
  - `initializer.py`, `project_resolver.py`, `session_lock.py`
  - `audit.py`, `context_loader.py`, `sanitizer.py`
  - `auto_dream.py`, `budget.py`, `acl.py`, `__init__.py`
  - `tests/test_integration.py`, `tests/__init__.py`
- **ARCHITECTURE_MEMORY_V2.md** — 984 שורות, ספציפיקציה מלאה
- **memory/CONVENTIONS.md** — L0 global
- **memory/store_master/CLAUDE.md**, **store_legal/CLAUDE.md**, **store_user_template/CLAUDE.md**
- **files_ref/** — מוצרים 0-3 (פרקים)
- **PROJECTS_MEMORY_SPEC.md**

### הצעד הבא המיידי (הרץ קודם כשחוזרים)
```bash
cd ~/Documents/neeman_Native/neeman_Native/claude-master
source venv/bin/activate
python -m pytest core/memory/tests/ -v
```

### אחרי שה-tests עוברים — לבנות
- `core/memory/staging.py` — two-phase write helper נפרד
- תיקון dual audit schema (bug מ-report)
- תיקון Hebrew slug bug ב-`project_resolver.py`

### באגים ידועים (מה-test report)
1. **Dual audit schema** — `initializer` + `tool` כותבים schema שונה ל-`.audit.log`
2. **Hebrew slug** ב-`project_resolver` — test שגוי
3. **pinned.py** — unused import `ScopeViolation`

### הצעד אחרי ה-tests
- Git init + `.gitignore`
- End-to-end test עם API אמיתי

---

## כללים קנוניים — חובה לפעול לפיהם תמיד

1. **אוטונומיה מלאה** — לא לשאול "האם אני יכול לבצע X". לבצע ישירות.
2. **אסור לבקש מהמשתמש דבר שאפשר לעשות לבד.**
3. **כשנדרש המשתמש** — להצהיר בשורה הראשונה: "נדרש ממך לבצע" או "נדרש ממך אישור".
4. **אובססיה לפתרונות** — כשיש מגבלה טכנית, לחפור ולמצוא עקיפה. לא לעצור ב"לא ניתן".
5. **עבודה מסודרת בתיקיית פרויקט בלבד** — לא לפזר קבצים.
6. **Anthropic-native** — להיצמד לדפוסי Anthropic והקהילה. לא להתחכם.

---

## הפרויקט

**מטרה:** מערכת ניהול מרכזית לצי Claude Code — משרד עו"ד Neeman.
Guy Neeman (super_admin) שולט ב-10 חברי צוות, כל אחד עם Anthropic workspace נפרד.

**תיקייה:** `~/Documents/neeman_Native/neeman_Native/claude-master/`
**Python:** 3.12 | **venv:** `venv/` | **הרצה:** `source venv/bin/activate`

---

## ארכיטקטורת זיכרון — 5 שכבות (Memory Layer V2)

```
L0 CONVENTIONS.md    ← memory/CONVENTIONS.md  — global, תמיד נטען, admin-only
L1 User CLAUDE.md    ← memory/store_user_{id}/CLAUDE.md
L2 Skills            ← opt-in, path-scoped
L3 Project Bundle    ← projects/{slug}/CLAUDE.md + INDEX + auto + pinned
L4 Session           ← רק ב-resume מפורש
```

**מנגנון טעינה:** `core/memory/initializer.MemoryInitializer.init_session()` →
`SessionContext` עם system_prompt מוכן, memory_tool, beta_headers, session_lock, audit.
`core/claude_master.ClaudeMaster.call()` קורא את זה לפני כל API call.

בידוד stores (ברמת פרויקט / לקוח — hashed slug):
- **store_master** → Admin (Guy Neeman) — רואה הכל כ-read-only cross-store
- **store_legal** → Legal agents — פסיקה, חוק, טיוטות (nevo + takdin)
- **store_tech** → Dev/ops — קוד, architecture
- **store_email** → Gmail routing (labels + filters)
- **store_user_{id}** → user pref + tasks של חבר צוות
- **store_user_template** → תבנית לשכפול ב-onboarding

---

## סטטוס נוכחי (2026-04-24)

### ✅ הושלם
- Google Cloud Project: claude-master-494312
- Gmail API + Drive API: מופעלים
- OAuth 2.0: credentials/gmail_credentials.json + gmail_token.pickle
- Gmail: 10 labels + 10 filters פעילים (Plus Addressing)
- 10 Anthropic Workspaces: נוצרו via Admin API
- Admin API Key: setup/.env
- **Memory layer V2 (core/memory/)** ✅ נבנה — initializer, context_loader, tool, pinned, auto, session_lock, project_resolver, scope_guard, index, audit
- **core/claude_master.py שולב עם memory layer** ✅ — ClaudeMaster.call() מקבל project_slug, משתמש ב-MemoryInitializer לפני כל API call
- CLAUDE.md לכל store: master, legal, user_template, tech, email ✅

### 🔄 בתהליך — הצעד הבא המיידי
**יצירת API Keys (1 לכל workspace) — הרץ:**
```bash
cd ~/Documents/neeman_Native/neeman_Native/claude-master
source venv/bin/activate
python setup/create_api_keys.py
```
הסקריפט: מחלץ cookies מ-Chrome → נכנס ל-platform.claude.com/settings/keys → יוצר 10 keys → שומר ב-setup/workspaces_created.json

### ⏳ ממתין
- Git init + .gitignore
- Google Workspace (neemanlaw-cidah.pro) — pending access
- End-to-end test של call() מול workspace אמיתי (עם memory layer live)
- onboarding של 10 ה-users דרך store_user_template

---

## צוות + Workspace IDs

| שם | תפקיד | Plus Address | Workspace Name | Workspace ID |
|----|--------|-------------|----------------|-------------|
| Guy Neeman | super_admin | guyn@cidah.ai | claude-master-admin | wrkspc_01TwEh7KTEA753YKo4XB6J6s |
| Lilach Keynan | manager_ops | guyn+ops@cidah.ai | team-lead-01 | wrkspc_01KN44oHJcxSPRyojkG8DeBV |
| Barak Orbach | manager_full | guyn+legal1@cidah.ai | team-member-01 | wrkspc_01Q4QrM6oxssETW9cYNTpk6j |
| Roy Boker | manager_full | guyn+legal2@cidah.ai | team-member-02 | wrkspc_017UEHsT2DeeYG8sWNNeRS7M |
| Adi Yehezkiel-Yaffe | team_lawyer | guyn+legal3@cidah.ai | team-member-03 | wrkspc_013PT8pmjmKaxhNrDcpsv79G |
| Dana Hasson | team_lawyer | guyn+legal4@cidah.ai | team-member-04 | wrkspc_01GG3pqYDhX5tUrbuDUYyMqy |
| Hila Cohen | team_lawyer | guyn+legal5@cidah.ai | team-member-05 | wrkspc_014ZfRArfvCyyxD5C8txK93Q |
| Philippe Lipschutz | team_lawyer | guyn+legal6@cidah.ai | team-member-06 | wrkspc_01BRRpM7st7ctGCGCbBD5Jnx |
| Tamar Maoz Knaz | team_lawyer | guyn+legal7@cidah.ai | team-member-07 | wrkspc_01EfCXdpLMcGieDDmcCo8a9Q |
| Yafit Mor | team_paralegal | guyn+para2@cidah.ai | team-member-08 | wrkspc_01HVajKv55TAk6PGSvKRGxWA |

---

## URLs קריטיים

| עמוד | URL |
|------|-----|
| API Keys | https://platform.claude.com/settings/keys |
| Admin Keys | https://platform.claude.com/settings/admin-keys |
| Workspaces | https://platform.claude.com/settings/workspaces |

⚠️ `console.anthropic.com` מנווט ל-`platform.claude.com` — השתמש ב-platform.claude.com ישירות.

---

## ידע טכני קריטי — לקחים מהסשן

### Admin API — מה עובד ומה לא
```
GET  /v1/organizations/api_keys              ✅ מחזיר רשימה
POST /v1/organizations/api_keys              ❌ Method Not Allowed
POST /v1/organizations/workspaces/{id}/api_keys  ❌ Not Found
```
**מסקנה:** יצירת API keys חייבת דרך UI בלבד.

### Playwright על Mac
- `headless=False` דורש XServer — לא עובד בסנדבוקס Linux של Cowork
- Google חוסם Playwright כ"browser לא מאובטח" בניסיון Google OAuth
- **פתרון עובד:** `browser_cookie3` מחלץ cookies מ-Chrome → Playwright מזריק → bypass login
- Chrome מצפין cookies עם macOS Keychain — browser_cookie3 מפענח אוטומטית (דורש סיסמת Mac)
- יש כמה Chrome profiles — הסקריפט מחפש את ה-profile עם cookies של `.claude.ai`

### סנדבוקס Cowork
- bash רץ ב-Linux, לא על Mac — אי אפשר לפתוח GUI
- גישה לתיקיית Documents דרך mount בלבד — אין גישה ל-~/Library
- כל סקריפט שצריך לפתוח דפדפן — חייב לרוץ על Mac ישירות

### Gmail Plus Addressing
- `guyn+legal1@cidah.ai` → מגיע לתיבת guyn@cidah.ai
- לא יוצר משתמש Anthropic נפרד — כולם resolve לאותו user_id
- שימוש: Gmail labels/routing בלבד, לא Anthropic accounts

---

## מבנה קבצים (מעודכן 2026-04-24)

```
claude-master/
├── CLAUDE.md                              ← קרא ראשון (קובץ זה)
├── setup/
│   ├── .env                               ← ANTHROPIC_ADMIN_KEY + MODEL_* + SESSION_MEMORY_BUDGET_KB
│   ├── create_workspaces.py               ← ✅ הורץ
│   ├── create_api_keys.py                 ← 🔄 הצעד הבא
│   ├── workspaces_created.json            ← API keys (לא ב-git)
│   └── debug_cookies.py
│
├── core/
│   ├── claude_master.py                   ← ✅ routing engine + memory layer integration
│   └── memory/                            ← ✅ Memory Layer V2 — נבנה
│       ├── __init__.py                    ← public surface (lazy + eager exports)
│       ├── initializer.py                 ← MemoryInitializer + SessionContext (entry point)
│       ├── context_loader.py              ← L0..L4 layer loader, sanitizer, budget
│       ├── project_resolver.py            ← resolve() → hashed slug (worktree-safe)
│       ├── session_lock.py                ← SessionLock + session_scope (V2 #1985/#7702)
│       ├── scope_guard.py                 ← path traversal / symlink defense (CVE-2026-34451)
│       ├── tool.py                        ← MemoryTool — 6-command dispatcher
│       ├── auto.py                        ← AutoMemory SDK bridge (as_request_params)
│       ├── pinned.py                      ← PinnedMemoryAPI (user-authored entries)
│       ├── index.py                       ← IndexBuilder + 180/200-line warn
│       └── audit.py                       ← append-only audit logger
│
├── email/
│   ├── gmail_manager.py                   ← ✅ Gmail + Drive
│   └── setup_labels_filters.py            ← ✅ 10 labels + 10 filters
│
├── credentials/                           ← לא ב-git!
│   ├── gmail_credentials.json
│   └── gmail_token.pickle
│
├── memory/                                ← L0 + per-store CLAUDE.md
│   ├── CONVENTIONS.md                     ← L0 global — admin-only, version controlled
│   ├── README.md                          ← תיעוד הארכיטקטורה
│   ├── store_master/                      ← ✅ Admin (Guy Neeman)
│   │   ├── CLAUDE.md                      ← ✅ נכתב
│   │   └── state.json
│   ├── store_legal/                       ← ✅ Legal agents
│   │   ├── CLAUDE.md                      ← ✅ נכתב
│   │   └── state.json
│   ├── store_tech/                        ← dev/ops
│   │   ├── CLAUDE.md
│   │   └── state.json
│   ├── store_email/                       ← Gmail ops
│   │   ├── CLAUDE.md
│   │   └── state.json
│   └── store_user_template/               ← ✅ template לשכפול
│       ├── CLAUDE.md                      ← ✅ נכתב
│       └── state.json
│
├── logs/                                  ← audit.jsonl + claude_master.log
├── docs/spec_v1.md                        ← מפרט טכני מלא
└── הרץ_API_Keys.command                   ← לחיצה כפולה ב-Finder
```

---

## איך להשתמש במערכת (Memory Layer V2)

### 1. קריאה בסיסית עם memory layer

```python
from core.claude_master import get_master

cm = get_master()

# כל call חייב project_slug — מבדל את ה-memory store של הלקוח / פרויקט.
result = cm.call(
    workspace="team-member-01",          # Barak Orbach
    project_slug="cohen-levy-matter-01", # ← מבודד memory store
    prompt="מה הפסיקה האחרונה בנושא פיצויי פיטורין?",
    route="legal_draft",                 # Opus 4.7 xhigh + nevo + takdin + meili
)

print(result["text"])
print(result["session_id"])          # uuid של ה-session
print(result["memory_warnings"])     # אם ה-INDEX קרוב ל-200 שורות וכו'
```

### 2. מה קורה מאחורי הקלעים בכל call

1. `MemoryInitializer.init_session(system, entity_type, entity_id=slug, user_id)`
2. `project_resolver.resolve()` → hashed slug (worktree-safe)
3. SessionLock.acquire() → freeze (readonly binding)
4. L0..L4 נטענים דרך `context_loader` → `system_prompt`
5. `AutoMemory.as_request_params()` → `tool_config + beta_headers`
6. API call דרך ה-workspace client של ה-member
7. `ctx.close()` → audit + release lock

### 3. Incognito mode

```python
cm.call(
    workspace="team-member-01",
    project_slug="sensitive-matter",
    prompt="...",
    incognito=True,    # אין auto-memory; pinned נטען readonly; audit עדיין פועל
)
```

### 4. Admin broadcast

```python
# רק Admin — שליחה לכל ה-team
cm.broadcast(
    project_slug="internal-announcement",
    prompt="רענון נוהל: ...",
    route="manual",
)
```

### 5. Onboarding של user חדש

```bash
cp -r memory/store_user_template memory/store_user_barak-orbach
# ערוך memory/store_user_barak-orbach/CLAUDE.md — החלף [REPLACE: ...]
# ערוך memory/store_user_barak-orbach/state.json
# הוסף workspace_id ל-setup/workspaces_created.json
```

### 6. משתני סביבה (setup/.env)

```
ANTHROPIC_ADMIN_KEY=sk-ant-admin-...
SESSION_MEMORY_BUDGET_KB=30
SESSION_MEMORY_BUDGET_WARN_AT=24
PROJECTS_ROOT=/Users/admincid/Documents/neeman_Native/neeman_Native/claude-master/data/projects
USERS_ROOT=/Users/admincid/Documents/neeman_Native/neeman_Native/claude-master/data/users
SKILLS_ROOT=/Users/admincid/Documents/neeman_Native/neeman_Native/claude-master/data/skills
CONVENTIONS_PATH=/Users/admincid/Documents/neeman_Native/neeman_Native/claude-master/memory/CONVENTIONS.md
LOG_LEVEL=INFO
```

---

## כלל עבודה בסיסי
- credentials לעולם לא יוצאים מהמחשב ולא נכנסים לגיט
- שלב שלב — לא הכל בבת אחת
- קבצים במקומם הנכון לפי מבנה הפרויקט
- **תמיד project_slug** בכל call — אף פעם לא קריאה בלי slug
- **בידוד לקוחות = קו אדום** — גם ל-Admin (ראה store_master/CLAUDE.md)
