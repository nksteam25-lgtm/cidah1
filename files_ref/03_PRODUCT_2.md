# CIDAH — מוצר 2: מוח החיפוש (Search Orchestration)

**גרסה:** 3.0 (קנוני — סופי)
**תאריך:** 24 אפריל 2026
**מטרה:** שכבת ה-orchestration של כל כלי החיפוש — מבוסס על Anthropic native blueprint
**חל רוחבית:** על מוצר 0 (UX) ועל כל המסלולים של מוצר 1
**מקור:** Anthropic docs (tool_use, parallel tools, think tool, tool_choice cookbook) + קהילה חזקה

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

### 🟨 מוצר 2 — מוח החיפוש (המסמך הזה)
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

## מעמד המסמך הזה

**מוצר 2 הוא שכבת חוקה — LAYER עליון על 0 ו-1.**

- הכללים שלו **חלים רוחבית** על כל מסלול במוצר 1 (כולל ידני של מוצר 0)
- במקרה של סתירה — **מוצר 2 גובר**
- מוצר 1 כבר מטמיע את הטבלה הקנונית מהמסמך הזה

---

# A. הבלו פרינט של Anthropic — 7 עקרונות רשמיים

המחקר החי הזה הוא הבסיס. זה לא המצאה — זה מה ש-Anthropic מלמדים במסמכים שלהם.

## 1. Description הוא המפתח

> "Claude decides when to call a tool based on the user's request and the tool's description."

**המשמעות:** האיכות של ה-description של כל כלי היא זו שקובעת אם המוח יבחר בו נכון.
לא תוספת — היסוד.

## 2. Parallel as default

> "For maximum efficiency, whenever you need to perform multiple independent operations, invoke all relevant tools simultaneously rather than sequentially. Prioritize calling tools in parallel whenever possible."

**המשמעות:** ברירת המחדל האגרסיבית של Anthropic היא parallel. לא sequential. Sequential הוא יוצא מן הכלל.

## 3. Prompt engineering ל-parallel

> "For even stronger parallel tool use use: `<use_parallel_tool_calls>` For maximum efficiency, whenever you perform multiple independent operations, invoke all relevant tools simultaneously rather than sequentially."

**המשמעות:** Anthropic נותנים prompt ספציפי לחזק parallel behavior. אנחנו משתמשים בו.

## 4. The "think" tool

> "The 'think' tool creates a dedicated space for Claude to pause during complex tool call chains."

**המשמעות:** כלי נפרד שמאפשר למוח לעצור ולחשוב באמצע שרשרת. מומלץ ב-chains של 5+ calls.

## 5. Batch tool pattern

> "Introducing a 'batch tool' that can act as a meta-tool to wrap invocations to other tools simultaneously. We find that if this tool is present, the model will use it to simultaneously call multiple tools in parallel."

**המשמעות:** כלי meta שעוטף כמה calls. עוזר במודלים שפחות טובים ב-parallel.

## 6. System prompt מסונתז

> "When you call the Claude API with the tools parameter, the API constructs a special system prompt from the tool definitions, tool configuration, and any user-specified system prompt."

**המשמעות:** לא רק ה-descriptions — ה-system prompt הסופי הוא סינתזה. אנחנו יכולים להנחות איך המוח מחליט (ראה סעיף G).

## 7. Tool choice control

4 מצבים רשמיים:
- `auto` — model decides (default)
- `any` — must use some tool
- `tool:name` — must use this specific tool
- `none` — cannot use tools

---

# B. 14 העקרונות הקנוניים של מוח החיפוש

## 1. Intent Detection לפי מהות, לא מילים

המוח מזהה צורך בחיפוש לפי **כוונת השאלה**. לא מחכה למילים "תחפש" או "בדוק".

## 2. Tool descriptions = DNA של ההחלטה

כל כלי חייב description שמגדיר:
- מה הוא עושה בדיוק
- מתי להשתמש בו
- **מתי לא להשתמש בו** ← חשוב לא פחות
- איזה parameters נדרשים

## 3. Trigger מפורש > Intent > Default

סדר עדיפות קנוני:

```
1. משתמש אמר "תחפש ב-X" → חובה X (עוקף הכל)
2. Intent detection זיהה → מפעיל אוטומטית
3. המוח מחליט לבד לפי descriptions
```

