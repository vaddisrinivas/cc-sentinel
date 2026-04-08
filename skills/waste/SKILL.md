---
name: waste-analysis
description: Deep waste analysis — runs precision numbers then interprets patterns, names specific projects, and explains why each waste pattern costs money.
user-invocable: true
allowed-tools: Bash Read Grep Glob
---

# Waste Analysis (Hybrid)

## Step 1 — Get precision data

```bash
python3 ${CLAUDE_PLUGIN_ROOT}/scripts/dispatch.py waste --json
```

## Step 2 — Interpret

From the JSON output, go beyond the numbers:

- For WebFetch→GitHub waste: which specific projects are the worst offenders? Show top 3 by count.
- For repetitive tool chains: what were the longest chains? Are they always Bash or Read? Suggest specific batching strategies.
- For oversized prompts: estimate how much these cost over time (each paste gets re-read every turn via cache).
- For Opus on simple tasks: name the specific sessions/projects. What were they doing that didn't need Opus?

Produce a narrative report, not just a table. Quote actual numbers. End with a prioritized action list.
