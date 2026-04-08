---
name: health-analysis
description: Health deep-dive — correlates session length with cost, spots patterns in frustration timing, and identifies which habits drive the highest bills.
user-invocable: true
allowed-tools: Bash Read Grep Glob
---

# Health Analysis (Hybrid)

## Step 1 — Get precision data

```bash
python3 ${CLAUDE_PLUGIN_ROOT}/scripts/dispatch.py health --json
```

```bash
python3 ${CLAUDE_PLUGIN_ROOT}/scripts/dispatch.py habits --json
```

## Step 2 — Correlate patterns

Go beyond the numbers:

- Do frustration signals cluster at certain times of day? (coding tired = more frustration)
- Which projects have the highest frustration-per-session ratio?
- Are long sessions correlated with high frustration? (spiral sessions)
- Is there a "break-even point" — after how many messages does cost accelerate?
- Are compaction events happening? If not, sessions are probably too long.

Produce health grades: A (great), B (ok), C (needs work), D (burning money).
Grade each project separately.