## 4. Parallel כ-default אגרסיבי

אם שני כלים לא תלויים זה בזה — **חובה מקביל**.
Sequential רק עם dependency מוכח.

## 5. Sequential עם dependency ברור

```
A → use result → B
```

דוגמה: `meili_search` → תוצאה → `code_execution`

## 6. Think tool לשרשרות 5+

כלי "פנימי" שהמוח מפעיל כדי לעצור ולחשוב באמצע שרשרת ארוכה.
מופעל אוטומטית ב-chain של 5+ calls.

## 7. Strict schema — חובה

`strict: true` לכל כלי. בלי יוצא מן הכלל.

## 8. Tool choice = auto (default)

המוח בוחר. המשתמש יכול לכפות `any`, `none`, או כלי ספציפי.

## 9. Fallback chain אוטומטי

```
nevo fails    → takdin
takdin fails  → nevo
web_search    → scrape
meili fails   → memory (future)
```

## 10. Iteration cap = 10 (safety)

> "while stop_reason == 'tool_use', execute the tools and continue. The loop exits on any other stop reason."

אבל cap של 10 למניעת runaway.

## 11. Context clearing אוטומטי

`clear_tool_uses_20250919` פעיל. המוח לא נחנק מתוצאות ישנות.

## 12. שקיפות מלאה

כל tool call מוצג: לפני, אחרי, עם תוצאה.
הודעה למשתמש: "🔍 מפעיל web_search: '[query]'..."

## 13. Server + Local — שילוב חלק

המוח לא מבחין בין Anthropic tools ל-local tools. כל הכלים באותה רמה.

## 14. 🔴 החוק העליון — חל רוחבית

**כל המסלולים יכולים להפעיל חיפוש.**
**Trigger מפורש תמיד עובד, גם במסלולים "סגורים".**

זה הכלל שגובר על כל כלל אחר. גם במסלול Mechanical (שהוא "none") — אם משתמש אומר "תחפש ב-X", הכלי מופעל.

---

# C. 10 הכלים — Descriptions קנוניים

**אלה ייכתבו ישירות בקוד. הם ה-DNA של ההחלטה של המוח.**

## Server Tools (של Anthropic — מובנים)

### 1. web_search

```json
{
 "name": "web_search",
 "description": "Search the web using Google for current information, news, facts about the world, or any topic requiring up-to-date public information. Use this when the user asks about events, people, products, places, or any factual knowledge that may have changed recently. Do NOT use for: specific URLs (use web_fetch), internal firm documents (use meili_search), or Israeli case law (use nevo_search or takdin_search).",
 "strict": true
}
```

### 2. web_fetch

```json
{
 "name": "web_fetch",
 "description": "Fetch the content of a specific URL provided by the user or found in previous context. Use this when: (a) the user includes a URL in their message, (b) a previous tool call returned URLs that need deep reading, (c) the user references a known website. Do NOT use for general search — use web_search for that.",
 "strict": true
}
```

### 3. code_execution

```json
{
 "name": "code_execution",
 "description": "Execute Python code in a sandboxed environment. Use for: calculations, data analysis, processing structured data, running algorithms, parsing JSON/CSV, statistical operations. Do NOT use for: simple math (respond directly), fetching external data (use web_* tools), or writing code the user will deploy (respond with the code).",
 "strict": true
}
```

### 4. tool_search

```json
{
 "name": "tool_search",
 "description": "Meta-tool. Use when you are unsure which specific tool is best for the user's request, especially in ambiguous queries involving multiple possible data sources. Returns a list of relevant tools to consider.",
 "strict": true
}
```

## Local Tools (שלנו — על Hostinger)

### 5. meili_search

```json
{
 "name": "meili_search",
 "description": "Search the firm's internal document store (Meilisearch on Hostinger). Contains: client matters, contracts, memos, internal knowledge, firm precedents. Use when the user asks about: specific clients, matters, firm documents, internal knowledge, 'what do we have on X', or any query referring to firm-private information. Do NOT use for: public information (use web_search) or case law (use nevo/takdin).",
 "strict": true
}
```

### 6. scrape

