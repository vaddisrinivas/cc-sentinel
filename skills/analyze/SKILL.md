---
name: analyze
description: Full Claude Code session retrospective — cost, habits, health, waste, model efficiency, savings projections, and behavioral insights. Use when the user asks about session costs, usage patterns, or wants optimization advice.
user-invocable: true
allowed-tools: Bash Read Grep Glob
---

# cc-retrospect Full Analysis

Run a comprehensive retrospective on the user's Claude Code sessions. Start with precision data, then layer behavioral insights.

## Step 1 — Run all analyzers

```bash
python3 ${CLAUDE_PLUGIN_ROOT}/scripts/dispatch.py cost
```

```bash
python3 ${CLAUDE_PLUGIN_ROOT}/scripts/dispatch.py waste
```

```bash
python3 ${CLAUDE_PLUGIN_ROOT}/scripts/dispatch.py model
```

```bash
python3 ${CLAUDE_PLUGIN_ROOT}/scripts/dispatch.py savings
```

```bash
python3 ${CLAUDE_PLUGIN_ROOT}/scripts/dispatch.py habits
```

```bash
python3 ${CLAUDE_PLUGIN_ROOT}/scripts/dispatch.py health
```

```bash
python3 ${CLAUDE_PLUGIN_ROOT}/scripts/dispatch.py compare
```

If any command fails, fall through to Source 2 (read `~/.cc-retrospect/sessions.jsonl` directly) or Source 3 (raw `~/.claude/projects/**/*.jsonl`).

## Step 2 — Behavioral analysis (Claude reasons about these)

From the raw session data, analyze things Python can't:

### Plan mode opportunities
Scan for sessions with high correction counts ("no", "wrong", "not what I meant"). These suggest the user should have used /plan to align upfront before writing code. Count how many corrections could have been avoided.

### Volatile hotspots
Identify files/projects with the highest edit churn. A file edited 50+ times in one session suggests an architectural problem or a debugging loop, not a feature.

### Model routing suggestions
For each project, recommend a default model based on the tools used:
- Projects using only Read/Edit/Bash/Grep → Sonnet
- Projects using Agent/WebSearch/EnterPlanMode → Opus
- Subagent-heavy projects → consider Haiku for subagents

### Compaction analysis
Read `~/.cc-retrospect/compactions.jsonl` if it exists. Report:
- How many compactions happened, how many tokens were freed
- Which sessions triggered the most compactions
- Whether compaction nudges (at 150/300 messages) were heeded

## Step 3 — Build the report

Combine precision numbers with behavioral insights into a single markdown report:

1. **Summary table** — sessions, cost, avg duration, frustrations, subagents, compactions
2. **Cost breakdown** — by project, model, daily
3. **Model efficiency** — justified Opus vs wasteful Opus, efficiency score
4. **Savings table** — per-habit with $/month, ranked by impact
5. **Habits** — peak hours, tools, session patterns
6. **Health signals** — long sessions, subagent overuse, cost velocity
7. **Waste signals** — WebFetch→GitHub, chains, mega prompts, model mismatch
8. **This week vs last week** — trend comparison
9. **Plan mode opportunities** — where /plan would have saved iterations
10. **Volatile hotspots** — most-churned files/projects
11. **Recommendations** — 5-7 specific, data-backed, with actual numbers

Every recommendation must quote actual numbers from the user's data. No generic advice.
