---
name: cleanup
description: Find and clean up disk waste from Claude Code sessions — stale logs, failed telemetry, old subagent data. Use when disk space is a concern.
user-invocable: true
allowed-tools: Bash Read Glob
---

# cc-retrospect Cleanup

Scan the user's Claude Code data directories for reclaimable disk space. Report findings, then ask before deleting anything.

## Step 1 — Survey disk usage

```bash
du -sh ~/.claude/ 2>/dev/null || echo "~/.claude not found"
```

```bash
du -sh ~/.claude/telemetry/ 2>/dev/null || echo "No telemetry dir"
```

```bash
find ~/.claude/projects/ -path "*/subagents/*" -name "*.jsonl" | wc -l
```

```bash
du -sh ~/.claude/projects/*/subagents/ 2>/dev/null | sort -rh | head -10
```

```bash
find ~/.claude/projects/ -name "*.jsonl" -mtime +7 | wc -l
```

```bash
du -sh ~/.cc-retrospect/ 2>/dev/null || echo "No data dir"
```

## Step 2 — Report findings

Present a table:

| Category | Size | Files | Safe to delete? |
|---|---|---|---|
| Failed telemetry events | | | Yes — never retried |
| Subagent session logs (>3 days old) | | | Yes — never reused |
| Stale worktree project data | | | Yes — if worktrees are gone |
| Session logs >7 days old | | | Caution — loses history |
| cc-retrospect cache | | | Safe — auto-rebuilds |

## Step 3 — Offer cleanup commands

For each category, show the exact command that would clean it up. DO NOT run them automatically.

Example:
```
# Delete failed telemetry (safe)
rm -rf ~/.claude/telemetry/

# Delete old subagent logs (safe, saves the most space)
find ~/.claude/projects/ -path "*/subagents/*" -name "*.jsonl" -mtime +3 -delete

# Delete stale worktree data (check first)
ls ~/.claude/projects/*worktrees*

# Delete sessions older than 7 days (loses history, cache rebuilds)
find ~/.claude/projects/ -name "*.jsonl" -mtime +7 -delete
```

## Rules

- NEVER delete without asking first
- NEVER delete the main (non-subagent) session files without explicit confirmation
- Always show the `du -sh` size before suggesting deletion
- Always explain what will be lost
