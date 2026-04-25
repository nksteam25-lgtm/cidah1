# neeman_Native · Claude Master — Brain Layer
**גרסה:** Phase C · 2026-04-25 · GATE 1 track

## ארכיטקטורה (post-merge)
```
neeman_Native (תחתית · Python brain)
  ├── core/claude_master.py     ← routing · 11 routes · 8 brains · API
  ├── core/memory/              ← Memory V2 · 15 modules · 5-layer context
  ├── email/                    ← Gmail integration (OAuth connected)
  ├── setup/                    ← workspace provisioning · .env
  ├── credentials/              ← OAuth token (NOT in git)
  ├── files_ref/                ← canonical product specs (read-only)
  └── ~/cidah_data/             ← runtime data (L0-L4 layers · projects · users)

CIDAH (עלית · surface layer) — cidah-routes.plugin v1.0.0
  ├── .claude/agents/           ← 7 subagents (compliance · draft · orchestrator...)
  ├── .claude/skills/           ← 5 CIDAH skills
  └── _cowork/                  ← operational docs · audit trail
```

## Phase C status (2026-04-25)
- ✅ build_system_prompt() deleted (legacy dead code)
- ✅ triple_canon disabled (enabled: False — executor broken)
- ✅ nevo/takdin HARD-BLOCKED (no adapters — legal integrity)
- ✅ old memory/ stores deleted (replaced by ~/cidah_data/)
- ✅ Memory V2: 20/20 tests passing
- ✅ 10 workspaces active · OAuth connected

## שלב נוכחי
- Phase C complete
- Phase E (merge execution) + Phase F (QA) pending

## הוראות הפעלה
ראה: docs/spec_v1.md
