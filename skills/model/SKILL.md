---
name: model-analysis
description: Model efficiency deep-dive — analyzes which projects and task types should use which model, with per-project routing recommendations.
user-invocable: true
allowed-tools: Bash Read Grep Glob
---

# Model Efficiency Analysis (Hybrid)

## Step 1 — Get precision data

```bash
python3 ${CLAUDE_PLUGIN_ROOT}/scripts/dispatch.py model --json
```

```bash
python3 ${CLAUDE_PLUGIN_ROOT}/scripts/dispatch.py cost --json
```

## Step 2 — Build per-project model map

From the data, produce a routing table:

| Project | Recommended Model | Reason | Current Opus Spend |
|---|---|---|---|

Rules:
- Projects using Agent/WebSearch/EnterPlanMode → Opus (justified)
- Projects using only Read/Edit/Bash/Grep → Sonnet
- Subagent-heavy projects → suggest Haiku for subagents
- Projects with < $5 total spend → skip (not worth optimizing)

End with: "Set these defaults with `/model sonnet` when working on [projects]."
