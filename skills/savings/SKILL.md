---
name: savings-analysis
description: Deep savings analysis — runs projections then prioritizes by impact, names projects, and explains the math behind each recommendation.
user-invocable: true
allowed-tools: Bash Read Grep Glob
---

# Savings Analysis (Hybrid)

## Step 1 — Get precision data

```bash
python3 ${CLAUDE_PLUGIN_ROOT}/scripts/dispatch.py savings --json
```

## Step 2 — Interpret

From the JSON output:

- Rank recommendations by $/month impact (highest first)
- For model switch savings: name which projects should switch and which should stay on Opus
- For session length savings: show the worst sessions by name, duration, and cost
- For each recommendation: explain the math ("X sessions × Y avg cost × 40% reduction = $Z/mo")
- Calculate: "If you did all of these, your bill goes from $X/mo to $Y/mo"

Make it concrete. No generic advice — every number should come from their data.
