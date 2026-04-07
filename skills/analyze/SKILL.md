---
name: analyze
description: Full Claude Code session retrospective — habits, health, tips, trends, and cost analysis. Use when the user asks about session costs, usage patterns, or wants optimization advice.
user-invocable: true
allowed-tools: Bash Read Grep Glob
---

# cc-retrospect

You are running a full retrospective on the user's Claude Code sessions. Produce a structured markdown report covering cost, habits, health, waste, and recommendations.

---

## Step 1 — Collect data (try sources in order, stop at first success)

### Source 1: Python dispatcher (most precise)

Run these and use the output directly:

```bash
python3 ${CLAUDE_PLUGIN_ROOT}/scripts/dispatch.py cost
```

```bash
python3 ${CLAUDE_PLUGIN_ROOT}/scripts/dispatch.py waste
```

If both succeed, skip to Step 2. If Python fails, try Source 2.

### Source 2: Pre-summarized cache

Read `~/.cc-retrospect/sessions.jsonl`. Each line is a JSON object with these fields:

| Field | Type | Meaning |
|---|---|---|
| `project` | string | Project directory name |
| `start_ts` | string | ISO timestamp of session start |
| `duration_minutes` | float | Session length in minutes |
| `message_count` | int | Total messages |
| `total_cost` | float | USD cost |
| `total_input_tokens` | int | Fresh input tokens |
| `total_output_tokens` | int | Output tokens |
| `total_cache_read_tokens` | int | Cache-read tokens |
| `frustration_count` | int | Frustration keyword hits |
| `frustration_words` | object | `{word: count}` map |
| `subagent_count` | int | Agent tool calls |
| `tool_counts` | object | `{tool: count}` map |
| `webfetch_domains` | object | `{domain: count}` map |
| `model_breakdown` | object | `{model: cost}` map |
| `tool_chains` | array | `[[tool, length], ...]` consecutive same-tool runs |
| `mega_prompt_count` | int | User messages > 1000 chars |

If this file is missing or empty, try Source 3.

### Source 3: Raw Claude Code session files (always present)

Glob `~/.claude/projects/**/*.jsonl`. Each file is one session. Each line is a conversation entry:

- `type: "assistant"` entries have `message.usage` (token counts) and `message.model` (model name)
- `type: "user"` entries have `message.content` (user text)
- `message.content[].type == "tool_use"` entries have `.name` for tool name
- `timestamp` on each entry gives timing

**Pricing to compute cost:**

| Model | Input $/MTok | Output $/MTok |
|---|---|---|
| Opus 4 | 15.00 | 75.00 |
| Sonnet 4 | 3.00 | 15.00 |
| Haiku 4 | 0.80 | 4.00 |

**Frustration keywords:** `again`, `ugh`, `still broken`, `not working`, `wrong`, `try again`, `wtf`, `come on`, `seriously`, `nope`

If raw files are also missing, tell the user: "No Claude Code session data found at `~/.claude/projects/`. Run some sessions first."

---

## Step 2 — Build the report

Produce all sections below. Use data from whichever source succeeded.

### Summary

| Metric | Value |
|---|---|
| Total sessions | |
| Total cost | |
| Avg session duration | |
| Avg messages/session | |
| Total subagent spawns | |
| Total frustration signals | |

### Cost breakdown

- Total cost by project (top 5) and by model
- Daily average for last 7 days
- If > $10 Opus spend: what-if savings if switched to Sonnet

### Habits

- Average and longest session duration
- Most-used tools (top 10)
- Peak hours (from `start_ts` hour)
- Peak days of week

### Health signals

Flag any that apply:
- Sessions > 120 min or > 200 messages
- Any session with > 10 subagents
- Frustration count > 0
- Cache hit rate < 70%
- Daily cost > $500

### This week vs last week

Split sessions by `start_ts` into current vs prior calendar week. Compare: cost, sessions, avg duration, frustrations, subagents.

### Waste signals

- WebFetch calls to GitHub/API domains (use `gh` CLI instead)
- Repeated tool chains (same tool 5+ times consecutively)
- Mega prompts (user messages > 1000 chars — use file references)
- Model mismatch (Opus on sessions with no Agent/WebSearch/WebFetch)

### Recommendations

3-5 specific, data-backed recommendations. Quote actual numbers. Name actual projects. No generic advice.

If analysis used Source 3 and is based on sampling, prefix recommendations with confidence level.
