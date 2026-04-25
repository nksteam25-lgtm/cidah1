#!/bin/bash
# Wave 3 — Init pilot project structure in cidah_data
# Run: bash setup/setup_pilot_project.sh
set -e

PILOT="$HOME/cidah_data/projects/neeman-pilot-2026"

mkdir -p "$PILOT/memory/auto"
mkdir -p "$PILOT/memory/pinned"
mkdir -p "$PILOT/memory/refs"
mkdir -p "$PILOT/sessions"

cat > "$PILOT/CLAUDE.md" << 'EOF'
# neeman-pilot-2026 — Project Context (L3a)
**Matter:** CIDAH Phase 1A Pilot
**Partner:** Guy Neeman
**Status:** Active — pilot 2026
**Workspace:** claude-master-admin
**Language:** Hebrew primary

## Context
First live matter on CIDAH Native system.
All actions require /approve before external send.
AI disclosure footer on every outbound document.
EOF

cat > "$PILOT/INDEX.md" << 'EOF'
# Project Memory Index — neeman-pilot-2026
*Auto-managed — do not edit manually*

## Matters
(none yet)

## Key Decisions
(none yet)
EOF

# User CLAUDE.md for Guy
mkdir -p "$HOME/cidah_data/users/guy-neeman"
cat > "$HOME/cidah_data/users/guy-neeman/CLAUDE.md" << 'EOF'
# Guy Neeman — Partner (L1)
Role: Managing Partner + CIDAH System Operator
Language: Hebrew primary; English for international
Workspace: claude-master-admin
Permissions: full
Preference: Concise, formal, evidence-based
EOF

echo "✅ Pilot project structure created:"
find "$HOME/cidah_data" -not -path "*/\.*" | sort