```json
{
 "name": "scrape",
 "description": "Scrape a single page from a specific website. Use when: (a) user explicitly says 'search on website X', (b) you need structured content from a known page that web_fetch can't easily parse. More precise than web_fetch for certain sites.",
 "strict": true
}
```

### 7. crawl

```json
{
 "name": "crawl",
 "description": "Crawl a domain deeply for comprehensive coverage. Use ONLY for explicit deep research requests on a specific domain. Expensive operation — prefer web_search or scrape when possible.",
 "strict": true
}
```

### 8. memory (Letta, עתידי)

```json
{
 "name": "memory",
 "description": "Access Letta long-term memory for cross-session context. Use when: (a) user references past conversations ('like we discussed'), (b) current task connects to ongoing matter, (c) need to recall client preferences or firm decisions.",
 "strict": true
}
```

### 9. nevo_search (עתידי)

```json
{
 "name": "nevo_search",
 "description": "Search Israeli case law on Nevo database. Use for: Israeli court decisions, case precedents, legal rulings, citations (ע\"א, ת\"א, דנ\"א, בג\"ץ). Primary tool for Israeli legal research. Pair with takdin_search for broader coverage.",
 "strict": true
}
```

### 10. takdin_search (עתידי)

```json
{
 "name": "takdin_search",
 "description": "Search Israeli case law on Takdin database. Alternative and complementary to nevo_search. Use for Israeli legal research, especially when nevo_search returns limited results. Often good to call in parallel with nevo_search for comprehensive coverage.",
 "strict": true
}
```

---

# D. 5 דפוסי Orchestration הקנוניים

## 1. Simple Call

```
שאלה → tool אחד → תשובה
```

80% מהזמן.

## 2. Parallel Batch

```
שאלה → [tool₁ ∥ tool₂ ∥ tool₃] → merge → תשובה
```

כשיש מקורות עצמאיים. Anthropic native supports this.

## 3. Sequential Chain

```
שאלה → tool₁ → analyze → tool₂ → תשובה
```

רק כשיש dependency.

## 4. Think-Guided Chain

```
שאלה → tool₁ → [think] → tool₂ → [think] → תשובה
```

לשרשרות 5+ calls.

## 5. Split-and-Merge

```
שאלה → split → [branch A, branch B] → merge → תשובה
```

לחקירה ממספר זוויות.

---

# E. השוואת עלות — סדר עדיפות למוח

```
חינם:      web_search, web_fetch, code_execution (Anthropic)
זול:       meili_search, scrape (compute שלנו)
בינוני:    memory (Letta compute)
יקר:       crawl, nevo/takdin (רישיונות + compute)
```

**עקרון:** המוח מעדיף את הזול אם מספיק.

---

# F. חלות רוחבית — טבלת search presets per route

**זו הטבלה הקנונית. מוצר 1 מטמיע אותה בכל מסלול.**

| מסלול | Default preset | Intent Detection | Trigger Override |
|---|---|---|---|
| 0. ידני | standard (web + meili) | ✅ ON | ✅ Always works |
| 1. Plan/Execute | full (all tools) | ✅ ON | ✅ Always works |
| 2. Advisor | standard | ✅ ON | ✅ Always works |
| 3. Mechanical | none | ❌ OFF | ✅ Always works |
| 4. Deep Thinking | research (web + think) | ✅ ON | ✅ Always works |
| 5. Fast Lane | web_search only | ❌ OFF | ✅ Always works |
| 6. Review Mode | none | ❌ OFF | ✅ Always works |
| 7. Triple Canon | full per phase | ✅ ON | ✅ Always works |
| 8. Research Deep | full + parallel | ✅ ON | ✅ Always works |
| 9. Legal Draft | legal (nevo+takdin+meili) | ✅ ON | ✅ Always works |
| 10. Budget-Controlled | standard | ✅ ON | ✅ Always works |

**החוק העליון:** "Trigger Override" = ✅ **בכל שורה**.
גם ב-Mechanical (שהוא "none"), משתמש שאומר "תחפש ב-X" — מפעיל את הכלי.

---

# G. System Prompt Additions — כללי המוח

הטקסט הזה נוסף ל-system prompt בכל קריאת API (ראה Anthropic עקרון 6 בסעיף A):

