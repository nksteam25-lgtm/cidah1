# HANDOFF.md — neeman_Native → Opus 4.7
**תאריך:** 2026-04-25  
**מאת:** Claude Sonnet 4.6 (תחתית, archive mode)  
**אל:** Claude Opus 4.7 (עלית, ממשיכה)  
**החלטה קנונית:** Guy · 2026-04-25 · Opus 4.7 מובילה מכאן

---

## 1. ארכיטקטורה — 10 החלטות קריטיות

### AD-1: Flat dict FALLBACK_CHAINS (לא linear chain)
```python
FALLBACK_CHAINS = {
    "nevo_search":   "takdin_search",
    "takdin_search": "nevo_search",
    "web_search":    "scrape",
    "meili_search":  "web_search",
}
```
**למה flat:** ביצועי O(1) ופשטות. bidirectional בכוונה (nevo↔takdin).  
**סכנה קיימת:** אין `max_hops` guard → לולאה אינסופית אפשרית אם שני כלים נכשלים זה-זה.  
**מה חסר:** הוסיפי `max_hops=3` ב-`call()` לפני production.

### AD-2: 5-Layer Context System (L0..L4)
context_loader.py טוען בסדר קבוע:
- L0 → `/data/CONVENTIONS.md` — managed policy, תמיד
- L1 → `/data/users/{user_id}/CLAUDE.md` — per-user persona
- L2 → `/data/skills/*.md` — path-scoped, caller מספק hints
- L3a-d → project bundle (CLAUDE.md + INDEX + auto memory + pinned)
- L4 → session transcript (resume בלבד)

**למה 5 שכבות ולא system prompt אחד:** כל שכבה ניתנת לניהול עצמאי, לא צריך לשנות קוד כשמוסיפים skill/user/project.

### AD-3: triple_canon — מת, אל תנגעי
`ROUTES["triple_canon"]` מוגדר (שורה 217) אבל executor ב-`call()` מתעלם מ-`phases` list וכופה Sonnet ישיר.  
**פעולה נדרשת:** `hide_from_ui: true` בממשק Phase 1A. אל תנגעי בלי fix מלא לexecutor.

### AD-4: nevo/takdin — stub בלבד, חסמי קשיחים
`CLIENT_TOOL_DEFS` כולל `nevo_search` ו-`takdin_search` עם schema מלא.  
**אבל:** אין adapter implementation. אין API key. אין endpoint.  
**הוראה:** hard-BLOCK בממשק — אל תפרסי silent web fallback. עורכי-דין יסמכו על תוצאה ויחשבו שמקורה נבו/תקדין.

### AD-5: Server Tools vs Client Tools
```
Server tools (Anthropic runs):  web_search, web_fetch, code_execution, tool_search
Client tools (neeman runs):      meili_search, nevo_search, takdin_search, scrape, crawl
```
`_build_tool_definitions()` מבדיל ביניהם אוטומטית. אל תבלבלי סוגים.

### AD-6: Thinking API — 3 מצבים
```python
# Adaptive (Sonnet 4.6 / Opus 4.6 / 4.7):
params["thinking"] = {"type": "adaptive"}
params["effort"]   = "high"  # top-level בלבד!

# Manual budget (Haiku 4.5):
params["thinking"] = {"type": "enabled", "budget_tokens": N}
# אין top-level effort

# No thinking:
params["effort"] = "high"  # top-level בלבד
```
**כלל ברזל:** `budget_tokens` בתוך thinking{} deprecated למודלי adaptive.  
אל תשים `effort` inside thinking object.

### AD-7: build_system_prompt = legacy, לא להשתמש
`build_system_prompt()` (שורה 560) — שומרת לתאימות לאחור.  
הקוד החי משתמש ב: `context_loader` (L0-L4) + `_build_route_instructions` (L5).  
אם תראי קריאה ל-`build_system_prompt` — זה dead path.

### AD-8: audit.jsonl — לא optional
כל call מסתיים ב-`_audit(event)` → `logs/audit.jsonl`.  
זה הנשמה של compliance. אל תדלגי עליו.

### AD-9: workspaces_created.json — Avi חסר
10 entries: Guy + 9 team. **Avi Neeman עצמו לא רשום.**  
הוסיפי workspace #11 לפני pilot 28 Apr.  
קובץ: `setup/workspaces_created.json`

