---
name: digest-analysis
description: Enhanced daily digest — runs yesterday's numbers then adds narrative context, trends, and specific next-action recommendations.
user-invocable: true
allowed-tools: Bash Read Grep Glob
---

# Daily Digest (Hybrid)

## Step 1 — Get precision data

```bash
python3 ${CLAUDE_PLUGIN_ROOT}/scripts/dispatch.py digest
```

```bash
python3 ${CLAUDE_PLUGIN_ROOT}/scripts/dispatch.py trends
```

## Step 2 — Add narrative

From the digest output:

- Was yesterday better or worse than the daily average? By how much?
- What was the single biggest cost driver yesterday? Name it.
- If there were frustration signals: what projects were they in? What time?
- Compare to the weekly trend: is the user improving?
- Give ONE specific action for today: "Today, try /model sonnet when working on [project]" or "Keep sessions under 30 minutes — yesterday's avg was 2 hours."

Keep it to 5 sentences max. This is a morning briefing, not a report.
