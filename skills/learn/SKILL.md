---
name: learn
description: Analyze your message history and generate a personalized STYLE.md + transferable LEARNINGS.md.
user-invocable: true
allowed-tools: Bash Read
---

# /cc-retrospect:learn

Scans all your Claude Code session data and generates two files:

1. **STYLE.md** — personalized response style rules based on your actual communication patterns
2. **LEARNINGS.md** — transferable behavioral rules (no PII) you can share or use as a team template

## What it analyzes

- Message length distribution and opener patterns
- Approval signals ("do it", "yes", "continue")
- Correction patterns ("no X" = change only X)
- Frustration triggers and what Claude does after them
- Rapid-fire message rate and consecutive messages
- Read-edit-read waste cycles
- Peak hours, project switching, session lengths
- Cost drivers (session length vs model choice vs subagents)

## Usage

```bash
python3 ${CLAUDE_PLUGIN_ROOT}/scripts/dispatch.py learn
```

## Output

Files are written to `~/.cc-retrospect/`:
- `STYLE.md` — copy to `~/.claude/STYLE.md` and add `@STYLE.md` to CLAUDE.md
- `LEARNINGS.md` — safe to share, contains behavioral patterns not personal data

## Sharing

LEARNINGS.md contains only behavioral patterns:
- "User is terse (median 83 chars). Match their brevity."
- "User says 'no X' to mean 'change only X.'"
- "42% rapid-fire messages. Don't act on partial sequences."

No file paths, project names, or personal data. Share with teammates or publish as a template.