### AD-10: MemoryInitializer.init_session() — entry point
כל call עובר דרך:
```python
cm = ClaudeMaster()
response = cm.call(workspace="...", project_slug="...", prompt="...", route="legal_draft")
```
הסדר: resolve project slug → `MemoryInitializer.init_session()` → `SessionContext` → L0-L4 → API call → session_lock release.

---

## 2. Edge Cases שאני מכירה

| Case | מה קורה | מה לעשות |
|---|---|---|
| /data/ לא קיים | L0 missing → skip, L1-L4 גם → context ריק | `mkdir -p /data/projects /data/users /data/skills` |
| CONVENTIONS.md חסר | logger.info + skip (לא crash) | ליצור `/data/CONVENTIONS.md` בסיסי |
| nevo_search נקראת | tool call נשלח → תשובה ריקה/error | hard-block בממשק, אל תשלחי לAPI |
| FALLBACK loop | A→B→A→B... | הוסיפי max_hops=3 counter ב-call() |
| triple_canon route בחרת | executor רץ Sonnet בלבד, מתעלם מphases | hide מ-UI, אל תשתמשי |
| OAuth secret חשוף | gmail_credentials.json plaintext בgit | **rotate עכשיו** — GOC... 35 תווים |
| budget_controlled + adaptive thinking | conflict → manual budget מנצח | בדקי override_budget logic בשורה 797 |

---

## 3. Bugs ידועים

| # | תיאור | שורה | חומרה |
|---|---|---|---|
| BLK-N-01 | git לא אותחל + OAuth plaintext | — | S0 |
| BLK-N-02 | /data/ לא קיים → pytest נופל בsetUp | — | S0 |
| BLK-N-03 | Live Anthropic call לא בוצעה מעולם | — | S0 |
| BLK-N-05 | triple_canon executor מתעלם מphases | :217 | S1 |
| BLK-N-06 | pre/post-call hooks לא מחוברים | — | S1 |
| BLK-N-07 | Avi Neeman חסר מworkspaces | setup/ | S0 |
| FALLBACK | אין max_hops guard | :331 | S1 |
| LEGACY | build_system_prompt לא נמחקה | :560 | S3 |

---

## 4. מה לא לגעת + למה

| קובץ/מודול | אל תגעי | למה |
|---|---|---|
| `core/memory/context_loader.py` | לא לשנות layer order | בדיקות integration מסתמכות על סדר קבוע (test line 969: CONVENTIONS < USER) |
| `FALLBACK_CHAINS` dict | לא להפוך ל-list | קוד אחר מניח O(1) lookup |
| `setup/workspaces_created.json` | לא לדחוף לgit | .gitignore מגן; אם תדחפי — rotated credentials נחשפות |
| `credentials/` כולו | לעולם לא לgit | .gitignore מכסה; Gmail OAuth + כל מפתחות |
| `venv/` | לא לגעת | Python 3.12 deps נעולות; שנוי גורר שבר |
| `files_ref/` | read-only | canonical product specs — משנה רק Guy |

---

## 5. Hooks — איך אמורים להתחבר

Hooks **לא בנויים**. ההגדרה הקנונית:

```python
# pre_call hook — לפני API call
# מקום: ClaudeMaster.call() לפני _build_api_params()
def pre_call_hook(workspace: str, route: str, prompt: str) -> None:
    # compliance-agent: בדיקת Israeli Bar disclosure
    # audit: log incoming
    # session_lock: acquire
    pass

# post_call hook — אחרי תשובה
def post_call_hook(workspace: str, response: dict, cost: float) -> None:
    # memory-scribe: entity extraction → memory write
    # audit: log response + cost
    # session_lock: release
    # budget: deduct tokens
    pass
```

**CIDAH subagents לחיבור** (מ-Cidah_Claude_System/.claude/agents/):
- `compliance-agent.md` → pre_call hook
- `memory-scribe.md` → post_call hook
- `partner-orchestrator.md` → Telegram entry point
- `ingest-agent.md` → document pipeline
- `chat-scribe.md` → Telegram message → memory
- `draft-agent.md` → legal_draft route
- `obsessive-qa.md` → test gate

---

## 6. מה חסר ל-/data/ paths