```markdown
## Tool Use Guidelines

You have access to {N} search tools. Decide based on the user's intent, not their words.

### Intent Detection
- Question about the world/news → web_search
- URL in message → web_fetch
- Firm/client/matter question → meili_search
- Israeli case law → nevo_search + takdin_search (parallel)
- Calculations/data → code_execution
- Ambiguous → tool_search

### Explicit Triggers (HIGHEST PRIORITY)
If user says "search on X", "check in Y", or names a specific tool/database —
use that tool. Override intent detection.

### Parallel vs Sequential
Default to parallel. Only go sequential when one tool's output is required
as input to another.

For example, when reading 3 files, run 3 tool calls in parallel to read
all 3 files into context at the same time.

<use_parallel_tool_calls>
For maximum efficiency, whenever you perform multiple independent operations,
invoke all relevant tools simultaneously rather than sequentially.

### When NOT to use tools
- Simple conversation
- Questions you already know the answer to
- Creative/analytical tasks not requiring external data
- Mechanical work (rename, format, etc.)

### The think tool
If you're in a chain of 5+ tool calls, use `think` to pause and reason
about next steps.

### Transparency
Before each tool call, briefly explain what you're doing:
"Checking web_search for current news on X..."
```

---

# H. `.env` עדכון (משולב במוצר 1)

הקטעים האלה מטמעים במוצר 1 (סעיף F של מוצר 1):

```bash
# SEARCH BRAIN
INTENT_DETECTION_ENABLED=true
INTENT_DETECTION_STRENGTH=balanced     # conservative | balanced | aggressive
PARALLEL_PROMPT_ENABLED=true           # adds <use_parallel_tool_calls>
SEQUENTIAL_DEPENDENCY_CHECK=true
THINK_TOOL_ENABLED=true
THINK_TOOL_AUTO_ACTIVATE_AT=5
TRIGGER_OVERRIDE_ALWAYS=true           # חוק עליון

# FALLBACK CHAINS
FALLBACK_NEVO=takdin
FALLBACK_TAKDIN=nevo
FALLBACK_WEB_SEARCH=scrape
FALLBACK_MEILI=memory

# BUDGET TRACKING
SHOW_TOOL_COSTS=true
WARN_ON_SESSION_TOOL_BUDGET=1.00       # USD
WARN_ON_CRAWL=true
```

---

# I. מבנה קוד — search-brain

תיקייה ייעודית בתוך `apps_bot/src/ai/`:

```
apps_bot/src/ai/search-brain/
├── intentDetector.ts           # מזהה כוונת חיפוש
├── toolSelector.ts             # בוחר כלי מתוך 10
├── orchestrator.ts             # parallel vs sequential
├── fallbackChain.ts            # fallback logic
├── thinkTool.ts                # think integration
├── budgetTracker.ts            # עלויות מצטברות
├── routeOverrides.ts           # חוקים per route
├── systemPromptBuilder.ts      # יצירת system prompt
└── patterns/
    ├── simple.ts
    ├── parallel.ts
    ├── sequential.ts
    ├── thinkGuided.ts
    └── splitMerge.ts
```

---

# J. 10 עקרונות קנוניים — סיכום סופי

1. ✅ **Descriptions = DNA של ההחלטה**
2. ✅ Intent detection לפי מהות, לא מילים
3. ✅ Trigger מפורש > Intent > Default
4. ✅ Parallel as default אגרסיבי
5. ✅ Think tool לשרשרות 5+
6. ✅ Strict schema חובה
7. ✅ Tool choice = auto (default)
8. ✅ Fallback chain אוטומטי
9. ✅ שקיפות מלאה
10. ✅ **חוק עליון — חל רוחבית על כל המסלולים**

---

# K. איך זה משתלב עם מוצר 0 ו-1

## במוצר 0 (UX):
- לשונית 🔍 מוצגת עם 10 הכלים + 6 presets
- Status bar מציג `🔍 auto, N active` + עלות מצטברת
- כל tool call מוצג בזמן אמת

## במוצר 1 (מטריצה):
- כל מסלול מקבל שני שדות:
 - `default_search_preset`
 - `intent_detection_enabled`
- **Trigger Override = תמיד ON בכל המסלולים**

---

**מוצר 2 סגור. מוח החיפוש מבוסס על Anthropic native blueprint. חל רוחבית.**