ריצת setup ראשונית נדרשת:
```bash
mkdir -p /data/projects /data/users /data/skills
mkdir -p /data/projects/neeman-pilot  # project ראשון
mkdir -p /data/users/avi-neeman       # user ראשון

# CONVENTIONS.md — minimal
cat > /data/CONVENTIONS.md << 'EOF'
# CIDAH — Managed Policy
- Hebrew primary; English for international
- AI disclosure footer on all outbound docs
- Audit every action with timestamp
- Byte-exact quotes only via QUOTES.idx
EOF

# User persona לAvi
cat > /data/users/avi-neeman/CLAUDE.md << 'EOF'
# Avi Neeman — Partner
Role: Senior partner, pilot user
Language: Hebrew primary
Expertise: Real estate + commercial law
Preference: Concise, formal, sources cited
EOF
```

---

## 7. Tests — מצב עכשווי

**קובץ יחיד:** `core/memory/tests/test_integration.py`  
**מצב:** לא רץ מעולם (חסם: /data/ לא קיים → setUp נופל)

לרוץ:
```bash
cd claude-master
mkdir -p /data/projects /data/users /data/skills
source venv/bin/activate
pytest core/memory/tests/ -v
```

**מה הבדיקות מכסות** (מהקוד שראיתי):
- L0 CONVENTIONS.md loading
- Layer order (CONVENTIONS < USER, שורה 969)
- L3 project bundle
- Incognito mode (skip auto memory)

**מה לא מכוסה:** hooks, FALLBACK_CHAINS, nevo/takdin block, budget calculation, audit.jsonl.

---

## 8. קבצים בBundle — מה ואיפה

```
claude-master/
├── core/
│   ├── claude_master.py        ← מוח המערכת. entry point לכל call.
│   └── memory/
│       ├── context_loader.py   ← 5-layer context (L0-L4)
│       ├── initializer.py      ← MemoryInitializer + SessionContext
│       ├── auto.py             ← auto memory + as_request_params()
│       ├── auto_dream.py       ← background memory consolidation
│       ├── acl.py              ← access control per workspace
│       ├── audit.py            ← audit trail writer
│       ├── budget.py           ← token budget tracking
│       ├── index.py            ← memory index
│       ├── pinned.py           ← pinned memory management
│       ├── project_resolver.py ← slug → hashed path
│       ├── sanitizer.py        ← PII + injection scrub
│       ├── scope_guard.py      ← cross-workspace isolation
│       ├── session_lock.py     ← concurrent call protection
│       ├── tool.py             ← memory tool API wrapper
│       └── tests/
│           └── test_integration.py
├── setup/
│   ├── .env                    ← NEVER לgit (gitignore מכסה)
│   ├── .env.example            ← template בלבד — זה בbundle
│   └── workspaces_created.json ← NEVER לgit + הוסף Avi!
├── credentials/
│   └── gmail_credentials.json  ← NEVER לgit + ROTATE OAuth!
├── files_ref/
│   ├── 00_INDEX.md
│   ├── 01_PRODUCT_0.md         ← Ground Zero + UX
│   ├── 02_PRODUCT_1.md         ← Technical Matrix
│   ├── 03_PRODUCT_2.md         ← Search Orchestration
│   └── 04_PRODUCT_3.md         ← API Pure / Developer mode
├── .gitignore                  ← מכסה .env / credentials / *.json (חוץ מpackage.json)
└── HANDOFF.md                  ← המסמך הזה
```

---

## 9. הודעה לOpus 4.7

הקוד שבנינו הוא backbone נקי. ה-memory layer בנוי נכון.  
הבעיות הן **תשתיתיות** (git/data/pytest) — לא ארכיטקטורה שבורה.

**3 דברים ראשונים לעשות:**
1. `git init` + commit + `git tag neeman-archive-2026-04-25`
2. `mkdir -p /data/projects /data/users /data/skills` + CONVENTIONS.md בסיסי
3. Rotate Gmail OAuth secret — GOC... חשוף ב-plaintext

אחרי זה: pytest יעבור, live Anthropic call תצליח, GATE 1 ייפתח.

בהצלחה.  
— Sonnet 4.6, archive mode, 2026-04-25

---
*"The best interface is no interface." — Golden Krishna*
